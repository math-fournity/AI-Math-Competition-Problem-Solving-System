# AnalysisSystemDesign.md — 错题分析系统设计总索引

> ⚠️ **过时标记（2026-08-20）**：本文档描述的是删除 Pipe 1/2/3 前的 4 Pipe 架构设计。
> 当前系统只有 Pipe 4 续传解题管线。设计文档参见 `docs/architecture/solve-pipeline.md`
> 和 `docs/architecture/dynamic-concurrency.md`。本文档保留作历史参考。

> **用途**：任何AI涉足错题分析系统时，从本文件开始。本文件索引所有需要看的文档、要遵守的规范、要参考的代码资产。
>
> **位置**：项目repo根目录（`AnalysisSystemDesign.md`）

---

## 1. 快速入口

### 我要创建新Pipe

1. 读`docs/architecture/framework-checklist.md`——12项必查清单
2. 读`MonitorPipe.md` §6——11步操作指南
3. **如果涉及多轮续传**——读`续传规范文档.md`（项目repo根目录）——HANDOFF.md八章节结构、提取规则、截断/完成判定、prompt模板
4. 以Pipe 4（`continuation_*.py`）为模板复制
5. 验证——`framework-checklist.md`末尾的验证清单

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
| **framework-checklist.md** | `docs/architecture/` | **12项必查清单**——独立自包含/前缀隔离/动态并发/优雅停止/stall检测/rate_limit/zombie/Monitor Pipe/DB-文件追溯/多轮续传/watchdog停止 |
| **MonitorPipe.md** | 项目repo根目录 | Monitor Pipe完整设计范式+新Pipe实现指南（§6 11步操作） |
| **续传规范文档.md** | 项目repo根目录 | **续传机制的标准规范**——HANDOFF.md八章节结构、从export提取规则、截断/完成判定、续传prompt模板、v1 vs v2方案对比。**任何涉及多轮续传的Pipe必须遵守此文档** |

### 第二优先级——理解架构和设计决策

| 文档 | 位置 | 用途 |
|---|---|---|
| architecture.md | `docs/architecture/` | 4个Pipe的演进（共享→扩展→独立自包含）、4步架构、目录结构 |
| graceful-shutdown.md | `docs/architecture/` | 优雅停止设计——信号处理、两种停止模式、**§5 watchdog停止核心问题** |
| dynamic-concurrency.md | `docs/architecture/` | 动态并发设计——Redis配置中心vs DB记录两种方案 |
| monitor-pipe-pattern.md | `docs/architecture/` | Monitor Pipe设计范式本地参考——三层架构、检查项目分类 |
| operational-concerns.md | `docs/architecture/` | 运维关注点——rate limit/stall/zombie/多轮续传/断点续传 |
| solver-harness-borrowing.md | `docs/architecture/` | 解题系统7个借鉴分析——多模块解耦/auto-restart/watchdog/classify/infra-vs-model/验证工具/reporter |

### 第三优先级——特定场景

| 文档 | 位置 | 何时读 |
|---|---|---|
| selfrun-workflow.md | `docs/architecture/` | 使用selfrun模式时 |
| solver-trajectory-schema.md | `docs/architecture/` | 处理trajectory数据时 |
| p27_monitor_spec.md | `docs/specs/` | Pipe 4的检查规范（A类9项/B类9项/C类5项） |
| **p27_monitor_pipe_operations.md** | `docs/specs/` | **Monitor Pipe操作规范（认知资产入口）**——Monitor Exec Devin启动时读这一份，包含认知资产加载清单+系统检查项目(A12/B9/C5)+self检查项目(S14)+可追溯性规范+完整工作流程。持续迭代文档 |
| **p27_session_management_and_polish_spec.md** | `docs/specs/` | **Session编号化管理+Monitor Pipe执行devin架构规范**——session注册表/DONE.md铁律/Monitor Exec Devin三位一体（检查+判断+修复）。`p27_monitor_spec.md`的演进：后者定义"检查什么"，本规范定义"Monitor Pipe执行devin怎么工作"和"session怎么管"。**修正了MonitorPipe.md §2.2的历史错误**——Monitor Pipe执行层恢复为Python(A/B类)+devin cli(C类+修复)两层架构，不再只是纯Python |
| POC-2.7/README.md | `POC-2.7/` | POC-2.7完整运行和检查指南 |

### 外部文档

| 文档 | 位置 | 用途 |
|---|---|---|
| 续传规范文档.md | 项目repo根目录 | **续传机制标准规范**——HANDOFF.md八章节结构、提取规则、截断/完成判定、prompt模板。414号方案 |
| MonitorPipe.md | 项目repo根目录 | Monitor Pipe完整设计范式+新Pipe实现指南 |
| 399号方案 | `Tell分类学研究过程文档/399-v0-2026-08-18-POC-2.6-续传机制验证-*.md` | POC-2.6续传机制验证方案——v1机械拼接方案的原始定义 |
| 415号方案 | `Tell分类学研究过程文档/415-v0-2026-08-18-POC-2.7-截断vs思维错误.md` | POC-2.7方案——948道DIRECTION_ERROR题全量续传，通过标准COMPLETED≥50% |
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
| `continuation_launcher.py` | `src/` | **核心**——并发启动+stall/rate_limit/zombie检测+多轮续传+优雅停止+classify_failure+`make_round_log_entry()`+中间产物归档 |
| `continuation_result_collector.py` | `src/` | 结果收集+通过率判定 |
| `monitor_continuation.py` | `src/` | Pipe 4的Monitor Pipe守护进程Python部分（A1-A9+B1-B9+C类抽样标记+定时启动Monitor Exec Devin） |
| `monitor_exec_launcher.py` | `src/` | **Monitor Pipe执行devin启动器**——定时启动devin cli做C类AI检查+修复（见`specs/p27_session_management_and_polish_spec.md` §B） |
| `session_registry.py` | `src/` | **Session编号化管理**——seq分配+注册表CRUD+一致性检查（见`specs/p27_session_management_and_polish_spec.md` §A） |
| `continuation_control.py` | `monitoring/` | Pipe 4统一控制工具（start/stop/status/health/set-concurrency+stop_watchdog+sessions管理） |
| `continuation_watchdog.sh` | `scripts/` | watchdog脚本（每30秒检查服务存活） |
| `p27_monitor_spec.md` | `specs/` | Pipe 4的检查规范（A类9项/B类9项/C类5项） |
| `p27_session_management_and_polish_spec.md` | `specs/` | **Session管理+Monitor Exec Devin架构规范**——session注册表/DONE.md铁律/三位一体工作循环 |
| `monitor_exec_prompt.md` | `templates/` | Monitor Exec Devin的prompt模板 |
| `monitor_check_continuation.sh` | `scripts/` | Pipe 4的检查脚本 |
| `run_continuation_pipeline.py` | 根目录 | Pipe 4端到端入口 |

### 端到端入口

| 文件 | 位置 | 用途 |
|---|---|---|
| `run_pipeline.py` | `` | Pipe 1端到端入口 |
| `run_audit_pipeline.py` | `` | Pipe 2端到端入口 |
| `run_selection_pipeline.py` | `` | Pipe 3端到端入口 |
| `run_continuation_pipeline.py` | `` | Pipe 4端到端入口 |

---

## 5. 设计原则（8条）

1. **独立自包含**（Pipe 4模式）——新Pipe不修改现有Pipe的代码，所有组件独立
2. **优雅停止**——停launcher不kill devin实例，等running自然完成；**有watchdog时先停watchdog**
3. **动态并发**——运行期可调整并发数，不需要重启
4. **Monitor Pipe（两层执行层）**——应该由AI智能检查的项目由devin cli部分做（C类+修复），Python部分做A/B类自动检查。检查+修复的日常循环由Monitor Pipe执行devin完成，Master Agent只在用户主动询问或自愈循环失效时介入
5. **DB-文件双向可追溯**——DB中run记录指向工作目录，工作目录有产出文件
6. **痕迹保留**——alert写入ArangoDB，全过程可审计
7. **中间产物不可覆盖**——每轮的中间产物用round编号区分路径，不被后续round覆盖（§6.6）
8. **DB记录完整性**——所有路径（成功/截断/失败）都写入rounds_log和event集合（§6.7）

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

### 6.6 中间产物不可覆盖原则（2026-08-18踩坑修复）

**问题**：多轮续传中，每轮的中间产物（HANDOVER.md/conversation_map.md/proof.md/handover_run/）如果路径不唯一，会被后续round覆盖，导致：
- 历史过程丢失——无法审计AI在每轮做了什么
- is_completed误判——Round 3启动时看到Round 2的proof.md，误判为已完成
- rounds_log字段名不匹配——写入时用`"export"`，读取时用`"export_path"`，导致Round 3+全部失败

**原则**：每轮的所有中间产物必须用round编号区分，路径唯一，不被后续round覆盖。

**实现**（`continuation_launcher.py`）：
- `generate_handover()`：`map_path = work_dir / f"round{N}_conversation_map.md"`，`handover_path = work_dir / f"round{N}_HANDOVER.md"`
- 完成判定时归档proof.md：`shutil.copy2(proof_path, work_dir / f"round{N}_proof.md")`
- 启动新round前删除旧proof.md：`old_proof.unlink()`（防止is_completed误判）
- `make_round_log_entry()`：统一构造rounds_log条目，包含7个中间产物路径字段

**rounds_log每条记录的完整字段**：
```python
{
    "round": 2,                    # 轮次编号
    "export": ".../round2/exports/conversation.json",
    "truncated": False,
    "completed": True,
    "reason": "proof.md有boxed",
    "method": "v2",                # 使用的方法（v2或v1回退）
    "handover_success": True,      # Pipe A是否成功
    "handover_path": ".../round1_HANDOVER.md",
    "map_path": ".../round1_conversation_map.md",
    "prompt_path": ".../round2_prompt.txt",
    "prev_export": ".../round1_export.json",
    "proof_path": ".../round2_proof.md",  # 归档路径，不会被覆盖
}
```

### 6.7 DB记录完整性原则（2026-08-18踩坑修复）

**问题**：失败路径（dead_session/stall/timeout/rate_limited/unknown）不写rounds_log，只更新run的status。导致失败轮次的过程信息完全丢失——无法审计AI在哪一轮失败、为什么失败。

**原则**：所有路径（成功/截断/失败）都必须写入rounds_log和event集合。

**实现**（`continuation_launcher.py`）：
- 所有6种失败路径都调用`make_round_log_entry()`写入rounds_log
- 所有路径都记录`insert_event()`：
  - `continuation_launched`（启动时，含handover_success）
  - `continuation_completed`（完成时）
  - `continuation_truncated`（截断续传时）
  - `continuation_truncated_at_max`（达到最大轮次时）
  - `continuation_failed`（dead_session/unknown/timeout/stall）
  - `infra_failure`（rate_limited/failed_connection）

### 6.8 Monitor Pipe检测能力完整性（2026-08-18踩坑修复）

**问题**：Monitor Pipe的`check_handover_completeness`用了和`generate_handover`一样的错误路径逻辑，检查了错误的目录。而且完全没有检查文件路径唯一性、rounds_log字段一致性、proof.md覆盖。

**原则**：Monitor Pipe不仅要检查结果质量，还要检查中间产物的完整性和唯一性。

**新增检查项**（`monitor_continuation.py`）：
- B8 `check_rounds_log_integrity`：检查rounds_log字段完整性 + export/handover/proof文件存在性 + round编号连续性
- B9 `check_intermediate_product_uniqueness`：检查同一run不同round的export/handover/proof路径不重复 + 不同run的work_dir不重复

### 6.9 为什么用DB注册表管理session（而不是文件）

**来源**：`specs/p27_session_management_and_polish_spec.md` §E.1

- tmux list-sessions只显示活着的session，死了的没痕迹——注册表是source of truth
- 文件会和tmux实际状态不同步（launcher崩溃后文件残留）——DB的update有原子性
- 已有ArangoDB连接，加一个collection成本为零
- 注册表可以查询历史（"上周创建过多少session"），文件不行

### 6.10 为什么Monitor Exec Devin并发=1

**来源**：`specs/p27_session_management_and_polish_spec.md` §E.2

- Monitor Exec Devin会commit代码，多个并发修改可能git冲突
- 每轮做完整检查+修复，并发了会重复检查同样的问题
- 一轮通常几分钟到十几分钟，串行足够
- 不需要Master Agent事后审计每一轮——自愈循环自己验证（下一轮检查会发现上一轮修的对不对）

### 6.11 为什么Monitor Exec Devin不能修改AGENTS.md/spec

**来源**：`specs/p27_session_management_and_polish_spec.md` §E.3

- AGENTS.md和spec是规范，修改规范需要用户参与讨论
- Monitor Exec Devin只修代码bug，不修规范——规范变更走Master Agent + 用户
- 如果bug的根因确实是规范有问题，Monitor Exec Devin在MONITOR_EXEC_REPORT.md中提出，Master Agent决定是否启动规范变更流程

### 6.12 为什么不把Monitor Exec Devin做成subagent

**来源**：`specs/p27_session_management_and_polish_spec.md` §E.4

- devin cli非交互模式本身不支持subagent
- subagent的输出不直接保留——Monitor Exec Devin的export是完整thinking，可审计
- subagent由Master Agent的session承载，session压缩后subagent上下文丢失——Monitor Exec Devin是独立devin cli实例，不受Master Agent session影响
- 这正是解决"Master Agent上下文漂移"的关键：打磨工作在独立devin cli里，不在Master Agent session里

### 6.13 为什么stuck session不自动kill

**来源**：`specs/p27_session_management_and_polish_spec.md` §E.5

- 用户明确要求："必须等到DONE.md出现再kill，否则就一直留在那里，等到Master Agent在用户的授意之下再处理"
- stuck的session可能自己恢复（rate_limit解除后devin cli继续）或自然退出（写完export后退出）
- 自动kill会重蹈export丢失的覆辙——这是本规范要根治的问题
- stuck不占并发槽，不影响系统吞吐——只是占tmux资源，tmux能承载几百个session

### 6.14 步进门闸=语义动作闸，底层I/O封装不设闸（2026-08-20定稿）

曾试行"所有Redis写装L1资源闸"的方案，回退——`enqueue_pending`有feeder/截断
重入队/防抖重入队三个调用方，各自的正确性标准不同，**"这次入队对不对"的答案
在调用方，不在I/O本身**，底层粒度写不出统一checklist，而checklist恰是门闸的
核心价值。定稿：闸只设在语义动作上（9个）；resource只是分类标签供批量hold。
checklist闭包的传递链：docstring（唯一事实源，随代码同commit）→inspect反射
→DB缓存→hold触发时置Y（waiting_for）→SOP_01/`--pending`按"放行前"标题提取
完整输出→Master Agent核对→`--step`放行。详见`docs/patterns/StepGate.md`。

### 6.15 截断判定必须先于dead判定；rounds_log必须含round-1（2026-08-20，sim实证）

原sweep结构里`is_truncated`只在"已完成"之后才被咨询——devin退出+无proof+截断
态export时dead分支抢占，**截断→重入队的多轮续传引擎结构性不可达**，真实截断
全部被误判dead_session（生产run 4712实证，其export是教科书式截断）。同理
round-1（seed重判）不补录rounds_log条目导致`current_round=len+1`重跑round 2。
两个修复均由全流程模拟首日运行实证（solve3剧本rounds_log从[2,2,3]修为[1,2,3]）。
**教训：未被生产数据触发过的分支≈未测试的分支**——生产299条rounds_log全是
completed、零截断条目，恰说明截断路径从未真正跑通过。

### 6.16 全流程模拟：命令行层注入，世界=文件+进程行为（2026-08-20，dev-docs/017）

模拟"AI世界"的正确注入点不在内部接缝（mock返回值破坏控制流），而在命令构造
处：SIM_MODE=1时devin命令换成剧本演员`src/sim/fake_devin.py`，命令结构（含
`echo $? > DONE.md; sleep 999999`）与生产完全一致。于是世界的全部输出
（export/proof/HANDOVER/DONE/pane/退出）由演员真实产生，launcher/feeder/门闸
100%真代码真跑于四层隔离环境（独立DB/Redis前缀/文件根/sim_题目id），可与生产
并行。7剧本覆盖launcher全部分支+016动力学回归不变量。**改launcher后跑
solve3+chaos_016作为发布门禁**。

### 6.17 成果文件必须双写入库（2026-08-20，018事故教训）

proof.md是解题成果的唯一凭证，原设计"盘上单点文件+DB只存路径"——018事故
（teardown误删生产目录）实证单点丢失不可恢复（124份proof永久丢失，APFS无
快照）。加固：finalize_run_completed把proof文本（≤100KB）写入
continuation_results，DB成为第二份存档。**通用原则：任何"只此一份"的产物
都要先问"丢了怎么办"。**

---

## 7. 解题系统参考

错题分析系统的很多设计借鉴自解题系统（`xishujuzhen/solver_harness/pipe/`）。完整分析见`docs/architecture/solver-harness-borrowing.md`。

| 借鉴项 | 解题系统位置 | 错题分析系统实现 |
|---|---|---|
| 多模块解耦 | `pipe_control.py`（6个独立服务） | Pipe 4保留单体launcher，拆retry/reporter |
| auto-restart | `pipe_control.py` `start_service()` | `continuation_control.py` `start_service()` |
| watchdog | `pipe_watchdog.sh` + launchd plist | `continuation_watchdog.sh` |
| 精细化classify() | `collector.py` `classify()`（10+终态） | `continuation_launcher.py` `classify_failure()` |
| infra-vs-model失败 | `retry_infrastructure.py` | `continuation_config.py` INFRA_FAILURES/MODEL_FAILURES |
| 优雅停止 | `graceful_shutdown.py` + `pipe_stop.sh` | `graceful_shutdown.py` + `continuation_control.py` |
| 动态并发 | Redis配置中心 | DB记录（batch.concurrency字段） |
