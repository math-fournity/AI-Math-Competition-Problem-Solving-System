# EXEC-26: 防重复启动：running 时不启动新的

> **门类**: EXEC · Monitor Exec Devin
> **状态**: [ ]
> **负责的WP**: WP-03, WP-04, WP-05
> **来源**: spec §C.2.5
> **所属章节**: §EXEC-VERIFY · 阶段2 端到端验证

## 需求描述

防重复启动：running 时不启动新的

## 验证方法

同时只有一个 monitor_exec running

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
