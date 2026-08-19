# LAUNCH-07: `stop --force` 分类处理：done 可 kill，running/stuck 留给用户

> **门类**: LAUNCH · Launcher启动与续传控制
> **状态**: [x]
> **负责的WP**: WP-01, WP-02
> **来源**: spec §A.5/§C.1.3
> **所属章节**: §LAUNCH · Launcher 启动与续传控制

## 需求描述

`stop --force` 分类处理：done 可 kill，running/stuck 留给用户

## 验证方法

stop --force 后 running/stuck 仍在

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
