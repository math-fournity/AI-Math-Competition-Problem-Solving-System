# MON-B6: truncation_pattern

> **门类**: MON-B · Monitor Pipe B类续传质量检查
> **状态**: [x]
> **负责的WP**: WP-02, WP-05
> **来源**: p27_monitor_spec.md §2/§3
> **所属章节**: §MON-B · Monitor Pipe B 类续传质量检查（9 项）

## 需求描述

truncation_pattern

## 详细信息

- **alert_type**: all_rounds_truncated
- **severity**: warning
- **阈值**: 5 轮全截断
- **说明**: spec §2.2

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
