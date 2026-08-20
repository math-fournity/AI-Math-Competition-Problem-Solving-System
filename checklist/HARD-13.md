# HARD-13: 成果文件必须双写入库（proof入库）

> **门类**: HARD · 硬约束
> **状态**: [x]
> **负责的WP**: 全部
> **来源**: dev-docs/018 / AnalysisSystemDesign §6.17
> **所属章节**: §HARD · 硬约束（贯穿全程）

## 需求描述

解题成果文件（proof.md）必须双写入库——盘上文件 + DB（continuation_results的proof_text字段，≤100KB）。不依赖盘上单点文件。

## 验证方法

抽样completed的run，查DB continuation_results是否有proof_text字段。

## 关联文件

- `src/continuation_launcher.py`（finalize_run_completed proof入库）
- `dev-docs/018-teardown误删生产目录事故报告.md`
- `docs/system/AnalysisSystemDesign.md` §6.17
- `checklist/README.md`（需求点全集）

## 变更记录

- v1 · 2026-08-20 · 018事故后新增（124份proof单点丢失不可恢复的教训）