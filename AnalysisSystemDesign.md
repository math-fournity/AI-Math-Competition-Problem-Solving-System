# AnalysisSystemDesign.md — 错题分析系统设计总索引

> **用途**：任何AI涉足错题分析系统（`analysis-devin-failure-system/`）时，从本文件开始。本文件索引所有需要看的文档、要遵守的规范、要参考的代码资产。
>
> **位置**：项目repo根目录（`/Users/user/glm5.2-math-worktree/AnalysisSystemDesign.md`）

---

## 1. 快速入口

### 我要创建新Pipe

1. 读`analysis-devin-failure-system/docs/framework-checklist.md`——12项必查清单
2. 读`MonitorPipe.md` §6——11步操作指南
3. 以Pipe 4（`continuation_*.py`）为模板复制
4. 验证——`framework-checklist.md`末尾的验证清单

### 我要运行现有Pipe

| Pipe | 启动 | 检查 | 停止 |
|---|---|---|---|
| Pipe 1 分析 | `run_pipeline.py --batch-id {id} --step all` | `scripts/monitor_check.sh {id}` | `monitoring/analysis_control.py stop` |
| Pipe 2 审计 | `run_audit_pipeline.py --batch-id {id} --step all` | `scripts/monitor_check.sh {id}` | `monitoring/analysis_control.py stop` |
| Pipe 3 选题 | `run_selection_pipeline.py --batch-id {id} --step all` | `scripts/monitor_check_selection.sh {id}` | `monitoring/analysis_control.py stop` |
| Pipe 4 续传 | `monitoring/continuation_control.py start --batch-id {id}` | `scripts/monitor_check_continuation.sh {id}` | `monitoring/continuation_control.py stop` |

### 我要停止系统（含watchdog）

```bash
# 错题分析系统Pipe 4（推荐——自动处理watchdog）
cd analysis-devin-failure-system
python -m monitoring.continuation_control stop          # 优雅停止
python -m monitoring.continuation_control stop --force  # 强制停止

# 解题系统
bash xishujuzhen/solver_harness/pipe/pipe_stop.sh           # 优雅停止（保留collector+watchdog）
bash xishujuzhen/solver_harness/pipe/pipe_stop.sh --finish  # 收尾停止（停collector+watchdog）
bash xishujuzhen/solver_harness/pipe/pipe_stop.sh --force   # 立即停止（停所有+watchdog）
bash xishujuzhen/solver_harness/pipe/pipe_stop.sh --kill    # 强制kill（停所有+kill harness session+watchdog）
```

**关键**：停止系统时必须先停watchdog（unload launchd plist + kill进程），否则watchdog会重启刚停掉的服务。

### 我要调整并发数

```bash
# Pipe 4——修改DB中batch记录
cd analysis-devin-failure-system
python -m monitoring.continuation_control set-concurrency --batch-id {id} --concurrency 20

# 解题系统——修改Redis配置
cd xishujuzhen/solver_harness/pipe
python pipe_control.py concurrency 50
```

---

## 2. 文档体系（必读顺序）

### 第一优先级——创建新Pipe前必读

| 文档 | 位置 | 用途 |
|---|---|---|
| **framework-checklist.md** | `analysis-devin-failure-system/docs/` | **12项必查清单**——独立自包含/前缀隔离/动态并发/优雅停止/stall检测/rate_limit/zombie/Monitor Pipe/DB-文件追溯/多轮续传/watchdog停止 |
| **MonitorPipe.md** | 项目repo根目录 | Monitor Pipe完整设计范式+新Pipe实现指南（§6 11步操作） |

### 第二优先级——理解架构和设计决策

| 文档 | 位置 | 用途 |
|---|---|---|
| architecture.md | `analysis-devin-failure-system/docs/` | 4个Pipe的演进（共享→扩展→独立自包含）、4步架构、目录结构 |
| graceful-shutdown.md | `analysis-devin-failure-system/docs/` | 优雅停止设计——信号处理、两种停止模式、**§5 watchdog停止核心问题** |
| dynamic-concurrency.md | `analysis-devin-failure-system/docs/` | 动态并发设计——Redis配置中心vs DB记录两种方案 |
| monitor-pipe-pattern.md | `analysis-devin-failure-system/docs/` | Monitor Pipe设计范式本地参考——三层架构、检查项目分类 |
| operational-concerns.md | `analysis-devin-failure-system/docs/` | 运维关注点——rate limit/stall/zombie/多轮续传/断点续传 |
| solver-harness-borrowing.md | `analysis-devin-failure-system/docs/` | 解题系统7个借鉴分析——多模块解耦/auto-restart/watchdog/classify/infra-vs-model/验证工具/reporter |

### 第三优先级——特定场景

| 文档 | 位置 | 何时读 |
|---|---|---|
| selfrun-workflow.md | `analysis-devin-failure-system/docs/` | 使用selfrun模式时 |
| solver-trajectory-schema.md | `analysis-devin-failure-system/docs/` | 处理trajectory数据时 |
| p27_monitor_spec.md | `analysis-devin-failure-system/specs/` | Pipe 4的检查规范（A类9项/B类7项/C类5项） |
| POC-2.7/README.md | `POC-2.7/` | POC-2.7完整运行和检查指南 |

### 外部文档

| 文档 | 位置 | 用途 |
|---|---|---|
| MonitorPipe.md | 项目repo根目录 | Monitor Pipe完整设计范式+新Pipe实现指南 |
| `~/.config/devin/rules/monitor-pipe-design-paradigm.md` | 全局rule | always-on，触发条件+三层架构定义 |
| AGENTS.md "POC-2.7系统运行与检查"节 | 项目AGENTS.md | POC-2.7在项目中的位置和运行方法 |

---

## 3. 必须遵守的规范（Rules）

### 项目级Rules（`.devin/rules/`）

| Rule | 文件 | 与错题分析系统的关系 |
|---|---|---|
| **pipeline-monitor-sop** | `.devin/rules/pipeline-monitor-sop.md` | 运行任何Pipe时必须启动Monitor Pipe并行监控，检查时用标准化脚本 |
| **six-dual-check-mechanism** | `.devin/rules/six-dual-check-mechanism.md` | 双重检查机制——代码检查+流程审计AI，检查规范用`.ai-check`文件 |
| **six-asset-grading** | `.devin/rules/six-asset-grading.md` | 检查规范应该是level 2资产（文件），不是嵌入代码或直接提示词 |
| **db-file-traceability** | `.devin/rules/db-file-traceability.md` | DB记录和物理文件双向可追溯——DB中run记录指向work_dir，work_dir有产出文件 |
| **solver-concurrency** | `.devin/rules/solver-concurrency.md` | Solver AI并发约束（解题系统，非错题分析系统，但参考其模式） |
| **solver-batch-health-check** | `.devin/rules/solver-batch-health-check.md` | 批量集群健康检查铁律 |
| **six-codebase-first** | `.devin/rules/six-codebase-first.md` | 代码为中心——从代码出发设计方案 |
| **six-trace-preservation** | `.devin/rules/six-trace-preservation.md` | 痕迹保留——alert写入ArangoDB，全过程可审计 |

### 全局Rules（`~/.config/devin/rules/`）

| Rule | 文件 | 用途 |
|---|---|---|
| **monitor-pipe-design-paradigm** | `~/.config/devin/rules/monitor-pipe-design-paradigm.md` | always-on，Monitor Pipe三层架构定义和触发条件 |

### 全局AGENTS.md中的元组

| 元组 | 位置 | 用途 |
|---|---|---|
| **monitor-pipe-design-paradigm** | `~/.config/devin/AGENTS.md` §元组 | Rule+Skill，连续工作系统的Monitor Pipe设计范式 |
| **db-file-traceability** | `~/.config/devin/AGENTS.md` §元组 | Rule+Skill，数据库-文件双向可追溯性验证 |

---

## 4. 代码资产索引

### 共享基础设施（所有Pipe共用）

| 文件 | 位置 | 用途 |
|---|---|---|
| `shared_logger.py` | `monitoring/` | 统一日志（每个模块一个logger） |
| `graceful_shutdown.py` | `monitoring/` | 优雅退出（SIGTERM/SIGINT→设flag，不kill devin实例） |
| `config.py` | `src/` | Pipe 1/2/3共享配置（路径/DB/RATE_LIMIT_PATTERNS） |
| `db_schema.py` | `src/` | Pipe 1/2/3共享ArangoDB集合+`connect_db()` |
| `redis_queue.py` | `monitoring/` | Pipe 1/2的Redis队列（`analysis:`前缀） |
| `recover_from_crash.py` | `monitoring/` | 断电恢复+僵尸清理 |
| `runtime_health_check.py` | `monitoring/` | 运行时健康检查 |
| `verify_completeness.py` | `monitoring/` | 数据完备性验证 |
| `verify_result_integrity.py` | `monitoring/` | 结果完整性验证 |
| `retry_infrastructure.py` | `monitoring/` | 基础设施失败自动重试 |
| `reporter.py` | `monitoring/` | 统计报告服务 |

### Pipe 1（分析）——共享基础设施层

| 文件 | 位置 | 用途 |
|---|---|---|
| `data_collector.py` | `src/` | 从ArangoDB获取失败题+构造AGENTS.md |
| `analysis_launcher.py` | `src/` | 并发启动devin cli（tmux） |
| `result_collector.py` | `src/` | 从export提取XML分析结果 |
| `aggregator.py` | `src/` | 汇总分析结果，输出报告 |
| `monitor_pipe.py` | `src/` | Pipe 1/2的Monitor Pipe |
| `analysis_control.py` | `monitoring/` | Pipe 1/2/3的统一控制工具 |
| `monitor_check.sh` | `scripts/` | Pipe 1/2的检查脚本 |
| `analysis_agents_md.md` | `templates/` | Pipe 1的AGENTS.md模板 |

### Pipe 2（审计）——共享+扩展

| 文件 | 位置 | 用途 |
|---|---|---|
| `audit_collector.py` | `src/` | 审计数据收集 |
| `audit_launcher.py` | `src/` | 审计并发启动 |
| `audit_result_collector.py` | `src/` | 审计结果收集 |
| `audit_aggregator.py` | `src/` | 审计汇总 |
| `audit_redis_queue.py` | `monitoring/` | Pipe 2的Redis队列（`audit:`前缀） |
| `audit_agents_md.md` | `templates/` | Pipe 2的AGENTS.md模板 |

### Pipe 3（选题）——共享+扩展

| 文件 | 位置 | 用途 |
|---|---|---|
| `selection_collector.py` | `src/` | 选题数据收集 |
| `selection_launcher.py` | `src/` | 选题并发启动 |
| `selection_result_collector.py` | `src/` | 选题结果收集 |
| `monitor_selection.py` | `src/` | Pipe 3的Monitor Pipe |
| `monitor_check_selection.sh` | `scripts/` | Pipe 3的检查脚本 |
| `selection_agents_md.md` | `templates/` | Pipe 3的AGENTS.md模板 |

### Pipe 4（续传）——独立自包含（推荐新Pipe采用此模式）

| 文件 | 位置 | 用途 |
|---|---|---|
| `continuation_config.py` | `src/` | 配置常量（`p27:`前缀/`p27-`tmux/`p27_*`集合/INFRA_FAILURES/MODEL_FAILURES） |
| `continuation_db_schema.py` | `src/` | ArangoDB集合定义+`connect_db()` |
| `continuation_redis_queue.py` | `src/` | Redis队列操作（`p27:`前缀） |
| `continuation_collector.py` | `src/` | 数据收集（从problem_list.json加载919道题） |
| `continuation_feeder.py` | `src/` | 入Redis队列 |
| `continuation_launcher.py` | `src/` | **核心**——并发启动+stall/rate_limit/zombie检测+多轮续传+优雅停止+classify_failure |
| `continuation_result_collector.py` | `src/` | 结果收集+通过率判定 |
| `monitor_continuation.py` | `src/` | Pipe 4的Monitor Pipe守护进程 |
| `continuation_control.py` | `monitoring/` | Pipe 4统一控制工具（start/stop/status/health/set-concurrency+stop_watchdog） |
| `continuation_watchdog.sh` | `scripts/` | watchdog脚本（每30秒检查服务存活） |
| `p27_monitor_spec.md` | `specs/` | Pipe 4的检查规范（A类9项/B类7项/C类5项） |
| `monitor_check_continuation.sh` | `scripts/` | Pipe 4的检查脚本 |
| `run_continuation_pipeline.py` | 根目录 | Pipe 4端到端入口 |

### 端到端入口

| 文件 | 位置 | 用途 |
|---|---|---|
| `run_pipeline.py` | `analysis-devin-failure-system/` | Pipe 1端到端入口 |
| `run_audit_pipeline.py` | `analysis-devin-failure-system/` | Pipe 2端到端入口 |
| `run_selection_pipeline.py` | `analysis-devin-failure-system/` | Pipe 3端到端入口 |
| `run_continuation_pipeline.py` | `analysis-devin-failure-system/` | Pipe 4端到端入口 |

---

## 5. 设计原则（6条）

1. **独立自包含**（Pipe 4模式）——新Pipe不修改现有Pipe的代码，所有组件独立
2. **优雅停止**——停launcher不kill devin实例，等running自然完成；**有watchdog时先停watchdog**
3. **动态并发**——运行期可调整并发数，不需要重启
4. **Monitor Pipe**——应该由AI智能检查的项目全部放入Pipe，结果收集到DB的alert集合
5. **DB-文件双向可追溯**——DB中run记录指向工作目录，工作目录有产出文件
6. **痕迹保留**——alert写入ArangoDB，全过程可审计

---

## 6. 关键设计决策记录

### 6.1 为什么Pipe 4采用独立自包含模式（而不是共享基础设施）

Pipe 1/2/3采用共享基础设施模式——复用config/db_schema/redis_queue。但运行中发现：
- 修改共享代码会影响正在运行的Pipe
- 前缀冲突导致Redis/ArangoDB数据混在一起
- 新Pipe的配置需求与共享配置不一致

Pipe 4改为独立自包含——8个文件全部独立，只共享`shared_logger.py`和`graceful_shutdown.py`。

### 6.2 为什么检查规范要提前落盘为独立文件

Pipe 1/2/3的检查规范内嵌在代码中——不可读、不可审计、不能被审计AI直接加载。

Pipe 4改为`specs/p27_monitor_spec.md`——独立的`.ai-check`格式文件，区分A类自动检查/B类质量检查/C类AI review抽样。

### 6.3 为什么stop_watchdog必须是stop命令的第一步

watchdog通过launchd自动启动后，如果只kill服务tmux session而不停watchdog，watchdog会在30秒内重启刚停掉的服务——导致"停不掉"。

`stop_watchdog()`必须同时做三步：
1. `launchctl unload` plist（从当前session移除，阻止launchd立即重启）
2. `launchctl disable` 服务（永久禁用——unload不够，plist文件还在，系统重启后launchd会自动重新加载）
3. kill watchdog的tmux session或进程（阻止当前运行的实例）

**unload vs disable**：unload只是当前session移除，disable是永久禁用。只unload不disable，系统重启后watchdog会自动回来。

### 6.4 为什么区分基础设施失败和模型能力失败

基础设施失败（rate_limited/failed_connection/dead_session）——可重试，重试3次后入pending重新启动。
模型能力失败（failed_timeout/failed_stall/failed_no_proof/truncated_at_max）——不可重试，是AI能力边界的数据，重试只会得到同样的结果。

Pipe 4的`classify_failure()`函数和`retry_eligible`字段实现这个区分。

### 6.5 为什么用auto-restart包裹launcher

919题跑8天，launcher可能因为Redis断连、未处理异常等崩溃。不自动重启会导致整个batch停滞。

auto-restart用bash while循环包裹：`while true; do python launcher.py; echo "退出, 5秒后重启"; sleep 5; done`

---

## 7. 解题系统参考

错题分析系统的很多设计借鉴自解题系统（`xishujuzhen/solver_harness/pipe/`）。完整分析见`analysis-devin-failure-system/docs/solver-harness-borrowing.md`。

| 借鉴项 | 解题系统位置 | 错题分析系统实现 |
|---|---|---|
| 多模块解耦 | `pipe_control.py`（6个独立服务） | Pipe 4保留单体launcher，拆retry/reporter |
| auto-restart | `pipe_control.py` `start_service()` | `continuation_control.py` `start_service()` |
| watchdog | `pipe_watchdog.sh` + launchd plist | `continuation_watchdog.sh` |
| 精细化classify() | `collector.py` `classify()`（10+终态） | `continuation_launcher.py` `classify_failure()` |
| infra-vs-model失败 | `retry_infrastructure.py` | `continuation_config.py` INFRA_FAILURES/MODEL_FAILURES |
| 优雅停止 | `graceful_shutdown.py` + `pipe_stop.sh` | `graceful_shutdown.py` + `continuation_control.py` |
| 动态并发 | Redis配置中心 | DB记录（batch.concurrency字段） |
