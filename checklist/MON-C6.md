# MON-C6: export_semantics

> **门类**: MON-C · Monitor Pipe C类AI判断
> **状态**: [ ]
> **负责的WP**: WP-05, WP-07
> **来源**: p27_monitor_spec.md §2.3/§3.3（2026-08-20 020审计新增）
> **所属章节**: §MON-C · Monitor Pipe C 类 AI 判断（6 项）

## 需求描述

export_semantics

## 详细信息

- **AI需要检查什么**: thinking是否真的在解这道题——不是跑题/循环废话/无实质推理/中途崩溃
- **通过标准**: thinking内容与题目相关且有实质推理
- **说明**: 2026-08-20 SOP有效性审计（dev-docs/020）新增的C类判断项，由Master Agent在SOP_04对monitor抽样（ai_review_sample）的同一批结果执行；monitor代码的check_items元数据未含此项，2026-08-21对齐审计（dev-docs/024）补建本checkpoint

## 关联文件

- `checklist/README.md`（需求点全集）
- `docs/sop/SOP_04_ai_judgment.md`（执行文档，C6节）
- `docs/specs/p27_monitor_spec.md` §3.3（标准定义）

## 变更记录

- v1 · 2026-08-21 · 初始创建（024对齐审计补建——020审计加了SOP_04的C6但漏了checkpoint）
