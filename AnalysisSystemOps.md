# AnalysisSystemOps.md — 错题分析系统运行操作手册

> **来源**：从 AGENTS.md 第3518-4216行外移（2026-08-19瘦身工程，392号方案）。
> **定位**：错题分析系统（analysis-devin-failure-system/）的运行操作手册。与 AnalysisSystemDesign.md 分工：Design=设计总索引/架构/决策，Ops=运行操作/SOP/检查清单/打磨记录。
> **加载时机**：当你要运行/监控/调试错题分析系统（analysis-devin-failure-system/，判定失败题是"方向出错"还是"token不够"并分类卡点类型）时，必须用read工具全文加载本文件。涉及错题分析系统设计时另读 AnalysisSystemDesign.md。不涉及错题分析系统时不需要读。
> **AGENTS.md索引**：AGENTS.md "外部文档索引"节有指向本文件的索引行。

---

## 错题分析系统（analysis-devin-failure-system）

> **用途**：用并发devin cli实例分析失败题——判定每道失败题是"方向出错"还是"token不够"，并分类卡点类型。用于Mid-Hint实验的选题阶段。
>
> **核心设计**：devin cli在运行时不调用任何工具，只读AGENTS.md中的内容（题目+标准答案+AI历史thinking），在TUI中输出XML格式的分析结果。程序通过tmux_pipe.log提取XML。

### 代码库位置

`analysis-devin-failure-system/`

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
cd analysis-devin-failure-system

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
cd /Users/user/glm5.2-math-worktree

# 端到端（全部步骤）
python analysis-devin-failure-system/run_pipeline.py --batch-id analysis-1 --limit 100 --concurrency 10

# 分步执行
# 1. 收集数据，构造AGENTS.md
python analysis-devin-failure-system/run_pipeline.py --batch-id analysis-1 --step collect --limit 100

# 2. 并发启动分析（feeder入队+launcher启动）
python analysis-devin-failure-system/run_pipeline.py --batch-id analysis-1 --step launch --concurrency 10
# 或分离模式：feeder入队 + launcher从队列取题
python -m src.feeder --batch-id analysis-1 --once
python -m src.analysis_launcher --batch-id analysis-1 --concurrency 10
# 或launcher的--auto-feed模式（一次性入队+启动）
python -m src.analysis_launcher --batch-id analysis-1 --concurrency 10 --auto-feed

# 3. 收集结果
python analysis-devin-failure-system/run_pipeline.py --batch-id analysis-1 --step collect-results

# 4. 汇总报告
python analysis-devin-failure-system/run_pipeline.py --batch-id analysis-1 --step aggregate

# 查看状态
python analysis-devin-failure-system/run_pipeline.py --batch-id analysis-1 --step status

# 停止所有
python analysis-devin-failure-system/run_pipeline.py --batch-id analysis-1 --step stop

# 指定题号分析
python analysis-devin-failure-system/run_pipeline.py --batch-id test --step collect --problem-ids polymath_01687,deepmath_103k_00021551
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
cd /Users/user/glm5.2-math-worktree/analysis-devin-failure-system

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
cd /Users/user/glm5.2-math-worktree/analysis-devin-failure-system

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
