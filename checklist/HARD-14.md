# HARD-14: 改调度/判定逻辑后跑sim发布门禁

> **门类**: HARD · 硬约束
> **状态**: [x]
> **负责的WP**: 全部
> **来源**: dev-docs/017 §7 / SOP_05 §4
> **所属章节**: §HARD · 硬约束（贯穿全程）

## 需求描述

改了调度/判定逻辑（continuation_launcher/feeder/redis_queue/step_gate/observability/monitor_continuation的判定或调度逻辑）后，必须跑 `src.sim.run_sim --scenario solve3 + chaos_016` 作发布门禁且全绿，才能commit。只改文档/配置可跳过（报表标[-]）。

## 验证方法

回顾git diff——改了调度逻辑则确认跑了sim两剧本且全绿（solve3 8/8 + chaos_016 23/23）。

## 关联文件

- `docs/sop/SOP_05_code_repair.md` §4
- `dev-docs/017-全流程模拟系统设计方案.md`
- `src/sim/run_sim.py`
- `checklist/README.md`（需求点全集）

## 变更记录

- v1 · 2026-08-20 · 016事故后新增（016 P0-1防抖修复引入新死循环——没有sim门禁回归不可见）