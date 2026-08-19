# MON-A!01: expected_concurrency 不从 DB 读（用启动参数 5），导致 session_health 误报

> **门类**: MON-A · Monitor Pipe A类自动检查
> **状态**: [!]
> **负责的WP**: WP-02, WP-05
> **来源**: CheckList.md MON-A已知问题 / p27_monitor_pipe_operations.md §3.1.1
> **所属章节**: §MON-A · Monitor Pipe A 类自动检查（12 项）

## 需求描述

expected_concurrency 不从 DB 读（用启动参数 5），导致 session_health 误报

## 详细信息

- **对应WP**: WP-02 Bug-1

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
