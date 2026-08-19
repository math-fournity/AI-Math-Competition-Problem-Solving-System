# Monitor Pipe设计范式（本地版）

## 1. 概述

Monitor Pipe是连续工作系统的AI智能检查架构。完整设计哲学见项目repo根目录的`MonitorPipe.md`，本文件是错题分析系统内的本地参考，指向具体的代码实现。

## 2. 三层架构

| 层 | 文件 | 用途 |
|---|---|---|
| 规范层 | `specs/{name}_monitor_spec.md` | 检查规范——A类自动检查/B类质量检查/C类AI review抽样 |
| 执行层 | `src/monitor_{name}.py` | Monitor Pipe守护进程——按规范执行检查，写alert到DB |
| 查询层 | `scripts/monitor_check_{name}.sh` | 检查脚本——Master AI每次检查都调用，输出N项检查+行动清单 |

## 3. 现有实现

| Pipe | 规范层 | 执行层 | 查询层 | alert集合 |
|---|---|---|---|---|
| Pipe 1/2 | 内嵌在代码中 | `src/monitor_pipe.py` (634行) | `scripts/monitor_check.sh` (124行) | `monitor_alerts` |
| Pipe 3 | 内嵌在代码中 | `src/monitor_selection.py` (683行) | `scripts/monitor_check_selection.sh` (174行) | `monitor_alerts` |
| Pipe 4 | `specs/p27_monitor_spec.md` (259行) | `src/monitor_continuation.py` (915行) | `scripts/monitor_check_continuation.sh` (241行) | `p27_monitor_alerts` |

**演进**：Pipe 1/2/3的检查规范内嵌在代码中。Pipe 4是第一个把检查规范提前落盘为独立系统资产的实现。

## 4. 检查项目分类

### A类自动检查（脚本判定，不需要AI）

基础设施健康检查——所有Pipe通用：
- session_health：tmux session数 vs DB running数
- queue_progress：Redis队列推进
- rate_limit：rate_limited数量
- zombie_sessions：空pane僵尸session
- export_landing：completed的run有export文件
- failure_rate：失败率
- launcher_dead：launcher进程存活
- long_running/stall_detection：单轮运行超时

### B类质量检查（脚本判定，系统特有）

产出质量检查——每个Pipe不同：
- Pipe 4：proof_completeness/proof_no_boxed/proof_too_small/handover_completeness/all_rounds_truncated/status_anomaly
- Pipe 3：field_completeness/value_distribution/logic_consistency（6个POC字段）

### C类AI review抽样（需Master AI判断）

需要AI判断的检查——每个Pipe不同：
- Pipe 4：proof_quality/proof_hallucination/answer_leak/handover_quality/continuation_direction
- Pipe 3：selection_reason合理性/6字段值合理性/suitable判定正确性

## 5. 新Pipe如何实现

1. 写检查规范（`specs/{name}_monitor_spec.md`）——参考`p27_monitor_spec.md`
2. 实现Monitor Pipe（`src/monitor_{name}.py`）——参考`monitor_continuation.py`
3. 实现检查脚本（`scripts/monitor_check_{name}.sh`）——参考`monitor_check_continuation.sh`

**完整设计范式**：`MonitorPipe.md`（项目repo根目录）+ `~/.config/devin/rules/monitor-pipe-design-paradigm.md`（全局rule）

## 6. 关键设计原则

1. Monitor Pipe让应该由Master AI智能检查的项目全部放入Pipe
2. 留下检查结果（alert）到DB的独立集合
3. 检查脚本每次检查都调用，在输出最后提醒Master AI去检查alerts
4. 能规则化和代码化检查的内容全面检查并放在检查脚本中
5. 检查规范提前落盘作为系统资产
6. alert集合用独立名称（`{name}_monitor_alerts`），不与其他Pipe冲突
