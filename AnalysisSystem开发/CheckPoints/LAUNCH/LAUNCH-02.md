# LAUNCH-02: Launcher 主循环每轮从 DB 动态读 concurrency（运行期可调）

> **门类**: LAUNCH · Launcher启动与续传控制
> **状态**: [x]
> **负责的WP**: WP-01, WP-02
> **来源**: WP-02 commit de38a5e
> **所属章节**: §LAUNCH · Launcher 启动与续传控制

## 需求描述

Launcher 主循环每轮从 DB 动态读 concurrency（运行期可调）

## 验证方法

运行中改 DB 后下一轮生效

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
