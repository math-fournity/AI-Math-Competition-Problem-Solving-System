# MON-A14: launch_churn（启动抖动/失控循环检测）

> **门类**: MON-A · Monitor Pipe A类自动检查
> **状态**: [x]
> **负责的WP**: WP-02, WP-05
> **来源**: p27_monitor_spec.md §2.1/§3（016事故新增）
> **所属章节**: §MON-A · Monitor Pipe A 类自动检查

## 需求描述

launch_churn——同题1小时内≥5次launch_solve=失控循环正在发生。基于行为流水log/flow/的churn_suspects聚合检测。

## 详细信息

- **alert_type**: launch_churn
- **severity**: critical
- **阈值**: 同题1小时内≥5次launch
- **说明**: 016事故（amo_bench_00000006失控循环18分钟上千次启动，Master Agent既看不见也拦不住）后新增。处置：立即`observability --stats --since 1h`看churn_detail→kill launcher→清空Redis队列→查根因（旧产物残留/feeder重喂）。详见dev-docs/016 §5。

## 关联文件

- `src/observability.py`（行为流水 + churn_suspects聚合）
- `src/monitor_continuation.py`（A14告警）
- `dev-docs/016-动态并发设置失效与amo_bench失控循环事故调查报告.md` §5
- `checklist/README.md`（需求点全集）

## 变更记录

- v1 · 2026-08-20 · 016事故后新增（补checklist缺口——p27_monitor_spec已有A14但checkpoint目录未跟上）