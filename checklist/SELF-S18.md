# SELF-S18: sim发布门禁

> **门类**: SELF · Master Agent self-check
> **状态**: [ ]
> **负责的WP**: WP-13
> **来源**: SOP_05 §4 / dev-docs/017 §7
> **所属章节**: §SELF-016 · 016事故后新增（S18-S22）

## 需求描述

改了调度/判定逻辑（continuation_launcher/feeder/redis_queue/step_gate/observability/monitor_continuation）后，是否跑了 `src.sim.run_sim --scenario solve3 + chaos_016` 作发布门禁且全绿？

## 详细信息

- **检查方法**: 回顾本轮SOP_05修复——改了调度逻辑则确认跑了sim两剧本；只改文档/配置可标[-]不适用
- **通过标准**: 改调度逻辑时sim全绿（solve3 8/8 + chaos_016 23/23）；没改时标[-]
- **不通过时怎么办**: sim失败=修复引入回归，不能commit，回去排查（016 P0-1防抖修复引入新死循环的教训）

## 关联文件

- `docs/sop/SOP_05_code_repair.md` §4
- `dev-docs/017-全流程模拟系统设计方案.md`
- `src/sim/run_sim.py`
- `checklist/README.md`（需求点全集）

## 变更记录

- v1 · 2026-08-20 · 016事故后新增self-check（016 P0-1修复引入新死循环——没有sim门禁回归不可见）