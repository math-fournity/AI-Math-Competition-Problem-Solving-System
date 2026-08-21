# 运维关注点——rate limit/stall/zombie/多轮续传

## 1. rate limit处理

### 问题

glm-5-2 API有速率限制。高并发时容易触发，表现为devin cli输出中出现rate_limit错误信息。不处理会持续触发，浪费API调用。

### 实现（`continuation_launcher.py`）

```python
RATE_LIMIT_PATTERNS = [
    "rate_limit", "rate limit", "Rate limit",
    "429", "Too Many Requests", "too many requests",
    "quota exceeded", "Quota exceeded",
]

# 主循环中检测
pane_output = tmux capture-pane ...
if any(pattern in pane_output for pattern in RATE_LIMIT_PATTERNS):
    rate_limit_paused_until = time.time() + 1200  # 暂停20分钟
    print(f"  [rate_limit] 检测到rate limit，暂停20分钟")
```

> **审计 Pipe 同款已接入（WP-J，2026-08-21）**：proof_audit_launcher 的running 检查段按同款模式实现——RATE_LIMIT_PATTERNS 匹配 → 全局暂停 20 分钟（audit_rate_paused_until）→ 不 kill session 留观。数据源为 pane 300 行 + pipe log 尾部 5KB 合并。

### 关键参数

- 暂停时间：1200秒（20分钟）——足够让API配额恢复
- 检测方式：pane输出文本匹配RATE_LIMIT_PATTERNS
- 暂停期间：不启动新run，但继续检查running状态

### 新Pipe如何实现

1. 从`continuation_config.py`导入`RATE_LIMIT_PATTERNS`（或自己定义）
2. 主循环中检测pane输出
3. 匹配到后设置`rate_limit_paused_until`
4. 暂停期间跳过"启动新的"部分

## 2. stall检测

### 问题

devin cli可能因为API错误、网络问题等原因卡住——不退出也不产出。不检测会浪费并发槽。

### 实现（`continuation_launcher.py`）

```python
# 每轮poll时对每个running session
pane_output = tmux capture-pane -t {session_name} -p -S -100
pane_hash = hash(pane_output[-500:])

if pane_hash != info["last_pane_hash"]:
    info["last_pane_hash"] = pane_hash
    info["last_activity"] = time.time()
idle_seconds = time.time() - info["last_activity"]

if idle_seconds > stall_seconds:
    # 判定为stall——★不kill★：标记session为stuck，等DONE.md或用户授意
    # （铁律：绝不kill无DONE.md的session——devin cli可能还在写export）
    mark_stuck(db, session_key, f"stall(idle {idle_sec}s)")
    mark_run_as_failed(run_key, "failed_stall")  # retry_eligible=False
```

### 关键参数

- `stall_seconds`：默认600秒（DEFAULT_STALL_SECONDS，10分钟无变化判定为stall）
- 检测方式：pane内容（末500字符）的hash变化
- 处理方式：**不kill**——标记stuck（等DONE.md），run标记failed_stall

### 注意事项

- pane内容中可能有时间戳等不断变化的内容——hash会一直变，不会判定为stall。这是正确的行为——只要pane在变化，说明devin还在工作。
- stall检测只针对pane内容完全无变化的情况——这才是真正的卡住。

## 3. zombie session清理

### 问题

devin cli退出后，tmux session不会自动销毁——残留为空pane session。这些zombie session会被`tmux list-sessions`计数，导致并发数判断错误。

### 实现（`continuation_launcher.py`）

两种zombie：

**类型1：run完成后的zombie**
```python
# run完成后（成功或失败），kill对应的tmux session
if run_completed:
    subprocess.run(["tmux", "kill-session", "-t", session_name])
```

**类型2：dead_session（session已退出但run没有完成标记）**
```python
# 检查running的session是否还存在
for session_name in running:
    result = subprocess.run(["tmux", "has-session", "-t", session_name])
    if result.returncode != 0:
        # session已退出但run没标记完成——dead_session
        mark_run_as_failed(run_key, "dead_session")
```

### Monitor Pipe的zombie检测

Monitor Pipe还有独立的zombie检测（A5检查项）：
```python
def check_zombie_sessions(db, batch_id):
    # 检查所有p27- session的pane是否空白
    for s in p27_sessions:
        pane_output = tmux capture-pane -t {s} -p -S -50
        lines = [l.strip() for l in pane_output if l.strip()]
        if len(lines) < 3:
            zombies.append(s)
    if len(zombies) >= 2:
        create_alert("zombie_sessions", "warning", {...})
```

## 4. 多轮续传机制

### 问题

glm-5-2单次API调用的completion_tokens上限是25000。竞赛数学题的thinking可能需要超过25000 tokens，导致AI在thinking中被截断（reasoning_content有46-73K字符，但message=0、tool_calls=0），无法进入working阶段。

### 截断判定（`is_truncated()`）

```python
def is_truncated(export_path):
    """检测export是否被截断"""
    rc = reasoning_content长度
    msg = message数量
    tc = tool_calls数量
    comp = completion_tokens

    if rc > 1000 and msg == 0 and tc == 0 and comp >= 24000:
        return True, "truncated"  # 截断
    if msg > 0 or tc > 0:
        return False, "completed"  # 完成
    return False, "unknown"  # 异常
```

### 完成判定（`is_completed()`）

```python
def is_completed(export_path, work_dir):
    """检测run是否完成——proof.md有boxed答案"""
    proof_path = Path(work_dir) / "proof.md"
    if not proof_path.exists():
        return False, "no_proof"
    content = proof_path.read_text()
    if "\\boxed" in content or "boxed{" in content:
        return True, "has_boxed"
    return False, "no_boxed"
```

### v1方案（机械拼接，已废弃）

把AI之前完成的reasoning_content作为新prompt的上下文注入。只传reasoning_content（thinking），不传tool_calls/observation。

**问题**：Round 1有多个agent step时，v1方案只传最后一个step的reasoning_content，丢失了前几步的全部上下文。

### v2方案（交接文档，当前使用）

从完整探索历程中提取有效内容，整理成结构化的研究文档（HANDOFF.md），交给下一个AI继续。

```python
def generate_handover(export_path, problem_id, round_num, problem_text, work_dir):
    # 1. 读export的conversation.json
    # 2. 提取所有agent step的reasoning_content + tool_calls + observation
    # 3. 整理成HANDOVER.md（结构化的研究文档）
    # 4. 写到work_dir/round{N}_HANDOVER.md（用round编号区分，防止覆盖）
    # 5. 面包屑地图写到work_dir/round{N}_conversation_map.md
    return handover_path
```

**中间产物不可覆盖原则**：所有中间产物用round编号区分路径（`round{N}_HANDOVER.md`/`round{N}_conversation_map.md`/`round{N}_proof.md`），不被后续round覆盖。详见`framework-checklist.md`第13项。

### proof.md归档机制

完成判定时（proof.md有boxed答案），归档proof.md为`round{N}_proof.md`，防止后续round覆盖：

```python
if is_completed(export, work_dir):
    # 归档proof.md
    archived = work_dir / f"round{round_num}_proof.md"
    shutil.copy2(work_dir / "proof.md", archived)
    # run级proof_path指向归档路径（不会被覆盖）
    mark_run_completed(run_key, "COMPLETED", proof_path=str(archived))
```

启动新round前删除旧proof.md，防止is_completed误判：

```python
# Round 2+启动前
old_proof = Path(work_dir) / "proof.md"
if old_proof.exists():
    old_proof.unlink()  # 删除上一轮的proof.md
```

### 多轮逻辑（`launch_batch()`）

```python
for each run:
    for round in 1..max_rounds:
        if round == 1:
            # 用原始export
            prompt = build_initial_prompt(problem_text)
        else:
            # 续传——用v2或v1方案
            if method == "v2":
                handover = generate_handover(...)
                prompt = build_v2_continue_prompt(problem_text, handover, round-1)
            else:
                prev_rc = extract_reasoning(prev_export)
                prompt = build_continue_prompt(problem_text, prev_rc, round-1)

        # 启动devin cli
        tmux new-session -d -s {name}-{pid}-r{round} "devin -p --prompt-file {prompt} ..."

        # 等待完成
        if is_completed(export, work_dir):
            mark_run_completed(run_key, "COMPLETED")
            break
        elif is_truncated(export):
            # 截断——继续下一轮
            continue
        else:
            # 异常
            mark_run_failed(run_key, "ERROR")
            break
    else:
        # max_rounds轮后仍未完成
        mark_run_completed(run_key, "TRUNCATED_AT_MAX")
```

### 新Pipe是否需要多轮续传

- **如果任务可能在单次API调用内完成**——不需要多轮续传，删除v1/v2/handover相关代码
- **如果任务可能超过25000 completion_tokens**——需要多轮续传，参考Pipe 4的实现

## 5. 断点续传

### 问题

批量运行可能因为各种原因中断（系统重启、launcher崩溃、手动停止）。恢复时需要能跳过已完成的题。

### 实现

- `results.json`记录已完成的题——`continuation_collector.py`的`collect_and_prepare()`检查已有结果，跳过已完成的题
- DB中run记录的status字段——`prepared`/`running`/`completed`/`failed_*`，恢复时只处理`prepared`和`failed_*`的run
- Redis队列——`clear_all()`清空后重新feed，或不清空直接继续（优雅停止模式下队列保留）

### 恢复方法

```bash
# 优雅停止后恢复——队列保留，直接重启launcher
python run_continuation_pipeline.py --batch-id p27-full --step launch

# 强制停止后恢复——需要重新feed
python run_continuation_pipeline.py --batch-id p27-full --step feed
python run_continuation_pipeline.py --batch-id p27-full --step launch
```

## 6. 失控循环防护（016事故P0修复，2026-08-20新增）

### 问题

2026-08-20凌晨事故（详见 `dev-docs/016-动态并发设置失效与amo_bench失控循环事故调查报告.md`）：
`amo_bench_00000006` 陷入"旧产物秒判→截断重入队→再启动"的失控循环，18分钟内启动
上千个 handover session，真实并发远超设定值，浪费 API 配额。

### 三个叠加根因与对应修复（`continuation_launcher.py` / `continuation_feeder.py` / `continuation_redis_queue.py`）

1. **判定函数读文件即判，不校验产物归属**：
   `is_truncated` / `is_completed` / `check_handover` 增加了 `since_ts`（本轮启动
   时间戳）参数——export/proof.md/HANDOVER.md 的 mtime 早于 since_ts 视为历史
   残留旧产物，不能判定本轮结果。主循环所有调用点都传了 `info["started_at"]`。
   round1 分支改为总是从 seed_export 覆盖拷贝 round1_export.json（它的语义就是
   seed 的镜像，覆盖无损），杜绝残留旧文件误判。

2. **feeder 重置截断重入队的优先级**：
   `enqueue_pending` 改为 NX 模式（`zadd nx=True`）——已存在的 member 不覆盖
   score。截断重入队用 `priority=round_num` 排队尾，feeder 重喂 `priority=0`
   不会再把它拉回队首。

3. **feeder 死循环**：`feed_batch` 原来返回"处理数"而非"新入队数"，主循环
   `while True` 永不退出。现在只统计 zadd 新增的（NX 返回 1 的），第二轮
   返回 0 自然退出。

### 同 run_key 防抖（最后一道闸）

launcher dequeue 后先做两个检查，命中则低优先级（priority=9999）重入队跳过：

- **内存检查**：run_key 已在 `running`/`handover_pending` dict 中（防同进程重复启动）；
- **注册表检查**：`find_active_session` 查 `p27_sessions` 中该 run 的 session，
  且 tmux 还活着（防 launcher 重启后对孤儿 session 的题重复启动）。

### 单元测试

`scripts/test_016_p0_fixes.py` —— 14 个断言覆盖 since_ts 校验/NX 幂等/
feeder 计数/队首顺序，运行：`source .env && python -m scripts.test_016_p0_fixes`

### 行为流水可观测性层（同日新增）

P0 修复拦住了已知循环，但 Master Agent 仍"看不见"系统的逻辑流动。新增
`src/observability.py`（行为流水/黑匣子）：

- **写侧**：launcher 每个状态转移（dequeue/skip_duplicate/skip_orphan/
  launch_solve/launch_handover/judge/requeue/round_done/run_completed/
  run_failed/graceful_stop）追加 JSONL 到 `log/flow/flow-YYYYMMDD.jsonl`，
  含判定理由（judge事件的reason）。写失败静默，绝不影响launcher主流程。
- **读侧**：`python -m src.observability --stats --since 1h`（聚合：启动速率/
  每题启动Top10/失控嫌疑/判定分布/重入队原因）、`--tail N`、
  `--run-key <key>`（单题完整生命周期）、`--event <type>`、
  `--clean-days 14`（保留14天）。
- **monitor 新检查**：A13 真实并发四源审计（**按solve/handover拆分**——DB/Redis的running只记solve，不拆分会把handover进行中误判为脱节）、A14 启动抖动（同 run 1小时≥5次 launch → critical）。A1 修复：并发从DB读+补"实际>设定"分支。alert `_key` 加随机后缀（MON-A!02修复）。launcher 防抖重入队加 `requeued_keys` 守卫（防"队列仅剩被跳过题"时poll内死循环）。
- **SOP 集成**：SOP_01 新增第8节"系统流动历史观察"（必查项），含判断标准表；`monitor_check_continuation.sh` 新增第9节输出行为流水统计。
- **测试**：`scripts/test_016_observability.py`（27 断言：读写过滤/聚合/churn告警模拟/DB并发读取/alert key唯一性/session分类）。

### 步进门闸（2026-08-20定稿：语义动作闸+X/Y注意力模型）

`src/step_gate.py`——`@gated`装饰器把**语义动作**（9个=launcher 8 + feeder 1：
启动solve/handover、kill session、截断/防抖重入队/初次入队、round1种子覆盖、
删旧proof、写COMPLETED终态）变成可单步跟踪门闸：

- **函数名=日志标志**：`launch_solve`→`GATE-LAUNCH-SOLVE`，grep直达；
- **docstring=自包含文档+checklist闭包**：注册表经inspect自动收集进
  `p27_step_gates`集合；"放行前Master Agent应检查"段是机器可提取接口，
  `--pending`和SOP_01例程按它截取完整输出——Master Agent在单步时刻直接
  拿到检查清单；
- **X/Y注意力模型**：X=mode（布防），Y=waiting_for（触发）。无Y不操心
  （auto静默记gate_pass流水）；hold未触发也是信息（该路径未发生）；
  SOP_01例行检查已接线Y通道（有Y自动打印闭包）；
- **范围铁律**：只对语义动作设闸——底层I/O封装（redis_queue）**不设闸**
  （多调用方正确性标准不同，写不出统一checklist——"所有Redis写全闸"的
  L1方案已试行并回退，教训见StepGate.md §3）；只读判定靠行为流水；
  resource参数只是分类标签（action/redis/db/file/tmux）供
  `--hold-resource`批量操作；
- **DB信号**：mode(auto/hold)+proceed(0/1)——hold时代码轮询proceed，
  0→1后代码自清零继续（Master Agent用`--step`放行）；
- **CLI**：`python -m src.step_gate --register/--list/--hold/--step/
  --pending(完整checklist)/--auto/--hold-resource RES`；
- **测试**：`scripts/test_016_step_gate.py`（13断言）+ sim全流程下
  gate_pass/gate_done流水验证（dev-docs/017）。

### 全流程模拟系统（2026-08-20建成，dev-docs/017）

`src/sim/`——被测系统100%真代码真跑，唯一替换的是devin命令（SIM_MODE=1
时换成剧本演员`fake_devin.py`，命令结构与生产一致）。四层隔离（独立DB/
Redis前缀/文件根/sim_题目id）可与生产并行。7剧本覆盖launcher全部分支
（solve3/first_try/never/dead/stall/h_timeout/chaos_016）+016动力学
回归不变量。四源终态断言（DB/Redis/flow流水/tmux）。

**运维要点**：
- 改launcher后跑`solve3`+`chaos_016`两剧本作**发布门禁**；
- 隔离环境只通过`run_sim`程序化设置——**绝不手动export后跑setup/teardown**
  （018事故的直接诱因）；
- 入口：`.venv/bin/python -m src.sim.run_sim --scenario <名> [--keep]`。

### 2026-08-20五bug修复+018事故（详见dev-docs/017 §5、dev-docs/018）

sim首日运行捕获5个真bug（全部已修+回归全绿），**launcher重启后生效**：

| 级别 | bug | 生产影响 |
|---|---|---|
| P0 | 截断判定被dead分支抢占，多轮续传引擎不可达 | 真实截断全被误判dead_session（4712实证）；核心使命的截断半边失效 |
| P1 | 主循环退出条件漏handover_pending | 批次最后一题走v2时被晾半路 |
| P1 | rounds_log不补录round-1条目→R2重跑一次 | 多耗一轮handover+solve；round2产物被二次启动覆盖 |
| P2 | TRUNCATED_AT_MAX不写run_completed流水 | 黑匣子漏终态 |
| P2 | 四处failed终态不写run_failed流水 | 黑匣子漏终态 |

**018事故**：sim收尾时teardown护栏不对称（缺文件根检查）+手动env漏设
→误删生产D盘p27-continuation。124份proof永久丢失（DB只存路径）；
5958个work_dir经collector重跑重建验证。加固：teardown护栏补全、
session匹配修复、**finalize把proof文本入库**（continuation_results双写）。
防再犯三条：清场默认值不指向生产；破坏性操作先预览目标；成果文件必须双写。

---

## 循环监控SOP（2026-08-18新增）

**核心认知**：检查脚本的输出不仅是信息，更是对AI的行动指令。AI通过反复运行检查脚本，形成"检查→处理→等待→再检查"的循环，直到所有题完成。这个循环可以跨越多个session——session被中断后，下一个session的AI只需运行检查脚本即可恢复全部上下文。

### 循环监控步骤
1. 运行标准化检查脚本（`monitor_check_continuation.sh` for Pipe 4, `monitor_check.sh` for Pipe 1/2/3）
2. 阅读检查脚本的输出——7项检查结果+行动清单+循环监控指令
3. 按行动清单逐项处理（重启挂掉的服务、处理alert、重新入队失败的题、修复代码bug）
4. 等待60-120秒，让devin cli继续工作
5. 再次运行检查脚本——如此循环，直到进度显示所有题completed或failed
6. 如果发现系统问题（代码bug/架构问题），修复代码后重启系统，然后继续循环监控

### 跨session连续性
- 检查脚本的输出包含系统当前状态、需要处理的问题、以及循环监控指令本身
- session被中断后，下一个session的AI只需运行检查脚本——脚本的输出会告诉你系统当前状态和需要做什么
- 不需要阅读之前的session历史——检查脚本是自包含的上下文恢复机制

### 系统健康判断标准
- ✅ 健康 = launcher+monitor运行中 + devin cli活跃（pane有内容）+ 进度在推进
- ⚠️ 需关注 = 有新alert + 失败率>15% + handover生成慢
- ❌ 修复 = launcher/monitor挂了 + devin cli全卡住 + 进度停滞
