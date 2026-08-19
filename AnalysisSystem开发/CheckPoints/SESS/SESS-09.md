# SESS-09: Session 命名格式 `p27-s{seq:04d}-{type}-{run_key_short}-r{round}`

> **门类**: SESS · Session编号化管理
> **状态**: [x]
> **负责的WP**: WP-01
> **来源**: spec §A.2
> **所属章节**: §SESS · Session 编号化管理（阶段1）

## 需求描述

Session 命名格式 `p27-s{seq:04d}-{type}-{run_key_short}-r{round}`

## 验证方法

tmux list-sessions 显示正确格式

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
