# WP-G 执行记录 — 并发治理

> **执行时间**: 2026-08-21 12:00–12:40（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（代码+机制验证全过；任务 3 实验按用户裁定提前终止，见 dev-docs/051）

---

## 一、做了什么

删除全部写死并发默认值（不止文档列的三处——grep 终查共五处），确立"DB batch.concurrency
唯一权威"，审计批次与续传批次同集合同命令。**用户裁定（2026-08-21）**：并发数值由用户
决定，AI 不做推荐实验；实验已按指示提前终止。

## 二、改动文件（实际 7 个——比任务书多 2 处 grep 终查发现的违规）

| 文件 | 改动 |
|---|---|
| `src/continuation_config.py` | 删 `DEFAULT_CONCURRENCY = 5`（注释改为指向硬约束） |
| `src/proof_audit_config.py` | 删 `AUDIT_DEFAULT_CONCURRENCY = 5` 及注释行 |
| `src/continuation_launcher.py` | import 去常量；`launch_batch(concurrency=None)`；DB 有值用 DB / 显式传参初始化 / **两者皆无报错退出**（新增 elif/else 分支）；main argparse default=None |
| `src/proof_audit_launcher.py` | 同构改造 + **get-or-create 批次记录**（paudit 批次此前不在 `p27_continuation_batches` 集合）；每轮 poll 从 DB 刷新（抄续传 try/except pass 模式）；main default=None |
| `scripts/run_proof_audit_pipeline.py` | `--concurrency default=None`（第三处） |
| `monitoring/continuation_control.py` | **第四处（终查新发现）**：`start --concurrency default=5` → None；cmd_start 改透传设计——传了则显式转发，未传则 launcher 走"DB 无记录报错"约束（tmux 命令串条件拼接） |
| `src/monitor_continuation.py` | **第五处（终查新发现）**：`--concurrency default=5` → None；check_session_health 的存活检查（不依赖预期值的 critical 分支）与并发比对分离——None 时跳过比对、保留存活检查 |

## 三、实测验证输出

### 报错路径（DB 无记录 + 不传参）
```
=== 启动审计批次 batch=paudit-p27-full ===
并发数未设置：DB batch 记录无 concurrency 字段且未传 --concurrency。
请先 python -m monitoring.continuation_control set-concurrency --batch-id paudit-p27-full --concurrency N
[ERROR] event=concurrency_not_set
```
（set-concurrency 对不存在的批次也维持既有语义："❌ batch paudit-p27-full 不存在"——
记录创建靠 launcher 显式传参 get-or-create）

### DB 记录创建 + 双批次隔离
```
启动时打印: 并发数: 1（命令行显式传入，初始化 DB batch 记录）
event=audit_batch_record_created concurrency=1
DB: paudit-p27-full = {concurrency:1, status:auditing} | p27-full concurrency 未被影响: 1
```

### poll 刷新双向生效（运行中 set-concurrency）
```
set-concurrency 1→2 → 15秒内日志: [concurrency] 并发数调整: 1 → 2（从DB读取）
set-concurrency 2→1 → 第二次调整日志落盘；p27-full 全程仍为 1
```

### 残留终查
```
grep -rn "DEFAULT_CONCURRENCY|default=5" src/ scripts/ monitoring/ --include="*.py" | grep -v sim
→ 仅剩 --max-rounds default=5（轮次上限，非并发语义）、--limit default=50（列表条数）
→ DEFAULT_CONCURRENCY 零命中 ✓
```

## 四、任务 3 实验——按用户裁定提前终止

原计划 concurrency=1 跑 8-10 题出推荐值。执行至第 5-6 题时用户裁定：
**并发数值由用户定，AI 不做推荐实验（系统解决问题能力优先于参数寻优）**。已 SIGINT
优雅停止（WP-H 二次实战验证）。已采集的 4 题耗时数据（102–326s）与裁定原文落盘
`dev-docs/051-审计并发实验记录.md`，仅作参考不做外推。

实验期间发现 00000688/00000764 两题 export 完全缺失（已知缺口，WP-P/WP-H 记录在案，
非新问题）。

## 五、验收 checklist 对照

- [x] 两个 config 无并发常量；pipeline 无 default=5
- [x] py_compile 七文件全过；DEFAULT_CONCURRENCY 零残留
- [x] DB 无记录+不传参 → 报错退出（§三贴输出）；DB 有记录 → 正常启动用 DB 值（poll 刷新即证）
- [x] set-concurrency 对 paudit-p27-full 生效且 p27-full 不受影响（双批次值贴出）
- [x] 运行中改值下轮生效（双向调整日志）
- [x] ~~dev-docs/051 含推荐推理~~ → 按用户裁定改为"终止说明+参考数据"
- [x] AGENTS.md（违规清单→已修复+现行机制+用户裁定）/ SYSTEM_CLOSURE §5 /
      dynamic-concurrency.md §6 已同步

## 六、遗留问题

1. monitor 的 `run_monitor_loop(expected_concurrency=1)` 函数签名默认值仍为 1——
   它只是 CLI 未传时的函数级 fallback 且 check_session_health 内部 DB 优先；
   若要彻底 None 化需连带改调用链，本包以 argparse 层清零为界（grep 已无并发语义
   的 default 数字），记录备查。
2. audit pipe 的批次记录 status 用 "auditing"（区别于续传 "launching"）——SOP_07
   设计时注意对账口径。

## 七、认知闭包与 checklist 影响分析

```
=== 认知闭包与 checklist 影响分析 ===
认知闭包（SYSTEM_CLOSURE.md）：
  - [已更新] §5 配置参数表：DEFAULT_CONCURRENCY 行 → "并发数唯一来源=DB batch"
  - [无需更新] 架构/模块节：机制未变（续传原有模式，审计对齐）
checklist/：
  - [无需更新] SOP_01 的 A13 四源一致检查逻辑不受影响（expected 从 DB 读的路径未变）
```
