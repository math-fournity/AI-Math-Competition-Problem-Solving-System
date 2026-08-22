# src/README.md — 续传解题管线实现代码导航

> **本文件是什么**：`src/` 目录的认知入口地图。新 AI 进入 `src/` 时先读本文件，
> 知道每个模块讲什么、覆盖哪些问题场景、该读哪些 docs。本文件只做导航，不重复
> 各模块 docstring 的详细内容和 `docs/sop/SYSTEM_CLOSURE.md` §4 的"异常时的表现"。
>
> **系统级认知**：`docs/sop/SYSTEM_CLOSURE.md`（架构/生命周期/判定框架，每次SOP注入）。
> **根目录引导地图**：`README.md`（全 repo 文档分类法索引）。

> **当前/目标边界（2026-08-22）**：WP-01 已把最大轮次迁移为无限可续传的调度窗口；
> 生产 launcher 仍只有 v1/v2，专职观察者/解题者、形式化充分性审计、OpenCode key lease
> 和目标最大并发30仍待后续工作包，见
> `dev-docs/057~064` 与 `dev-docs/final-system-workpackages/`。不要把目标误称已实现。

---

## 目录角色

`src/` 是续传解题管线（Solve Pipeline）的实现代码。系统只有这一条管线——
对失败的数学题启动多轮 handover→solve 循环，让 devin cli 接力解题；每次调度窗口默认
处理若干数学 Round，窗口用完后题目保持可继续。Pipe 1/2/3（分析/审计/选题）已删除。

管线内部顺序调用 devin cli：一道题任意时刻最多 1 个 devin cli 在为它工作
（handover 或 solve，不会同时）。**系统并发数 = 同时在跑的管线条数 =
devin cli 实例数上限**。详见 `docs/architecture/solve-pipeline.md`。

---

## 一、主管线模块（4个，按数据流顺序）

```
continuation_collector → continuation_feeder → continuation_launcher → continuation_result_collector
   收集失败题入DB          入Redis队列         并发启动devin cli解题       汇总最终结果
```

### `continuation_collector.py` — 数据收集（管线入口）

从 `problem_list.json` 取失败题，为每道题构造续传 run 记录入 DB（status=prepared）。

**覆盖问题场景**：管线无输入时（题目未入 DB=collector 没跑或失败）；新建批次时。
**用法**：`python -m src.continuation_collector --batch-id p27-full`
**依赖**：`continuation_config`（路径/集合名）；DB schema 见 `continuation_db_schema`。

### `continuation_feeder.py` — 入队（prepared → Redis pending）

从 DB 取 prepared 的 run，入 Redis pending 队列（NX 幂等，priority=0 最高）。

**覆盖问题场景**：死循环重喂（016：队列永远清不空）；prepared 堆积但 pending=0 时。
**用法**：`python -m src.continuation_feeder --batch-id p27-full`
**依赖**：`continuation_redis_queue`（队列操作）；`step_gate`（`GATE-FEED-ENQUEUE` 闸）；
`observability`（行为流水）。

### `continuation_launcher.py` — 并发引擎（管线核心，99KB）

并发引擎：dequeue → launch devin cli → judge（截断/完成/放弃）→ requeue/done。
复用 analysis_launcher 的 stall/rate_limit/zombie 检测模式，适配多轮续传逻辑。
核心差异：多轮续传（`round_window_size` 只限制本次窗口）、v2方案双pipe（先 handover 再 solve）、
完成判定（proof.md 含 `\boxed`）、更长 timeout（30分钟）。

**覆盖问题场景**：失控循环（016：同题高频启动）；截断误判（017 P0：真实截断被误判
dead_session）；并发控制（DB batch 记录覆盖命令行参数）；窗口结束
（`window_exhausted`非永久终态）；round-1 seed 预检轮。
**用法**：
```
python -m src.continuation_launcher --batch-id p27-full --concurrency 1 --round-window-size 5 --method v2
python -m src.continuation_launcher --status --batch-id p27-full
python -m src.continuation_launcher --stop --batch-id p27-full
```
**依赖**：`continuation_config`（所有阈值/路径/模型）；`continuation_db_schema`；
`continuation_redis_queue`；`session_registry`（session 编号化）；
`step_gate`（8个闸：REMOVE-OLD-PROOF/START-HANDOVER/LAUNCH-SOLVE/REQUEUE-SKIP/
OVERWRITE-ROUND1-SEED/KILL-SESSION/REQUEUE-TRUNCATED/FINALIZE-RUN-COMPLETED）；
`observability`（行为流水）。启动控制见 `monitoring/continuation_control.py`。

### `continuation_result_collector.py` — 结果收集（管线出口）

收集终态 run 的产出，生成汇总报告，proof 入库双写（continuation_results）。

**覆盖问题场景**：结果未归档=数据丢失风险（018教训：proof 双写不依赖盘上单点）。
**用法**：`python -m src.continuation_result_collector --batch-id p27-full`
**依赖**：`continuation_config`；`continuation_db_schema`。

---

## 二、支撑模块（6个，被各模块依赖）

### `continuation_config.py` — 全局配置常量

全局配置常量：DB 集合名 / Redis key 结构 / 模型（DEVIN_MODEL=glm-5-2）/ 路径 /
门闸 ID / 判定阈值（并发/超时/stall/截断token/调度窗口）。

**覆盖问题场景**：配置漂移=各模块引用不一致；SOP_01/05 判断依据；devin cli model
必须显式指定（铁律10）。完整参数表见 `SYSTEM_CLOSURE.md` §5"关键配置参数"。
**依赖**：被所有 continuation_* 模块 import。

### `round_window.py` — 无限续传的调度窗口领域逻辑

不连接 DB/Redis 的纯逻辑：开启/结束/暂停/恢复窗口、记录数学 Round 是否消耗窗口额度、
计算下一绝对 Round。窗口额度只限制本次默认处理量，不建立题目寿命上限。

**覆盖问题场景**：跨窗口继续时 Round 号重复；基础设施失败误耗数学额度；历史
`TRUNCATED_AT_MAX` 恢复时丢失旧证据；窗口结束误进永久终态。
**依赖**：launcher、窗口管理脚本和 sim 调用；所有入队/回收动作仍走现有 Gate。

### `prompt_contract.py` — v3 三角色模板严格渲染接口

冻结 round1/observer/solver 的模板路径和大写占位符集合；用逐占位符替换避开 LaTeX 普通
花括号，缺字段、额外字段或模板漂移均 fail-fast。WP-03 只提供纯接口，尚未接生产 launcher。

**覆盖问题场景**：prompt 占位符漏填；observer/solver 接线时字段名漂移；数学 LaTeX 被
`str.format` 误解释。模板说明见 `templates/README.md`，资产合同见
`docs/architecture/round-artifact-contract.md`。
**依赖**：无 DB/Redis/Gate；WP-02 生产编排和 WP-10 回归可直接调用。

### `formal_verification.py` — 解题侧形式化交付运行与检查

归档临时验证资产，以非 shell argv 运行 Lean/Python/其他工具，保存版本、退出码、stdout/
stderr和运行元数据；扫描明显 `sorry/admit/axiom`、secret、外部路径，并生成 WP-02 可登记
进 rounds_log 的稳定字段。只判断结构/运行事实，始终要求独立审计，不裁定数学充分性。

**覆盖问题场景**：验证脚本只留临时目录；命令不可重跑；Lean `sorry` 退出0被误当充分；
有限 Python 扫描冒充普遍证明；后轮修复覆盖前轮失败日志。
**用法**：`python -m src.formal_verification --help`。
**依赖**：标准库；本机工具按命令调用，不连接 DB/Redis/Gate。详细语义见
`docs/architecture/formal-delivery.md`。

### `continuation_db_schema.py` — DB 连接+集合管理

ArangoDB 连接 + p27_continuation_* 集合管理 + AQL 封装。复用现有 connect_db 配置。

**覆盖问题场景**：连接失败=全系统不可用；DB 集合结构变更时。
**依赖**：`continuation_config`（连接参数/集合名）。

### `continuation_redis_queue.py` — Redis 队列操作

Redis 队列操作封装：pending/running 原子转移、enqueue/dequeue、stats。
v2方案双队列（pending_handover/pending_solve 等），v1方案单队列（备用）。

**覆盖问题场景**：队列原子性破坏=重复启动；Redis key 结构变更时。
完整 key 结构见 `SYSTEM_CLOSURE.md` §5"Redis 队列 key 结构"。
**依赖**：`continuation_config`（前缀/key名）。

---

## 三、监控/治理模块（4个）

### `monitor_continuation.py` — Monitor Pipe（每120s检查写alert）

按 `docs/specs/p27_monitor_spec.md` 检查规范实现。每120s 执行 A类14项自动检查
+ B类9项续传质量检查，alert 写 DB p27_monitor_alerts。C类6项 AI 判断（C1-C6，
含 020 审计新增的 C6 export_semantics）由 Master Agent SOP_04 执行（不在本模块）。

**覆盖问题场景**：不写 alert=检查失效；A13 四源不一致（016新增）；A14 失控循环
（016新增）。完整 alert_type 清单（34种）见 `SYSTEM_CLOSURE.md` §6。
**用法**：
```
python -m src.monitor_continuation --batch-id p27-full --interval 120
python -m src.monitor_continuation --batch-id p27-full --check-alerts
python -m src.monitor_continuation --batch-id p27-full --resolve-alert <alert_key>
```
**依赖**：`continuation_config`；`continuation_db_schema`；`session_registry`；
`observability`。检查规范见 `docs/specs/p27_monitor_spec.md`；
设计范式见 `docs/patterns/MonitorPipe.md`。

### `session_registry.py` — Session 编号化管理

所有 devin cli 实例（solve/handover/monitor_exec）的 tmux session 注册到
p27_sessions 集合。全局 seq 单调递增，永不复用。命名规则 `p27-s{seq:04d}-*`。
状态流转：running→done（DONE.md出现）/ running→stuck（超时无DONE.md）/ done|stuck→cleaned。

**覆盖问题场景**：注册表脱节（A10/A13：tmux vs DB vs Redis 不一致）；
session 命名/查询/清理/一致性检查。12个需求点（SESS-01~12）见
`docs/specs/p27_session_management_and_polish_spec.md` §A。
**依赖**：`continuation_config`（集合名/counter key）。

### `step_gate.py` — 步进门闸（9个语义动作可hold/step）

基于 DB 信号的单步跟踪系统。9个语义动作闸（launcher 8 + feeder 1）可被
Master Agent hold/step/auto。X/Y注意力模型：X=mode（布防），Y=waiting_for
（Master Agent 只在 Y 出现时操心）。checklist 闭包经 docstring 反射传递
（inspect 自动收集进 DB 注册表，永不漂移）。

**覆盖问题场景**：单步调试/审计自动化系统时；给新 Pipe 加门闸时；
016事故场景（Master Agent 拦不住系统动作）。设计范式见
`docs/patterns/StepGate.md`；操作文档见 `docs/sop/SOP_01_system_health.md` §8.5。
**用法**：
```
python -m src.step_gate --list                    # 门闸目录
python -m src.step_gate --hold GATE-LAUNCH-SOLVE  # 卡住下一次解题启动
python -m src.step_gate --pending                 # 看谁在等（输出论证依据闭包）
python -m src.step_gate --step GATE-ID --reason '...'  # 放行（必须附理由）
python -m src.step_gate --auto GATE-ID            # 恢复自动
```
**门闸 ID 全清单**（9个）见 `SYSTEM_CLOSURE.md` §5"门闸 ID 全清单"。
**依赖**：`continuation_config`；`continuation_db_schema`；`observability`（流水）。

### `observability.py` — 行为流水黑匣子（016根因修复）

launcher 的每个状态转移追加一行 JSONL 到 `log/flow/flow-YYYYMMDD.jsonl`。
这是"系统行为黑匣子"——Master Agent 用 CLI 回看任意时间窗口的完整逻辑流动。
016事故根因：monitor 的 A 类检查都是存量快照，看不到流动过程（同题18分钟被
启动上千次，存量视角只看到 pending 一直是500）。

**覆盖问题场景**：失控循环预警（churn_suspects 非空=同题1小时≥5次启动）；
回看某题完整生命周期；016 根因分析。铁律14：每轮 SOP_01 必查行为流水。
**用法**：
```
python -m src.observability --stats --since 1h    # 失控嫌疑/启动Top10/判定分布
python -m src.observability --run-key <run_key>    # 某题完整生命周期（含判定理由）
```
**依赖**：`continuation_db_schema`（flow ledger DB，降级时写文件）。

---

## 四、sim/ — 全流程模拟（6个模块）

全流程模拟系统：被测系统（launcher/feeder/门闸/注册表/Redis队列/判定逻辑）
100% 原代码真跑，唯一被替换的是 devin cli 命令——在 tmux 里跑的换成
`fake_devin.py`（剧本演员），它按剧本写真 export/proof/DONE/HANDOVER 再退出。
设计见 `dev-docs/017-全流程模拟系统设计方案.md`。

**覆盖问题场景**：改调度逻辑后跑 sim 发布门禁（铁律12：solve3+chaos_016）；
单步跟踪 launcher 全部分支路径；016 不变量验证（同 run 无5秒内重复 launch）。
**用法**：`.venv/bin/python -m src.sim.run_sim --scenario solve3`

| 模块 | 职责 |
|---|---|
| `sim/scenarios.py` | 剧本库——每个剧本对应 launcher 的一条真实分支路径（7剧本） |
| `sim/fake_devin.py` | 剧本演员——被 launcher 在 tmux 里启动，按剧本写真文件后退出 |
| `sim/setup.py` | 造批次——fixture 题目 + 截断态 seed export + prepared runs（三重安全护栏） |
| `sim/run_sim.py` | 编排器——setup→真feeder→真launcher→等终态→断言→清场（入口） |
| `sim/assert_final.py` | 终态断言——DB终态/Redis队列/行为流水/tmux 四源核对 |
| `sim/teardown.py` | 清场——tmux/Redis/DB/文件（018事故后护栏补全：默认值不指向生产） |

**安全护栏**（setup/teardown 共用）：SIM_MODE=1 + ARANGO_DB≠生产库 +
SOLVER_BASE 不在 /Volumes/data，三重满足才执行。018事故教训：teardown 护栏
不对称曾误删生产 D 盘目录（124份 proof 永久丢失）。

---

## 速查：模块按问题场景索引

| 你要做什么 | 看哪个模块 |
|---|---|
| 管线无输入 / 新建批次 | `continuation_collector` |
| prepared 堆积 / 死循环重喂 | `continuation_feeder` |
| 失控循环 / 截断误判 / 终态判定 / 并发控制 | `continuation_launcher` |
| 结果归档 / proof 双写 | `continuation_result_collector` |
| 配置漂移 / model 参数 / 阈值 | `continuation_config` |
| v3 prompt 渲染 / 占位符漂移 | `prompt_contract` |
| formal源码归档 / 命令日志 / rounds_log字段 | `formal_verification` |
| DB 连接 / 集合结构 | `continuation_db_schema` |
| 队列原子性 / Redis key 结构 | `continuation_redis_queue` |
| alert 不产生 / A类B类检查 | `monitor_continuation` |
| session 命名 / 注册表脱节 | `session_registry` |
| 单步调试 / hold/step/auto | `step_gate` |
| 失控循环预警 / 行为流水 | `observability` |
| 改调度逻辑后发布门禁 | `sim/run_sim` |
