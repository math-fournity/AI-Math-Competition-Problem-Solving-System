# AnalysisSystemOps.md — 错题分析系统运行操作手册

> **来源**：从 AGENTS.md 第3518-4216行外移（2026-08-19瘦身工程，392号方案）。
> **定位**：错题分析系统（）的运行操作手册。与 AnalysisSystemDesign.md 分工：Design=设计总索引/架构/决策，Ops=运行操作/SOP/检查清单/打磨记录。
> **加载时机**：当你要运行/监控/调试错题分析系统（，判定失败题是"方向出错"还是"token不够"并分类卡点类型）时，必须用read工具全文加载本文件。涉及错题分析系统设计时另读 AnalysisSystemDesign.md。不涉及错题分析系统时不需要读。
> **AGENTS.md索引**：AGENTS.md "外部文档索引"节有指向本文件的索引行。

---

## 错题分析系统

> **用途**：用并发devin cli实例分析失败题——判定每道失败题是"方向出错"还是"token不够"，并分类卡点类型。用于Mid-Hint实验的选题阶段。
>
> **核心设计**：devin cli在运行时不调用任何工具，只读AGENTS.md中的内容（题目+标准答案+AI历史thinking），在TUI中输出XML格式的分析结果。程序通过tmux_pipe.log提取XML。

### 代码库位置

``

### 架构（5组件解耦，模仿并发解题系统）

```
data_collector.py     ← 从DB+题库+trajectory收集三类数据，构造AGENTS.md，写入DB（status=prepared）
        ↓
feeder.py             ← 从DB取status=prepared的run，入Redis pending队列（水位机制）
        ↓
analysis_launcher.py  ← 从Redis pending队列dequeue取题，并发启动devin cli（tmux session）
        ↓
result_collector.py   ← 从tmux_pipe.log提取XML分析结果
        ↓
aggregator.py         ← 汇总所有分析结果，按维度1/维度2统计
```

**retry_infrastructure.py** 独立运行：扫描failed队列→基础设施失败重新入pending队列→launcher自然取到

| 组件 | 文件 | 职责 |
|---|---|---|
| 数据收集 | `src/data_collector.py` | 从ArangoDB获取失败题列表，从7个题库获取标准答案，从trajectory获取thinking（4级优先级），构造AGENTS.md，写入prepared.json+DB（analysis_batches+analysis_runs，status=prepared） |
| 选题入队 | `src/feeder.py` | 独立进程，从DB取status=prepared的run，写入Redis pending队列，水位机制自动补充，更新DB为queued（对应solver_harness的feeder.py） |
| 并发启动 | `src/analysis_launcher.py` | 从Redis pending队列dequeue取题→从DB查run记录获取work_dir→并发启动devin cli（tmux，用`--prompt-file`注入AGENTS.md避免read工具调用），3秒启动间隔避免rate limit，监控运行状态，检测完成/基础设施错误/timeout/stall，DB+Redis双写 |
| 结果收集 | `src/result_collector.py` | 从tmux_pipe.log去掉ANSI转义码后提取`<analysis>...</analysis>` XML块，用正则逐字段解析 |
| 汇总 | `src/aggregator.py` | 按维度1/维度2统计，输出JSON报告+CSV |
| DB | `src/db_schema.py` | ArangoDB 5集合+6个操作函数（见下方数据库安排） |
| Redis | `monitoring/redis_queue.py` | Redis 5队列封装（见下方数据库安排） |
| 配置 | `src/config.py` | 路径常量、DB连接、并发配置 |
| 模板 | `templates/analysis_agents_md.md` | AGENTS.md模板（分析任务说明+XML输出格式） |
| Pipeline | `run_pipeline.py` | 端到端串联4个组件 |

### 数据库安排（对齐solver_harness）

**ArangoDB 5集合**（模仿solver_harness的4集合+1个分析专属集合）：

| 集合 | 对应solver_harness | 用途 | 索引数 |
|---|---|---|---|
| `analysis_batches` | `devin_batch_runs` | 批次元信息+统计（status/concurrency/status_counts等） | 2 |
| `analysis_runs` | `devin_problem_runs` | 每道题的分析run记录（20+字段，含paths/observability/verdict） | 5 |
| `analysis_events` | `devin_run_events` | 事件流（launch/complete/timeout/error） | 4 |
| `analysis_results` | （新增） | XML分析结果（8个目标字段+_raw_xml） | 5 |
| `analysis_counters` | `devin_counters` | 全局计数器（run_id原子递增） | 0 |

**analysis_runs的20+字段**（模仿devin_problem_runs）：
- 标识：`_key`(=analysis_exp_id), `problem_id`, `batch_id`, `run_id`, `source_exp_id`, `analysis_exp_id`
- 状态：`status`, `tmux_session`, `created_at`, `updated_at`, `started_at`, `ended_at`, `launch_started_at`
- 统计：`runtime_seconds`, `end_reason`
- 数据：`solution_source`, `problem_text_length`, `solution_length`, `thinking_length`, `work_dir`
- 结构化：`paths`(7个路径), `observability`(活动签名/标记/文件大小), `verdict`(auto_status/reason/confidence)

**Redis 5队列**（模仿solver_harness的redis_queue.py）：

| 队列 | 类型 | 用途 |
|---|---|---|
| `analysis:pending` | Sorted Set | 待分析任务（score=priority） |
| `analysis:running` | Hash | 运行中任务（field=run_key, value=JSON metadata） |
| `analysis:completed` | List | 已完成任务 |
| `analysis:failed` | List | 失败任务 |
| `analysis:stats` | Hash | 实时统计（pending/running/completed/failed计数） |

**降级机制**：Redis不可用时，launcher直接退出（新架构依赖Redis队列调度）。请确保Redis可用后再启动。

**DB+Redis双写策略**：
- ArangoDB：持久化存储，所有状态变更都写入DB
- Redis：实时队列，用于并发管理和快速统计查询
- launcher每次状态变更时同时更新DB和Redis
- 监控脚本优先查Redis（快），兜底查DB（准）

### 监控脚本系统（模仿solver_harness）

| 脚本 | 用途 | 对应solver_harness脚本 |
|---|---|---|
| `monitoring/shared_logger.py` | 共享日志基础设施（1MB分片+1GB总量+循环滚动） | `pipe/shared_logger.py` |
| `monitoring/redis_queue.py` | Redis 5队列封装（pending/running/completed/failed/stats） | `pipe/redis_queue.py` |
| `monitoring/retry_infrastructure.py` | 基础设施失败自动重试（扫描failed队列，重试infra失败） | `pipe/retry_infrastructure.py` |
| `monitoring/analysis_control.py` | 控制工具（start/stop/status/health/logs/set-concurrency/retry） | `pipe/pipe_control.py` |
| `monitoring/query_progress.py` | 进度查询（概览/批次/题目/实验） | `pipe/query_progress.py` |
| `monitoring/query_failures.py` | 失败分类统计（by-verdict/turning-point/source/batch） | `pipe/query_failures.py` |
| `monitoring/verify_completeness.py` | 数据完备性验证（ids/files/tmux/db-sync/redis-sync） | `pipe/verify_completeness.py` |
| `monitoring/verify_result_integrity.py` | 结果完整性验证（8字段+合法值+XML解析+质量） | `pipe/verify_run_integrity.py` |
| `monitoring/runtime_health_check.py` | 运行时健康检查（10维度A-J：并发安全+DB-Redis一致性+网络+落盘+日志） | `pipe/scripts/concurrency_safety_check.py` |
| `monitoring/recover_from_crash.py` | 断电恢复+僵尸清理（running记录+孤儿session） | `pipe/recover_from_crash.py` |
| `monitoring/audit_trace.py` | 双向追溯验证（DB↔文件，题目↔run↔result） | `pipe/audit_trace.py` |
| `monitoring/reporter.py` | 定时报告+告警（未启动/失败率/session过多） | `pipe/reporter.py` |

**日志位置**：`/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/analysis-devin-failure/_logs/`
- `analysis.log`：统一日志（所有模块）
- `{module}.log`：模块专属日志（data_collector/launcher/result_collector/aggregator等）

**监控命令速查**：
```bash


# 状态查看
python -m monitoring.analysis_control status
python -m monitoring.analysis_control health

# 进度查询
python -m monitoring.query_progress
python -m monitoring.query_progress --batch-id analysis-1
python -m monitoring.query_progress --problem-id polymath_01687

# 失败分类
python -m monitoring.query_failures --summary
python -m monitoring.query_failures --by-verdict DIRECTION_ERROR
python -m monitoring.query_failures --by-turning-point mod_p_grouping

# 验证
python -m monitoring.verify_completeness --all --batch-id analysis-1
python -m monitoring.verify_result_integrity --batch-id analysis-1
python -m monitoring.audit_trace --all --batch-id analysis-1

# 运行时健康检查（系统运行中执行，10维度A-J）
python -m monitoring.runtime_health_check
# 检查并发安全、DB-Redis一致性、网络健康、落盘完整性、日志健康等

# 恢复
python -m monitoring.recover_from_crash --dry-run
python -m monitoring.recover_from_crash

# 报告
python -m monitoring.reporter --once
python -m monitoring.reporter --interval 60

# 动态并发调整（运行中可调）
python -m monitoring.analysis_control set-concurrency --batch-id analysis-1 --concurrency 20
# launcher下一轮poll时自动生效，无需重启

# 启动（一键：feeder入队+launcher启动+retry服务启动）
python -m monitoring.analysis_control start --batch-id analysis-1 --concurrency 30
python -m monitoring.analysis_control start --batch-id analysis-1 --concurrency 30 --clear  # 清空Redis后启动
python -m monitoring.analysis_control start --batch-id analysis-1 --concurrency 30 --no-feed  # 不自动feeder

# 停止（默认优雅退出服务，保留an-分析session等自然完成）
python -m monitoring.analysis_control stop
python -m monitoring.analysis_control stop --force              # 强制kill服务
python -m monitoring.analysis_control stop --kill-sessions      # 同时kill an-分析session
python -m monitoring.analysis_control stop --force --kill-sessions  # 全部强制停止
python -m monitoring.analysis_control stop-all                  # 兼容旧命令（强制kill全部）

# 日志
python -m monitoring.analysis_control logs --lines 50
python -m monitoring.analysis_control logs --module launcher --lines 100
```

### 动态并发管理（对齐solver_harness）

**并发数可以运行中动态调整，无需重启launcher。**

**机制**（模仿solver_harness）：
1. launcher轮询循环每轮从DB读取`analysis_batches.concurrency`字段
2. 用`set-concurrency`命令修改DB中的值
3. launcher下一轮poll时自动生效（通常poll_seconds=5秒内生效）
4. 每次变更记录`concurrency_changed`事件到`analysis_events`

**设置方法**：
```bash
# 启动时指定初始并发数
python run_pipeline.py --batch-id analysis-1 --step launch --concurrency 10

# 运行中动态调整（另开终端）
python -m monitoring.analysis_control set-concurrency --batch-id analysis-1 --concurrency 20
# ↑ launcher自动从10并发提升到20并发

# 也可以降低并发数（让正在运行的题完成后不再启动新题）
python -m monitoring.analysis_control set-concurrency --batch-id analysis-1 --concurrency 5
```

**并发数配置位置**：
- 默认值：`src/config.py`中`DEFAULT_CONCURRENCY = 10`
- 启动时覆盖：`--concurrency N`命令行参数
- 运行中覆盖：`set-concurrency`命令修改DB中`analysis_batches.concurrency`
- 优先级：DB值 > 命令行参数 > config.py默认值

**注意事项**：
- 并发数受API rate limit约束——GLM-5.2的Pro plan有并发上限，建议不超过20
- 降低并发数不会kill正在运行的题——只是不再启动新题，等当前题完成后逐步降到目标并发数
- 提高并发数会立即启动新题填满并发槽（如果pending队列中还有题）

### 环境变量旋钮与隔离（2026-08-20新增）

| 变量 | 作用 | 默认 | 说明 |
|---|---|---|---|
| `ARANGO_DB` | ArangoDB库名 | `xishujuzhen_math_glm52` | **代码现在真的读这个env**（此前AGENTS要求source .env确认但代码硬编码——已修复的隐性不一致） |
| `ARANGO_HOST` | ArangoDB地址 | `http://localhost:8529` | 同上 |
| `P27_REDIS_PREFIX` | Pipe 4队列键前缀 | `p27:` | sim隔离用`p27sim:` |
| `SIM_MODE` | =1时devin命令换成剧本演员 | 空 | **生产绝不设置** |
| `HANDOVER_TIMEOUT_SECONDS` | Pipe A超时秒数 | 600 | env化为sim可调短 |

（`SOLVER_BASE`/`TRAJECTORY_BASE`为既有env，指向D盘数据根。）

### 步进门闸操作面（2026-08-20定稿，详见docs/patterns/StepGate.md）

9个语义动作闸（launcher 8 + feeder 1）。X/Y注意力模型：auto且无waiting_for=
不需操心；hold触发时置Y，SOP_01例程和`--pending`会完整输出该闸的checklist
闭包（认知闭包），按清单核对后放行：

```bash
.venv/bin/python -m src.step_gate --list               # 目录（按resource分组）
.venv/bin/python -m src.step_gate --hold GATE-LAUNCH-SOLVE   # 布防
.venv/bin/python -m src.step_gate --pending            # 看谁在等+完整checklist
.venv/bin/python -m src.step_gate --step GATE-LAUNCH-SOLVE   # 放行一次
.venv/bin/python -m src.step_gate --auto GATE-LAUNCH-SOLVE   # 恢复
.venv/bin/python -m src.step_gate --hold-resource tmux       # 按分类批量hold
```

### 全流程模拟（2026-08-20建成，dev-docs/017）

**用途**：改launcher/调度逻辑后的发布门禁；新剧本=下一个事故的固化回归。

```bash
# 跑一个剧本（setup→真feeder→真launcher→等终态→四源断言→清场）
.venv/bin/python -m src.sim.run_sim --scenario solve3
.venv/bin/python -m src.sim.run_sim --scenario chaos_016 --keep   # 保留现场
# 7个剧本：solve3/first_try/never/dead/stall/h_timeout/chaos_016
```

**安全规则（018事故后）**：隔离环境只通过run_sim程序化设置，**绝不手动
export环境变量后直接跑setup/teardown**——teardown护栏已补全（文件根检查），
但手动env仍是018事故的直接诱因。

### 2026-08-20行为变化（5个bug修复，launcher重启后生效）

1. **截断判定先于dead判定**（P0）——此前真实截断被误判dead_session，
   多轮续传引擎不可达（生产4712实证）。生产曾误判dead的run重置prepared后
   将正确走截断续传；
2. **rounds_log含round-1条目**——轮序从[2,3..]变为[1,2,3..]，round 1
   （seed重判）的历史在DB完整可见；此前R2会被重跑一次；
3. 主循环退出条件补handover_pending（批次最后一题不再被晾半路）；
4. TRUNCATED_AT_MAX终态写run_completed流水；
5. 四处failed终态（unknown/rate_limit/timeout/stall）写run_failed流水；
6. **proof文本入库**（018加固）——continuation_results现在存每个COMPLETED
   run的proof全文（≤100KB），不再依赖盘上单点文件。

### 异常处理与重试（对齐solver_harness）

**网络抖动、API限流、进程异常退出等基础设施失败会自动重试，题目不会丢失。**

**失败分类**（对齐solver_harness的INFRA_FAILURES vs MODEL_FAILURES）：

| 分类 | 失败类型 | 是否重试 | 说明 |
|---|---|---|---|
| **基础设施失败** | `rate_limited` | ✅ 重试 | API限流（检测到rate limit/429/Too Many Requests） |
| **基础设施失败** | `failed_connection` | ✅ 重试 | 网络错误（检测到connection error/ECONNREFUSED/socket hang up等） |
| **基础设施失败** | `dead_session` | ✅ 重试 | tmux session异常退出但没有完成标记 |
| **基础设施失败** | `launch_error` | ✅ 重试 | 启动失败 |
| **模型能力失败** | `failed_timeout` | ❌ 不重试 | 分析超时（超过max_runtime） |
| **模型能力失败** | `failed_stall` | ❌ 不重试 | 分析卡住（超过stall_seconds无活动） |
| **模型能力失败** | `failed_no_xml` | ❌ 不重试 | 分析完成但无XML输出 |
| **模型能力失败** | `failed_incomplete` | ❌ 不重试 | 分析未完成 |

**检测机制**（launcher轮询循环中）：
1. 完成检测（`</analysis>`或"分析完成"）→ completed
2. **基础设施错误检测**（在timeout之前）→ 检测rate_limit/connection_error模式 → failed(infra)
3. tmux session退出检测 → 有完成标记=completed，无完成标记=dead_session → failed(infra)
4. timeout检测（超过max_runtime）→ failed(model)
5. stall检测（超过stall_seconds无活动）→ failed(model)

**重试机制**（`monitoring/retry_infrastructure.py`）：
```bash
# 执行一次重试扫描
python -m monitoring.analysis_control retry --once

# 循环模式（每120秒扫描一次）
python -m monitoring.analysis_control retry --interval 120

# 只看不执行
python -m monitoring.analysis_control retry --once --dry-run

# 也可以直接调用
python -m monitoring.retry_infrastructure --once
```

**重试流程**：
1. 扫描Redis `analysis:failed`队列
2. 识别基础设施失败（`failure_type=infra`或reason在INFRA_FAILURES中）
3. 查DB中该run已有的infra失败次数
4. 未达上限（max_retries=3）→ 重新入`analysis:pending`队列 + 更新DB状态为`pending_retry`
5. 达到上限 → 跳过，保留在failed队列中
6. 模型能力失败 → 不重试，保留在failed队列中

**重试后题目如何重新启动**：
- 重试脚本将题目重新入`analysis:pending`队列
- 如果launcher还在运行，下一轮poll时会从pending队列dequeue取出重新启动
- 如果launcher已退出，需要重新启动launcher：`python -m src.analysis_launcher --batch-id <id> --concurrency N`
- launcher会从Redis pending队列取题——pending队列中只有重试的题，不会重复启动已completed的题

**DB记录**：
- 每次infra失败：`analysis_runs.status` = 失败类型，`analysis_events`记录`infra_failure`事件
- 每次重试：`analysis_runs.status` = `pending_retry`，`analysis_events`记录`retry_scheduled`事件
- 重试成功后：`analysis_runs.status` = `completed`
- 重试次数 = DB中该run_key的infra失败次数

### 用法

```bash
cd ../..

# 端到端（全部步骤）
python run_pipeline.py --batch-id analysis-1 --limit 100 --concurrency 10

# 分步执行
# 1. 收集数据，构造AGENTS.md
python run_pipeline.py --batch-id analysis-1 --step collect --limit 100

# 2. 并发启动分析（feeder入队+launcher启动）
python run_pipeline.py --batch-id analysis-1 --step launch --concurrency 10
# 或分离模式：feeder入队 + launcher从队列取题
python -m src.feeder --batch-id analysis-1 --once
python -m src.analysis_launcher --batch-id analysis-1 --concurrency 10
# 或launcher的--auto-feed模式（一次性入队+启动）
python -m src.analysis_launcher --batch-id analysis-1 --concurrency 10 --auto-feed

# 3. 收集结果
python run_pipeline.py --batch-id analysis-1 --step collect-results

# 4. 汇总报告
python run_pipeline.py --batch-id analysis-1 --step aggregate

# 查看状态
python run_pipeline.py --batch-id analysis-1 --step status

# 停止所有
python run_pipeline.py --batch-id analysis-1 --step stop

# 指定题号分析
python run_pipeline.py --batch-id test --step collect --problem-ids polymath_01687,deepmath_103k_00021551
```

### 分析维度

**维度1：失败类型**
- `DIRECTION_ERROR`：AI走了错误方向，没使用标准解答的关键方法
- `TOKEN_LIMIT`：AI方向正确但token用尽
- `CONNECTION_ERROR`：AI没有真正尝试（连接错误、秒退）
- `PARTIAL_PROGRESS`：AI部分走对但在关键转折点走错

**维度2：卡点类型**（仅DIRECTION_ERROR和PARTIAL_PROGRESS）
- `mod_p_grouping` / `mod_p_non_obvious` / `quadratic_residue_euler` / `lte_lemma` / `p_adic_valuation` / `multi_step_mod_p` / `crt` / `permutation_polynomial` / `finite_field_structure` / `other`

### 输出格式

devin cli在TUI中输出XML：

```xml
<analysis>
  <problem_id>polymath_01687</problem_id>
  <dimension1_verdict>PARTIAL_PROGRESS</dimension1_verdict>
  <dimension1_explanation>AI identified permutation polynomial but derailed into interpretation debates</dimension1_explanation>
  <dimension2_turning_point_type>permutation_polynomial</dimension2_turning_point_type>
  <dimension2_explanation>Standard solution uses gcd(k,p-1)=1 criterion</dimension2_explanation>
  <ai_direction_summary>AI correctly framed problem but went in circles</ai_direction_summary>
  <standard_solution_key_technique>gcd(k,p-1)=1 for monomial permutation polynomials</standard_solution_key_technique>
  <confidence>high</confidence>
</analysis>
```

### 数据源

详见 `eight-system/runs/midhint/data_source_map.md`

三类数据的获取：
1. **题目文本**：solver工作目录的AGENTS.md（`/Volumes/data/math-agent-glm5.2-tmux-agents-dir/{exp_id}/`）
2. **标准答案**：7个题库的原始数据文件（parquet/jsonl/lean/json），按problem_id前缀匹配
3. **AI解题过程**：trajectory目录的4级优先级数据源（mitm > sessions_db > exports > collector）

### 已知问题

1. **PolyMath 1564道not_found**：id映射规则可能不是简单整数对应，待调查
2. **DeepMath/ODA-Math解答质量**：AI生成的解答（r1_solution_1/response），不是人类专家解答
3. **compfiles的lean proof**：Lean形式化证明，不是人类可读推理
4. **fate无人类解答**：只有Lean formal statement，不适合分析
5. **XML解析**：devin cli输出中数学公式的`<>`可能导致标准XML解析失败，已用正则逐字段提取兜底
6. **旧schema兼容性**：test-2/test-2b批次的DB记录使用旧schema（数字_key、缺paths/observability/verdict字段）。新批次会使用新schema（analysis_exp_id做_key、20+字段）。监控脚本同时兼容两种schema。如果需要清理旧数据，可以删除analysis_runs中_key为纯数字的记录。

### 端到端测试结果（2026-08-15）

**smoke-v3批次**（新schema，DB+Redis对齐solver_harness后）：

polymath_01687（置换多项式问题）：
- collect：✅ analysis_batches记录+analysis_runs记录（20+字段，_key=analysis_exp_id）
- launch：✅ 52秒完成，DB+Redis双写，runtime_seconds=52，tmux_session记录
- collect-results：✅ parsed=1，XML提取成功
- aggregate：✅ PARTIAL_PROGRESS × permutation_polynomial，confidence=high
- 6项健康检查：全部OK
- 结果完整性验证：8字段+合法值全部通过
- DB→文件追溯：完整

分析结果：
- 维度1：PARTIAL_PROGRESS（AI识别了置换多项式但纠结于"集合"的解释）
- 维度2：permutation_polynomial
- 信心度：high
- 分析质量高——devin cli准确理解了标准解答的关键技巧和AI的失败原因

**旧测试**（test-2b批次，旧schema，已过时）：
- test-2b用旧schema跑通（数字_key、缺paths/observability/verdict字段）
- smoke-v2因完成检测bug失败（prompt中的"### ANALYSIS COMPLETE"被误判为完成）

### 当前状态（2026-08-15）

**系统状态**：已建立、已测试、已验证，数据库+Redis已对齐solver_harness，但**尚未大规模运行**。

| 项目 | 状态 |
|---|---|
| 代码库（4组件+10监控脚本） | ✅ 完成 |
| shared_logger集成 | ✅ 完成 |
| ArangoDB 5集合+索引 | ✅ 完成（对齐solver_harness） |
| Redis 5队列封装 | ✅ 完成（对齐solver_harness） |
| DB+Redis双写 | ✅ 完成（launcher每次状态变更双写） |
| 端到端测试（1道题） | ✅ 通过 |
| 监控脚本验证（6项健康检查） | ✅ 全部通过 |
| 大规模分析（6181道失败题） | ❌ 未开始 |
| PolyMath 1564道not_found | ❌ 未解决 |
| 分析结果用于Mid-Hint选题 | ❌ 未开始 |

**已有数据**（注意：test-2/test-2b是DB对齐前的旧数据，使用旧schema——数字_key、缺paths/observability/verdict字段。smoke-v2因完成检测bug失败。smoke-v3是新schema下完整跑通的验证批次）：
- test-2批次：2道题，launch完成但result收集失败（早期bug，XML提取逻辑已修复）
- test-2b批次：1道题，旧schema完整跑通，结果已入DB
- smoke-v2批次：1道题，因完成检测bug失败（12秒误判完成，已修复）
- smoke-v3批次：1道题，新schema完整跑通（52秒完成），DB+Redis双写验证通过
- DB中analysis_counters.run_id已递增到5（下一批次从r000006开始）

### 关键经验教训（未来session必读）

1. **完成检测陷阱**（已修复）：devin cli的prompt中包含"结尾输出 ### ANALYSIS COMPLETE"文本。当tmux的ANSI转义码打断prompt行时，"### ANALYSIS COMPLETE"会出现在"请按AGENTS.md"之后的agent输出区域中，被误判为分析完成（smoke-v2因此失败，12秒就"完成"了）。**修复方法**：完成检测只依赖`</analysis>`标记和"分析完成"中文标记，不再依赖ANALYSIS_COMPLETE_MARKER。smoke-v3用修复后的逻辑成功跑通（52秒完成）。

2. **XML解析陷阱**：devin cli输出的XML中可能包含数学公式的`<`和`>`符号（如`F_{p^k}`、`x < p`），导致标准`xml.etree.ElementTree`解析失败。**修复方法**：标准解析失败时，用正则`r"<{tag}>(.*?)</{tag}>"`逐字段提取8个目标字段。

3. **devin cli的行为特点**：
   - devin cli的输出在TUI中显示，tmux_pipe.log会记录但充满ANSI转义码——需要去掉ANSI后再提取XML
   - devin cli可能不严格按照模板格式输出XML——它可能用更复杂的嵌套结构，但8个目标字段通常都有
   - 用`-p`单轮模式时，devin cli完成后自动退出（不需要等待新输入）；pane中有`DEVIN_CLI_EXITED code=0`标记

4. **--prompt-file注入大prompt文件**（重要）：当AGENTS.md > 15KB时，超出devin cli的rules注入token限制，devin cli会显示"could not be injected due to token limits. Read them using the read_file tool"，然后AI调用read工具读AGENTS.md。这会导致：(a) 每个run多1-2次API请求（read工具调用）；(b) AGENTS.md内容累积到prompt中，后续请求prompt体积翻2-4倍（从~20K tokens涨到42-75K tokens）；(c) 30并发同时read → rate limit。**修复方法**：用`devin -p --prompt-file <AGENTS.md>`代替`devin -p 'prompt'`，直接把AGENTS.md内容作为初始prompt注入，绕过rules机制，devin cli不需要read工具。单例测试验证：72KB的AGENTS.md用`--prompt-file`注入，0 tool_calls，10秒内输出完整XML。

5. **tmux session命名**：tmux session名不能含点号（`.`），且不超过50字符。analysis_launcher中用`an-{analysis_exp_id[:48]}`命名，将点号替换为连字符。

6. **DB key冲突**：同一problem_id在同一batch_id下重复运行时，DB key会冲突。**已修复**：用`next_run_id()`原子递增生成唯一analysis_exp_id，格式`{batch_id}-r{run_id:06d}-{problem_id}`，DB _key=analysis_exp_id。

7. **数据库对齐solver_harness**：错题分析系统的DB+Redis安排已完全对齐solver_harness——5个ArangoDB集合（analysis_batches/runs/events/results/counters）+5个Redis队列（analysis:pending/running/completed/failed/stats）。launcher每次状态变更时DB+Redis双写。Redis是新架构的硬依赖（feeder→pending队列→launcher的调度链路依赖Redis）。

8. **异常处理对齐solver_harness**：launcher现在检测3类基础设施错误（rate_limited/failed_connection/dead_session）+2类模型失败（timeout/stall）。基础设施失败通过`retry_infrastructure.py`自动重试（max_retries=3），模型失败不重试。关键：dead_session检测——之前tmux session退出一律算completed，现在区分有完成标记=completed vs 无完成标记=dead_session（可重试）。

9. **feeder+launcher分离架构**：错题分析系统现在对齐solver_harness的feeder+runner分离架构——feeder从DB取prepared的run入Redis pending队列，launcher从pending队列dequeue取题启动。retry_infrastructure重新入pending队列的题，launcher能自然取到（解决了之前重试后题目无法重新启动的问题）。`analysis_control start`一键启动feeder+launcher+retry，`stop`一键优雅停止。

10. **一键启停对齐solver_harness**（重要）：`analysis_control.py`现在对齐solver_harness的`pipe_control.py`——`start`一键启动feeder入队+launcher（tmux session）+retry服务（auto-restart tmux session），`stop`发SIGINT优雅退出launcher/retry（等10秒，超时才kill），默认保留an-分析session等自然完成（`--kill-sessions`才kill）。launcher不auto-restart（批处理任务处理完退出），retry auto-restart（长期运行自动重试基础设施失败）。

11. **--prompt-file注入大prompt**（重要，见经验教训第4条）：launcher用`devin -p --prompt-file AGENTS.md`代替`devin -p 'prompt'`，直接把AGENTS.md作为初始prompt注入，绕过rules注入token限制，避免devin cli调用read工具读AGENTS.md导致prompt体积翻倍和rate limit。3秒启动间隔避免API rate limit（对齐solver_harness runner.py）。

### 运行前检查清单（未来session接手时执行）

```bash
cd ..

# 1. 健康检查
python -m monitoring.analysis_control health
# 期望：6项全部OK（tmux/D盘/ArangoDB/Redis/日志目录/僵尸session）

# 2. 查看已有状态
python -m monitoring.analysis_control status
# 看有哪些批次、各批次进度

# 3. 检查是否有残留的running记录（断电恢复）
python -m monitoring.recover_from_crash --dry-run
# 如果有running记录，执行 python -m monitoring.recover_from_crash 恢复

# 4. 检查日志
python -m monitoring.analysis_control logs --lines 20
# 看最后一次操作的日志

# 5. 如果要大规模运行，先小规模测试
python run_pipeline.py --batch-id smoke-test --step collect --limit 5
python -m monitoring.analysis_control start --batch-id smoke-test --concurrency 2 --clear
# 等launcher处理完（tmux session退出后表示完成）
python -m monitoring.analysis_control stop  # 停止retry服务
python run_pipeline.py --batch-id smoke-test --step collect-results
python run_pipeline.py --batch-id smoke-test --step aggregate
# 确认smoke-test通过后再大规模运行
```

### 大规模运行指南

**目标**：分析所有6181道失败题（其中约4325道有标准答案+thinking，可分析）。

**推荐步骤**：
```bash
# 0. 运行前检查（见上方"运行前检查清单"）
python -m monitoring.analysis_control health  # 6项全部OK

# 1. 收集所有可分析的题（约10分钟，主要是加载题库）
python run_pipeline.py --batch-id full-analysis --step collect
# 产出：prepared.json + analysis_batches记录 + analysis_runs记录（20+字段，新schema）

# 2. 一键启动分析系统（feeder入队+launcher启动+retry服务启动）
python -m monitoring.analysis_control start --batch-id full-analysis --concurrency 30 --clear
# 启动后launcher在tmux session中运行，处理完所有题后自动退出
# retry服务auto-restart，长期运行自动重试基础设施失败
# 3秒启动间隔避免rate limit（对齐solver_harness）

# 3. 运行中监控（另开终端）
python -m monitoring.reporter --interval 60          # 定时报告+告警
python -m monitoring.analysis_control status         # 批次状态
python -m monitoring.analysis_control health         # 基础设施健康检查
python -m monitoring.runtime_health_check            # 运行时健康检查（10维度A-J）
# Redis队列查看（可选）：
python -c "from monitoring.redis_queue import *; r=get_redis(); print(get_stats(r))"
# 运行中可查DB：
python -m monitoring.query_progress --batch-id full-analysis
python -m monitoring.query_failures --summary

# 3b. 动态调整并发（运行中可调，无需重启launcher）
python -m monitoring.analysis_control set-concurrency --batch-id full-analysis --concurrency 20

# 4. 优雅停止（默认保留an-分析session等自然完成）
python -m monitoring.analysis_control stop
# 强制停止所有（包括an-分析session）：
python -m monitoring.analysis_control stop --force --kill-sessions

# 5. 收集结果
python run_pipeline.py --batch-id full-analysis --step collect-results
# 产出：collected_results.json + analysis_results记录 + analysis_runs状态更新

# 6. 验证结果完整性
python -m monitoring.verify_result_integrity --batch-id full-analysis
python -m monitoring.verify_completeness --all --batch-id full-analysis
python -m monitoring.audit_trace --all --batch-id full-analysis

# 7. 汇总报告
python run_pipeline.py --batch-id full-analysis --step aggregate
# 产出：aggregated_report.json + aggregated_report.csv

# 8. 最终验证
python -m monitoring.query_failures --summary
python -m monitoring.query_failures --export --output full-analysis-results.json
```

**预估**：每道题分析约1-3分钟，30并发约6000题/小时，4325道约需45分钟。

**断电恢复**：如果运行中断电或launcher异常退出：
```bash
# 1. 检查残留running记录
python -m monitoring.recover_from_crash --dry-run
# 2. 执行恢复（清理running记录，kill僵尸session）
python -m monitoring.recover_from_crash
# 3. 恢复后重新启动——feeder只入队status=prepared的run，不会重复启动已completed的题
python -m monitoring.analysis_control start --batch-id full-analysis --concurrency 30
```

### 连续打磨SOP（5题一组手动运行 + 质量检查）

> **铁律**：错题分析系统必须以5题一组手动运行，每轮运行后必须按质量检查SOP逐项检查。禁止跳过质量检查直接扩大规模。

#### 运行流程（每轮）

```bash
cd ..

# 1. 选题——5题一组，优先选后期批次（无MITM，验证真实数据）
#    写题号到 output/polish5_ids.txt
#    选题原则：覆盖不同题库（polymath/deepmath/oda_math/omni_math/aime）
#    优先选 mitm_enabled=False 的题（当前和未来数据的真实情况）

# 2. collect
.venv/bin/python3 -m src.data_collector --batch-id polish-N --problem-ids-file output/polish5_ids.txt
# 验证：prepared=5, skipped=0

# 3. 启动分析（5并发）
.venv/bin/python3 -m monitoring.analysis_control start --batch-id polish-N --concurrency 5 --clear

# 4. 等待完成（约2-3分钟）
sleep 120
.venv/bin/python3 -c "from monitoring.redis_queue import *; r=get_redis(); print(get_stats(r))"
# 期望：pending=0 running=0 completed=5 failed=0

# 5. 收集结果
.venv/bin/python3 -m src.result_collector --batch-id polish-N
# 验证：parsed=5, no_xml=0, no_output=0, incomplete=0

# 6. 停止服务
.venv/bin/python3 -m monitoring.analysis_control stop --force --kill-sessions

# 7. 质量检查（见下方SOP）——必须执行，不可跳过
```

#### 质量检查SOP（每轮必须执行）

**检查1：技术指标**
- parsed / no_xml / no_output / incomplete / failed 的数量
- 标准：parsed=5, 其余全=0
- 不达标时：检查no_xml题的conversation.json是否有analysis XML块

**检查2：CONNECTION_ERROR误判**
- 查d1=CONNECTION_ERROR的题
- 标准：CONNECTION_ERROR只用于thinking<500 chars且无数学内容的技术失败
- 如果d1=CONNECTION_ERROR但thinking>500 chars或有数学内容 → 误判，记录问题
- 如果AI解了不同的题 → 应该是DIRECTION_ERROR不是CONNECTION_ERROR

**检查3：模板占位符泄漏**
- 检查d1_explanation/d2_explanation中是否含"1-3 sentences"或"ONE_OF:"或"Your 1-3 sentence"
- 注意：`|` 不是占位符——数学公式中合法使用绝对值符号如`|f(x)|`。只检查明确的模板占位符文本。
- 标准：0个泄漏
- 不达标时：检查模板中的占位符格式，加强"Output exactly ONE value"指令

**检查4：d2_explanation完整性**
- 查d2_explanation是否为空、"?"、或过短（<20 chars）
- 标准：0个空/问号/过短
- 不达标时：检查XML解析是否正确提取了d2_explanation标签

**检查5：d1/d2一致性**
- d1=DIRECTION_ERROR或PARTIAL_PROGRESS时，d2不应为空
- d1=TOKEN_LIMIT或CONNECTION_ERROR时，d2可以是"other"或空
- 不达标时：检查模板中对d2的触发条件描述

**检查6：内容质量抽查**
- 逐题读d1_explanation的前120 chars，判断是否合理
- 逐题读d2_explanation的前120 chars，判断是否合理
- 关注：d1_exp是否准确描述了AI的方向（vs标准解答的方向）
- 关注：d2_exp是否准确描述了标准解答的关键技巧

**检查7：跨批次一致性（可选）**
- 如果某题在之前的轮次中运行过，比较两次结果是否一致
- d1/d2应该一致（同一题同一AI的thinking不变，分析结果应该稳定）

**检查8：d2_exp XML标签泄漏**
- 检查d1_explanation/d2_explanation中是否含`</dimension`或`<dimension`
- 标准：0个泄漏
- 根因：devin cli有时输出标签闭合错误（如`<dimension2_explanation>内容</dimension2_turning_point_type>`），导致正则跨标签提取
- 不达标时：parse_xml已修复（截断到第一个错误闭合标签之前），但需重新收集结果

#### 质量检查执行方式

用一段Python脚本一次性检查所有7项，输出汇总表：

```python
# 模板：每轮运行后执行
import sys; sys.path.insert(0, '.')
from src.db_schema import connect_db, ANALYSIS_RESULTS_COLLECTION, ANALYSIS_RUNS_COLLECTION

db = connect_db()
aql = "FOR r IN analysis_results FILTER r.run_key LIKE 'polish-N%' RETURN r"
results = list(db.aql.execute(aql, ttl=60))

print(f"=== 质量检查（{len(results)}题）===")

# 检查1: 技术指标（从result_collector输出获取）
# 检查2: CONNECTION_ERROR误判
ce_results = [r for r in results if r.get('dimension1_verdict') == 'CONNECTION_ERROR']
print(f"\n检查2: CONNECTION_ERROR={len(ce_results)}题")
for r in ce_results:
    run = db.collection(ANALYSIS_RUNS_COLLECTION).get(r.get('run_key', ''))
    thinking_len = run.get('thinking_length', 0)
    if thinking_len > 500:
        print(f"  *** 误判: {run.get('problem_id')} thinking={thinking_len} chars > 500")

# 检查3: 模板占位符泄漏（注意：|不是占位符，数学公式中合法）
placeholder_count = 0
for r in results:
    for field in ['dimension1_explanation', 'dimension2_explanation']:
        val = str(r.get(field, ''))
        if '1-3 sentences' in val or 'ONE_OF:' in val or 'Your 1-3 sentence' in val:
            placeholder_count += 1
            print(f"  *** 占位符泄漏: {r.get('run_key')} {field}")
print(f"\n检查3: 占位符泄漏={placeholder_count}")

# 检查4: d2_explanation完整性
empty_d2 = 0
for r in results:
    d2_exp = str(r.get('dimension2_explanation', ''))
    if not d2_exp or d2_exp == '?' or len(d2_exp) < 20:
        empty_d2 += 1
        print(f"  *** d2_exp不完整: {r.get('run_key')} d2_exp='{d2_exp[:30]}'")
print(f"\n检查4: d2_exp不完整={empty_d2}")

# 检查5: d1/d2一致性
inconsistent = 0
for r in results:
    d1 = r.get('dimension1_verdict', '')
    d2 = r.get('dimension2_turning_point_type', '')
    if d1 in ('DIRECTION_ERROR', 'PARTIAL_PROGRESS') and (not d2 or d2 == '?'):
        inconsistent += 1
        print(f"  *** d1/d2不一致: {r.get('run_key')} d1={d1} d2={d2}")
print(f"\n检查5: d1/d2不一致={inconsistent}")

# 检查6: 内容质量抽查（逐题）
print(f"\n检查6: 内容质量抽查")
for r in results:
    run = db.collection(ANALYSIS_RUNS_COLLECTION).get(r.get('run_key', ''))
    pid = run.get('problem_id', '?')
    d1 = r.get('dimension1_verdict', '?')
    d2 = r.get('dimension2_turning_point_type', '?')
    d1_exp = str(r.get('dimension1_explanation', ''))[:120]
    d2_exp = str(r.get('dimension2_explanation', ''))[:120]
    print(f"  {pid}: d1={d1} d2={d2}")
    print(f"    d1_exp: {d1_exp}")
    print(f"    d2_exp: {d2_exp}")

# 检查8: d2_exp XML标签泄漏
xml_leak = 0
for r in results:
    for field in ['dimension1_explanation', 'dimension2_explanation']:
        val = str(r.get(field, ''))
        if '</dimension' in val or '<dimension' in val:
            xml_leak += 1
            print(f"  *** XML标签泄漏: {r.get('run_key')} {field}")
print(f"\n检查8: XML标签泄漏={xml_leak}")

# 汇总
total_issues = len(ce_results) + placeholder_count + empty_d2 + inconsistent + xml_leak
print(f"\n=== 汇总: {total_issues}个问题 ===")
if total_issues == 0:
    print("  ✅ 全部通过，可以进入下一轮")
else:
    print("  ❌ 有问题，需要修复后再运行下一轮")
```

#### 打磨记录

| 轮次 | 题数 | 批次类型 | 发现的问题 | 修复 |
|---|---|---|---|---|
| 轮1 | 5 | 早期(有MITM) | XML标签闭合错误+模板格式+thinking缺tool_results | 修复3个问题 |
| 轮2 | 5 | 早期(有MITM) | 无新问题，质量全部通过 | — |
| 轮3b | 5 | 后期(无MITM) | 无新问题，thinking提取正常工作 | — |
| 轮4 | 5 | 后期(无MITM,4题库) | 检查3误报(\|是数学符号)+TOKEN_LIMIT/PARTIAL_PROGRESS边界模糊 | 修正检查3条件+模板加tiebreaker规则 |
| 轮5 | 5 | 后期(无MITM,同题验证) | tiebreaker使分析AI显式推理"是否收敛"，polymath_01152仍为TOKEN_LIMIT但有理由（递归方法valid但慢）。5题跨批次全部一致。 | — |
| 轮6 | 5 | 后期(无MITM,全新题) | 无新问题，5题全部通过。覆盖4题库，d1分布：3 DIRECTION_ERROR + 1 PARTIAL_PROGRESS + 1 TOKEN_LIMIT。 | — |
| 轮7 | 5 | 后期(无MITM,全新题) | 无新问题，5题全部通过。d1分布：3 DIRECTION_ERROR + 2 PARTIAL_PROGRESS。 | — |
| 轮8 | 5 | 后期(无MITM,全新题) | 无新问题，5题全部通过。d1分布：4 DIRECTION_ERROR + 1 TOKEN_LIMIT。 | — |
| 轮9 | 5 | 后期(无MITM,全新题) | 无新问题，5题全部通过。d1分布：4 DIRECTION_ERROR + 1 TOKEN_LIMIT。首次出现d2=p_adic_valuation。 | — |
| 轮10 | 5 | 后期(无MITM,全新题) | 无新问题，5题全部通过。d1分布：5 DIRECTION_ERROR。 | — |
| 深度验证 | 3 | 抽查 | 检查8：d2_exp XML标签泄漏（10%命中）——devin cli标签闭合错误导致正则跨标签提取 | parse_xml加截断逻辑+重新收集所有批次+SOP加检查8 |

### 待解决问题

1. **PolyMath 1564道not_found**：`polymath_{id:05d}`的id映射可能不是简单整数对应。需要调查problem_extraction_progress集合或原始录入脚本确认正确的映射规则。这会导致约25%的PolyMath题无法匹配标准答案。

2. **--export不生成文件**：devin cli的`--export`参数在TUI模式下可能不生成conversation.json。当前用tmux_pipe.log兜底，但如果需要更可靠的数据源，需要调查devin cli的export机制。

3. **DeepMath/ODA-Math解答质量**：这两个题库的解答是AI生成的（r1_solution_1/response），不是人类专家解答。分析结果中"标准解答的关键技巧"可能不准确——需要交叉验证或只用于提取关键技巧名。

4. **compfiles的lean proof**：Lean形式化证明不是人类可读推理。当前data_collector跳过了compfiles题（返回"compfiles_lean"）。如果需要分析compfiles题，需要先将lean proof翻译成自然语言推理。

5. **分析结果用于Mid-Hint选题**：分析完成后，需要根据维度1/维度2的分布，选择适合Mid-Hint实验的题目（DIRECTION_ERROR+PARTIAL_PROGRESS的题，覆盖不同卡点类型）。

6. **旧数据清理**：test-2/test-2b批次的DB记录使用旧schema（数字_key）。大规模运行前可以考虑清理这些旧记录，避免监控脚本查询时混入旧schema数据。清理方法：`FOR r IN analysis_runs FILTER IS_NUMBER(TO_NUMBER(r._key)) REMOVE r IN analysis_runs`。

7. ~~**launcher跳过已completed题的逻辑 + 从pending队列取题**~~（已解决）：launcher现在从Redis pending队列dequeue取题（不再从prepared.json顺序加载）。feeder只入队status=prepared的run，已completed的题不会重复入队。retry_infrastructure重新入pending队列的题，launcher能从pending队列取到。

---

#### POC-2.6 续传机制经验沉淀（2026-08-18）

**completion_tokens限制与续传机制**：glm-5-2单次API调用的completion_tokens上限是25000（thinking+content+tool_calls都算在内）。竞赛数学题的thinking spin可能需要超过25000 tokens，导致AI在thinking中被截断（reasoning_content有46-73K字符，但message=0、tool_calls=0），无法进入working阶段。**续传机制**：让AI在新的API调用中继续思考。每轮25000 completion_tokens推进一部分，多轮累积完成。续传脚本：`Tell分类学研究过程文档/poc_assets/poc_2.6/continue_solver.py`。

**v1方案（机械拼接reasoning_content，已废弃）**：把AI之前完成的reasoning_content作为新prompt的上下文注入。只传reasoning_content（thinking），不传tool_calls/observation。**验证结果**：CC-101_bare和CC-101_vein成功（这两题Round 1只有1个agent step，全部是thinking，所以只传reasoning_content刚好够用）。**但CC-103_bare暴露了严重问题**：Round 1有6个agent step（web_search + 多轮thinking），完整内容221K字符（reasoning 137K + tool_calls 1.8K + observation 82K），v1方案只传了最后一个step的reasoning_content（66K，30%），丢失了前5步的全部上下文——AI做了什么web search、得到了什么结果、写了什么脚本全部丢失。Round 2的81K thinking全在计划写代码但从未写出，因为AI不知道自己之前已经搜索到了Dumitrescu-Jiang论文的Theorem 4。

**v2方案（交接文档，当前使用）**：不是机械拼接thinking，是从完整探索历程中提取有效内容，整理成结构化的研究文档（HANDOFF.md），交给下一个AI继续。像数学家交接研究笔记——下一个AI读了就能直接接手。**验证结果**：CC-103_bare用交接文档续传，AI在2分钟内写出verify_area3.py（z3 SAT solver验证），7分钟内跑出关键结果（7×5网格UNSAT→A(3)≤3），而v1方案同样时间还在thinking中打转。对比效果极为显著。

**交接文档（HANDOFF.md）的标准结构**：
1. **题目**——原始问题
2. **答案猜想**——当前最佳猜想及置信度
3. **已确认的结论**——带推导概要的数学事实（不是原始thinking，是提炼后的结论）
4. **已尝试的方向**——走了哪些路线、成功/失败/未完成
5. **关键文献**——搜索到的论文、定理、已知结果
6. **已有的中间产物**——脚本、计算结果、文件
7. **当前卡在哪里**——截断时正在做什么、遇到了什么困难
8. **建议的下一步**——从已有发现看该试什么

**从每轮export中提取什么**：
- thinking spin → 确认的数学结论、猜想、证明策略、关键计算结果、死胡同及原因（不提取：重复推理、元评论、已纠正的错误细节）
- tool calls → web search的关键发现、写的脚本及运行结果、创建的文件（不提取：失败的搜索、无关结果）
- observation → 论文定理、计算验证结果、搜索到的关键信息（不提取：无关的搜索结果全文）

**循环操作流程**（检测截断→读取完整export→更新HANDOFF.md→启动下一轮→重复）：
1. 检测：export是否被截断（rc>0, msg=0, tc=0, comp≥24000）
2. 读取完整export：所有agent step的thinking + tool_calls + observation
3. 更新HANDOFF.md：把本轮新发现加入交接文档（新确认的结论、新尝试的方向、新写的脚本及运行结果、新的卡点）
4. 启动下一轮：用更新后的HANDOFF.md作为prompt，`devin -p --prompt-file roundN_handoff_prompt.txt`
5. 重复：直到AI输出message（有working产出）或写出proof.md

**v2方案与v1方案的关键区别**：v1是机械拼接reasoning_content（丢70%内容），v2是每轮都整理成结构化的交接文档（保留有效内容、去掉涂改和死胡同）。v2的交接文档整理目前是Master Agent手动做的——后续可自动化为脚本（让一个AI读export、提取有效内容、更新HANDOFF.md）。

**基于cwd的devin进程管理**：当系统中有多个devin实例并行运行（如Grove harness系统在`/Volumes/data/math-agent-glm5.2-tmux-agents-dir/`下跑多个agent），需要精确识别哪些进程属于当前业务。方法：用`lsof -p <pid> | grep cwd`查进程的工作目录——每个run在独有的work_dir中启动，cwd就是进程身份标识。本脚本的进程cwd都在`poc_assets/poc_2.6/workdirs/p26-*`下，别的系统的进程cwd在别处，不会混淆。**不设超时限制**——devin自然运行到完成（输出message后自动退出）。需要中断时跟用户确认后用kill命令（基于cwd匹配杀进程），不要用超时自动杀。续传脚本的`find`命令查进程、`kill`命令杀进程，都基于cwd识别。

#### POC-2.5批量续传实例（2026-08-18启动·跨session持续运行）

**背景**：POC-2.6续传机制验证通过后，启动POC-2.5的16个run批量续传。这个批量运行会跨越多个session（每个run约13-45分钟，15个run串行总计可能需要数小时），后续session的AI需要能定位和管理这个运行。

**如何定位正在运行的实例**：

```bash
# 1. 查当前正在跑的续传devin进程（基于cwd识别）
cd ../..
python3 "Tell分类学研究过程文档/poc_assets/poc_2.6/continue_solver.py" find

# 2. 查批量脚本本身是否还在运行
ps aux | grep "continue_solver.py batch" | grep -v grep

# 3. 查tmux session（每个run的续传在独立tmux session中）
tmux list-sessions 2>&1 | grep p26

# 4. 查已完成run的export文件
ls -la "Tell分类学研究过程文档/poc_assets/poc_2.6/trajectories/"*/round*/exports/conversation.json 2>/dev/null
```

**关键路径**：
- 续传脚本：`Tell分类学研究过程文档/poc_assets/poc_2.6/continue_solver.py`
- 续传数据目录：`Tell分类学研究过程文档/poc_assets/poc_2.6/`
  - `trajectories/p26-<problem>-<condition>/roundN/exports/conversation.json`——每个run每轮的export
  - `workdirs/p26-<problem>-<condition>/`——每个run的工作目录（AI写的脚本/proof.md在这里）
  - `workdirs/p26-<problem>-<condition>/roundN_prompt.txt`——续传prompt（注入的reasoning_content）
- POC-2.5第一轮原始数据：`Tell分类学研究过程文档/poc_assets/poc_2.5_round1/`

**批量脚本运行参数**：
```bash
python3 continue_solver.py batch --max-rounds 5 --problems \
  CC-101_vein CC-101_vein_hint CC-101_hint \
  CC-103_bare CC-103_vein CC-103_vein_hint CC-103_hint \
  CC-104_bare CC-104_vein CC-104_vein_hint CC-104_hint \
  CC-105_bare CC-105_vein CC-105_vein_hint CC-105_hint
```
（CC-101_bare已在POC-2.6单题测试中完成，跳过）

**续传策略**：
- 13个有export的run（Round 1被截断但有reasoning_content）：从Round 2续传开始，注入Round 1的reasoning_content
- 3个无export的run（CC-103-bare/CC-104-bare/CC-105-vein，Round 1有多轮tool call但未生成export）：从Round 1重新运行

**如何中断**（需要跟用户确认后）：
```bash
# 杀当前正在跑的devin进程和批量脚本
python3 "Tell分类学研究过程文档/poc_assets/poc_2.6/continue_solver.py" kill
# 然后杀批量脚本本身
ps aux | grep "continue_solver.py batch" | grep -v grep | awk '{print $2}' | xargs kill
```

**完成后如何分析**：16个run全部完成后，按398号§5.3判定逻辑分析因果效应。注意§2.5的澄清——vein条件混入了特化方法引导的混淆变量，分析时需区分"非特化策略的效果"和"特化方法引导的效果"。CC-101的初步观察显示vein可能误导（bare走Rado定理成功，vein走p-adic卡住），但需等全部run完成后做完整分析。

**首批目标Tell家族**：局部-全局表示切换（Local Representation Switch）——已有CasePack v1（22道题，`poc_assets/poc_0/casepack_v1.md`，2026-08-17冻结：6正迁移+4假朋友+2边界从Pipe 3精筛，4 source trace+4变形+2组合保留v0）和383号TellCore v0候选C（7字段最小充分集）。

**当前状态**：理论框架和POC方案设计已完成（396-412号），7项POC资产已准备（poc_assets/）。下一步是执行——**执行编排见413号**（`Tell分类学研究过程文档/413-v0-2026-08-17-非特化研究执行编排-*.md`），413号定义了六批先后顺序、并行关系、时间估算、关键检查点，以及自包含文档加载纪律（执行任何一步前必须全文加载对应的自包含方案文档+§8清单文档）。**第一步是Pipe 3扩展代码修改（412号§5.1-5.3），完成后立即启动Pipe 3规模化运行（~40小时·瓶颈），在等待期间并行做POC-9和selfrun继续。**

**与解题侧脉络分析线的关系**：解题侧（391号P1-P3）和非特化研究（398-409号POC系列）是两条不同的线——解题侧验证"trace识别能否在真实轨迹上产出可用trace"（VMS-31核心+trace_auditor），非特化研究验证"Tell/Hint能否有效指导AI"。两者在P2/Grove闭环接入时汇合——trace→tell匹配需要TellCore，而TellCore由非特化研究产出。

#### POC-2.7系统运行与检查（2026-08-18实现·Pipe 4+Monitor Pipe）

**★ 错题分析系统总索引**：`AnalysisSystemDesign.md`（项目repo根目录）——任何AI涉足错题分析系统时从该文件开始，索引所有文档、规范、代码资产。

**背景**：POC-2.7把续传机制应用到919道DIRECTION_ERROR题上，验证续传能否大规模解决截断问题。系统已实现为错题分析系统的Pipe 4（独立自包含模式）+ Monitor Pipe设计范式（详见`MonitorPipe.md`）。完整运行和检查指南见`POC-2.7/README.md`。

**当前运行状态**（2026-08-18 14:13重启，异步handover架构）：▶️运行中——launcher+monitor运行中，concurrency=5, max_rounds=5, method=v2。通过标准COMPLETED≥50%。**架构改进**：handover生成已改为异步（start_handover+check_handover），不再阻塞主循环——多个handover可并行生成，完成后自动启动解题devin cli填满并发槽。

**三层架构**：
- **规范层**：`docs/specs/p27_monitor_spec.md` (259行)——检查规范（A类自动检查9项/B类续传质量检查9项/C类AI review抽样5项）
- **执行层**：`src/monitor_continuation.py` (915行)——Monitor Pipe守护进程，按规范执行18项检查，写alert到ArangoDB `p27_monitor_alerts`集合
- **查询层**：`scripts/monitor_check_continuation.sh` (285行)——检查脚本，Master AI每次检查都调用，输出7项检查（含系统健康）+8步行动清单+循环监控指令

**Pipe 4核心文件**（独立自包含，不修改现有Pipe 1/2/3的代码）：
- `src/continuation_config.py`——配置常量（Redis前缀`p27:`/tmux前缀`p27-`/DB集合`p27_continuation_*`/INFRA_FAILURES/MODEL_FAILURES）
- `src/continuation_db_schema.py`——ArangoDB集合定义+索引
- `src/continuation_redis_queue.py`——Redis队列操作
- `src/continuation_collector.py`——数据收集（从problem_list.json加载919道题+创建batch记录）
- `src/continuation_feeder.py`——入Redis队列
- `src/continuation_launcher.py`——**核心**，并发启动devin cli+stall/rate_limit/zombie检测+多轮续传+优雅停止+classify_failure(infra/model)
- `src/continuation_result_collector.py`——结果收集+通过率判定
- `monitoring/continuation_control.py`——**统一控制工具**（start/stop/status/health/set-concurrency+stop_watchdog）
- `scripts/continuation_watchdog.sh`——watchdog脚本（每30秒检查服务存活+每5分钟一致性检查）
- `run_continuation_pipeline.py`——端到端入口（collect→feed→launch→collect-results）

**★ 如何启动全量续传**（推荐——自动启动launcher+monitor到tmux，带auto-restart）：
```bash
cd ..
.venv/bin/python3 -m monitoring.continuation_control start --batch-id p27-full --concurrency 5 --max-rounds 5 --method v2
```

**★ 如何启动watchdog**（守护launcher+monitor，崩溃自动重启）：
```bash
cd ..
tmux new-session -d -s p27-watchdog "bash scripts/continuation_watchdog.sh --batch-id p27-full"
```

**如何查看状态**：
```bash

.venv/bin/python3 -m monitoring.continuation_control status --batch-id p27-full
```

**如何健康检查**（4项检查：服务存活/并发量/DB进度/alert）：
```bash

.venv/bin/python3 -m monitoring.continuation_control health --batch-id p27-full
```

**如何动态调整并发数**（launcher下次poll时自动生效，不影响running）：
```bash

.venv/bin/python3 -m monitoring.continuation_control set-concurrency --batch-id p27-full --concurrency 10
```

**如何检查（Master AI每次检查都调用）**：
```bash
cd ../..
bash scripts/monitor_check_continuation.sh p27-full
```
输出7项检查（Monitor pane/alerts/进程状态/进度/续传质量/通过率判定/**系统健康**）+ 8步行动清单 + **循环监控指令**。

**★ 循环监控SOP**（Master AI的核心职责——反复执行直到所有题完成）：
1. 运行检查脚本，阅读7项检查结果
2. 按行动清单逐项处理（重启挂掉的服务、处理alert、重新入队失败的题）
3. 等待60-120秒，让devin cli继续工作
4. 再次运行检查脚本——如此循环，直到第4项进度显示所有题completed或failed
5. 如果发现系统问题（代码bug/架构问题），修复代码后重启系统，然后继续循环监控
6. **如果session被中断**，下一个session的AI只需运行检查脚本即可恢复全部上下文——脚本的输出会告诉你系统当前状态和需要做什么

**系统健康判断标准**：
- ✅ 健康 = launcher+monitor运行中 + devin cli活跃（pane有内容）+ 进度在推进
- ⚠️ 需关注 = 有新alert + 失败率>15% + handover生成慢
- ❌ 修复 = launcher/monitor挂了 + devin cli全卡住 + 进度停滞

**如何查看和处理alerts**：
```bash
# 查看新alerts
&& .venv/bin/python3 -m src.monitor_continuation --batch-id p27-full --check-alerts
# 标记alert为已解决
.venv/bin/python3 -m src.monitor_continuation --batch-id p27-full --resolve-alert <alert_key>
```

**alert分类**（详见`specs/p27_monitor_spec.md`）：
- A类自动检查（9项）：session_health/queue_stalled/rate_limit/zombie_sessions/export_missing/failure_rate/launcher_dead/long_running
- B类续传质量检查（7项）：proof_missing/proof_no_boxed/proof_too_small/handover_missing/handover_too_small/all_rounds_truncated/status_anomaly
- C类AI review抽样（5项，需Master AI判断）：proof_quality/proof_hallucination/answer_leak/handover_quality/continuation_direction

**通过标准**（415号§7.1）：919道题中COMPLETED≥50% → POC-2.7通过。

**★ 如何停止系统**（推荐——自动处理watchdog+launcher+monitor）：
```bash

# 优雅停止（不kill devin实例，等running自然完成）
.venv/bin/python3 -m monitoring.continuation_control stop
# 强制停止（kill所有session+清空Redis队列）
.venv/bin/python3 -m monitoring.continuation_control stop --force
```
**注意**：stop命令的第一步是stop_watchdog()——launchctl unload+disable plist + kill tmux session，防止watchdog重启已停掉的服务。

