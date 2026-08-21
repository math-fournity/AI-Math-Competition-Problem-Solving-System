# WP-P — 现场补救：收集 10 个已完成审计 + 清 5 个孤儿 session + 状态修正

> **优先级**: 第一批（**必须在 WP-N 之后执行**——WP-P 的收集动作依赖 WP-N 修好的
> PARSE_ERROR 分支，否则解析失败的样本会被错误标为 audit_failed）
> **依赖**: WP-N
> **预计规模**: 操作型（少量 DB/Redis/tmux 操作 + 一个修复脚本），无生产代码改动
> **性质**: 数据补救 + 状态修复，全程留痕

---

## 0. 给执行 AI 的第一句话

2026-08-21 07:51-07:56 启动的 5 个审计 devin cli session 早已全部完成，但审计
launcher 在它们完成前被 kill——结果没人收集：`p27_proof_audits` 至今为 0，5 个
tmux session 因 `sleep 999999` 设计仍挂在 tmux 里（孤儿），DB 还错误地显示它们
running。你要把这些结果收进来、把孤儿清掉、把三处状态修正，全程按"直接检查"原则
（看文件/tmux 实物，不信 DB 字段）并留痕。

## 1. 背景（为什么）

这是 030 用户需求 1（优雅停止第二层）的事故现场：审计 devin cli 完成 ≠ 审计完成——
后者的完整链是"devin 退出 → launcher 判定 → kill session → **result_collector 解析
export → 写 p27_proof_audits → 更新 runs 的 audit_passed**"。launcher 被杀导致后三步
缺失。系统级修复在 WP-H（收尾即收集）；本 WP 是一次性数据补救（030 §6.7 预授权）。

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **确认 WP-N 已完成**（总控状态表 + `grep -n mark_parse_error src/proof_audit_result_collector.py`） | 收集时 PARSE_ERROR 样本会被正确处理。**若 WP-N 未完成，停止本 WP** |
| 2 | `src/proof_audit_result_collector.py` 的 `collect_results()`（读函数即可） | 收集的候选条件：`status=='completed' AND audit_status==null`——这就是为什么步骤 2 要先修 DB status |
| 3 | `src/proof_audit_config.py` 顶部 import 块 + 集合名 | `PROOF_AUDIT_RUNS_COLLECTION`="p27_proof_audit_runs"、audit_run_key 的构造规则 `paudit-{run_key}` |
| 4 | 铁律确认：AGENTS.md "绝不 kill 无 DONE.md 的 session" | 你 kill 的每个 session 前必须亲眼看 DONE.md 存在 |
| 5 | `docs/architecture/graceful-shutdown.md` §背景（选读） | 为什么会有孤儿：sleep 999999 是有意设计（保 pane 可查），launcher 死了才无人 kill |

## 3. 现场事实基线（2026-08-21 09:30 实测——**执行前必须全部复核**）

| 事实 | 值（当时） | 复核命令 |
|---|---|---|
| 孤儿 tmux session | 5 个：`paudit-27-full-deepmath_103k_{00000036,00000174,00000521,00000550,00000571}` | `tmux list-sessions \| grep ^paudit` |
| 每个的 DONE.md | 全部存在 | `ls /Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-proof-audit/paudit-p27-full-deepmath_103k_{ID}/exports/DONE.md` |
| 每个的 export | 137-293KB（有实质内容） | 同目录 `conversation.json` 的 `stat -f%z` |
| Redis | `paudit:pending`=130、`paudit:running`=5、`paudit:completed`=5、`paudit:failed`=0 | `redis-cli ZCARD paudit:pending; redis-cli HLEN paudit:running; redis-cli LLEN paudit:completed; redis-cli LLEN paudit:failed` |
| DB `p27_proof_audit_runs` | 141 条 = 131 prepared + 5 running + 5 completed | 见下方 python 片段 |
| DB `p27_proof_audits` | **0 条** | 同上 |
| tmux session 名 vs DB key | session 名是 key 的**后 30 字符**（`tmux_session_name()` 截断），DB key 是 `paudit-p27-full-deepmath_103k_{ID}` | `src/proof_audit_launcher.py` 的 `tmux_session_name()` |

**基线漂移预期**：
- 若 WP-N 已执行：`proof_audit_result_collector.py` 有 `mark_parse_error`——正常
- 若续传系统在跑（p27-launcher 活着）：正常，**不要动续传系统的任何东西**
- 若 paudit session 数量 >5 或 Redis 数字不同：说明有新审计批次启动过——此时
  逐 session 判断（DONE.md 在→已完成可处理；不在且 DB running→真在跑，别动），
  并在执行记录中写明偏差
- **若 5 个 session 已经消失**（有人清理过）：跳过 kill 步骤，继续收集与状态修正

## 4. 任务分解

### 任务 1：复核基线（§3 全部命令跑一遍，结果记入执行记录）

### 任务 2：直接验证 5 个"running"实为 completed，修正 DB status

写脚本 `scripts/fix_wp_p_running_status.py`（>3 行逻辑必须成文件——铁律 4）：

```
逻辑：
for audit_run_key in [5个key]:
    1. export_dir = .../p27-proof-audit/{audit_run_key}/exports/
    2. 断言 DONE.md 存在 且 conversation.json 存在且 size>1000 ——【直接检查】
       任一不成立：打印警告并跳过该条（不要盲改 DB）
    3. update_audit_run(db, audit_run_key, {"status": "completed", "ended_at": utc_now()})
    4. 打印每条的修改结果
```
用 `src/proof_audit_db_schema.py` 的 `connect_db/update_audit_run`。跑之前先加
`--dry-run` 输出计划，确认后真跑。

### 任务 3：跑 result_collector 收集全部已完成审计

```
source .env && python -m src.proof_audit_result_collector --batch-id paudit-p27-full
```
预期收集 10 条（5 个原 completed + 5 个刚修正的）。输出里注意 PASS/FAIL 分布和
`parse_errors` 计数（WP-N 已修复，PARSE_ERROR 样本会走 mark_parse_error——若有，
记入执行记录）。

### 任务 4：清 Redis `paudit:running` 的 5 个成员

对每个 audit_run_key：`redis-cli HDEL paudit:running "paudit-p27-full-deepmath_103k_{ID}"`。
清完断言 `HLEN paudit:running` == 0。

### 任务 5：kill 5 个孤儿 tmux session（逐个、先验证）

```
对每个 session 名：
  1. key = paudit-p27-full- + session名去掉开头的 paudit-（见基线表的映射说明）
  2. ls 该 key 的 exports/DONE.md ——【亲眼确认，铁律 3】
  3. tmux kill-session -t <session名>
  4. 记录到执行记录
```

### 任务 6：核对 DB/Redis 差 1（131 prepared vs 130 pending）

```
对比集合差集：
  DB:    FOR r IN p27_proof_audit_runs FILTER r.status=='prepared' RETURN r._key
  Redis: ZRANGE paudit:pending 0 -1
找出在 DB 不在 Redis 的 key（或反之），查明原因（collector 的 NX 入队撞已有 key？
之前 DB无记录 skip 分支加过 failed？），记录到执行记录。不要擅自"修复"——只报告，
除非原因明确且修复无副作用（如该 key 的审计早已 completed，只是 DB status 没更新）。
```

### 任务 7：终态快照 + 留痕

- 终态断言：`p27_proof_audits` ≥ 10（若有 skip 则=10-skip 数，skip 原因要写明）；
  `tmux list-sessions | grep -c ^paudit` == 0；`HLEN paudit:running` == 0
- `p27_proof_audits` 的 audit_status 分布记入执行记录
- WORKLOG.md 追加一段（人话，含时间/操作/结果）
- commit：`git add scripts/fix_wp_p_running_status.py WORKLOG.md` +
  执行记录文件（exec-log 下）

## 5. 禁止事项

- ❌ 不动续传系统（p27-launcher/monitor/p27-* solve session）
- ❌ 不 kill 任何无 DONE.md 的 session（任务 5 的验证步骤不可省）
- ❌ 不重启审计 launcher（130 个 pending 的批次怎么跑是 WP-G 实验的事，不是本 WP）
- ❌ 不修改 `p27_continuation_runs` 的 audit 字段以外的任何字段（result_collector
  自己会写，你别手写）
- ❌ Redis 只允许 HDEL paudit:running 和只读查询——不动 pending/completed/failed

## 6. 验收 checklist

- [ ] DB 复核命令输出贴记录（任务 1 全表）
- [ ] `fix_wp_p_running_status.py --dry-run` 输出 + 真跑输出贴记录
- [ ] result_collector 输出（collected/parse_errors 计数）贴记录
- [ ] `redis-cli HLEN paudit:running` → 0
- [ ] `tmux list-sessions | grep -c ^paudit-` → 0（或已消失的说明）
- [ ] `p27_proof_audits` count ≥10，audit_status 分布贴记录
- [ ] 差 1 的原因查明并记录
- [ ] WORKLOG.md 有记录；exec-log/WP-P-执行记录.md 存在；commit 完成

## 7. 完成汇报要求

执行记录必须包含：每一步的命令与输出、5 个 session 的 kill 前 DONE.md 验证证据、
收集结果的 PASS/FAIL/PARSE_ERROR 分布、差 1 结论、任何与基线的偏差及处置。

## 8. 审计对照

1. 我会交叉验证：p27_proof_audits 每条的 source_run_key ↔ 5 个 session 的
   audit_run_key 对应关系；DB 里这 5+5 条的 audit_status 与 export 内容抽样比对
   （抽 2 个 export 直接读 XML 块核对 audit_status 一致——直接检查）
2. kill 的 5 个 session 每个 DONE.md 验证证据是否在记录里
3. Redis/DB 终态数字与记录一致
4. 没有越权操作（续传系统/pending 队列未被触碰）
