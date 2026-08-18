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

### 关键参数

- 暂停时间：1200秒（20分钟）——足够让API配额恢复
- 检测方式：pane输出文本匹配RATE_LIMIT_PATTERNS
- 暂停期间：不启动新run，但继续检查running状态

### 新Pipe如何实现

1. 从`config.py`导入`RATE_LIMIT_PATTERNS`（或自己定义）
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
pane_hash = hash(pane_output)

if session_name in last_pane_hash:
    if pane_hash == last_pane_hash[session_name]:
        # pane内容无变化
        idle_seconds = time.time() - last_change_time[session_name]
        if idle_seconds > stall_seconds:  # 默认300秒
            # 判定为stall
            tmux kill-session -t {session_name}
            mark_run_as_failed(run_key, "failed_stall")
    else:
        # pane内容有变化——更新hash和时间
        last_pane_hash[session_name] = pane_hash
        last_change_time[session_name] = time.time()
```

### 关键参数

- `stall_seconds`：默认300秒（5分钟无变化判定为stall）
- 检测方式：pane内容的hash变化
- 处理方式：kill-session + 标记为failed_stall

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
