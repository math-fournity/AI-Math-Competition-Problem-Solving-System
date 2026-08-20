# HARD-16: 每轮SOP_01必查行为流水

> **门类**: HARD · 硬约束
> **状态**: [x]
> **负责的WP**: 全部
> **来源**: SOP_01 §8 / dev-docs/016
> **所属章节**: §HARD · 硬约束（贯穿全程）

## 需求描述

每轮SOP_01必须查行为流水（`observability --stats --since 1h`），检查churn_suspects是否为空。非空=失控循环正在发生，立即按016§5处置（kill launcher→清队列→查根因）。checks.py已自动跑_check_flow_snapshot。

## 验证方法

查check_output.txt是否有"行为流水快照"段；churn_suspects是否为空。

## 关联文件

- `scripts/sop/checks.py`（_check_flow_snapshot）
- `src/observability.py`
- `docs/sop/SOP_01_system_health.md` §8
- `dev-docs/016-动态并发设置失效与amo_bench失控循环事故调查报告.md` §5
- `checklist/README.md`（需求点全集）

## 变更记录

- v1 · 2026-08-20 · 016事故后新增（016根因：存量没变但流动病态，靠行为流水才看得见）