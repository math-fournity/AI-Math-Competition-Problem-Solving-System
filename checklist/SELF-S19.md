# SELF-S19: 行为流水必查

> **门类**: SELF · Master Agent self-check
> **状态**: [ ]
> **负责的WP**: WP-13
> **来源**: SOP_01 §8 / dev-docs/016
> **所属章节**: §SELF-016 · 016事故后新增（S18-S22）

## 需求描述

每轮SOP_01是否查了行为流水（`observability --stats --since 1h`）？churn_suspects是否为空？

## 详细信息

- **检查方法**: 回顾SOP_01——是否运行了observability --stats，是否检查了churn_suspects字段
- **通过标准**: 查了observability且churn_suspects为空（或非空时已按016§5处置：kill launcher→清队列→查根因）
- **不通过时怎么办**: churn_suspects非空=失控循环正在发生，立即按016§5处置

## 关联文件

- `docs/sop/SOP_01_system_health.md` §8
- `src/observability.py`
- `dev-docs/016-动态并发设置失效与amo_bench失控循环事故调查报告.md` §5
- `checklist/README.md`（需求点全集）

## 变更记录

- v1 · 2026-08-20 · 016事故后新增self-check（016根因：存量没变但流动病态，靠行为流水才看得见）