# AGENTS.md — 续传解题系统

## 核心概念：解题管线（Solve Pipeline）

**解题管线** = 一道题从第一次解题→续传→再解题→...→解出/放弃的完整生命周期。系统里只有这一条管线，Pipe 1/2/3（分析/审计/选题）已删除。

**关键性质：管线内部顺序调用 devin cli。** 一道题任意时刻最多 1 个 devin cli 在为它工作（handover 或 solve，不会同时）。因此：

> **系统并发数 = 同时在跑的解题管线条数 = 任意时刻 devin cli 实例数上限**

设 concurrency=1 = 一次只有 1 道题在走管线 = 任意时刻最多 1 个 devin cli。并发数从 DB 动态读取（见下方"并发控制"）。

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

### 终态判定

| 终态 | 判定 | 代码位置 |
|---|---|---|
| 解出 | proof.md 存在且含 `\boxed` | `continuation_config.py:95` PROOF_COMPLETE_MARKER |
| AI 放弃 | devin cli 输出放弃信号 | `continuation_launcher.py` 状态检查逻辑 |
| 达到最大轮次 | current_round > max_rounds（默认5）| `continuation_launcher.py:1223` → TRUNCATED_AT_MAX |

### 并发控制

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
   python -m monitoring.continuation_control start --batch-id p27-full --concurrency 5
   ```
   确认 launcher/monitor/watchdog 三个 tmux session 都在运行。
   **注意**：`--concurrency 5` 只是初始值。如果 DB 的 batch 记录里已有 concurrency 字段，launcher 会用 DB 的值覆盖命令行参数。运行中改并发用 `set-concurrency`（见上方"并发控制"），不要重启 launcher。

   > **这两条命令都是短命令，可以直接在 shell 里裸跑**：
   > - `continuation_control start` 执行完就退出，它内部自己用 `tmux new-session -d` 把 launcher/monitor/watchdog 三个长服务各自放进独立 tmux session（`continuation_control.py:158-161`）——你不需要手动套 tmux。
   > - `python -m scripts.sop.run` 每次只跑**一个 SOP 步骤**就退出（`scripts/sop/run.py:48-113`，读 `_state.json` 决定步骤→执行检查→推进状态→退出）。所谓"7x24 持续循环"是 Master Agent 用 `todo_write` 自驱动一次次执行 `sop.run`，循环的承载者是 AI 本身，不是某个后台脚本。

2. **启动 SOP 监控循环**：
   ```
   python -m scripts.sop.run
   ```

3. **持续循环**——用 `todo_write` 建 todo list，最后一项固定是"执行 `python -m scripts.sop.run`"。完成当前阶段所有 todo 后，执行最后一项自动触发下一阶段。8 步循环（01→02→03→04→05→06→Z→OP→01...）持续运行，这就是 7x24 监控。

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
有效步骤编号：`01` `02` `03` `04` `05` `06` `Z` `OP`

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

**你是续传解题系统的 Monitor AI。系统运行时，你通过 8 步 SOP 循环持续检查+判断+修复+报告+自我审查。**

### 核心理念

Master Agent 自己（不是独立 devin cli）作为 Monitor Pipe 的承载者。7x24 持续循环通过**自驱动 todo list 机制**实现——每个 SOP 脚本输出末尾要求用 `todo_write` 建 todo list，最后一项固定是"执行下一个脚本"，完成 todo 自动触发下一阶段。不依赖 devin -p 定时启动，因为本 repo 上下文负担小（无 .devin/rules/，AGENTS.md 聚焦），Master Agent 直接做比独立 cli 更简单且能力更强。方案详情见 `dev-docs/013-Master-Agent-SOP流程控制机制方案.md`。

### 启动循环

用户说"开始工作"时，执行 SOP 入口脚本：
```
python -m scripts.sop.run
```

### 8 步循环（6 工作 + 1 元/整体检查 + 1 运营知识刷新）

| 步骤 | 名称 | 检查什么 |
|---|---|---|
| 01 | 系统存活+进度+Session | 进程状态/进度统计/session注册表一致性/stuck/done |
| 02 | 数据完整性 | 产出文件存在性/rounds_log 7字段/DB-文件一致性/Redis-DB一致性 |
| 03 | alert分类 | 读未处理alert，分类为代码bug/数据/基础设施/需重跑/需清理 |
| 04 | C类AI判断 | 读proof.md/HANDOVER.md做C1-C5判断（数学正确性/幻觉/泄漏/质量/方向） |
| 05 | 代码修复 | 修分类为代码bug的问题+py_compile+git commit+文档同步 |
| 06 | 报告+WORKLOG+Self-check | 写报告+续写WORKLOG+执行SELF-S1~S17+resolve alert |
| Z | 元检查+整体检查 | 每个SOP步骤合理性+整体系统是否需要调整 |
| OP | 运营知识刷新 | 硬约束/外部索引/快速开始/SOP机制——每轮循环末尾注入，突破AGENTS.md 16K限制 |

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
有效编号：`01` `02` `03` `04` `05` `06` `Z`

### SOP 文档与运营知识

每个SOP脚本读取并完整打印对应文档到stdout（自包含：认知闭包+执行指令+todo），不依赖AGENTS.md always-on。SOP文档目录`docs/sop/`（8个：01~06+Z+OP），脚本目录`scripts/sop/`。

**报表系统**：每次SOP步骤执行后自动在D盘生成报表目录（report.md必填/snapshot.json/snapshot_runs.json/check_output.txt），模板在`docs/sop/templates/`。不填写报表=检查没完成。

> 运营知识（硬约束全条/外部文档索引/快速开始/SOP文档与报表系统详细说明）已迁移到 **SOP_OP 步骤**——每轮循环末尾由run.py注入，突破AGENTS.md 16K限制。核心铁律索引见 L0 §7（SYSTEM_CLOSURE.md，每step注入）。

---

> **强制声明**：本 repo 的 AI 工作引导地图在 `README.md`。AI 必须先用 read 工具完整加载 `README.md`，才能回答用户的问题或进行后续操作。README.md 描述了每个文档讲什么、覆盖哪些问题场景、和其他文档的关系。
>
> 本文件只放铁律 + 最小索引。文档详细定位见 `README.md` 引导地图。

---

## 运营知识（详见 SOP_OP 步骤）

> 项目概况 / 硬约束10条+016/017/018新增4条 / 外部文档索引 / 快速开始 / SOP文档与报表系统详细说明
> 已迁移到 `docs/sop/SOP_OP_operations_knowledge.md`（run.py每轮循环末尾注入）。
> 核心铁律索引见 L0 §7（每step注入）；文档详细定位见 `README.md` 引导地图。
