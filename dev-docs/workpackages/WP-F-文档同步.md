# WP-F — 全量文档同步（所有代码类 WP 完成后的最终对齐）

> **优先级**: 最后（线 1 收尾）——**必须在其他所有线 1 WP 完成后执行**
> **依赖**: 全部（N/P/H/G/A/B/S/I/J/K/L/C/D/E/Q/R）
> **预计规模**: AGENTS.md / SYSTEM_CLOSURE / README.md / StepGate.md / architecture
> 若干 / checklist 若干——以对齐审计的方式执行
> **性质**: 纯文档对齐（无代码改动）

---

## 0. 给执行 AI 的第一句话

前面的 WP 各自做了局部文档同步，但跨文档的**一致性**没有全局校验过——024 对齐审计
（commit 02aa267）就是干这个的：数数、清单、口径在所有第一级文档里必须一致且与代码
一致。你要做一次全量对齐：以代码为 ground truth（024 方法论），把 030~036 链与本批
WP 造成的所有变化同步到全部第一级文档，并清点遗留。

## 1. 背景（为什么）

- 铁律 2（改代码同步第一级文档）在每个 WP 局部执行过——但"文档 A 说 9 步、文档 B
  说 8 步"这类**跨文档漂移**只能全局对齐抓
- 历史教训：SOP_01 说 9 门闸 vs SYSTEM_CLOSURE 说 13（031 C4）；AGENTS.md 说违规
  2 处实际 3 处（031 C3）；SYSTEM_CLOSURE alert 清单超前代码（031 C2）；AGENTS.md:238
  铁律与代码不符（033）——全是"局部同步了、全局不一致"
- 本 WP 是用户审计本批工作包前的"最后一次撒谎清零"

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **总控状态表**（README.md §四） | 确认全部 WP 状态=完成——有未完成者，本 WP 只对齐已完成部分并在执行记录声明范围 |
| 2 | `dev-docs/024-AGENTS与docs对SOP-src对齐审计报告.md`（方法论段，~60 行） | 对齐审计的方法：ground truth=代码>git时间线>文档；编号以 spec §2 为准；计数只留一处权威 |
| 3 | 各 WP 的执行记录（exec-log/ 目录全部） | 每个 WP 实际改了什么——你的同步事实源 |
| 4 | 全部第一级文档清单：AGENTS.md / README.md / docs/sop/*.md（9+1 个）/ docs/architecture/*.md / docs/patterns/StepGate.md / docs/specs/p27_monitor_spec.md / checklist/README.md | 逐个过（§4 的核对矩阵） |
| 5 | `git log --oneline` 本批全部 commit | 时间线与改动面 |
| 6 | 代码现状的若干 grep（§4 矩阵中每项的验证命令） | ground truth |

## 3. 现场事实基线

各 WP 局部同步已做（执行记录可查）。本 WP 的"基线"是**核对矩阵**（§4）——逐项
验证，发现不一致才改。预计的不一致高危点：
- SOP 步数（8→9）在 SOP_Z/SOP_OP/README/AGENTS.md（WP-C 已同步，复查）
- 门闸数（13）在 SOP_01/StepGate.md（WP-A/D 同步过，复查）
- 并发来源（DB batch）在 AGENTS.md 硬约束段/SYSTEM_CLOSURE 配置表/dynamic-concurrency
  （WP-G 同步过，复查）+ **AGENTS.md:185-188 的违规清单残留**（031 P2-a：列了 2 处
  违规+错误的"WP-H（030方案）"引用——WP-G 的同步是否清了这行，复查）
- "适度依赖 Master Agent"硬约束段是否补了 033 的边界判据（034 §六承诺补——是否真补了）
- alert 清单（WP-Q 对齐后）与 SOP_03 的一致性
- 13 门闸清单表（SYSTEM_CLOSURE §5）与 step_gate --list 实际注册的一致性
- 资产保留铁律段与 WP-S 的 partial 归档语义一致

## 4. 任务分解

### 任务 1：核对矩阵（逐项跑验证命令，不一致→改文档）

| # | 核对项 | ground truth 验证 | 文档核对点 |
|---|---|---|---|
| 1 | SOP 步数=9（01-06,07,Z,OP） | `grep -n "SOP_STEPS" scripts/sop/sop_state.py` | AGENTS.md 循环表/有效编号列表、SYSTEM_CLOSURE 循环图、SOP_Z 循环段、SOP_OP 文档清单段、README.md |
| 2 | 门闸数=13（9+4） | `python -m src.step_gate --list \| tail -1`（或 DB count） | SOP_01 §8.5、StepGate.md 首段、SYSTEM_CLOSURE §5 门闸表（逐行对 --list） |
| 3 | 并发无写死+DB 来源 | `grep -rn "DEFAULT_CONCURRENCY\|AUDIT_DEFAULT_CONCURRENCY" src/ scripts/` → 0；`grep -n "default=5" scripts/run_proof_audit_pipeline.py` → 0 | AGENTS.md 硬约束段（违规清单应标"已修复"或删除）+ :185-188 残留清理、SYSTEM_CLOSURE §5 配置表、dynamic-concurrency.md |
| 4 | PARSE_ERROR 语义 | `grep -n "mark_parse_error" src/proof_audit_result_collector.py` | SYSTEM_CLOSURE alert 行、SOP_07 文档的复查指引（如涉及） |
| 5 | alert 清单 vs 代码 | `grep -rn "alert_type" src/ --include="*.py" \| grep -o '"[a-z_]*"' \| sort -u` | SYSTEM_CLOSURE §6 表逐行、SOP_03 分诊表 |
| 6 | partial 归档语义 | `grep -n "proof_partial" src/continuation_launcher.py` | AGENTS.md 资产保留段的"唯一允许的删除"表述、SYSTEM_CLOSURE rounds_log 说明 |
| 7 | 审计优雅停止+收尾即收集 | `grep -n "should_stop\|collect_one" src/proof_audit_launcher.py` | graceful-shutdown.md §3.4、SYSTEM_CLOSURE §2/§4 |
| 8 | ai_gave_up 终态 | `grep -n "ai_gave_up" src/continuation_launcher.py` | SYSTEM_CLOSURE §3 生命周期/§6 状态、029 无需动 |
| 9 | 共享模块存在 | `ls src/devin_cli_failure_detection.py` | SYSTEM_CLOSURE §4 支撑模块表加行 |
| 10 | 直接检查 rule | `ls .devin/rules/direct-verification-ironlaw.md` | README.md 外部索引（若有 rules 索引处）、AGENTS.md 是否引用（可选） |
| 11 | "适度依赖"边界判据 | 读 AGENTS.md 该段——含"能否写成确定性函数"句 | 没有则补（033 建议原文见 dev-docs/033 §四.1） |
| 12 | retry 机制 | `ls src/retry_infrastructure.py` | SYSTEM_CLOSURE §4 表、operational-concerns 或新文档（WP-L 已写，复查） |
| 13 | checklist/ 目录 | grep 本批 WP 涉及的 checkpoint 编号（AUDIT-08 等） | 更新对应条目状态 |
| 14 | README.md（repo 根） | 分类法索引 | 新增文档的登记：workpackages/ 目录、037/038/039（若产生） |

### 任务 2：写对齐报告

`dev-docs/040-本批工作包文档对齐报告.md`：矩阵逐项结果（一致/已修正）、修正清单
（哪份文档哪一行改了什么）、未决事项。

### 任务 3：commit

显式路径 add 全部改动文档 + 040 报告。

## 5. 禁止事项

- ❌ **不改任何代码**（发现代码 bug → 记入 040"未决事项"，另立 WP）
- ❌ 不美化/扩写文档（对齐=让文档与代码一致，不是写作文）
- ❌ 计数只留一处权威（024 方法论）：同一计数在多处出现时，其余处改为引用权威处
  （如"门闸数见 SYSTEM_CLOSURE §5"）
- ❌ 不要跳过矩阵任何一行（哪怕"看起来没问题"——跑验证命令就是证据）

## 6. 验收 checklist

- [ ] 矩阵 14 项逐项有验证命令输出与结论（贴 040 报告）
- [ ] 所有修正项列出（文档/行/前后）
- [ ] AGENTS.md:185-188 的历史残留（违规清单/"WP-H（030 方案）"引用）确认清理
- [ ] "适度依赖"边界判据确认在 AGENTS.md（或列入修正）
- [ ] 040 报告存在
- [ ] commit 只含文档+报告

## 7. 完成汇报要求

执行记录（可并入 040）：矩阵全表、修正清单、未决事项。

## 8. 审计对照

1. 我会重跑矩阵中至少 5 项的验证命令独立核对
2. 抽查"计数一处权威"原则的执行（门闸数/步数/alert 数——多文档 grep 同一数字）
3. 040 的"未决事项"我会逐条追问（这是下批工作包的候选）
