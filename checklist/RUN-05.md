# RUN-05: proof.md 质量（存在数 vs COMPLETED 数，有 boxed 数 vs 存在数）

> **门类**: RUN · POC-2.7运行与监控
> **状态**: [x]
> **负责的WP**: WP-13
> **来源**: WP-13（SOP_02 数据完整性检查）
> **所属章节**: §RUN · POC-2.7 运行与监控

## 需求描述

proof.md 质量（存在数 vs COMPLETED 数，有 boxed 数 vs 存在数）

## 验证方法

`scripts/sop/checks.py` 的 `check_02_data_integrity()` 函数实现了全量统计：
- 查询批次所有 run 的 final_status 和 proof_path
- 统计 COMPLETED 数 / proof.md 存在数 / 有 `\boxed` 数
- 计算存在率（proof_exists/COMPLETED）和 boxed 率（has_boxed/proof_exists）
- COMPLETED 缺 proof.md → 数据丢失风险告警
- proof.md 缺 boxed → 未完成证明告警

## 关联文件

- `checklist/README.md`（需求点全集）
- `checklist/ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
