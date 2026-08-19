# LAUNCH-08: `stop --force` 清空 Redis 队列

> **门类**: LAUNCH · Launcher启动与续传控制
> **状态**: [x]
> **负责的WP**: WP-01, WP-02
> **来源**: spec §A.5
> **所属章节**: §LAUNCH · Launcher 启动与续传控制

## 需求描述

`stop --force` 清空 Redis 队列

## 验证方法

Redis pending 为空

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
