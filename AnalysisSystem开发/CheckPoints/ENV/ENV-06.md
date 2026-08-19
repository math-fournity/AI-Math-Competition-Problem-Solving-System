# ENV-06: 外部工作目录可写：`/Volumes/data/math-agent-glm5.2-tmux-agents-dir/`（Solver）+ `/Volumes/data/p27-monitor-exec/`（Exec Devin）

> **门类**: ENV · 环境与基础设施
> **状态**: [ ]
> **负责的WP**: WP-01, WP-09
> **来源**: AnalysisSystem.md §7
> **所属章节**: §ENV · 环境与基础设施

## 需求描述

外部工作目录可写：`/Volumes/data/math-agent-glm5.2-tmux-agents-dir/`（Solver）+ `/Volumes/data/p27-monitor-exec/`（Exec Devin）

## 验证方法

`touch` 测试文件写入成功

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
