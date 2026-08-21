---
trigger: always_on
---

# 直接检查铁律——判断状态必须看到最底层实物

**硬约束**：任何"SOP 检查 / 回答系统状态问题 / commit 前验证 / DB 与文件不一致排查"
场景，只要你要下"X 正常 / X 完成了"的结论，就必须有最底层实物的直接证据。
DB 和 Redis 是"结果的转述"，不是"事实本身"——只看转述就下结论 = 间接调查 = 禁止。

## 为什么（028 教训）

DB 说 138 题 completed，硬盘只有 14 个 proof.md——其中 124 个被 018 事故删除
（dev-docs/028）。若当时的检查是直接的（不只查 status 还 ls 文件），事故后第一轮
SOP 就能发现，不用等 027 报告追认。状态字段可以被任何写入者变成任何值；只有
硬盘文件、tmux 会话、进程表是物理事实。

## 判定对照表（❌ 间接=禁止单独作为结论依据；✅ 直接=必须附带）

| 检查类型 | ❌ 间接（转述层） | ✅ 直接（实物层） |
|---|---|---|
| 题目完成状态 | DB status=completed | + `ls work_dir/proof.md` + `grep '\\boxed' proof.md` |
| 审计完成状态 | DB audit_status=PASS | + 读 export 文件确认 `<proof_audit>` XML 块存在 |
| 审计收集完成 | DB runs.audit_passed 非 null | + p27_proof_audits 有记录 + 抽样读 export 比对 |
| 进程存活 | DB session status=running | + `tmux has-session -t <name>` 实测 |
| 队列状态 | DB run status=prepared | + `redis-cli ZCARD/HLEN` 对应 key 实测 |
| session 真在干活 | session 存在 | + capture-pane 看内容（注意 -p 模式 pane 仅最终输出） |

## 与 verify-with-logs rule 的关系（互补不重复）

那条管"查**过程证据**"（日志+行为流水三层法——launcher 判定过程有没有发生）；
本条管"看到**最底层实物**"（判定的对象在物理世界是否真实存在）。两者叠加成完整
链路：查 DB（结果）→ 查日志/流水（过程）→ 查文件/tmux/进程（实物）。下结论三层都要有，
缺哪层就补哪层，不存在冲突。

## 与"适度依赖 Master Agent"原则的关系

直接检查负责给出**事实**；怎么处置事实（判定/修复/翻案）按适度依赖原则分工——
可靠的确定性判定进代码（能写成确定性函数并单测覆盖），语义判断给 Master Agent。
事实层永远不做分工妥协：无论谁判定，先看到实物。

## 附录：现有 SOP 检查的间接→直接升级清单（落地在 WP-C/D/E，非本包任务）

- SOP_01 进度检查：+ 抽样 N 个 completed 题 ls proof.md（WP-D）
- SOP_04 C7/C8：抽查题读 export XML + proof.md 原文，不只读 audit_summary（WP-E）
- SOP_07（新）：审计产出直接验证 / 通过题交叉验证 / 孤儿 session 对账（WP-C）
