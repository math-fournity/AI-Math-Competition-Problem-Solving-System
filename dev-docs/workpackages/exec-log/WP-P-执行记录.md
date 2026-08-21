# WP-P 执行记录 — 现场补救：收集 10 个已完成审计 + 清 5 个孤儿 session + 状态修正

> **执行时间**: 2026-08-21 10:20–11:00（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（含 1 处文档没预期的漂移处置 + 1 个只报告未修复的根因发现）

---

## 一、前置认知确认

| # | 项 | 结果 |
|---|---|---|
| 1 | WP-N 已完成 | ✅ `mark_parse_error` 在 src/proof_audit_result_collector.py:307，总控状态表 ✅ |
| 2 | collect_results 候选条件 | `status=='completed' AND audit_status==null`——先修 DB status 的原因确认 |
| 3 | 集合名/key 构造 | `p27_proof_audit_runs`；audit_run_key=`paudit-{run_key}`；tmux session 名=key 后 30 字符加 paudit- 前缀 |
| 4 | 铁律 3 | AGENTS.md"绝不 kill 无 DONE.md 的 session"——每个 kill 前亲眼验证 |

## 二、任务 1：基线复核（全部通过，与 §3 一致）

| 事实 | 基线值 | 实测值 | 一致 |
|---|---|---|---|
| 孤儿 tmux session | 5 个（07:51:42–07:56:41 创建） | 5 个，创建时间逐一吻合 | ✅ |
| DONE.md | 全部存在 | 全部存在（2B exit code） | ✅ |
| export 大小 | 137–293KB | 137084/176680/209543/254820/293248 B | ✅ |
| Redis | pending=130 running=5 completed=5 failed=0 | 相同；running 成员=预期 5 key | ✅ |
| DB runs | 141 = 131 prepared + 5 running + 5 completed | 相同 | ✅ |
| p27_proof_audits | 0 | 0 | ✅ |

**偏差**：`.env` 无 `D_TRAJ_DIR` 变量（config 默认 `/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory`），首次路径探测落空后改用 config 默认值——无实质影响。

## 三、任务 2：修 DB status（dry-run → 真跑）

脚本 `scripts/fix_wp_p_running_status.py`（直接检查原则：每条先验 DONE.md 存在 + conversation.json >1000B）。

**dry-run 输出**：5 条全部 `[fix]` 计划，磁盘证据齐全（export 137084–293248B），0 skip。

**真跑输出**：5 条 running → completed，改后逐条复核 status=completed、ended_at=2026-08-21T14:33:55Z。

## 四、★ 与文档没预期的漂移：result_collector 解析 bug（处置：最小修复 + 独立 commit a4c436b）

首跑 collector **10 条全部 skip"无 export 或无 assistant 文本"**——但磁盘上 export 明明存在。直接检查发现：

1. **source 枚举不符**：`extract_audit_from_export` 过滤 `source == "assistant"`（d6d3dba 引入时凭空假设），实测 export 格式为 `system/user/agent`（续传与审计一致）。10 个真实 export 一个都提取不到文本——收集器自上线起就收不到任何结果。
2. **真截断样本**：00000036 的 agent message 为空、79074 字符全在 reasoning_content、comp=25000 撞输出硬上限、无 XML 无 COMPLETE 标记、DONE.md 内容为退出码 `1`。旧代码对"export 存在但无文本"静默 skip → run 永远停在 audit_status=null 被反复重扫。

**处置理由**：不修则 WP-P 核心使命（把结果收进来）无法达成；两处都不在任何禁止事项范围内；修复语义严格对齐 029 §3.3 与 WP-P 任务 3 的预期（"PARSE_ERROR 样本会走 mark_parse_error"）。改动：

- source 过滤改 `in ("agent", "assistant")`（兼容容错）
- "export 存在但无文本"分支接 `mark_parse_error`（文件完全缺失仍保持静默 skip——那可能是 launcher 层问题，语义不同）

单测 `scripts/test_wp_p_export_parse.py`：10 PASS / 0 FAIL；WP-N 单测回归 30 PASS / 0 FAIL。独立 commit `a4c436b`。

## 五、任务 3：收集结果（重跑）

```
待收集审计结果: 10
[pass] 00000130 PASS_WITH_CAVEAT   [pass] amo_00000008 PASS_WITH_CAVEAT
[pass] 00000258 PASS               [pass] 00000360 PASS
[pass] 00000295 PASS               [parse-error] 00000036 export 存在但无 agent 文本
[pass] 00000174 PASS_WITH_CAVEAT   [pass] 00000521 PASS
[pass] 00000550 PASS               [pass] 00000571 PASS_WITH_CAVEAT
collected: 10, parse_errors: 1
```

分布：**5 PASS + 4 PASS_WITH_CAVEAT + 1 PARSE_ERROR**。PARSE_ERROR 走 mark_parse_error：audit_status=PARSE_ERROR、audit_passed=None、status 不变、alert 已建（`p27-alert-audit_parse_error-k_00000036`，severity=warning）。

## 六、任务 4：清 Redis running

5 次 HDEL 各返回 1；断言 `HLEN paudit:running` == **0** ✅。pending/completed/failed 未触碰。

## 七、任务 5：kill 孤儿 session（逐个先验证）

| session | kill 前 DONE.md 验证 | 结果 |
|---|---|---|
| paudit-27-full-deepmath_103k_00000036 | ✅ 存在，内容=`1`（devin 退出码 1——截断互证） | 已终止 |
| paudit-27-full-deepmath_103k_00000174 | ✅ 存在，内容=`0` | 已终止 |
| paudit-27-full-deepmath_103k_00000521 | ✅ 存在，内容=`0` | 已终止 |
| paudit-27-full-deepmath_103k_00000550 | ✅ 存在，内容=`0` | 已终止 |
| paudit-27-full-deepmath_103k_00000571 | ✅ 存在，内容=`0` | 已终止 |

终态 `tmux list-sessions | grep -c ^paudit-` == **0** ✅。续传系统全程未动（p27-launcher 及 solve session 保持运行）。

## 八、任务 6：差 1 核对（结论：只报告，未修复）

**现象**：DB prepared=131 vs Redis pending=130。差集 = `paudit-p27-full-amo_bench_00000006`（在 DB 不在 Redis）。

**证据链**：
1. collector 07:50:31 为它写 DB 记录 + 建 work_dir/trajectory 目录（日志 line 1），enqueue 代码无条件调用
2. 第一个审计 launcher 实例 07:50:39 启动，日志只有一行 `audit_batch_start` 就消失——零门闸、零 launch
3. 第二个实例 07:51:40 的第一次出队拿到的是 amo_bench_000000**08**——而 06 字典序更小（ZPOPMIN 同分按字典序），若 06 还在 pending 必然先被 pop → **07:51:40 时 06 已不在队列**
4. GATE-AUDIT-LAUNCH 恰好 10 条 = 10 次已入账的 launch，06 无门闸痕迹；其 solver work_dir 为空（collector 建的，launcher 的 prepare 从未写入 AGENTS.md）；exports/tmux 空
5. 数据健康：proof_text 5327B、problem_text 500B、源题续传侧 completed——排除数据质量 skip

**最可能根因**：第一个 launcher 实例 pop 了字典序最小的 06 后、在 audit_launch 之前崩溃（无任何痕迹）。系统性缺陷：`launch_batch` 的 dequeue（ZPOPMIN 破坏性弹出）到 add_running 之间**没有 try/except**——任何异常都会杀死整个 launcher 且无声丢失已弹出的 key。次选假设（enqueue 静默失败）概率较低：Redis 异常会中断 collector 循环，但 131 条 prepare_audit 全部落盘。

**处置**：按 WP-P 纪律"原因未完全钉死前不擅自修复"，仅报告。建议：(a) 给 dequeue→launch 代码段加 try/except（失败 key 入 failed 队列留痕）——可并入 WP-H；(b) 下批审计运行（WP-G 实验）时重新入队该 key（数据健康，重跑无副作用）。

## 九、任务 7：终态快照

| 断言 | 预期 | 实测 | 结果 |
|---|---|---|---|
| p27_proof_audits count | ≥10（有 skip 则=10−skip） | **9** = 10 − 1 PARSE_ERROR（029 §3.3 设计：PARSE_ERROR 不建审计结果记录，alert 即痕迹） | ✅（skip 原因已写明） |
| audit_status 分布 | — | 5 PASS + 4 PASS_WITH_CAVEAT（+1 PARSE_ERROR 在 runs.audit_status，不入此集合） | ✅ |
| tmux paudit session | 0 | 0 | ✅ |
| HLEN paudit:running | 0 | 0 | ✅ |
| runs status 分布 | prepared+completed，无 running | 131 prepared + 10 completed | ✅ |
| pending 队列 | 不动 | 130（原样） | ✅ |

## 十、验收 checklist 对照

- [x] DB 复核命令输出贴记录（§二）
- [x] dry-run + 真跑输出贴记录（§三）
- [x] result_collector 输出 collected=10 / parse_errors=1 贴记录（§五）
- [x] HLEN paudit:running → 0（§六）
- [x] tmux paudit 计数 → 0（§七）
- [x] p27_proof_audits count=9（=10−1 PARSE_ERROR，原因写明）+ 分布贴记录（§九）
- [x] 差 1 原因查明并记录（§八）
- [x] WORKLOG.md 有记录；本执行记录存在；commit 完成

## 十一、遗留问题

1. **dequeue→launch 无异常保护**（系统性，建议并入 WP-H）：失败 key 应入 failed 队列留痕而非无声丢失
2. **amo_bench_00000006 待重新入队**：下批审计运行时处理（WP-G 实验前顺手）
3. **审计管线零 flow 流水**：GATE-AUDIT-* 事件 run_key=null 且无 launch/dequeue 事件——行为流水对审计管线不可观测，SOP_07 设计时需补（记录给 WP-C 参考）
4. **reasoning_content 不参与提取**（有意保持）：截断样本的 thinking 里即使出现 XML 片段也不应被误解析——当前实现正确，无需动作

## 十二、认知闭包与 checklist 影响分析

```
=== 认知闭包与 checklist 影响分析 ===
认知闭包（SYSTEM_CLOSURE.md）：
  - [需更新-轻] §6 alert 清单：audit_parse_error 行已存在且描述正确，无需改；
    但"completed=devin已退出≠审计成功"的 E1 语义澄清属 WP-A/WP-F 范围，此处不动
  - [无需更新] 架构/模块/数据产出：本次是数据补救+bug 修复，不改架构
checklist/：
  - [暂不更新] SOP_02 的 export 存在性检查等升级属 WP-S/WP-C 范围
```

---

**Commit 清单**：
- `a4c436b` 收集器解析 bug 修复（src/proof_audit_result_collector.py + scripts/test_wp_p_export_parse.py）
- 本 commit：scripts/fix_wp_p_running_status.py + WORKLOG.md + dev-docs/workpackages/exec-log/WP-P-执行记录.md + dev-docs/workpackages/README.md（状态表）
