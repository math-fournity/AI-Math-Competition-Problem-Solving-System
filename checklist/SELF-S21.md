# SELF-S21: 成果双写（proof入库）

> **门类**: SELF · Master Agent self-check
> **状态**: [ ]
> **负责的WP**: WP-13
> **来源**: dev-docs/018 / AnalysisSystemDesign §6.17
> **所属章节**: §SELF-016 · 016事故后新增（S18-S22）

## 需求描述

completed的run的proof是否入库了 continuation_results（双写）？不依赖盘上单点文件。

## 详细信息

- **检查方法**: 抽样completed的run，查DB continuation_results集合是否有proof_text字段（≤100KB）
- **通过标准**: completed的run在DB有proof文本（双写，不依赖盘上文件）
- **不通过时怎么办**: proof只在盘上=单点丢失风险（018实证124份proof不可恢复），查finalize_run_completed是否执行了proof入库

## 关联文件

- `src/continuation_launcher.py`（finalize_run_completed proof入库）
- `dev-docs/018-teardown误删生产目录事故报告.md`
- `docs/system/AnalysisSystemDesign.md` §6.17
- `checklist/README.md`（需求点全集）

## 变更记录

- v1 · 2026-08-20 · 018事故后新增self-check（proof单点文件丢失不可恢复的教训）