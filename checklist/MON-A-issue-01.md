# MON-A!01: expected_concurrency 不从 DB 读（用启动参数 5），导致 session_health 误报 ✅ 已修复

> **门类**: MON-A · Monitor Pipe A类自动检查
> **状态**: [x] 已修复（commit `edcb439` 2026-08-20）
> **负责的WP**: WP-02, WP-05
> **来源**: CheckList.md MON-A已知问题 / p27_monitor_spec.md §3（原 p27_monitor_pipe_operations.md §3.1.1，该文档已废弃）
> **所属章节**: §MON-A · Monitor Pipe A 类自动检查（12 项）

## 需求描述

expected_concurrency 不从 DB 读（用启动参数 5），导致 session_health 误报

## 详细信息

- **对应WP**: WP-02 Bug-1

## 修复记录

- commit `edcb439`（2026-08-20 04:41，"016可观测性补强...A1修复"）实现根本修复：
  - 新增 `_batch_concurrency(db, batch_id, fallback)` 函数（`monitor_continuation.py:153-162`）——先从 DB 读 `batch.concurrency`，读不到才 fallback 到启动参数
  - `check_session_health` 第 171 行调用 `_batch_concurrency(db, batch_id, expected_concurrency)`——每次检查都从 DB 动态读取
- commit `c2be5d4`（2026-08-20）将 fallback 默认值从 5 改为 1（与当前单并发运行模式对齐）

## 关联文件

- `checklist/README.md`（需求点全集）
- `checklist/ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
- v2 · 2026-08-20 · 标记已修复——commit `edcb439` 已实现从 DB 动态读取，记录代码位置
