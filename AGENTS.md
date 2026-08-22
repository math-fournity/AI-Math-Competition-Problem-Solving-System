# AGENTS.md — 续传解题系统

> **接手第一步**：先用 read 工具完整加载 `README.md`。它是 repo 的 AI 工作引导地图——
> 开头"〇、核心资产"段告诉你 repo 有 SOP/src/docs 三套运行支柱及各自入口，下方分类法
> 索引每个文档讲什么、覆盖哪些问题场景、和其他文档的关系。读完 README.md 再读本文件。
> 本文件只放铁律 + 最小索引，文档详细定位见 `README.md`。

## 核心概念：解题管线（Solve Pipeline）

**解题管线** = 一道题从第一次解题→观察/续传→再解题→形式化验证→独立审计→确认正确
或用户明确永久放弃的完整生命周期。AI 某轮放弃、预算耗尽或本次默认 Round 额度用完，都
不是题目永久寿命终点。系统里只有这一条长期管线，Pipe 1/2/3（分析/审计/选题）已删除。

> **⚠️ 2026-08-22 最终成品认知已冻结**：未来实现者先读
> `dev-docs/057-最终成品系统大图与产品定义.md`、
> `058-最终成品系统Feature-List与需求追踪.md`、`059~063` 专题规范和
> `dev-docs/final-system-workpackages/README.md`。当前代码仍有与目标相反的历史语义，
> 完整差距见 `064-当前实现差距与实施路线总图.md`。这些目标文档优先于下方旧代码现状
> 描述，但不得把“目标”谎称为“已实现”。

**关键性质：管线内部角色串行。** 当前 legacy 代码顺序调用 devin cli；最终目标是专职
observer/solver 经 OpenCode ACP 主后端或 Devin 备用后端执行。无论后端，一道题任意时刻
最多 1 个解题工作实例，观察者和解题者不会同时运行。因此：

> **解题并发数 = 同时在跑的解题管线条数 = 任意时刻解题工作实例数上限**

设 concurrency=1 = 一次只有 1 道题在走解题管线 = 任意时刻最多 1 个 observer/solver
实例。审计等其他角色的资源必须另行如实记账，不能偷偷混入或突破 key 容量。并发数从 DB
动态读取（见下方“并发控制”）。

### 解题管线在代码中的体现

一道题走管线的完整流程，对应这些模块/脚本：

```
① 入题  continuation_collector.py    从 problem_list.json 加载题，创建 DB run 记录（status=prepared）
② 入队  continuation_feeder.py       把 prepared 的 run 入 Redis pending 队列
③ 启动  continuation_launcher.py     主循环：从队列取题→启动 devin cli→监控状态→判定终态
   ├─ handover 阶段  start_handover()  devin cli 生成 round{N}_HANDOVER.md（占并发槽）
   └─ solve 阶段     launch_solve()    devin cli 解题，写 proof.md（占并发槽）
④ 监控  monitor_continuation.py      A/B 类自动检查（session健康/队列推进/rate_limit/zombie...）+ 生成 alert
⑤ 收集  continuation_result_collector.py  收集终态 run 的产出
⑥ 控制  monitoring/continuation_control.py  start/stop/status/set-concurrency/sessions 管理
⑦ 看门狗 scripts/continuation_watchdog.sh  auto-restart launcher/monitor
```

**管线内部串行的代码依据**：`continuation_launcher.py:1172`——handover_pending 和 running 共享并发槽：
```python
while ... len(running) + len(handover_pending) < concurrency ...
```
handover 完成后才启动 solve，一道题不会同时跑两个 devin cli。

### 当前实现判定与最终目标语义（必须区分）

| 事件 | 当前实现 | 最终目标语义 |
|---|---|---|
| proof.md 含 `\boxed` | 直接按完成处理 | 仅“候选成功”；必须有充分形式化包并经独立审计通过才确认数学正确 |
| AI 输出放弃信号 | 当前按 `ai_gave_up` 终止本次 run | 只代表本轮/本实例放弃；题目未来仍可继续 |
| 本次 Round 窗口额度用完 | 写 `status=window_exhausted`、`final_status=null`，不进永久终态队列 | 保存现场、释放资源、未来显式开启新窗口并从下一绝对 Round 继续 |

历史 `TRUNCATED_AT_MAX` 保持只读兼容，未经用户批准不批量迁移。形式化候选/最终正确的
剩余实施见最终工作包 WP-04/05。


### v2 解题管线（当前开发中——与上方 p27 续传管线独立）

**v2 是当前活跃开发的解题管线**，使用 OpenCode ACP + Ox Alpha 后端，融合观察者/解题者递归消化链架构（详见 `dev-docs/053-v2续传编排技术说明书-观察者做题者递归消化链.md` 与 `dev-docs/054-v2架构影响评估与行动方案.md`）。

| 维度 | 说明 |
|---|---|
| 启动 | `python scripts/run_v2_batch.py --batch-id v2-p27-full`（直接运行，不走 continuation_control） |
| 停止 | kill tmux session `v2-batch`（**continuation_control stop 不覆盖此管线**） |
| 模型 | openrouter/stealth/ox-alpha，effort=max |
| 架构 | 观察者/解题者两阶段轮替 + 递归消化链 + BUDGET_STARVED 指纹 |

**与其他管线的关系**：
- 上方 p27 续传管线（devin -p + tmux）：过渡期保留，最终将被 v2 替代
- 平凡解题系统 pipe-*（solver_harness）：不同 repo 的旧系统，仅知其存在
- 三条管线各自独立启停——停一条不停其他

### 并发控制

**目标最大并发解题管线暂定 30**。30 是产品目标容量/上限，不是代码默认值；实际并发仍
由 DB batch.concurrency 和用户动态决定，可以低于 30。OpenCode ACP 还受系统内部 key
可用 slot 约束：每个实例取得一个 lease，每个 key 的 `capacity` 可配置，可支持一个或多个
实例，不得写死一 key 一实例或两实例。key 规范见 `dev-docs/062-*`。

**并发数存在 DB 的 batch 记录里，launcher 每轮 poll 从 DB 读取**（`continuation_launcher.py:1041-1052`）。改并发不改代码：
```
python -m monitoring.continuation_control set-concurrency --batch-id p27-full --concurrency 1
```
launcher 下次 poll 自动生效（通常 15 秒内）。只影响后续新启动的管线，不影响正在跑的。启动时如果 DB 已有 concurrency 则用 DB 的，否则用 `--concurrency` 参数初始化（`continuation_launcher.py:964-969`）。

详细概念文档：`docs/architecture/solve-pipeline.md`。动态并发设计：`docs/architecture/dynamic-concurrency.md`。

---

## ⚠️ 启动指令（最前面，不可截断）

### 触发短语 → 动作对照

| 用户说 | 你做什么 |
|---|---|
| `开启系统` / `启动系统` / `开启解题系统` / `启动解题系统` | **启动解题系统 + 启动 SOP 监控循环**（完整流程，见下方） |
| `启动监控` / `开启监控` / `开始监控` / `开始工作` | **只启动 SOP 监控循环**（不启动解题系统，假设系统已在运行，见下方） |
| `停止` / `停` / `结束` / `停止监控` | **停止 SOP 循环 + 停止解题系统**（见下方停止命令） |
| `查看SOP状态` / `SOP状态` | **查看 SOP 流程状态**（`python -m scripts.sop._set_next status`） |

---

### 动作1：启动解题系统 + SOP 监控（触发：开启系统/启动系统/开启解题系统/启动解题系统）

1. **启动解题系统**（如果尚未运行）：
   ```
   source .env
   python -m monitoring.continuation_control start --batch-id p27-full --concurrency 1
   ```
   确认 launcher/monitor 两个 tmux session 都在运行（`start` 只启动这两个；watchdog 可选，不由此命令启动——需 launchd plist 或手动 `tmux new-session -d -s p27-watchdog "bash scripts/continuation_watchdog.sh --batch-id p27-full"`）。
   **注意**：`--concurrency 1` 只是初始值。如果 DB 的 batch 记录里已有 concurrency 字段，launcher 会用 DB 的值覆盖命令行参数。运行中改并发用 `set-concurrency`（见上方"并发控制"），不要重启 launcher。

   > **这两条命令都是短命令，可以直接在 shell 里裸跑**：
   > - `continuation_control start` 执行完就退出，它内部自己用 `tmux new-session -d` 把 launcher/monitor 两个长服务各自放进独立 tmux session（`continuation_control.py:158-161`）——你不需要手动套 tmux。
   > - `python -m scripts.sop.run` 每次只跑**一个 SOP 步骤**就退出（`scripts/sop/run.py:48-113`，读 `_state.json` 决定步骤→执行检查→推进状态→退出）。所谓"7x24 持续循环"是 Master Agent 用 `todo_write` 自驱动一次次执行 `sop.run`，循环的承载者是 AI 本身，不是某个后台脚本。

2. **启动 SOP 监控循环**：
   ```
   python -m scripts.sop.run
   ```

3. **持续循环**——用 `todo_write` 建 todo list，最后一项固定是"执行 `python -m scripts.sop.run`"。完成当前阶段所有 todo 后，执行最后一项自动触发下一阶段。9 步循环（01→02→03→04→05→06→07→Z→OP→01...）持续运行，这就是 7x24 监控。

4. **停止条件**——只有以下情况停止循环：
   - 用户说"停止"/"停"/"结束"→ 执行停止命令
   - 检查脚本显示"所有任务已完成"（pending=0, running=0）→ 执行停止命令
   - 系统出现无法自动修复的严重故障需用户介入

### 动作2：只启动 SOP 监控循环（触发：启动监控/开启监控/开始监控/开始工作）

假设解题系统已在运行，只启动 SOP 循环：
```
python -m scripts.sop.run
```
然后同样用 `todo_write` 自驱动持续循环。

### 停止命令

```
# 优雅停止（推荐）——launcher收到SIGINT后不再启动新run，等running自然完成
python -m monitoring.continuation_control stop

# 强制停止——停服务+清理done session+清空Redis队列（stuck/running不kill，等DONE.md）
python -m monitoring.continuation_control stop --force
```

### SOP 流程状态查看和跳步控制

```
# 查看当前 SOP 流程状态（上一个/下一个步骤/循环轮次）
python -m scripts.sop._set_next status

# 强制设定下一步（跳步用——正常情况下不需要，SOP自动推进）
python -m scripts.sop._set_next 03        # 跳到步骤03（alert分类）
python -m scripts.sop._set_next 01        # 回到循环开始（系统健康检查）
python -m scripts.sop._set_next Z         # 跳到元/整体检查
```
有效步骤编号：`01` `02` `03` `04` `05` `06` `07` `Z` `OP`

### 其他控制命令

```
python -m monitoring.continuation_control status --batch-id p27-full    # 查看系统状态
python -m monitoring.continuation_control health --batch-id p27-full    # 健康检查
python -m monitoring.continuation_control set-concurrency --batch-id p27-full --concurrency 3  # 动态调并发
python -m monitoring.continuation_control sessions --status stuck       # 查看stuck session
python -m monitoring.continuation_control sessions --clean-done         # 批量清理done session
python -m monitoring.continuation_control sessions --consistency-check  # 注册表vs tmux一致性
python -m monitoring.continuation_control resolve-alert <alert_key>      # 标记alert已处理（SOP_06）
python -m monitoring.continuation_control resolve-alert --all-critical   # 批量resolve所有critical alert
python -m monitoring.continuation_control mark-ai-review <run_key> --result PASS  # 标记AI判断完成（SOP_04）
python -m monitoring.continuation_control mark-ai-review <run_key> --result FAIL --note "C2幻觉"
```

### 硬约束：判断系统状态必须查过程证据 + 直接检查

> **详见** `.devin/rules/verify-with-logs.md`（always-on rule——过程证据三层法）
> **详见** `.devin/rules/direct-verification-ironlaw.md`（always-on rule——最底层实物直接检查）

**任何判断系统状态时，必须查过程证据（日志+行为流水），不能只看 DB 结果。** DB 是"结果"，日志是"过程"——只看结果不看过程会漏掉状态同步 bug、得出错误结论。**且结论必须有最底层实物的直接证据**（硬盘文件/tmux/进程实物）——DB 与 Redis 是转述不是事实（028 教训：DB 说 138 题完成、硬盘仅 14 个 proof.md）。两条规则叠加：查 DB→查日志/流水→查实物，下结论三层都要有。

触发时机：接手时确认状态 · 用户问"做题成功吗" · commit 前验证 · DB 与文件不一致时。

```
# 第1层：DB 查结果
python -m monitoring.continuation_control status

# 第2层：日志查事件流
python -m scripts.sop.log_search --problem-id <pid>
python -m scripts.sop.log_search --level ERROR --since "2026-08-21 01:43"

# 第3层：行为流水查状态转移链
python -m src.observability --run-key <run_key>
python -m src.observability --stats --since 1h
```

三层交叉验证——DB 说 completed 但 flow 无 run_completed = 状态同步 bug。

### 硬约束：禁止代码中写死并发数

**并发数的默认值来源只有一个：本 AGENTS.md。** 代码中禁止写死任何并发数默认值（如 `DEFAULT_CONCURRENCY = 5`、`AUDIT_DEFAULT_CONCURRENCY = 5`）。

**为什么**：
- 并发数 = 同时在跑的管线条数 = devin cli 实例数上限（见上方"核心概念"）
- 这个数字影响 API 配额消耗、系统资源占用、rate limit 风险——是系统级配置，不是代码级常量
- 写死在代码里 = 改并发要改代码 = 违反"改并发不改代码"的设计原则
- 030 教训：`proof_audit_config.py` 写死 `AUDIT_DEFAULT_CONCURRENCY = 5`，这个 5 是拍脑袋设的，没有依据（没有实验、没有推理、没有 rate limit 分析）

**正确做法**：
- 续传系统：并发数存 DB batch 记录，launcher 每轮 poll 从 DB 读取（见上方"并发控制"）
- 审计系统：同样从 DB batch 记录读取，或从本 AGENTS.md 读取
- 代码中只写"从 DB/AGENTS.md 读取并发数"的逻辑，不写默认值
- 如果 DB 中没有并发数记录，launcher 应该报错并提示"请先设置并发数"，而不是用写死的默认值

**当前违规**：~~3 处写死~~ **已全部修复**（2026-08-21 WP-G，commit 见 git log）：
- `continuation_config.py` / `proof_audit_config.py` 的两个常量已删
- `run_proof_audit_pipeline.py` / 两个 launcher 的 argparse default 已改 None
- `continuation_control.py start` 的 default=5 已改 None（透传 launcher 执行硬约束）
- `monitor_continuation.py --concurrency default=5` 已改 None（无值时跳过并发比对，保留存活检查）

**现行机制**：并发数唯一来源 = DB batch.concurrency（set-concurrency 设置）；DB 无记录
且未传参 → 报错退出，不做数值兜底。审计批次与续传批次同集合同命令。
**并发数值由用户决定**（2026-08-21 用户裁定：AI 不做推荐实验；系统解决问题能力优先
于参数寻优）。

### 硬约束：适度依赖 Master Agent 介入——不追求完全自动化判定

**原则**：系统不必追求"所有判定都自动化"。如果某些判定系统无法完美做出，**交给 Master Agent 侧完成最终判定和收场**——这比把不完美的判定逻辑硬塞进代码更好。

**为什么**：
- 追求 100% 自动化判定会导致代码中堆砌大量边缘情况处理——判定逻辑臃肿、难维护、易出错
- 适度依赖 Master Agent 介入可以让代码和运行逻辑在某种意义上更"干净"——代码只做能可靠做的事，做不了的事明确标记为"待人工"并交给 Master Agent
- Master Agent 有完整上下文和判断能力，比代码中的硬编码规则更能处理边缘情况
- 系统的 alert 机制本身就是这个理念的具体实现——系统检测到异常但不自动修复，创建 alert 交给 Master Agent 判断

**具体表现**：
- **终态分类不完美时**：代码做出能可靠判定的分类（completed/dead_session/timeout），分类不明确的标记为"待人工复查"（如 PARSE_ERROR → `audit_passed=None` + 创建 alert，不改 status，等人工处理——029 §3.3 设计）
- **孤儿 session 等边缘情况**：SOP_07 检查发现 tmux session 与 Redis running 不一致 → 创建 alert，Master Agent 判断该 kill 还是该等
- **审计结果无法自动解析时**：result_collector 标记 PARSE_ERROR 不走 FINALIZE-FAIL 门闸，保留原 status，等 Master Agent 人工复查
- **并发数等系统级配置**：代码不写死，从 DB 读取，由 Master Agent 通过 `set-concurrency` 设置

**设计准则**：
1. **代码做能可靠做的事**——可靠的终态判定（有 proof/无 proof/超时）放代码
2. **不可靠的判定标记为"待人工"**——不强行自动判定（PARSE_ERROR、语义质量、边缘终态）
3. **"待人工"必须有可发现的痕迹**——创建 alert 或标记字段（`audit_passed=None`），Master Agent 通过 SOP 检查发现
4. **边界判据（033 补充）**：检验一个判定属于哪边——"能否写成确定性函数并单测覆盖？"能→代码；不能→标"待人工"+alert，绝不硬写启发式。模式匹配类检测项的完备性靠 SOP 漏判发现机制迭代，不靠一次写全
4. **不为"待人工"情况写复杂的自动判定逻辑**——那是 Master Agent 的工作，不是代码的工作

**反模式**：
- ❌ 为了"自动化"把 PARSE_ERROR 也走 FINALIZE-FAIL 自动改 status=audit_failed——这会让题目被错误排除出选题池（031 C1 / 032 C1 验证的问题）
- ❌ 为了"完美"在代码中堆砌大量边缘终态判定逻辑——臃肿且易出错
- ✅ 代码做可靠判定，不可靠的标记"待人工"+创建 alert，Master Agent 通过 SOP 收场

### 硬约束：解题运行结果资产保留铁律

**原则**：整个系统运行的所有解题结果，无论是最终做出来了还是没有做出来的，都是宝贵的运行结果资产。**每一个 round 都必须全部保留目录、文件、export 出来的 conversation.json 等数据。禁止删除、覆盖、清理任何 round 的产出。**

**为什么**：
- 没做出来的 round 的 conversation.json 包含 AI 的完整推理过程（尝试了什么、为什么失败、走到哪一步）——这是分析 AI 能力边界的宝贵数据，比做出来的 round 更有价值
- 每轮的 export/proof/prompt/HANDOVER 都是 run 的完整生命周期证据——删除任何一环都会破坏可审计性
- 系统是数据采集器 + 可靠判定器，不是全知全能的自动机——保留所有数据是 Master Agent / 人类 / 未来 AI 分析的前提

**必须保留的产出**（每个 round）：
| 产出 | 位置 | 保留要求 |
|---|---|---|
| `conversation.json`（export） | `{TRAJECTORY_BASE}/p27-continuation/{run_key}/round{N}/exports/` | **必须保留**——含 thinking/reasoning_content，是最核心的资产 |
| `proof.md` 归档 | work_dir/`round{N}_proof.md` | **成功轮必须归档**——`shutil.copy2` 在判定完成时执行 |
| `round{N}_prompt.txt` | work_dir | **必须保留**——每轮的提示词是复现条件 |
| `HANDOVER.md` | work_dir | **必须保留**——续传交接信息 |
| tmux pipe log | `round{N}/tmux/` | **必须保留**——tmux 原始输出 |
| DB rounds_log | `p27_continuation_runs.rounds_log` | **必须完整**——每轮的 export_path/prompt_path/proof_path/reason |

**审计系统同样适用**：审计的 `conversation.json` 无论审计是否成功，都必须保留——审计失败的 conversation.json 包含审计 AI 的推理过程，是分析审计质量的数据。

**唯一允许的删除**：`remove_old_proof()`（`continuation_launcher.py`）在启动新一轮前清理上一轮残留的 `proof.md`——这是防止旧 proof 被误判为完成的必要操作（016 事故 P0-2 根因）。**删除前自动归档为 `round{N}_proof_partial.md`（2026-08-21 WP-S 起，无 boxed 的部分证明同样留档）**；成功轮归档仍为 `round{N}_proof.md`（门闸检查项 2）。export/prompt/HANDOVER/tmux log 不在此列——它们永远不会被删除。

**当前存在的问题**（032 §七点六调查）：
1. **round1 的 export 存放位置不统一**——round1 的 export 只存在于 work_dir 的 `round1_export.json`，不在 `round1/exports/conversation.json`（其他轮的存放位置）。需要统一（WP-S 行动项 1）
2. 需要验证是否有手动清理脚本会误删 work_dir 或 round 目录

**反模式**：
- ❌ 为了"节省磁盘空间"清理失败轮的 export——失败轮的 export 是最有价值的资产
- ❌ 为了"干净"在 run 完成后清理 work_dir——work_dir 包含 prompt/HANDOVER/归档 proof，是 run 的完整生命周期证据
- ❌ 覆盖上一轮的 export 文件——每个 round 的 export 是独立的，不应覆盖
- ✅ `remove_old_proof` 清理旧 proof.md（前提是已归档）——这是防止误判的必要操作，不是"清理资产"

### 实战速查：016事故后新增的介入能力

> 016事故（失控循环空转18分钟、上千个session）后系统新增三种能力，SOP_01 §8/§8.5详述。这里放always-on速查——后部可能被截断，实战中你必须知道这些武器存在。

**① 行为流水——"看见"系统流动（016预警核心）**

日志只看存量（队列数/session数），016事故中存量没变但流动病态。行为流水（`log/flow/flow-*.jsonl`）记录launcher每个状态转移：

```
python -m src.observability --stats --since 1h    # 失控嫌疑/启动Top10/判定分布
python -m src.observability --run-key <run_key>    # 某题完整生命周期（含判定理由）
```

`churn_suspects`非空（1小时内某题启动≥5次）= **失控循环正在发生**，立即按016报告§5处置。

**② 步进门闸——"拦住"系统动作（单步跟踪）**

`@gated`把9个语义动作（启动/杀session/重入队/初次入队/覆盖文件/写终态）变成可冻结断点：

```
python -m src.step_gate --list                    # 门闸目录
python -m src.step_gate --hold GATE-LAUNCH-SOLVE  # 卡住下一次解题启动
python -m src.step_gate --pending                 # 看谁在等（输出完整论证依据闭包）
python -m src.step_gate --step GATE-LAUNCH-SOLVE --reason '看到1✓+2✓...理由...'  # 放行（必须附理由，落盘flow流水）
python -m src.step_gate --auto GATE-LAUNCH-SOLVE  # 恢复自动
```

SOP_01例程每轮自动查Y通道（有闸在等会打印论证依据闭包：检查项+查法+可放行/不可放行判定+理由）。**放行必须附--reason理由（落盘flow流水可grep回溯），不放行也要在report.md门闸记录区填原因——没有理由的放行=审计断点**。hold是调试模式，用完记得--auto。

**③ A13/A14应急处置（016场景重演时的critical alert）**

- **`launch_churn`(A14)**：同题1小时内≥5次启动=失控循环。**立即**：`observability --stats --since 1h`看明细→kill launcher→清空Redis队列→查根因（旧产物残留/feeder重喂）。
- **`real_concurrency_mismatch`(A13)**：tmux实际 vs DB vs Redis vs 设定四源不一致=孤儿进程/注册表脱节。查`sessions --consistency-check`清理孤儿。

详见 `docs/specs/p27_monitor_spec.md` §A13/A14、`docs/patterns/StepGate.md`、`dev-docs/016` §5。

---

## ⚠️ Master Agent SOP 流程控制机制

**你是续传解题系统的 Monitor AI。系统运行时，你通过 9 步 SOP 循环持续检查+判断+修复+报告+自我审查。**

### 核心理念

Master Agent 自己（不是独立 devin cli）作为 Monitor Pipe 的承载者。7x24 持续循环通过**自驱动 todo list 机制**实现——每个 SOP 脚本输出末尾要求用 `todo_write` 建 todo list，最后一项固定是"执行下一个脚本"，完成 todo 自动触发下一阶段。不依赖 devin -p 定时启动，因为本 repo 上下文负担小（无 .devin/rules/，AGENTS.md 聚焦），Master Agent 直接做比独立 cli 更简单且能力更强。方案详情见 `dev-docs/013-Master-Agent-SOP流程控制机制方案.md`。

### 启动循环

用户说"开始工作"时，执行 SOP 入口脚本：
```
python -m scripts.sop.run
```

### 9 步循环（6 工作 + 1 审计健康 + 1 元/整体检查 + 1 运营知识刷新）

| 步骤 | 名称 | 检查什么 |
|---|---|---|
| 01 | 系统存活+进度+Session | 进程状态/进度统计/session注册表一致性/stuck/done/门闸Y通道/行为流水/系统全景视图 |
| 02 | 数据完整性 | 每轮输入/输出文件存在性/rounds_log 6路径字段/DB-文件一致性/Redis-DB一致性/题源完成率 |
| 03 | alert分类 | 读未处理alert，分类为代码bug/数据/基础设施/需重跑/需清理 |
| 04 | C类AI判断 | 读proof.md/HANDOVER.md做C1-C6判断（数学正确性/幻觉/泄漏/质量/方向/语义） |
| 05 | 代码修复 | 修分类为代码bug的问题+py_compile+git commit+文档同步+sim发布门禁（改调度/判定逻辑时） |
| 06 | 报告+WORKLOG+Self-check | 写报告+续写WORKLOG+执行SELF-S1~S22+resolve alert |
| 07 | 审计系统健康检查 | 审计队列/失败分布/门闸Y通道/审计产出实物验证/通过题交叉验证/作弊复核/孤儿session对账/PARSE_ERROR堆积（8项含4项直接检查，WP-C） |
| Z | 元检查+整体检查 | 每个SOP步骤合理性+整体调整+方向性判断+审计（AUDIT-01~07，每5轮） |
| OP | 运营知识刷新 | 硬约束/外部索引/快速开始/SOP机制/环境验证——每轮循环末尾注入，突破AGENTS.md 16K限制 |

**自我进化机制**：Z 步骤检查整个 SOP 系统本身是否需要调整——SOP 系统不仅能修目标系统，还能修自己。

### 自驱动机制

每个脚本的输出末尾要求你用 `todo_write` 建立 todo list，**最后一项固定是"执行 `python -m scripts.sop.run`"**。完成当前阶段所有 todo 后，执行最后一项 → 自动触发下一阶段。OP 步骤的最后一项回到 01——循环回到开始。这就是 7x24 持续循环。

### 顺序校验

脚本通过 `scripts/sop/_state.json` 记录上一个/下一个应该执行的步骤。错误执行其他步骤时，脚本会拒绝并提示正确的下一步。需要跳步时：
```
python -m scripts.sop._set_next 03        # 强制设定下一步为步骤03
python -m scripts.sop._set_next Z         # 跳到元/整体检查
python -m scripts.sop._set_next status    # 查看当前状态
```
有效编号：`01` `02` `03` `04` `05` `06` `Z` `OP`

### SOP 文档与运营知识

每个SOP脚本读取并完整打印对应文档到stdout（自包含：认知闭包+执行指令+todo），不依赖AGENTS.md always-on。SOP文档目录`docs/sop/`（8个：01~06+Z+OP），脚本目录`scripts/sop/`。

**报表系统**：每次SOP步骤执行后自动在D盘生成报表目录（report.md必填/snapshot.json/snapshot_runs.json/check_output.txt），模板在`docs/sop/templates/`。不填写报表=检查没完成。

> 运营知识（硬约束全条/外部文档索引/快速开始/SOP文档与报表系统详细说明）已迁移到 **SOP_OP 步骤**——每轮循环末尾由run.py注入，突破AGENTS.md 16K限制。核心铁律索引见 L0 §7（SYSTEM_CLOSURE.md，每step注入）。

---

> **强制声明**：本 repo 的 AI 工作引导地图在 `README.md`（见本文件开头"接手第一步"）。本文件只放铁律 + 最小索引，文档详细定位见 `README.md` 引导地图。

---

## 运营知识（详见 SOP_OP 步骤）

> 项目概况 / 硬约束10条+016/017/018新增4条 / 外部文档索引 / 快速开始 / SOP文档与报表系统详细说明
> 已迁移到 `docs/sop/SOP_OP_operations_knowledge.md`（run.py每轮循环末尾注入）。
> 核心铁律索引见 L0 §7（每step注入）；文档详细定位见 `README.md` 引导地图。
