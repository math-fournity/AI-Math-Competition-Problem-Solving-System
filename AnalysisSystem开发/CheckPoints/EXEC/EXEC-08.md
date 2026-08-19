# EXEC-08: `should_launch_monitor_exec(db, batch_id) -> bool`——无 running 的 monitor_exec + 距上次完成已过 interval

> **门类**: EXEC · Monitor Exec Devin
> **状态**: [ ]
> **负责的WP**: WP-03, WP-04, WP-05
> **来源**: spec §C.2.2
> **所属章节**: §EXEC-LAUNCH · 启动器

## 需求描述

`should_launch_monitor_exec(db, batch_id) -> bool`——无 running 的 monitor_exec + 距上次完成已过 interval

## 验证方法

单元测试

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
