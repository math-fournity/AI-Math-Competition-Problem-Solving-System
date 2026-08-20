# HARD-15: Gate放行必须附--reason落盘论证

> **门类**: HARD · 硬约束
> **状态**: [x]
> **负责的WP**: 全部
> **来源**: docs/patterns/StepGate.md §2.3 / SOP_01 §8.5
> **所属章节**: §HARD · 硬约束（贯穿全程）

## 需求描述

步进门闸放行必须用 `--step GATE-ID --reason '...'` 附理由——理由落盘到gate_release行为流水（log/flow/，grep可回溯"某轮某闸放行了什么、为什么"）。不放行（维持hold）也要在report.md门闸记录区填原因。没有理由的放行=审计断点。

## 验证方法

查gate_release流水事件是否含reason字段；查report_step_01门闸记录区是否填了原因。

## 关联文件

- `src/step_gate.py`（--reason机制）
- `docs/patterns/StepGate.md` §2.3
- `docs/sop/SOP_01_system_health.md` §8.5
- `checklist/README.md`（需求点全集）

## 变更记录

- v1 · 2026-08-20 · 门闸落盘论证机制后新增（016教训：失控循环就是无人论证的动作连续发生）