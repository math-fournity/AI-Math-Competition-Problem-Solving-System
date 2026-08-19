# EXEC-09: `build_monitor_exec_prompt(exec_seq, db) -> str`——读模板 + 替换 `{exec_seq}` + 从上一轮复制 WORKLOG.md

> **门类**: EXEC · Monitor Exec Devin
> **状态**: [ ]
> **负责的WP**: WP-03, WP-04, WP-05
> **来源**: spec §B.5/§C.2.2
> **所属章节**: §EXEC-LAUNCH · 启动器

## 需求描述

`build_monitor_exec_prompt(exec_seq, db) -> str`——读模板 + 替换 `{exec_seq}` + 从上一轮复制 WORKLOG.md

## 验证方法

prompt 包含正确 exec_seq 和 work_dir

## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
