# SELF-S1: export 完整性

> **门类**: SELF · Exec Devin self-check
> **状态**: [ ]
> **负责的WP**: WP-04, WP-07
> **来源**: p27_monitor_pipe_operations.md §4
> **所属章节**: §SELF-RUN · 运行完整性（S1-S4）

## 需求描述

export 完整性

## 详细信息

- **检查方法**: 检查自己的 conversation.json 是否存在且非空
- **通过标准**: 文件存在且>1KB
- **不通过时怎么办**: [ ]

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
