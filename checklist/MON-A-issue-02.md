# MON-A!02: alert 的 `_key` 冲突（同轮同类型 timestamp 相同时重复）

> **门类**: MON-A · Monitor Pipe A类自动检查
> **状态**: [✅已修复]
> **负责的WP**: WP-02, WP-05
> **来源**: CheckList.md MON-A已知问题 / p27_monitor_spec.md §3（原 p27_monitor_pipe_operations.md §3.1.1，该文档已废弃）
> **所属章节**: §MON-A · Monitor Pipe A 类自动检查（12 项）

## 需求描述

alert 的 `_key` 冲突（同轮同类型 timestamp 相同时重复）

## 详细信息

- **对应WP**: WP-02 Bug-2

## 修复记录

- **2026-08-21 修复**：`create_alert` 重写为幂等去重版（`src/monitor_continuation.py:98-179`）。
  `_key` 从 `p27-alert-{ts}-{type}-{随机}` 改为 `p27-alert-{type}-{hash10}`（确定性 hash = sha1(type+summary)[:10]）。
  同 type+summary 且未 resolve 的 alert 只保留一条，重复检测只刷 `occurrence_count`/`last_seen_at`。
  resolve 后状态回归 → reopen 同文档（key 不变，`reopened:True`）。
  原始 _key 冲突问题（MON-A!02）由确定性 hash 天然解决：不同 summary → 不同 hash。
  验证：solve3 门禁 8/8 + chaos_016 门禁 23/23 + 实测去重生效（1788 stuck 残留从 450 条/分钟降到稳定 1 条/状态）。

## 关联文件

- `checklist/README.md`（需求点全集）
- `checklist/ExecDevin.md`（如在本需求点在子集中）
- `src/monitor_continuation.py:98-179`（create_alert 实现）
- `docs/specs/p27_monitor_spec.md` §4（alert 结构文档）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
- v2 · 2026-08-21 · 状态改为 [✅已修复]，记录去重修复详情
