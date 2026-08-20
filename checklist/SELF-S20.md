# SELF-S20: 落盘论证（Gate放行附理由）

> **门类**: SELF · Master Agent self-check
> **状态**: [ ]
> **负责的WP**: WP-13
> **来源**: SOP_01 §8.5 / docs/patterns/StepGate.md §2.3
> **所属章节**: §SELF-016 · 016事故后新增（S18-S22）

## 需求描述

Gate放行是否用 `--step GATE-ID --reason '...'` 附了理由？不放行（维持hold）是否在 report.md 门闸记录区填了原因？

## 详细信息

- **检查方法**: 回顾本轮Gate事件——每个放行是否带--reason（落盘gate_release流水）；每个hold是否在report门闸记录区有原因
- **通过标准**: 所有放行附理由（gate_release流水含reason字段）；所有hold在report有原因
- **不通过时怎么办**: 没有理由的放行=审计断点，补理由或回溯gate流水

## 关联文件

- `docs/sop/SOP_01_system_health.md` §8.5
- `docs/sop/templates/report_step_01.md`（门闸放行/hold记录区）
- `src/step_gate.py`（--reason机制）
- `docs/patterns/StepGate.md` §2.3
- `checklist/README.md`（需求点全集）

## 变更记录

- v1 · 2026-08-20 · 016事故后新增self-check（016教训：失控循环就是无人论证的动作连续发生）