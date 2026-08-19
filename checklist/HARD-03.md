# HARD-03: Solver 的 devin cli 必须在外部目录运行（`/Volumes/data/math-agent-glm5.2-tmux-agents-dir/`），不能在本 repo 内

> **门类**: HARD · 硬约束
> **状态**: [ ]
> **负责的WP**: 全部
> **来源**: §7-3
> **所属章节**: §HARD · 硬约束（贯穿全程）

## 需求描述

Solver 的 devin cli 必须在外部目录运行（`/Volumes/data/math-agent-glm5.2-tmux-agents-dir/`），不能在本 repo 内

## 验证方法

work_dir 路径检查

## 关联文件

- `checklist/README.md`（需求点全集）
- `checklist/ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
