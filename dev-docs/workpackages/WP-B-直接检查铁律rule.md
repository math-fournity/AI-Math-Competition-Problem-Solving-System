# WP-B — 直接检查铁律 rule（.devin/rules/direct-verification-ironlaw.md）

> **优先级**: 第二批（小包，可与任何 WP 并行）
> **依赖**: 无
> **预计规模**: 1 个 rule 文件（~90 行）+ SOP 检查项升级清单（写入本 rule 的附录，
> 具体落地在 WP-C/D/E）
> **性质**: 纯文档（always-on rule）

---

## 0. 给执行 AI 的第一句话

028 事故（DB 说 138 题 completed，硬盘只有 14 个 proof.md）的教训是方法论级的：**查
DB/Redis 的状态字段就下结论 = 间接调查 = 禁止**。你要把这条写成项目级 always-on
rule，让未来所有 AI 在任何检查场景都先看到它。

## 1. 背景（为什么）

- 用户 030 需求 6 原文："我们所有的SOP中的检查，无论是脚本化的检查，还是使用了AI智能
  的检查，都必须是'直接'的，都必须直接看到底层，而不是看到redis和数据库就放心了。"
- repo 已有先例 rule：`.devin/rules/verify-with-logs.md`（d3b0dbb，"判断系统状态必须
  查过程证据"三层法：DB→日志→行为流水）——**新 rule 与它是互补关系不是重复**：
  那条管"查过程证据（日志/流水）"，本条管"看到最底层实物（硬盘文件/tmux/文件内容）"。
  rule 里必须写清这个关系，避免未来 AI 以为两条冲突。
- 本 rule 只立规矩；SOP 检查项的具体升级在 WP-C（SOP_07）/WP-D（SOP_01）/WP-E（SOP_04）
  落地，本 WP 的附录给它们提供清单。

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `.devin/rules/verify-with-logs.md` | 现有 rule 的**格式**（标题/触发时机/正文结构）——新 rule 对齐它；以及三层法内容（引用关系用） |
| 2 | `dev-docs/028-DB-completed与硬盘proof不一致根因调查.md` §结论段（选读前 80 行） | 028 教训的事实细节（138/14/124 被删）——rule 的案例引用 |
| 3 | `ls .devin/rules/` | 目录现状（确认无同名文件） |
| 4 | `dev-docs/032-对031审计报告的审计.md` §7.5（"适度依赖 Master Agent"） | 两条原则的关系：直接检查是"看到事实"，适度依赖是"判定分工"——rule 里一句话衔接 |

## 3. 现场事实基线

- `.devin/rules/` 现有 rule 数量：ls 确认（至少 verify-with-logs.md）
- 无 direct-verification 相关 rule
- 复核：`ls .devin/rules/ && grep -rl "直接" .devin/rules/`

## 4. 任务分解

### 任务 1：写 `.devin/rules/direct-verification-ironlaw.md`

结构（对齐 verify-with-logs.md 的格式）：

```markdown
# 直接检查铁律——判断状态必须看到最底层实物

> 触发时机：任何"SOP 检查/回答用户系统状态问题/commit 前验证/DB 与文件不一致排查"
> 场景，只要你要下"X 正常/X 完成了"的结论。

## 规则

DB 和 Redis 是"结果的转述"，不是"事实本身"。任何结论必须有最底层实物的直接证据：

| 检查类型 | ❌ 间接（禁止单独作为结论依据） | ✅ 直接（必须附带） |
|---|---|---|
| 题目完成状态 | DB status=completed | + ls work_dir/proof.md + grep '\\boxed' proof.md |
| 审计完成状态 | DB audit_status=PASS | + 读 export 文件确认 <proof_audit> XML 块存在 |
| 审计收集完成 | DB runs.audit_passed 非 null | + p27_proof_audits 有记录 + 抽样读 export 比对 |
| 进程存活 | DB session status=running | + tmux has-session -t <name> 实测 |
| 队列状态 | DB run status=prepared | + redis-cli ZCARD 对应 key 实测 |
| tmux session 真在干活 | session 存在 | + capture-pane 看内容（注意：-p 模式 pane 仅最终输出） |

## 为什么（028 教训）

DB 说 138 题 completed，硬盘只有 14 个 proof.md——124 个被 018 事故删除。若检查是
直接的（不只查 status 还 ls 文件），事故后第一轮 SOP 就能发现，不用等 027 报告。

## 与 verify-with-logs rule 的关系

那条管"查过程证据"（日志+行为流水三层法）；本条管"看到最底层实物"。两者叠加：
查 DB（结果）→ 查日志/流水（过程）→ 查文件/tmux（实物）。下结论三层都要有。

## 与"适度依赖 Master Agent"原则的关系

直接检查给出"事实"；怎么处置事实（判定/修复/翻案）按适度依赖原则分工——可靠的
确定性判定进代码，语义判断给 Master Agent。

## 附录：现有 SOP 检查的间接→直接升级清单（落地在 WP-C/D/E）

- SOP_01 进度检查：+ 抽样 N 个 completed 题 ls proof.md（WP-D）
- SOP_04 C7/C8：抽查题读 export XML + proof.md 原文，不只读 audit_summary（WP-E）
- SOP_07（新）：审计产出直接验证/通过题交叉验证/孤儿 session 对账（WP-C）
```

（以上是内容骨架——用你自己的语言完整成文，人话铁律，保留表格和三层关系。）

### 任务 2：确认 rule 被发现

`.devin/rules/` 下的 rule 是 devin cli 的 always-on 机制（本 repo 的 Master Agent
运行时按目录扫描）。验证：`ls .devin/rules/` 列出新文件；若 repo 有 rule 索引文档
（grep -rn "verify-with-logs" docs/ README.md AGENTS.md 找引用点），同步加一行引用。

### 任务 3：commit

显式路径 add `.devin/rules/direct-verification-ironlaw.md` + 引用点文件。

## 5. 禁止事项

- ❌ 不要在 rule 里复制 028 报告全文（引用编号即可，rule 要短——always-on 占上下文）
- ❌ 不要动 verify-with-logs.md
- ❌ 不要把升级清单写成本 WP 的任务（清单是给 C/D/E 的交接，不是你现在做）

## 6. 验收 checklist

- [ ] `.devin/rules/direct-verification-ironlaw.md` 存在，含：判定表格（≥5 行对照）/ 028 引用 / 与 verify-with-logs 的关系 / 与适度依赖的关系 / 升级清单附录
- [ ] `grep -c "间接\|直接" .devin/rules/direct-verification-ironlaw.md` > 10（核心词密度）
- [ ] 格式与 verify-with-logs.md 对齐（有触发时机头）
- [ ] 引用点已更新（若存在索引处）
- [ ] commit 完成且只含本 WP 文件

## 7. 完成汇报要求

执行记录：rule 全文、索引引用点的 grep 证据。

## 8. 审计对照

1. rule 的判定表覆盖 031 §6.4 的 5 行场景（题目完成/审计完成/进程存活/队列/审计结果）
2. 三条关系（verify-with-logs / 适度依赖 / 028）都写清了
3. 长度克制（<120 行——always-on 负担）
