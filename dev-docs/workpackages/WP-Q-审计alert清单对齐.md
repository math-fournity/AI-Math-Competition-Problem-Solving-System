# WP-Q — 审计 alert 清单对齐（SYSTEM_CLOSURE 的 alert_type 与代码产生点一致）

> **优先级**: 第三批（WP-N 之后；与 WP-C/D/E 并行可）
> **依赖**: WP-N（audit_parse_error alert 的产生者）
> **预计规模**: SYSTEM_CLOSURE 修订 ~30 行 + （可选）audit_gate_waiting 的说明调整
> **性质**: 文档对齐（清单不撒谎）

---

## 0. 给执行 AI 的第一句话

SYSTEM_CLOSURE §6 的 alert_type 清单自称"**代码中实际产生的** alert_type 字符串"，
但其中 5 种审计 alert（audit_queue_stalled/audit_completion_slow/audit_failure_rate_high/
audit_parse_error/audit_gate_waiting）在 036 核查时**没有一行代码产生它们**（清单超前
于代码——031 C2）。WP-N 已补上 audit_parse_error；你要把清单逐项对齐到真实产生点：
有代码的标来源，没代码的明确处置（删除或改标注），让清单恢复"不撒谎"。

## 1. 背景（为什么）

- SOP_03 按 alert_type 分诊——清单里有一种 alert 实际永远不会出现 = 分诊表里有死条目
  = 未来 AI 检查"为什么这种 alert 从没触发过"时浪费时间甚至误判系统缺件
- 024 对齐审计的方法论（memory：ground truth=代码>git时间线>文档）——文档清单必须
  与代码一致
- 处置裁定（031 WP-Q 原案 + 036 未推翻）：monitor **不加**审计检查（保持 monitor 只管
  续传管线的边界）；审计健康由 SOP_07 承载；结果驱动型 alert（cheating_detected/
  audit_parse_error）由 result_collector 产生

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **确认 WP-N 完成** | audit_parse_error 有产生代码（result_collector） |
| 2 | `docs/sop/SYSTEM_CLOSURE.md` §6 的 alert_type 完整清单表（34+6 行） | 逐行读——你的对齐对象；注意表头的声明"代码中实际产生的" |
| 3 | `grep -rn "alert_type" src/ --include="*.py"` | **代码真实产生点全量清单**（monitor_continuation 的 30+ 种 + result_collector 的 2 种）——对齐的事实基础 |
| 4 | `scripts/sop/checks.py` 的 check_07（WP-C 后） | audit_gate_waiting 类的"提示输出"在 SOP 检查里的形态（它不是 DB alert——是检查输出） |
| 5 | `dev-docs/031` WP-Q 段 + `dev-docs/036` §四.2（选读） | 处置裁定的原始推理 |

## 3. 现场事实基线（前序 WP 后）

六种审计 alert 的当前状态（逐项核实——你的 §4 就按核实结果写）：
| alert_type | 产生代码 | 处置方向 |
|---|---|---|
| cheating_detected | result_collector（audit_finalize_fail 内） | 保留，标来源 |
| audit_parse_error | **WP-N 后**：result_collector（mark_parse_error） | 保留，标来源 |
| audit_queue_stalled | 无（checks.py 的 A15 是提示输出非 alert） | 改标注："SOP 检查提示，非 DB alert"或删行 |
| audit_completion_slow | 无 | 删行（无承载者，SOP_07 也不按此名报警） |
| audit_failure_rate_high | 无（check_07 输出警告提示） | 改标注："SOP_07 检查提示（>20% 警告），非 DB alert" |
| audit_gate_waiting | 无（_check_pending_gates/A18 输出提示） | 改标注："SOP 检查提示，非 DB alert" |

复核命令：`grep -rn "audit_queue_stalled\|audit_completion_slow\|audit_failure_rate_high\|audit_gate_waiting\|audit_parse_error\|cheating_detected" src/ scripts/ --include="*.py"`

## 4. 任务分解

### 任务 1：SYSTEM_CLOSURE §6 清单修订

- 表头声明保持"代码中实际产生的 alert_type"——**只留真产生的**（DB alert）在主表
- 三种"检查提示级"（queue_stalled/failure_rate_high/gate_waiting）移到表下方的
  **"SOP 检查提示（非 DB alert）"**小节：说明它们由 check_01/check_07 的输出承载、
  不入库、SOP_03 分诊不适用
- audit_completion_slow：若你复核后确认无任何承载（SOP_07 也没实现它）→ 直接删行
  并在变更注记说明（或者你也可以选择在 check_07 补一个完成速率提示——**不推荐**，
  scope 蔓延；删行是诚实的选择）
- 表格下加一行变更注记：`2026-08-21 WP-Q 对齐：审计 alert 6 种 → DB alert 2 种
  （cheating_detected/audit_parse_error，均 result_collector 产生）+ SOP 提示 3 种 +
  删除 1 种（无承载）`

### 任务 2：SOP_03 的分诊表联动

`docs/sop/SOP_03_alert_triage.md` 若列了这 6 种（grep 确认）——同步：DB alert 两种
保留分诊行；提示级的标注"由 SOP_01/07 检查承载，不会出现在 alert 队列"。

### 任务 3：验证 + commit

验证：清单每一行的 alert_type 字符串都能 `grep -rn "<type>" src/ --include="*.py"`
找到产生点（DB alert 类）或在 SOP 检查代码找到提示输出（提示类）——把 grep 证据贴
执行记录。commit 显式路径（SYSTEM_CLOSURE + SOP_03）。

## 5. 禁止事项

- ❌ 不要为了"清单不缺项"而在 monitor/checks 里补写 alert 创建代码（031 裁定 monitor
  不加审计检查；诚实删行优于虚假补齐）
- ❌ 不动 cheating_detected/audit_parse_error 的产生代码
- ❌ 不动清单里续传部分的 30+ 行（只对齐审计 6 种）

## 6. 验收 checklist

- [ ] 逐行 grep 证据贴记录：主表每种 DB alert 有 src/ 产生点；提示类有 checks.py 输出点
- [ ] audit_completion_slow 的处置（删行）+ 变更注记存在
- [ ] SOP_03 联动同步（若适用）
- [ ] 表头声明与内容再次自洽（"代码中实际产生"名副其实）
- [ ] commit 显式路径

## 7. 完成汇报要求

执行记录：对齐前后对照表、每行的 grep 证据、删除决策理由。

## 8. 审计对照

1. 我会随机抽清单 3 行（含 1 个审计行）反查代码——grep 得到才算过
2. 没有新增任何 alert 创建代码（diff 验证）
3. 表头声明与内容一致（032 犯过"铁律写了代码没兑现"，同类错误不得再现）
