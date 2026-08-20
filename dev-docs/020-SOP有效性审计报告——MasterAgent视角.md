# 020-SOP有效性审计报告——Master Agent视角

> **日期**：2026-08-20
> **审计视角**：未来 Master Agent 在 SOP 驱动下监管运行中的续传解题系统
> **审计对象**：SOP_01~06+Z+OP 八个文档 + SYSTEM_CLOSURE + 报表模板 + checks.py
> **审计标准**：每个步骤的内容是否能**有效帮助** Master Agent 完成任务——内容充分性、指引清晰度、检查项覆盖、AI 判断支撑、todo 可执行性

---

## 一、总体评价

**SOP 机制整体有效，但存在若干执行缺口和认知不一致。**

8 步循环结构合理，每步有认知闭包（L0+L1）+ 自动化检查 + AI 判断指引 + todo 指令 + 报表模板，形成完整闭环。SYSTEM_CLOSURE（L0）提供了优秀的系统级认知基础——架构/生命周期/判定框架/A 类标准/异常信号/铁律索引，让 Master Agent 在任何步骤都能推理"系统现在工作得对不对"。

但逐步审计后发现若干问题：有些步骤指引的操作没有对应的脚本命令（执行缺口），有些步骤的内容与代码实际行为不一致（认知偏差），有些步骤的 AI 判断部分缺乏足够支撑（判断盲区）。

---

## 二、逐步审计

### SOP_01 系统存活+进度+Session —— ✅ 有效，有小问题

**优点**：
- 8 项自动化检查覆盖全面（进程/进度/session/健康/门闸/行为流水）
- §8 行为流水必查是 016 事故的核心教训，有判断标准表格
- §8.5 门闸 Y 通道有 X/Y 注意力模型解释和完整操作命令
- §9 model 参数检查有具体命令
- 报表模板 report_step_01 有 10 个自动化检查项 + 3 个 AI 判断项 + 门闸记录区

**问题**：

**P01-1（认知偏差）**：§1 "你是谁"写"你是错题分析系统的 Monitor AI"——应改为"续传解题系统的 Monitor AI"。与 SYSTEM_CLOSURE §1 和 AGENTS.md 的更新不一致。

**P01-2（认知偏差）**：§3 重启命令写 `python -m monitoring.continuation_control start --batch-id p27-full --concurrency 5`，但 AGENTS.md 已说明 `--concurrency 5` 只是初始值会被 DB 覆盖。这里没有提示这个事实，Master Agent 可能误以为重启会重置并发。

**P01-3（指引缺失）**：§6 "深入了解"引用 `docs/system/AnalysisSystemDesign.md`——该文档已标过时。应改为指向 `docs/architecture/solve-pipeline.md`。

**P01-4（报表模板小问题）**：report_step_01 的"系统快照摘要"只有 4 行（总 run/COMPLETED/完成率/sessions），缺少 pending/running/failed——这些是判断系统健康的关键指标。Master Agent 需要从 check_output.txt 手动提取，不如直接放快照。

---

### SOP_02 数据完整性 —— ✅ 有效，内容最充实

**优点**：
- 自动化检查覆盖 7 个维度（文件完整性/proof 质量/results 集合/events/prepared 堆积/题源完成率/round 连续性），是所有步骤中自动化程度最高的
- §2e "跨题目模式分析"明确标注"AI 必须做"，给出 3 个分析方向（全 0% 题源诊断/完成率差异/失败模式分布），这是 AI 核心价值的正确定位
- rounds_log 7 字段检查有 round-1 特殊处理说明（只有 5 基础字段），避免误报
- 报表模板有完整的检查项清单

**问题**：

**P02-1（指引缺失）**：§2b/2c/2d 的深度检查用 Python inline 代码示例（`from src.continuation_redis_queue import ...`）——这违反 no-inline-scripts 规则（超过 3 行）。Master Agent 如果照做就是写 inline 脚本。应该提供持久化脚本或 continuation_control 子命令。

**P02-2（编号混乱）**：文档结构有编号问题——§3 "填写报表"出现在 §2 之后，但 §3 "日志观察"又出现在 todo list 之后（第 211 行）。两个 §3 编号冲突，后者应为 §5 或移到前面。

---

### SOP_03 alert 分类 —— ✅ 有效，简洁精准

**优点**：
- alert 类型清单表格完整（20 种 alert_type + 含义 + 分类 + 处理方式），是 Master Agent 分类的权威参考
- 分类标准清晰（5 类：代码 bug/数据/基础设施/需重跑/需清理）
- "需立即处理"段明确哪些不等步骤 05（launcher_dead 立即重启）

**问题**：无重大问题。这是 8 个步骤中结构最清晰、指引最直接的。

**P03-1（小问题）**：alert 类型清单中 `session_health` 的"分类"写"代码bug或配置问题"，但 A1 标准是"session 数≈DB running≈设定并发"——不匹配可能是 session_registry 脱节（A13），不一定是代码 bug。分类可以更精确。

---

### SOP_04 C 类 AI 判断 —— ⚠️ 有效但有执行缺口

**优点**：
- C1-C6 检查项定义清晰（proof 质量/幻觉/答案泄漏/handover 质量/续传方向/export 语义），每个有"你要读什么 + 判断什么 + 通过标准"
- §2 逐个判断指引具体（如 C2 幻觉给出 3 种具体表现：编造定理/编造引用/虚假计算）
- C6 export_semantics 明确标注"脚本完全无法做的检查"——正确定位 AI 价值
- 报表模板 report_step_04 有逐 run 的 C1-C6 记录模板

**问题**：

**P04-1（执行缺口——严重）**：§4 "标记已判断"说"在 DB 中标记 `ai_review_done = true`，记录 `ai_review_result`"——**但没有提供任何命令或脚本**。continuation_control.py 没有 `mark-ai-review` 子命令，monitor_continuation.py 有 `resolve_alert()` 但没有 `mark_ai_review()`。Master Agent 要完成这个操作只能写 inline Python/AQL——违反 no-inline-scripts 规则，且每次都重写。

**影响**：Master Agent 可能跳过这个步骤（不知道怎么标记），导致同一批 needs_ai_review 的 run 每轮都被 check_04 查出来重复判断——浪费 AI 精力。

**P04-2（判断盲区）**：C1 proof_quality 说"检查 boxed 答案是否正确（如果知道标准答案的话）"——但 Master Agent 不一定知道标准答案。文档没有说明：如果不知道标准答案怎么办？应该指引 Master Agent 去哪里找标准答案（如 problem.txt 中是否含答案、或 DB 中是否有标准答案字段）。

**P04-3（认知偏差）**：§1 "什么是 C 类检查"写"监控 Pipe 的检查分三类：A 类/B 类/C 类"——这是旧 4 Pipe 时代的分类（monitor_continuation.py 实际只做 A 类和 B 类，C 类是 monitor_exec 的职责但从未实现）。当前 C 类判断由 Master Agent 在本步骤做，不是由 monitor_continuation 触发。文档应说明"C 类判断由你（Master Agent）做，monitor_continuation 只负责抽样标记 needs_ai_review"。

---

### SOP_05 代码修复 —— ✅ 有效，约束清晰

**优点**：
- 修复约束 8 条明确（不 push/不改架构级规范/显式 add/py_compile/只修本轮问题/同步文档/更新 trace/sim 门禁）
- §4 发布门禁是 016 核心教训，有具体命令（solve3 + chaos_016）和适用范围
- commit message 格式有模板

**问题**：

**P05-1（指引过时）**：§2 修复约束第 2 条"不能修改这些文件"列出 `docs/system/AnalysisSystemDesign.md` §5/§6——该文档已标过时。如果这些文档已过时，"不能修改"的约束意义不大。应更新为当前有效的架构级规范清单。

**P05-2（trace.csv 引用）**：§2 第 8 条"更新 trace.csv"和 §3 第 6 步"更新 trace.csv"——但项目根目录没有 trace.csv 文件。这个要求可能来自全局规则 cognition-trace-ironlaws，但本 repo 似乎没有实施 trace.csv。Master Agent 会困惑"trace.csv 在哪"。

**P05-3（深入了解过时）**：§5 引用 `docs/system/AnalysisSystemDesign.md` §6——已标过时。

---

### SOP_06 报告+WORKLOG+Self-check —— ⚠️ 有效但有执行缺口

**优点**：
- Self-check 22 项覆盖全面（S1-S22，含 016/017/018 新增的 S18-S22）
- 报告格式模板清晰（检查摘要/修复/未修复/self-check/下一轮建议）
- WORKLOG 续写格式有模板

**问题**：

**P06-1（执行缺口——严重）**：§4 "resolve 已处理的 alert"说"更新 status 为 resolved"——**但没有提供任何命令或脚本**。continuation_control.py 没有 `resolve-alert` 子命令。与 P04-1 同类问题。Master Agent 要完成这个操作只能写 inline AQL。

**影响**：未 resolve 的 alert 会在每轮 SOP_03 中重复出现，Master Agent 每轮都要重新分类已处理过的 alert——浪费精力且可能误判（以为是新问题）。

**P06-2（认知偏差）**：§1 报告名称写 `MONITOR_EXEC_REPORT.md`——这是旧 monitor_exec 时代的命名。当前系统没有 monitor_exec，报告由 Master Agent 自己写。应改为更通用的名称如 `SOP_REPORT.md` 或 `MONITOR_REPORT.md`。

**P06-3（编号不一致）**：§3 写"执行 Self-check（S1-S17）"——但实际表格列了 S1-S22（含 016/017/018 新增）。标题编号与实际不符。

**P06-4（报表模板不一致）**：report_step_06 标题写"step_06 报告+WORKLOG+Self-check"，§二标题写"Self-check S1-S17"——但表格列了 S1-S22。与 SOP_06 文档同样的编号不一致。

**P06-5（S1/S2 适用性）**：S1 "export 完整性"和 S2 "DONE.md 写入"——这两个检查项是给 monitor_exec devin cli 的（检查自己的 conversation.json 和 DONE.md）。Master Agent 不是 devin cli，没有自己的 export 和 DONE.md。这两个检查项对 Master Agent 不适用，应标 `[-]` 或重新定义。

---

### SOP_Z 元检查+整体检查 —— ✅ 有效，自我进化机制好

**优点**：
- 元检查覆盖 6 个工作步骤的合理性 + 016 新能力接线检查
- 整体检查 7 个维度（步骤划分/顺序/状态机制/适配度/AGENTS.md/需求覆盖/方向性判断）
- §7 方向性判断是最高层判断——策略有效性/产出价值/系统性问题诊断，明确标注"AI 必须做，脚本无法替代"
- AUDIT-01~07 审计框架设计完整（每 5 轮一次）

**问题**：

**PZ-1（内容过时）**：§第一部分"对 6 个工作步骤逐个反思"——但实际是 8 步（含 OP）。OP 步骤没有被纳入元检查范围。

**PZ-2（引用过时）**：§SOP 系统结构列表没有列 SOP_OP 文档——应补上。

**PZ-3（方向性判断过时）**：§7b "系统产出价值判断"写"系统产出（判定结果）对 Mid-Hint 实验的选题是否有用"——Mid-Hint 实验选题是旧 Pipe 1/2/3 的使命，当前系统是续传解题，不是选题。应更新为续传解题的价值判断（如"解出的题是否真的正确""续传是否真的比单轮更好"）。

**PZ-4（AUDIT-06 过时）**：§AUDIT-06 通过率判定写"≥50% → POC-2.5 候选题基础成立""≥80% → POC-2.5 需要重新选题"——POC-2.5 选题是旧使命，应更新为续传解题的通过率标准。

---

### SOP_OP 运营知识刷新 —— ✅ 有效（已在 019 报告中修复）

已在 019 报告 P0/P1 中修复了项目概况和外部文档索引。当前状态良好。

**小问题**：

**POP-1（硬约束引用过时）**：硬约束第 1 条"改代码必须同步更新第一级文档"列出 `docs/system/*.md`——该目录三个文档已标过时。应更新为当前有效的第一级文档清单。

---

### SYSTEM_CLOSURE（L0）—— ✅ 有效（已在 019 报告中修复）

已在 019 报告 P0 中修复了系统使命和架构描述。当前状态良好。

**小问题**：

**PSC-1（§4 模块职责表不完整）**：列出 6 个模块（launcher/feeder/monitor_continuation/session_registry/step_gate/observability），但缺少 continuation_collector 和 continuation_result_collector——这两个是管线的入口和出口，虽然异常时表现不明显，但职责表应完整。

---

## 三、报表模板审计

| 模板 | 与 SOP 文档匹配度 | 问题 |
|---|---|---|
| report_step_01 | ✅ 匹配 | 快照缺 pending/running/failed（P01-4） |
| report_step_02 | ✅ 匹配 | 无重大问题 |
| report_step_03 | ✅ 匹配 | 无重大问题 |
| report_step_04 | ✅ 匹配 | 无重大问题 |
| report_step_05 | ✅ 匹配 | 无重大问题 |
| report_step_06 | ⚠️ 编号不一致 | 标题写 S1-S17，表格列 S1-S22（P06-4） |
| report_step_Z | ✅ 匹配 | 无重大问题 |
| report_step_OP | ✅ 匹配 | 无重大问题 |

---

## 四、跨步骤问题

### X1（执行缺口——最严重）：缺少 alert resolve 和 ai_review mark 的持久化脚本

SOP_04 §4 要求"标记 ai_review_done=true"和 SOP_06 §4 要求"resolve alert"——两者都没有提供持久化命令或脚本。continuation_control.py 只有 start/stop/status/health/set-concurrency/sessions 六个子命令，缺少：
- `resolve-alert <alert_key>` — 标记 alert 为 resolved
- `mark-ai-review <run_key> --result PASS/FAIL` — 标记 AI 判断完成+结果

**影响**：Master Agent 要么写 inline 代码（违反 no-inline-scripts），要么跳过这些操作（导致 alert/review 候选重复出现）。这是 SOP 循环中最大的执行缺口。

**建议**：在 continuation_control.py 新增这两个子命令，或在 scripts/ 下新建 `sop_ops.py` 脚本。

### X2（认知不一致）：SOP 文档中的"错题分析系统"命名

多个 SOP 文档仍用"错题分析系统"命名（SOP_01 §1、SOP_06 §1 报告名 MONITOR_EXEC_REPORT）。SYSTEM_CLOSURE 和 AGENTS.md 已改为"续传解题系统"。应统一命名。

### X3（trace.csv 引用）：SOP_05 引用不存在的 trace.csv

SOP_05 §2 第 8 条和 §3 第 6 步要求"更新 trace.csv"——本 repo 没有 trace.csv。这来自全局规则 cognition-trace-ironlaws，但本 repo 未实施。应删除引用或说明"如本 repo 实施 trace.csv 则更新"。

### X4（深入了解更多指向过时文档）

SOP_01 §6、SOP_05 §5 都引用 `docs/system/AnalysisSystemDesign.md`——已标过时。应更新为当前有效文档。

---

## 五、修复优先级

| 优先级 | 问题 | 修复方式 | 工作量 |
|---|---|---|---|
| P0 | X1：缺少 resolve-alert + mark-ai-review 脚本 | 新增 continuation_control 子命令或新脚本 | 中 |
| P0 | P04-1/P06-1：SOP_04/06 的执行缺口 | 修复 X1 后更新 SOP 文档引用命令 | 小 |
| P1 | P01-1：SOP_01 "你是谁"命名过时 | 改 1 行 | 极小 |
| P1 | P04-3：SOP_04 C 类检查定位偏差 | 补说明"C 类由你做，monitor 只抽样" | 小 |
| P1 | P06-2：MONITOR_EXEC_REPORT 命名过时 | 改报告名 | 小 |
| P1 | P06-3/P06-4：S1-S17 编号不一致 | 改 S1-S22 | 极小 |
| P1 | PZ-1：SOP_Z 元检查漏 OP | 补 OP 检查 | 小 |
| P1 | PZ-3/PZ-4：SOP_Z 方向性判断过时 | 更新为续传解题价值判断 | 中 |
| P2 | P01-2：重启命令并发说明 | 补注 DB 覆盖 | 极小 |
| P2 | P01-3/P05-3：深入了解引用过时文档 | 更新指向 | 极小 |
| P2 | P02-1：深度检查 inline 代码 | 提供持久化脚本 | 中 |
| P2 | P02-2：SOP_02 编号混乱 | 重新编号 | 小 |
| P2 | P04-2：C1 标准答案指引缺失 | 补说明 | 小 |
| P2 | P05-1：修复约束引用过时文档 | 更新清单 | 小 |
| P2 | P05-2/X3：trace.csv 引用 | 删除或条件化 | 极小 |
| P2 | P06-5：S1/S2 适用性 | 重新定义或标 [-] | 小 |
| P2 | POP-1：硬约束引用过时文档 | 更新清单 | 小 |
| P2 | PSC-1：模块职责表不完整 | 补 2 行 | 极小 |
| P3 | P01-4：报表快照缺指标 | 补 3 行 | 极小 |
| P3 | P03-1：alert 分类精度 | 微调 | 极小 |

---

## 六、结论

**SOP 机制整体有效**——8 步循环 + 三层认知闭包（L0 系统级 + L1 步骤级 + L2 论证依据）+ 自动化检查 + AI 判断指引 + 报表审计，形成了完整的监管闭环。SYSTEM_CLOSURE 的判定框架（四特征 + A 类 14 项标准 + 异常信号）尤其优秀——让 Master Agent 在任何步骤都能推理系统状态。

**最大的问题是执行缺口（X1）**：SOP_04 和 SOP_06 要求的操作（标记 ai_review_done、resolve alert）没有对应的持久化命令。这不是文档问题而是工具问题——需要补脚本。不修复的话，alert/review 候选会每轮重复出现，浪费 Master Agent 精力。

**第二类问题是认知不一致**：多个 SOP 文档仍用旧命名（"错题分析系统"/MONITOR_EXEC_REPORT）和引用过时文档。这些是 019 报告修复的遗漏——019 修了 SYSTEM_CLOSURE 和 SOP_OP 的核心认知，但各步骤文档中的局部引用没扫干净。

**第三类问题是内容过时**：SOP_Z 的方向性判断还在用旧使命（Mid-Hint 选题/POC-2.5），需要更新为续传解题的价值判断。

**建议修复顺序**：先修 X1（补脚本，解决执行缺口），再批量修 P1（认知不一致+编号错误），P2/P3 后续逐步处理。
