# EXEC-15: `monitor_continuation.py` 主循环每轮 A/B 检查后调 `should_launch_monitor_exec`，True 则 `launch_monitor_exec`

> **门类**: EXEC · Monitor Exec Devin
> **状态**: [ ]
> **负责的WP**: WP-03, WP-04, WP-05
> **来源**: spec §C.2.3
> **所属章节**: §EXEC-INTEGRATION · Pipe 集成

## 需求描述

`monitor_continuation.py` 主循环每轮 A/B 检查后调 `should_launch_monitor_exec`，True 则 `launch_monitor_exec`

## 验证方法

日志有 `[monitor_exec_start]`

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
