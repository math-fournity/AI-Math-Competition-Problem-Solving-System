# MON-A13: real_concurrency（真实并发四源审计）

> **门类**: MON-A · Monitor Pipe A类自动检查
> **状态**: [x]
> **负责的WP**: WP-02, WP-05
> **来源**: p27_monitor_spec.md §2.1/§3（016事故新增）
> **所属章节**: §MON-A · Monitor Pipe A 类自动检查

## 需求描述

real_concurrency——真实并发四源审计：tmux实际进程数 vs DB running数 vs Redis running数 vs batch设定concurrency。任一不一致=孤儿进程/注册表脱节。

## 详细信息

- **alert_type**: real_concurrency_mismatch / real_concurrency_exceeded
- **severity**: critical
- **阈值**: 任何不一致
- **说明**: 016事故（失控循环"设1跑6"）后新增。tmux_solve↔DB↔Redis对账；tmux_total(solve+handover)↔batch设定对账（handover占并发槽是设计行为）。A13按session类型拆分防误报（solve↔DB↔Redis；total↔设定）。处置：`sessions --consistency-check`清理孤儿进程。

## 关联文件

- `src/monitor_continuation.py`（_classify_p27_session + real_concurrency检查）
- `src/observability.py`（行为流水）
- `dev-docs/016-动态并发设置失效与amo_bench失控循环事故调查报告.md` §4.1
- `checklist/README.md`（需求点全集）

## 变更记录

- v1 · 2026-08-20 · 016事故后新增（补checklist缺口——p27_monitor_spec已有A13但checkpoint目录未跟上）