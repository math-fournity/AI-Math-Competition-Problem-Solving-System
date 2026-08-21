# MasterAgentCheck — Master Agent SOP 索引

> **状态变化（2026-08-19）**：本文件的检查内容已迁移到 `docs/sop/SOP_01~05.md`，由 SOP 脚本机制承载。本文件保留为索引。
>
> **新的工作方式**：用户说"开始工作"时，执行 `python -m scripts.sop.sop_01_health_check`，进入 5 步 SOP 循环。详见 `AGENTS.md` 最前面的"Master Agent SOP 流程控制机制"。
>
> **历史**：本文件原来是从 `checklist/ExecDevin.md` 提取的"按需检查清单"（运行 monitor_check_continuation.sh 后全文加载逐项处理）。现已升级为 7x24 持续循环的 SOP 脚本机制。

---

## SOP 文档索引（内容已迁移）

| SOP 文档 | 对应脚本 | 内容来源 |
|---|---|---|
| `docs/sop/SOP_01_health_check.md` | `scripts/sop/sop_01_health_check.py` | 原来的"运行检查脚本"+A类检查项 |
| `docs/sop/SOP_02_alert_triage.md` | `scripts/sop/sop_02_alert_triage.py` | 原来的"新alert分类处理" |
| `docs/sop/SOP_03_ai_judgment.md` | `scripts/sop/sop_03_ai_judgment.py` | 原来的"§C类AI判断（MON-C1~C5）" |
| `docs/sop/SOP_04_code_repair.md` | `scripts/sop/sop_04_code_repair.py` | 原来的"修复操作规范" |
| `docs/sop/SOP_05_report_worklog.md` | `scripts/sop/sop_05_report_worklog.py` | 原来的"执行结果记录" + WORKLOG |

## 检查规范

`docs/specs/p27_monitor_spec.md`（MON-A/B/C 详细标准）—— SOP 文档中引用此规范。

## 和 ExecDevin.md 的关系

`checklist/ExecDevin.md` 是给独立 Monitor Pipe devin cli 用的（已废弃此角色）。本文件和 SOP 脚本机制取代它的角色。ExecDevin.md 保留作为历史参考。

---

## §C类AI判断（MON-C1~C5）

**这些是 Python 做不了的，必须由 Master Agent 做 AI 判断**。Python 部分只做抽样标记（`needs_ai_review=True`），Master Agent 读标记后做真正的 AI 判断。

| 编号 | 检查项 | AI 需要检查什么 | 通过标准 | 详情文件 |
|---|---|---|---|---|
| MON-C1 | proof_quality | 读 proof.md，检查数学正确性——答案对不对、证明逻辑是否完整 | 答案正确且证明逻辑完整 | `checklist/MON-C1.md` |
| MON-C2 | proof_hallucination | proof.md 是否有幻觉——编造的定理、不存在的引用、虚假的计算结果 | 无幻觉 | `checklist/MON-C2.md` |
| MON-C3 | answer_leak | proof.md 是否答案泄漏——直接从题目描述抄答案而非推导 | 答案是通过推导得到的 | `checklist/MON-C3.md` |
| MON-C4 | handover_quality | 读 HANDOVER.md，是否准确总结上一轮思考——有无遗漏关键结论、有无编造 | 准确总结、无遗漏、无编造 | `checklist/MON-C4.md` |
| MON-C5 | continuation_direction | 续传方向是否正确——在上一轮基础上继续还是从头重复 | 在上一轮基础上继续 | `checklist/MON-C5.md` |

**C 类检查的输入**：
- proof.md 路径（从 rounds_log 的 proof_path 字段获取）
- HANDOVER.md 路径（从 rounds_log 的 handover_path 字段获取）
- export 路径（从 rounds_log 的 export 字段获取，用于判断 continuation_direction）

**C 类检查的输出**：
- 在执行结果记录中记录每条抽样的判断结果
- 判定 FAIL 的，写 alert 到 DB（alert_type=ai_review_*，severity 根据问题严重程度定）
- 判定 PASS 的，resolve 对应的 needs_ai_review 标记

**处理方式**：
1. 从检查脚本第2项 alerts 输出中找到 `needs_ai_review=True` 的抽样
2. 逐个读 proof.md / HANDOVER.md
3. 按 C1-C5 标准逐项判断
4. 记录判断结果，FAIL 的写 alert，PASS 的 resolve 标记

---

## §self-check（SELF-S1~S17）

**这些是 Master Agent 对自己的检查**——确保自己的运行正确、不引入新问题。每轮检查必须执行。

### 运行完整性（S1-S4）

| 编号 | 检查项 | 检查方法 | 通过标准 | 详情文件 |
|---|---|---|---|---|
| SELF-S1 | export 完整性 | 检查自己的 conversation.json 是否存在且非空 | 文件存在且>1KB | `checklist/SELF-S1.md` |
| SELF-S2 | DONE.md 写入 | 退出前确认 echo 命令正确 | 自动（prompt 中的 exit 命令） | `checklist/SELF-S2.md` |
| SELF-S3 | REPORT 完整性 | 检查执行结果记录包含必需章节 | 包含§检查结果摘要/§C类AI判断详情/§修复操作/§未修复问题 | `checklist/SELF-S3.md` |
| SELF-S4 | session 注册 | 检查自己 session 在 p27_sessions 中 | type=monitor_exec 记录存在 | `checklist/SELF-S4.md` |

### 修复正确性（S5-S8）

| 编号 | 检查项 | 检查方法 | 通过标准 | 详情文件 |
|---|---|---|---|---|
| SELF-S5 | py_compile 通过 | 修复代码后运行 `python -m py_compile <修改的文件>` | 无语法错误 | `checklist/SELF-S5.md` |
| SELF-S6 | git commit 成功 | 修复后 git add + git commit | commit 成功 | `checklist/SELF-S6.md` |
| SELF-S7 | 未修改第二级架构级规范 | `git diff --name-only` | 不包含 AGENTS.md/.devin/rules/*.md/MonitorPipe.md/AnalysisSystemDesign.md §5§6 | `checklist/SELF-S7.md` |
| SELF-S8 | git add 规范 | `git diff --cached --name-only` | 只 add 具体路径，没有 git add -A/. /-u | `checklist/SELF-S8.md` |

### 行为正确性（S9-S12）

| 编号 | 检查项 | 检查方法 | 通过标准 | 详情文件 |
|---|---|---|---|---|
| SELF-S9 | 只修本轮发现的问题 | 回顾修复操作 | 无重构/改架构/顺便修其他问题 | `checklist/SELF-S9.md` |
| SELF-S10 | 未 spawn subagent | 回顾工具调用 | 无 run_subagent 调用（除非明确需要） | `checklist/SELF-S10.md` |
| SELF-S11 | 未 push 代码 | 回顾 git 操作 | 无 git push | `checklist/SELF-S11.md` |
| SELF-S12 | C 类判断有依据 | 回顾 C 类判断 | 每个判断都有读了 proof.md/HANDOVER.md 的记录 | `checklist/SELF-S12.md` |

### 循环检测（S13-S14）

| 编号 | 检查项 | 检查方法 | 通过标准 | 详情文件 |
|---|---|---|---|---|
| SELF-S13 | 是否陷入重复修复 | 读最近3轮的执行结果记录 | 同一问题没有连续3轮修 | `checklist/SELF-S13.md` |
| SELF-S14 | 同一 alert 是否反复出现 | 查 DB 中同一 alert_type 的创建历史 | 同一 alert_type 没有在最近5轮中反复创建 | `checklist/SELF-S14.md` |

### 文档同步（S15-S17）

| 编号 | 检查项 | 检查方法 | 通过标准 | 详情文件 |
|---|---|---|---|---|
| SELF-S15 | 第一级文档同步 | 改了代码就改了对应文档（同一 commit 中） | git diff 包含对应文档修改 | `checklist/SELF-S15.md` |
| SELF-S16 | 第二级规范建议记录 | 涉及第二级规范需更新时 | 在执行结果记录中记录"建议同步更新 X" | `checklist/SELF-S16.md` |
| SELF-S17 | 同步清单完整性 | 对照第一级文档清单 | 该改的都改了 | `checklist/SELF-S17.md` |

**第一级文档清单**（Master Agent 必须同步修改，和代码在同一个 commit 中）：
- `docs/architecture.md` · `docs/operational-concerns.md` · `docs/graceful-shutdown.md` · `docs/dynamic-concurrency.md` · `docs/framework-checklist.md` · `docs/monitor-pipe-pattern.md` · `docs/solver-harness-borrowing.md`
- `docs/system/AnalysisSystemDesign.md` §4 代码资产索引
- `docs/specs/p27_monitor_spec.md` §2/§3 · `docs/specs/p27_session_management_and_polish_spec.md` §A/§B
- ⚠️ `docs/specs/p27_monitor_pipe_operations.md` 已废弃（原 §3/§4 内容已并入 p27_monitor_spec.md）

**第二级规范清单**（Master Agent 改时需谨慎，记录变更原因）：
- `AGENTS.md` · `.devin/rules/*.md` · `docs/patterns/MonitorPipe.md` 三层架构定义/设计原则 · `docs/system/AnalysisSystemDesign.md` §5 设计原则/§6 关键设计决策

**判定标准**：改的是"是什么"（事实）还是"应该是什么"（设计决策）。
- "launcher 的 rate_limited 分支从 kill 改为标记 stuck" → 事实性变更 → 同步改 `docs/architecture/operational-concerns.md`（第一级，自己改）
- "Monitor Pipe 应该从纯 Python 改为 Python+devin cli 两层" → 架构级变更 → 谨慎修改第二级规范，记录变更原因

---

## §新alert分类处理

**输入**：检查脚本第2项 alerts 输出 + 第8项 runtime_health_check 输出

**处理流程**：
1. 逐个读 alert，确认是真实问题还是已知问题
2. 按类型分类处理（见下表）
3. 处理完用 `--resolve-alert <key>` 标记为 fixed
4. 需要重跑的题：从 alert 的 problem_ids 字段获取 problem_id，在 DB 中找到对应的 run，将 status 改回 prepared，重新入队

### A类自动检查 alert 处理（MON-A1~A12）

| alert_type | severity | 处理方式 | 详情文件 |
|---|---|---|---|
| session_health | critical | launcher可能挂了，检查进程状态（第3项） | `checklist/MON-A1.md` |
| queue_stalled | critical | 检查collector是否在处理completed队列 | `checklist/MON-A2.md` |
| no_completions | warning | 检查completed队列是否在增长 | `checklist/MON-A3.md` |
| rate_limit | critical | 立即降并发（修改batch.concurrency） | `checklist/MON-A4.md` |
| zombie_sessions | warning | 手动kill空pane session | `checklist/MON-A5.md` |
| export_missing | critical | 检查D盘是否挂载、trajectory目录是否可写 | `checklist/MON-A6.md` |
| failure_rate | warning | 检查failure_breakdown，判断是AI能力问题还是基础设施问题 | `checklist/MON-A7.md` |
| launcher_dead | critical | 重启launcher | `checklist/MON-A8.md` |
| long_running | warning | 检查是否真的stall，可能需要kill后重新入队 | `checklist/MON-A9.md` |
| session_registry_inconsistency | critical/warning | 检查注册表 vs tmux实际session | `checklist/MON-A10.md` |
| stuck_session_accumulated | warning/critical | stuck session堆积，检查是否需要清理 | `checklist/MON-A11.md` |
| done_session_uncleaned | info | done状态但未清理的session，定期清理 | `checklist/MON-A12.md` |

### B类续传质量 alert 处理（MON-B1~B9）

| alert_type | severity | 处理方式 | 详情文件 |
|---|---|---|---|
| proof_missing | critical | COMPLETED但无proof.md，需重跑 | `checklist/MON-B1.md` |
| proof_no_boxed | warning | proof.md无boxed答案，需检查是否真正完成 | `checklist/MON-B2.md` |
| proof_too_small | warning | proof.md太小，可能内容不完整 | `checklist/MON-B3.md` |
| handover_missing | critical | v2方案但无HANDOVER.md，Pipe A失败 | `checklist/MON-B4.md` |
| handover_too_small | warning | HANDOVER.md太小，可能总结不完整 | `checklist/MON-B5.md` |
| all_rounds_truncated | warning | 5轮全截断，可能是真正的思维错误 | `checklist/MON-B6.md` |
| status_anomaly | info | final_status分布异常，观察 | `checklist/MON-B7.md` |
| rounds_log_* (6子项) | warning/critical | rounds_log字段完整性问题，逐项检查 | `checklist/MON-B8.md` |
| intermediate_product_collision / work_dir_collision | critical | 中间产物路径重复，检查路径生成逻辑 | `checklist/MON-B9.md` |

---

## §已知问题诊断（MON-A-issue-01~05）

**处理原则**：根因已诊断的不重复诊断；根因未诊断的优先诊断（这是 Master Agent 的核心价值）；每轮主动 resolve 已处理 alert。

| 编号 | 问题 | 根因状态 | Master Agent 的处理方式 | 详情文件 |
|---|---|---|---|---|
| MON-A!01 | ~~`expected_concurrency` 不从 DB 读，session_health 误报~~ **已修复**（commit `edcb439`） | **已修复** | 正常处理即可——session_health 现在从 DB 读 concurrency | `checklist/MON-A-issue-01.md` |
| MON-A!02 | ~~alert 的 `_key` 冲突~~ **已修复**（2026-08-21 去重修复，`create_alert` 幂等去重版） | **已修复** | 正常处理即可——alert 现在确定性 hash key + 去重 | `checklist/MON-A-issue-02.md` |
| MON-A!03 | `rounds_log_export_missing` 大量出现 | **根因未诊断** | **优先诊断**——选3-5个run检查work_dir结构+launcher命令构造逻辑 | `checklist/MON-A-issue-03.md` |
| MON-A!04 | `export_missing` 大量出现 | **根因未诊断** | **优先诊断**——选2-3个run检查work_dir+is_completed判定逻辑。可能与MON-A!03有关联 | `checklist/MON-A-issue-04.md` |
| MON-A!05 | 850+ alert 堆积 | 根因已知（阶段2未完成） | 每轮主动resolve已处理的alert，逐步消化堆积 | `checklist/MON-A-issue-05.md` |

**诊断方法**：
1. 从 DB 中找到有问题的 run（用 alert 的 problem_ids 字段）
2. 检查 run 的 work_dir 结构——目录是否存在、文件是否完整
3. 检查 launcher 命令构造逻辑——命令中的路径是否正确
4. 检查 is_completed 判定逻辑——什么条件下标记 completed
5. 找到根因后，修复代码，commit，记录诊断过程

---

## §落盘完整性检查

**每个 round 的完整落盘验证**——确保做题过程的完整落盘（用户需求中的"整个做题过程是完整落盘的，可能需要很多 round，每个 round 都要落盘"）。

**检查项**：
1. **每个 run 的 work_dir 是否存在**——DB 中 run 记录的 work_dir 字段指向的目录是否存在
2. **每个 round 的产物是否完整**：
   - export 文件（conversation.json）——rounds_log 的 export 字段指向的文件是否存在
   - HANDOVER.md——handover_success=True 时，handover_path 指向的文件是否存在
   - proof.md——completed=True 时，proof_path 指向的文件是否存在
3. **round 编号连续性**——rounds_log 的 round 字段是否连续（1,2,3,...无跳号无重复）
4. **中间产物路径唯一性**——不同 run 的 work_dir 不应重复

**检查方法**：
- 检查脚本第5项续传质量汇总已包含部分检查（proof.md统计、5轮全截断统计）
- 检查脚本第8项 runtime_health_check 的 [H] 落盘完整性维度
- 如发现不完整，按 MON-B8 子项分类处理

---

## §修复操作规范

**发现问题后的修复流程**：

1. **诊断根因**——不要只修症状，要找到根因
2. **修复代码**——改代码解决问题
3. **同步更新文档**——改了代码就改对应的第一级文档（同一 commit 中）
4. **py_compile 验证**——`python -m py_compile <修改的文件>`
5. **git 显式路径 add**——`git add <具体路径>`，禁止 `git add -A/. /-u`
6. **commit**——commit message 用人话写，说明为什么这么修
7. **维护 trace.csv**——commit 同时包含 repo 变更和 trace.csv 变更
8. **记录修复**——在执行结果记录中记录修复操作和 commit hash

**硬约束**（来自 HARD 门类）：
- HARD-05：Monitor Pipe 执行 devin 的 cwd 在外部目录，不在 worktree 内
- HARD-06：绝不 kill 无 DONE.md 的 session——rate_limited/timeout/stall 标记 stuck 不 kill
- HARD-08：禁止 inline 脚本——超过3行的逻辑写成文件
- HARD-09：人话铁律——所有文档/回复/注释/commit message 用人话写
- HARD-10：给选项必含利弊+推荐+推荐理由

**不能做的事**：
- 不重构不相关的代码（SELF-S9）
- 不修改第二级架构级规范（SELF-S7，除非明确需要并记录原因）
- 不 push 代码（SELF-S11）
- 不 kill 无 DONE.md 的 session（HARD-06）

---

## 版本记录

- 2026-08-19：创建。从 `checklist/ExecDevin.md` 提取 Master Agent 需要的检查项，重新组织为"Master Agent 视角"。来源：`dev-docs/005-Master-Agent接管Monitor-Pipe检查工作.md`（需求）+ `dev-docs/006-Master-Agent接管Monitor-Pipe检查工作方案.md`（方案 §2.3）。
