# EXEC-13: 超时（`MONITOR_EXEC_MAX_RUNTIME_SECONDS`）标记 stuck，不 kill

> **门类**: EXEC · Monitor Exec Devin
> **状态**: [ ]
> **负责的WP**: WP-03, WP-04, WP-05
> **来源**: spec §B.6/§C.2.2
> **所属章节**: §EXEC-LAUNCH · 启动器

## 需求描述

超时（`MONITOR_EXEC_MAX_RUNTIME_SECONDS`）标记 stuck，不 kill

## 验证方法

超时后 session 留在 tmux

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
