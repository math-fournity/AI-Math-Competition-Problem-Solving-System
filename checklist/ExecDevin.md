# CheckList-ExecDevin — Monitor Exec Devin 必读需求点子集

> **本文件是什么**：从 `checklist/README.md`（127 个需求点全集）中提取的 Monitor Exec Devin 必须知道的需求点子集。
> **为什么需要这个子集**：全集 127 个需求点中，约 46% 是 Master Agent/开发者的事（环境确认、控制命令实现、运行监控、审计、文档同步、待决策问题），Exec Devin 不需要知道。信息散落在 6 个文档中，Exec Devin 需要一个统一视角的"我要检查什么、我要遵守什么"清单。
>
> **与全集的关系**：本文件的编号与全集一致（如 `MON-A1` 在两个文件中是同一个需求点）。全集更新时本文件同步更新。
>
> **Exec Devin 怎么用**：
> 1. 启动后读 WORKLOG.md（跨轮记忆）
> 2. 读认知资产（p27_monitor_pipe_operations.md 等 6 个文档）
> 3. **读本文件**——确认本轮要检查什么、要遵守什么约束、要对自己做什么 self-check
> 4. 执行工作循环（检查→判断→修复→报告→退出）
>
> **来源**：`checklist/README.md` v1（2026-08-19）第一档（必须知道）+ 第二档（知道概念）。

---

## 子集索引

| 门类 | 需求点数 | 在 Exec Devin 工作中的角色 |
|---|---|---|
| MON-A | 12 + 5 已知问题 | 读 alert 做分类处理——必须知道每个 alert 的含义 |
| MON-B | 9（含 B8 的 6 子项） | 同上——B 类续传质量检查 |
| MON-C | 5 | **核心工作**——做 AI 判断 |
| SELF | 17 | **对自己的检查**——每轮必须执行 |
| HARD | 5 | 工作硬约束 |
| SESS（概念） | 3 | 理解自己的 session 名和注册表记录 |
| LAUNCH（概念） | 4 | 理解 stuck session 和 DONE.md 机制 |
| EXEC-CONF（概念） | 2 | 理解 prompt 模板和 WORKLOG 格式 |
| EXEC-VERIFY | 6 | 验证标准——它的行为要满足这些 |

**合计**：约 68 个需求点（全集 127 个中的 54%）。

---

## §MON-A · A 类自动检查（Exec Devin 读结果做分类处理）

这些由 `monitor_continuation.py` 的 Python 部分每 120 秒自动执行，结果写成 alert。Exec Devin 运行检查脚本时获取这些 alert，按类型分类处理。

| 编号 | 检查项 | alert_type | severity | 阈值 | 说明 |
|---|---|---|---|---|---|
| MON-A1 | session_health | session_health | critical | — | p27- session 数 vs DB running 数 vs 设定并发——不匹配说明 launcher 挂了 |
| MON-A2 | queue_progress (stalled) | queue_stalled | critical | 15 分钟无变化 | pending 队列没在减少 |
| MON-A3 | queue_progress (no completions) | no_completions | warning | 15 分钟无变化 | completed 没在增加 |
| MON-A4 | rate_limit_detection | rate_limit | critical | ≥3 个 | 最近 interval 内 rate_limited 数量 |
| MON-A5 | zombie_sessions | zombie_sessions | warning | ≥2 个 | 空 pane 僵尸 session |
| MON-A6 | export_landing | export_missing | critical | 缺失率>10% | completed 的 run 无 export 文件 |
| MON-A7 | failure_rate | failure_rate | warning | >15% | 最近 interval 失败率 |
| MON-A8 | launcher_dead | launcher_dead | critical | — | launcher 进程消失但还有 prepared/running 任务 |
| MON-A9 | stall_detection | long_running | warning | 单轮>30 分钟 | 单个续传轮次运行超时 |
| MON-A10 | session_registry_consistency | session_registry_inconsistency | critical/warning | — | 注册表 vs tmux 实际 session 不一致 |
| MON-A11 | stuck_sessions | stuck_session_accumulated | warning/critical | >5 warning, >10 critical | stuck 状态 session 数量 |
| MON-A12 | done_sessions_uncleaned | done_session_uncleaned | info | >20 个 | done 状态但未清理的 session |

### A 类已知问题（Exec Devin 处理 alert 时必须知道）

**详见 `p27_monitor_pipe_operations.md` §3.1.1**。这里是要点速查：

| 编号 | 问题 | 根因状态 | Exec Devin 的处理方式 |
|---|---|---|---|
| MON-A!01 | `expected_concurrency` 不从 DB 读，session_health 误报 | 根因已诊断，待 WP-02 修复 | 不重复诊断，REPORT 记录"已知问题待修复" |
| MON-A!02 | alert 的 `_key` 冲突 | 根因已诊断，待 WP-02 修复 | 不重复诊断，REPORT 记录"已知问题待修复" |
| MON-A!03 | `rounds_log_export_missing` 大量出现 | **根因未诊断** | **优先诊断**——选 3-5 个 run 检查 work_dir 结构 + launcher 命令构造逻辑 |
| MON-A!04 | `export_missing` 大量出现 | **根因未诊断** | **优先诊断**——选 2-3 个 run 检查 work_dir + is_completed 判定逻辑。可能与 MON-A!03 有关联 |
| MON-A!05 | 850+ alert 堆积 | 根因已知（阶段2未完成） | 每轮主动 resolve 已处理的 alert，逐步消化堆积 |

**处理原则**：根因已诊断的不重复诊断；根因未诊断的优先诊断（这是 Exec Devin 的核心价值）；每轮主动 resolve 已处理 alert。

---

## §MON-B · B 类续传质量检查（Exec Devin 读结果做分类处理）

| 编号 | 检查项 | alert_type | severity | 阈值 | 说明 |
|---|---|---|---|---|---|
| MON-B1 | proof_completeness | proof_missing | critical | — | COMPLETED 的 run 无 proof.md |
| MON-B2 | proof_completeness | proof_no_boxed | warning | — | proof.md 无 \boxed 答案 |
| MON-B3 | proof_too_small | proof_too_small | warning | <1KB | proof.md 太小 |
| MON-B4 | handover_completeness | handover_missing | critical | — | v2 方案的 round 无 HANDOVER.md |
| MON-B5 | handover_completeness | handover_too_small | warning | <500B | HANDOVER.md 太小 |
| MON-B6 | truncation_pattern | all_rounds_truncated | warning | 5 轮全截断 | 可能是思维错误不是截断错误 |
| MON-B7 | final_status_distribution | status_anomaly | info | — | final_status 分布异常 |
| MON-B8 | rounds_log_integrity | rounds_log_* (6 子项) | warning/critical | — | rounds_log 字段完整性 + 路径有效性 + round 编号连续性 |
| MON-B9 | intermediate_product_uniqueness | intermediate_product_collision / work_dir_collision | critical | — | 中间产物路径重复 |

**B8 子项明细**：
- B8a: rounds_log_missing_field（缺必需字段 round/export/truncated/completed/reason）
- B8b: rounds_log_export_missing（export 指向的文件不存在）← **注意 MON-A!03 已知问题**
- B8c: rounds_log_handover_missing（handover_path 指向的文件不存在，handover_success=True 时）
- B8d: rounds_log_proof_missing（proof_path 指向的文件不存在，completed=True 时）
- B8e: rounds_log_no_proof_path（completed=True 但无 proof_path 字段）
- B8f: rounds_log_duplicate_round（round 编号重复）

---

## §MON-C · C 类 AI 判断（Exec Devin 的核心工作）

**这些是 Python 做不了的，必须由 Exec Devin 做 AI 判断**。Python 部分只做抽样标记（`needs_ai_review=True`），Exec Devin 读标记后做真正的 AI 判断。

| 编号 | 检查项 | AI 需要检查什么 | 通过标准 |
|---|---|---|---|
| MON-C1 | proof_quality | 读 proof.md，检查数学正确性——答案对不对、证明逻辑是否完整 | 答案正确且证明逻辑完整 |
| MON-C2 | proof_hallucination | proof.md 是否有幻觉——编造的定理、不存在的引用、虚假的计算结果 | 无幻觉 |
| MON-C3 | answer_leak | proof.md 是否答案泄漏——直接从题目描述抄答案而非推导 | 答案是通过推导得到的 |
| MON-C4 | handover_quality | 读 HANDOVER.md，是否准确总结上一轮思考——有无遗漏关键结论、有无编造 | 准确总结、无遗漏、无编造 |
| MON-C5 | continuation_direction | 续传方向是否正确——在上一轮基础上继续还是从头重复 | 在上一轮基础上继续 |

**C 类检查的输入**：
- proof.md 路径（从 rounds_log 的 proof_path 字段获取）
- HANDOVER.md 路径（从 rounds_log 的 handover_path 字段获取）
- export 路径（从 rounds_log 的 export 字段获取，用于判断 continuation_direction）

**C 类检查的输出**：
- 在 MONITOR_EXEC_REPORT.md 中记录每条抽样的判断结果
- 判定 FAIL 的，写 alert 到 DB（alert_type=ai_review_*，severity 根据问题严重程度定）
- 判定 PASS 的，resolve 对应的 needs_ai_review 标记

---

## §SELF · Exec Devin self-check（17 项，每轮必须执行）

**这些是 Exec Devin 对自己的检查**——确保自己的运行正确、不引入新问题。

### 运行完整性（S1-S4）

| 编号 | 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
|---|---|---|---|---|
| SELF-S1 | export 完整性 | 检查自己的 conversation.json 是否存在且非空 | 文件存在且>1KB | 在 REPORT 中记录"export 可能不完整"；不影响本轮工作 |
| SELF-S2 | DONE.md 写入 | 退出前确认 echo 命令正确 | 自动（prompt 中的 exit 命令） | 无需检查 |
| SELF-S3 | REPORT 完整性 | 检查 MONITOR_EXEC_REPORT.md 包含必需章节 | 包含§检查结果摘要/§C 类 AI 判断详情/§修复操作/§未修复问题 | 补全缺失章节 |
| SELF-S4 | session 注册 | 检查自己 session 在 p27_sessions 中 | type=monitor_exec 记录存在 | 记录"session 未注册，可能 Python 部分启动逻辑有问题" |

### 修复正确性（S5-S8）

| 编号 | 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
|---|---|---|---|---|
| SELF-S5 | py_compile 通过 | 修复代码后运行 `python -m py_compile <修改的文件>` | 无语法错误 | 继续修直到通过 |
| SELF-S6 | git commit 成功 | 修复后 git add + git commit | commit 成功 | 记录"commit 失败，原因..." |
| SELF-S7 | 未修改第二级架构级规范 | `git diff --name-only` | 不包含 AGENTS.md/.devin/rules/*.md/MonitorPipe.md/AnalysisSystemDesign.md §5§6 | 如果误改了，git checkout 还原 |
| SELF-S8 | git add 规范 | `git diff --cached --name-only` | 只 add 具体路径，没有 git add -A/. /-u | 如果误 add 了，git reset HEAD <路径>后重新 add |

### 行为正确性（S9-S12）

| 编号 | 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
|---|---|---|---|---|
| SELF-S9 | 只修本轮发现的问题 | 回顾修复操作 | 无重构/改架构/顺便修其他问题 | 如果做了额外修改，在 REPORT 中说明原因 |
| SELF-S10 | 未 spawn subagent | 回顾工具调用 | 无 run_subagent 调用 | — |
| SELF-S11 | 未 push 代码 | 回顾 git 操作 | 无 git push | 如果误 push 了，在 REPORT 中记录（需 Master Agent 评估是否回滚） |
| SELF-S12 | C 类判断有依据 | 回顾 C 类判断 | 每个判断都有读了 proof.md/HANDOVER.md 的记录 | 如果判断没有依据，标记为"不确定" |

### 循环检测（S13-S14）

| 编号 | 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
|---|---|---|---|---|
| SELF-S13 | 是否陷入重复修复 | 读最近 3 轮的 MONITOR_EXEC_REPORT.md | 同一问题没有连续 3 轮修 | 如果陷入循环，在 REPORT 中写"⚠️ 同一问题已连续 N 轮未修好，建议 escalate 给 Master Agent"，不再尝试修复该问题 |
| SELF-S14 | 同一 alert 是否反复出现 | 查 DB 中同一 alert_type 的创建历史 | 同一 alert_type 没有在最近 5 轮中反复创建 | 如果反复出现，说明根因没找到，在 REPORT 中写"⚠️ alert_type X 反复出现，可能需要系统级重构" |

### 文档同步（S15-S17）

| 编号 | 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
|---|---|---|---|---|
| SELF-S15 | 第一级文档同步 | 改了代码就改了对应文档（同一 commit 中） | git diff 包含对应文档修改 | 补充修改文档，重新 commit；如果确实不需要同步，在 REPORT 中说明 |
| SELF-S16 | 第二级规范建议记录 | 涉及第二级规范需更新时 | 在 REPORT 和 WORKLOG 中记录"建议 Master Agent 同步更新 X" | 补充记录 |
| SELF-S17 | 同步清单完整性 | 对照第一级文档清单 | 该改的都改了 | 补充遗漏的文档 |

**第一级文档清单**（Exec Devin 必须同步修改，和代码在同一个 commit 中）：
- `docs/architecture.md` · `docs/operational-concerns.md` · `docs/graceful-shutdown.md` · `docs/dynamic-concurrency.md` · `docs/framework-checklist.md` · `docs/monitor-pipe-pattern.md` · `docs/solver-harness-borrowing.md`
- `AnalysisSystemDesign.md` §4 代码资产索引
- `specs/p27_monitor_spec.md` §2/§3 · `specs/p27_monitor_pipe_operations.md` §3/§4 · `specs/p27_session_management_and_polish_spec.md` §A/§B

**第二级规范清单**（Exec Devin 不能改，只在 REPORT 和 WORKLOG 中记录建议）：
- `AGENTS.md` · `.devin/rules/*.md` · `MonitorPipe.md` 三层架构定义/设计原则 · `AnalysisSystemDesign.md` §5 设计原则/§6 关键设计决策

**判定标准**：改的是"是什么"（事实）还是"应该是什么"（设计决策）。
- "launcher 的 rate_limited 分支从 kill 改为标记 stuck" → 事实性变更 → 同步改 `docs/operational-concerns.md`（第一级，自己改）
- "Monitor Pipe 应该从纯 Python 改为 Python+devin cli 两层" → 架构级变更 → 只在 REPORT+WORKLOG 记录建议（第二级，Master Agent 改）

---

## §HARD · Exec Devin 工作硬约束（5 条）

| 编号 | 硬约束 | 验证方法 |
|---|---|---|
| HARD-05 | Monitor Pipe 执行 devin 的 cwd 在外部目录（`/Volumes/data/p27-monitor-exec/{exec_seq}/`），不在 worktree 内 | work_dir 路径检查 |
| HARD-06 | 绝不 kill 无 DONE.md 的 session——rate_limited/timeout/stall 标记 stuck 不 kill，等 Master Agent 在用户授意下处理 | 代码 review |
| HARD-08 | 禁止 inline 脚本——超过 3 行的逻辑写成文件 | 代码 review |
| HARD-09 | 人话铁律——所有文档/回复/注释/commit message 用人话写 | 文档 review |
| HARD-10 | 给选项必含利弊+推荐+推荐理由 | 文档 review |

---

## §SESS · Session 管理概念（Exec Devin 需要知道的概念，不需要知道实现）

| 编号 | 需要知道的概念 | 为什么需要 |
|---|---|---|
| SESS-04 | `allocate_seq(db)` 原子递增 seq——Exec Devin 启动时 Python 部分调这个为它分配 seq | 知道自己的 seq 是怎么来的，在 REPORT 中引用 |
| SESS-05 | `create_session_record(db, seq, session_name, type, ...)` 创建注册表记录——Python 部分启动 Exec Devin 时调这个 | SELF-S4 检查自己的 session 是否在注册表中，需要知道记录应该长什么样 |
| SESS-09 | Session 命名格式 `p27-s{seq:04d}-{type}-{run_key_short}-r{round}`——Exec Devin 的 session 名是 `p27-s{seq:04d}-monitor-exec-{exec_seq}` | 在 tmux 中看到自己的 session 名知道这是什么；在日志中按 session 名过滤 |

---

## §LAUNCH · Launcher 机制概念（Exec Devin 需要知道的概念）

| 编号 | 需要知道的概念 | 为什么需要 |
|---|---|---|
| LAUNCH-03/04/05 | rate_limited/timeout/stall 分支标记 stuck 不 kill | 处理 A11 stuck_sessions alert 时，知道这些 session 为什么在 tmux 里留着——它们不是 bug，是设计如此 |
| LAUNCH-06 | stuck session 不占并发槽 | 理解为什么 stuck session 堆积不影响系统吞吐 |
| LAUNCH-09 | DONE.md 文件检测机制（不用 pane 文本检测） | Exec Devin 的退出依赖这个——写 DONE.md 后 Python 部分检测到，更新注册表 status=done |

---

## §EXEC-CONF · 配置与模板概念（Exec Devin 需要知道的概念）

| 编号 | 需要知道的概念 | 为什么需要 |
|---|---|---|
| EXEC-05 | `templates/monitor_exec_prompt.md`——Exec Devin 的 prompt 模板，Python 部分读这个模板 + 替换 `{exec_seq}` 构造完整 prompt | 知道自己的 prompt 是怎么构造的，如果发现 prompt 有问题可以在 REPORT 中建议修改模板 |
| EXEC-14 | WORKLOG.md 跨轮跨目录传递——上一轮的 WORKLOG.md 复制到本轮 work_dir，Exec Devin 续写后下一轮再复制 | 知道 WORKLOG.md 的来源和去向，正确续写（追加到末尾，不覆盖） |

**WORKLOG.md 续写格式**（追加到从上一轮复制来的 WORKLOG 末尾）：
```
## 唤醒 #{exec_seq} · {timestamp}
### 检查发现（A/B/C 类 alert 摘要）
### 修复操作（每个修复简述+commit hash）
### 思考（推理和判断——为什么这么修、发现了什么模式、对系统的观察）
### self-check结果
```

---

## §EXEC-VERIFY · 阶段2 验证标准（Exec Devin 的行为要满足这些）

这些是验证 Exec Devin 工作是否正确的标准。Exec Devin 应该主动满足这些标准，不等验证时才发现问题。

| 编号 | 验证标准 | Exec Devin 怎么主动满足 |
|---|---|---|
| EXEC-23 | 完整流程跑通：检查→判断→修复→报告→退出 | 按 §5 工作流程执行，不跳步 |
| EXEC-24 | export 完整保留：conversation.json/DONE.md/MONITOR_EXEC_REPORT.md/WORKLOG.md/tmux.log 5 个文件都存在 | SELF-S1 检查 conversation.json；退出前确认 DONE.md/REPORT/WORKLOG 已写 |
| EXEC-25 | prompt 约束生效：不改 AGENTS.md/specs/、不 push 代码 | SELF-S7 检查未改第二级规范；SELF-S11 检查未 push |
| EXEC-26 | 防重复启动：running 时不启动新的 | Python 部分的 `should_launch_monitor_exec` 保证，Exec Devin 不需要检查 |
| EXEC-27 | C 类 AI 判断真正发生（读 proof.md 做判断，不是只写标记） | SELF-S12 检查每个判断都有读了 proof.md/HANDOVER.md 的记录 |
| EXEC-28 | 自愈能力：构造的代码 bug 被修复 | 这是验证时的测试，Exec Devin 正常工作就满足 |

---

## 使用说明（给 Exec Devin）

### 启动后读本文件的顺序

1. **先读 WORKLOG.md**——跨轮记忆，知道之前每次唤醒做了什么
2. **读本文件**——确认本轮要检查什么、要遵守什么约束、要对自己做什么 self-check
3. **按需读详细规范**——遇到具体 alert 时查 `p27_monitor_spec.md` §3 的详细标准；遇到 self-check 不通过时查 `p27_monitor_pipe_operations.md` §4.5 的文档同步分级

### 本文件与认知资产的关系

| 文档 | 什么时候读 | 本文件的角色 |
|---|---|---|
| `p27_monitor_pipe_operations.md` | 每次启动都读（§3 检查项目 + §4 self-check + §5 工作流程） | 本文件是其 §3/§4 的需求点清单视角——"要检查什么"的统一列表 |
| `p27_monitor_spec.md` | 遇到具体 alert 时查 §3 详细标准 | 本文件的 MON-A/B/C 是其 §2 的速查版，详细标准仍查原文档 |
| `p27_session_management_and_polish_spec.md` | 涉及 session 管理问题时查 §A/§B | 本文件的 SESS/LAUNCH 是其 §A 的概念提取，实现细节仍查原文档 |
| `AnalysisSystemDesign.md` | 需要理解系统整体时读 | 本文件不替代它——本文件是需求点清单，不是设计文档 |
| `MonitorPipe.md` | 需要理解架构范式时读 | 本文件不替代它 |
| `续传规范文档.md` | 涉及续传问题时读 | 本文件不替代它 |

### 发现本文件过时时怎么办

Exec Devin 在工作中可能发现本文件与实际代码/系统状态不符。**不是所有不符都要 Master Agent 处理**——要区分你能改什么、不能改什么。

#### 你能改的（第一级·事实性·自己同步更新）

这些是反映代码/系统实际状态的内容，你修复了问题或发现了事实变化后，应该自己同步更新（属于 SELF-S15 第一级文档同步）：

| 内容 | 什么时候改 | 怎么改 | 同步更新哪些文件 |
|---|---|---|---|
| 需求点**状态标记**（`[ ]`/`[x]`/`[!]`/`[-]`） | 你完成了一个需求点，或修复了一个 `[!]` 的问题 | `[ ]`→`[x]` 或 `[!]`→`[x]` | `CheckList.md`（全集同步状态）+ `p27_monitor_pipe_operations.md` §3.1.1（如果是已知问题修复，移到"已修复"记录）+ §6 加 v 记录 |
| 已知问题**条目**（MON-A!XX 的存在） | 你发现了新的已知问题 | 在本文件和 `CheckList.md` 加 `[!]` 行 | `p27_monitor_pipe_operations.md` §3.1.1 加行 + §6 加 v 记录 |

#### 你不能改的（第二级·架构级·在 REPORT 中建议）

这些是定义"系统应该检查什么"的内容，变更需要 Master Agent 确认后执行：

| 内容 | 为什么不能改 | 你应该做什么 |
|---|---|---|
| 需求点**定义**（检查项是什么、阈值是多少、通过标准） | 这是架构级决策——定义系统应该检查什么 | 在 REPORT 和 WORKLOG 中记录"建议新增/修改 XXX 检查项，理由是 YYY"，Master Agent 决定后执行更新链条 |
| 新增检查项（如 A13） | 同上 | 同上 |
| 新增 self-check（如 S18） | 同上 | 同上 |
| 删除检查项 | 同上 | 同上 |

#### 判定标准

改的是"是什么"（事实）还是"应该是什么"（设计决策）：
- "MON-A!01 已修复" → 事实性变更 → 你自己改状态标记（第一级）
- "A11 的阈值应该从 >5 改为 >3" → 架构级变更 → 在 REPORT 中建议（第二级）
- "发现了一个新的已知问题 MON-A!06" → 事实性变更 → 你自己加已知问题条目（第一级）
- "应该加一个 A13 检查项检查 XXX" → 架构级变更 → 在 REPORT 中建议（第二级）

#### 完整的更新链条（当你能改时）

当你修复了一个已知问题（如 MON-A!01）后，按以下顺序同步更新：

```
第1步：CheckList-ExecDevin.md（本文件）——状态 [!]→[x]，已知问题速查更新
  │
第2步：CheckList.md（全集）——同步状态 [!]→[x]
  │
第3步：p27_monitor_pipe_operations.md §3.1.1——从"当前问题"移到"已修复"记录
  │
第4步：p27_monitor_pipe_operations.md §6——加 v 记录（版本号+日期+"MON-A!01 已修复"）
  │
第5步：commit（代码修复+文档同步在同一个 commit 中——SELF-S15 要求）
```

**注意**：如果你修复的 bug 涉及检查项定义的变化（如修复 MON-A!01 后 expected_concurrency 的检查逻辑变了），那定义部分是第二级，你在 REPORT 中建议 Master Agent 更新 spec，但状态标记你自己改。

---

## 版本记录

- **v1 · 2026-08-19** · 初始版本——从 CheckList.md v1 提取第一档（必须知道）+ 第二档（知道概念），约 68 个需求点。
- **v1.1 · 2026-08-19** · 扩展"发现本文件过时时怎么办"为完整的维护规则——区分 Exec Devin 能改的（第一级·事实性·状态标记和已知问题条目）和不能改的（第二级·架构级·需求点定义），含判定标准和完整更新链条。
