# SELF-S22: step_gate Y通道接线

> **门类**: SELF · Master Agent self-check
> **状态**: [ ]
> **负责的WP**: WP-13
> **来源**: SOP_01 §8.5 / docs/patterns/StepGate.md §6
> **所属章节**: §SELF-016 · 016事故后新增（S18-S22）

## 需求描述

checks.py是否每轮自动查了step_gate Y通道（waiting_for非空的闸）？有Y时是否完整输出了checklist闭包并按论证依据核对后放行/hold？

## 详细信息

- **检查方法**: 回顾SOP_01——check_output.txt是否有"步进门闸Y通道"段；有Y时是否按闭包核对后--step放行或维持hold
- **通过标准**: checks.py每轮查Y（_check_pending_gates + _check_flow_snapshot）；无Y=✅；有Y=按论证依据闭包核对后放行/hold
- **不通过时怎么办**: Y通道没接线=Master Agent看不见被hold冻结的系统，查checks.py的_check_pending_gates

## 关联文件

- `scripts/sop/checks.py`（_check_pending_gates + _check_flow_snapshot）
- `docs/sop/SOP_01_system_health.md` §8.5
- `src/step_gate.py`
- `docs/patterns/StepGate.md`
- `checklist/README.md`（需求点全集）

## 变更记录

- v1 · 2026-08-20 · 016事故后新增self-check（016教训：Master Agent拦不住失控循环，门闸Y通道让冻结点可见）