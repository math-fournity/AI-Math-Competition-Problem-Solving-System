# AnalysisSystem 系统功能 CheckList（需求点清单）

> **本文件是什么**：错题分析系统全部功能需求点的分门别类清单。
> **不是什么**：不是实施计划（那是 WP-01~WP-10 的事），不是检查规范详情（那是 `p27_monitor_spec.md` 的事），不是设计文档（那是 `AnalysisSystemDesign.md` 的事）。
>
> **用途**：
> 1. 开发前——确认"要做哪些功能"没有遗漏
> 2. 开发中——每个功能点有唯一编号，WP 和 commit message 可引用
> 3. 验收时——逐项打勾判定系统是否完成
> 4. 跨 session——新 AI 接手时一眼看清系统全貌
>
> **编号规则**：`<门类>-<序号>`，如 `SESS-01`、`MON-A1`、`EXEC-03`。编号稳定，不随文档重组而变。
>
> **状态标记**：`[ ]` 待做 · `[~]` 进行中 · `[x]` 已完成 · `[!]` 已知有问题待修 · `[-]` 决定不做
>
> **来源整合**：AnalysisSystem.md §6/§7 + p27_session_management_and_polish_spec.md §A/§B/§C + p27_monitor_spec.md §2/§3 + p27_monitor_pipe_operations.md §3/§4/§5 + WP-01~WP-10 + 2026-08-19 审计发现的遗漏点。

---

## 门类索引

| 门类代号 | 名称 | 需求点数 | 负责的 WP |
|---|---|---|---|
| ENV | 环境与基础设施 | 6 | WP-01, WP-09 |
| SESS | Session 编号化管理（阶段1） | 12 | WP-01 |
| LAUNCH | Launcher 启动与续传控制 | 10 | WP-01, WP-02 |
| MON-A | Monitor Pipe A 类自动检查 | 12 | WP-02, WP-05 |
| MON-B | Monitor Pipe B 类续传质量检查 | 9 | WP-02, WP-05 |
| MON-C | Monitor Pipe C 类 AI 判断 | 5 | WP-05, WP-07 |
| EXEC | Monitor Exec Devin（阶段2） | 14 | WP-03, WP-04, WP-05 |
| SELF | Monitor Exec Devin self-check | 17 | WP-04, WP-07 |
| CTRL | 控制命令与查看支持 | 9 | WP-01, WP-06 |
| RUN | POC-2.7 运行与监控 | 8 | WP-09 |
| AUDIT | 系统审计 | 7 | WP-10 |
| DOC | 文档同步（阶段3） | 8 | WP-08 |
| HARD | 硬约束（贯穿全程） | 10 | 全部 |

**合计**：13 个门类，127 个需求点。

---

## §ENV · 环境与基础设施

启动系统前的环境确认和基础设施就绪检查。

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| ENV-01 | `ARANGO_DB=xishujuzhen_math_glm52` 环境变量已设置 | AnalysisSystem.md §1/§7 | [ ] | `echo $ARANGO_DB` 输出正确值 |
| ENV-02 | ArangoDB `localhost:8529` 可连接，数据库存在 | AnalysisSystem.md §1 | [ ] | `curl -s http://localhost:8529/_api/database` 返回 200 |
| ENV-03 | Redis 可连接（launcher 依赖 Redis 队列） | AnalysisSystemOps.md | [ ] | `redis-cli ping` 返回 PONG |
| ENV-04 | Git 在 `glm5.2` 分支 | AnalysisSystem.md §1/§7 | [ ] | `git branch --show-current` |
| ENV-05 | Python venv `.venv/` 可用（python3.14） | AnalysisSystem.md §1 | [ ] | `.venv/bin/python3 --version` |
| ENV-06 | 外部工作目录可写：`/Volumes/data/math-agent-glm5.2-tmux-agents-dir/`（Solver）+ `/Volumes/data/p27-monitor-exec/`（Exec Devin） | AnalysisSystem.md §7 | [ ] | `touch` 测试文件写入成功 |

---

## §SESS · Session 编号化管理（阶段1）

阶段1核心——所有 devin cli 实例（Solver/handover/Monitor Exec）的统一编号化管理。地基工作，不做的话后续都无从落地。

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| SESS-01 | `p27_sessions` collection 定义存在 | spec §C.1.1 | [x] | `continuation_db_schema.py` 中有定义 |
| SESS-02 | `p27_session_counter` 文档存在（`_key=session_counter`, `counter=0`） | spec §C.1.1 | [x] | DB 查询确认 |
| SESS-03 | `ensure_schema()` 创建 collection + 5 个索引（seq/session_name/status/batch_id+type/triggered_by_alert） | spec §C.1.1 | [x] | 索引列表确认 |
| SESS-04 | `allocate_seq(db) -> int` 原子递增 seq | spec §C.1.2 | [x] | 并发调用不跳号不重号 |
| SESS-05 | `create_session_record(db, seq, session_name, type, ...)` 创建注册表记录 | spec §C.1.2 | [x] | 记录字段完整 |
| SESS-06 | `update_session_status(db, session_key, status, **fields)` 更新状态 | spec §C.1.2 | [x] | 状态流转正确 |
| SESS-07 | `list_sessions(db, batch_id, status, type)` 查询列表 | spec §C.1.2 | [x] | 过滤条件生效 |
| SESS-08 | `find_orphaned_sessions(db)` + `find_unregistered_sessions(db)` 一致性检查 | spec §C.1.2 | [x] | 能发现注册表/tmux 不一致 |
| SESS-09 | Session 命名格式 `p27-s{seq:04d}-{type}-{run_key_short}-r{round}` | spec §A.2 | [x] | tmux list-sessions 显示正确格式 |
| SESS-10 | `launch_solve()` 和 `start_handover()` 启动前调 `allocate_seq` + `create_session_record` | spec §C.1.2 | [x] | DB 中有对应记录 |
| SESS-11 | 所有 `tmux_kill` 调用前检查注册表状态（done 才能 kill） | spec §C.1.2/§A.5 | [x] | 代码 review |
| SESS-12 | 每轮检查时更新注册表 `tmux_alive` 字段（对比 tmux 实际状态） | spec §C.1.3 | [x] | 字段值与 tmux 实际一致 |

---

## §LAUNCH · Launcher 启动与续传控制

Launcher 的启动逻辑、续传机制、异常处理。

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| LAUNCH-01 | Launcher 启动时从 DB 读 batch.concurrency（不覆盖已有值） | WP-02 commit 7767fa8 | [x] | 重启 launcher 后 DB concurrency 不变 |
| LAUNCH-02 | Launcher 主循环每轮从 DB 动态读 concurrency（运行期可调） | WP-02 commit de38a5e | [x] | 运行中改 DB 后下一轮生效 |
| LAUNCH-03 | rate_limited 分支：从 `tmux_kill` 改为 `update_session_status(stuck)` | spec §A.5/§C.1.3 | [x] | rate_limit 发生时 session 留在 tmux |
| LAUNCH-04 | timeout 分支：从 `tmux_kill` 改为 `update_session_status(stuck)` | spec §A.5/§C.1.3 | [x] | timeout 发生时 session 留在 tmux |
| LAUNCH-05 | stall 分支：从 `tmux_kill` 改为 `update_session_status(stuck)` | spec §A.5/§C.1.3 | [x] | stall 发生时 session 留在 tmux |
| LAUNCH-06 | stuck session 不占并发槽（launcher 继续启动新 run） | spec §A.5 | [x] | stuck 后并发槽可用 |
| LAUNCH-07 | `stop --force` 分类处理：done 可 kill，running/stuck 留给用户 | spec §A.5/§C.1.3 | [x] | stop --force 后 running/stuck 仍在 |
| LAUNCH-08 | `stop --force` 清空 Redis 队列 | spec §A.5 | [x] | Redis pending 为空 |
| LAUNCH-09 | DONE.md 文件检测（不用 pane 文本检测） | spec §A.5 反模式 | [x] | 代码 review |
| LAUNCH-10 | handover session 也有注册表记录（type=handover） | WP-01 | [ ] | DB 中有 type=handover 记录 |

---

## §MON-A · Monitor Pipe A 类自动检查（12 项）

脚本判定的自动检查，Monitor Pipe 的 Python 部分每 120 秒执行。

| 编号 | 检查项 | alert_type | severity | 阈值 | 来源 | 状态 |
|---|---|---|---|---|---|---|
| MON-A1 | session_health | session_health | critical | — | spec §2.1 | [x] |
| MON-A2 | queue_progress (stalled) | queue_stalled | critical | 15 分钟无变化 | spec §2.1 | [x] |
| MON-A3 | queue_progress (no completions) | no_completions | warning | 15 分钟无变化 | spec §2.1 | [x] |
| MON-A4 | rate_limit_detection | rate_limit | critical | ≥3 个 | spec §2.1 | [x] |
| MON-A5 | zombie_sessions | zombie_sessions | warning | ≥2 个 | spec §2.1 | [x] |
| MON-A6 | export_landing | export_missing | critical | 缺失率>10% | spec §2.1 | [x] |
| MON-A7 | failure_rate | failure_rate | warning | >15% | spec §2.1 | [x] |
| MON-A8 | launcher_dead | launcher_dead | critical | — | spec §2.1 | [x] |
| MON-A9 | stall_detection | long_running | warning | 单轮>30 分钟 | spec §2.1 | [x] |
| MON-A10 | session_registry_consistency | session_registry_inconsistency | critical/warning | — | spec §A.7 | [x] |
| MON-A11 | stuck_sessions | stuck_session_accumulated | warning/critical | >5 warning, >10 critical | spec §A.7 | [x] |
| MON-A12 | done_sessions_uncleaned | done_session_uncleaned | info | >20 个 | spec §A.7 | [x] |

**A 类已知问题**（来自 WP-02 / INDEX 当前状态）：

| 编号 | 问题 | 状态 | 修复 WP |
|---|---|---|---|
| MON-A!01 | expected_concurrency 不从 DB 读（用启动参数 5），导致 session_health 误报 | [!] | WP-02 Bug-1 |
| MON-A!02 | alert 的 `_key` 冲突（同轮同类型 timestamp 相同时重复） | [!] | WP-02 Bug-2 |
| MON-A!03 | rounds_log_export_missing 大量出现（根因未诊断） | [!] | WP-02 Bug-3 |
| MON-A!04 | export_missing 大量出现（根因未诊断） | [!] | WP-02 Bug-4 |
| MON-A!05 | 850+ alert 堆积（Monitor Exec Devin 未实现，无自动 resolve） | [!] | WP-05 完成后自愈 |

---

## §MON-B · Monitor Pipe B 类续传质量检查（9 项）

POC-2.7 续传 Pipe 特有的结构化质量检查，脚本判定。

| 编号 | 检查项 | alert_type | severity | 阈值 | 来源 | 状态 |
|---|---|---|---|---|---|---|
| MON-B1 | proof_completeness | proof_missing | critical | — | spec §2.2 | [x] |
| MON-B2 | proof_completeness | proof_no_boxed | warning | — | spec §2.2 | [x] |
| MON-B3 | proof_too_small | proof_too_small | warning | <1KB | spec §2.2 | [x] |
| MON-B4 | handover_completeness | handover_missing | critical | — | spec §2.2 | [x] |
| MON-B5 | handover_completeness | handover_too_small | warning | <500B | spec §2.2 | [x] |
| MON-B6 | truncation_pattern | all_rounds_truncated | warning | 5 轮全截断 | spec §2.2 | [x] |
| MON-B7 | final_status_distribution | status_anomaly | info | — | spec §2.2 | [x] |
| MON-B8 | rounds_log_integrity | rounds_log_* (6 子项) | warning/critical | — | spec §2.2 | [x] |
| MON-B9 | intermediate_product_uniqueness | intermediate_product_collision / work_dir_collision | critical | — | spec §2.2 | [x] |

**B8 子项明细**（rounds_log_integrity 的 6 个子检查）：
- B8a: rounds_log_missing_field（缺必需字段 round/export/truncated/completed/reason）
- B8b: rounds_log_export_missing（export 指向的文件不存在）
- B8c: rounds_log_handover_missing（handover_path 指向的文件不存在，handover_success=True 时）
- B8d: rounds_log_proof_missing（proof_path 指向的文件不存在，completed=True 时）
- B8e: rounds_log_no_proof_path（completed=True 但无 proof_path 字段）
- B8f: rounds_log_duplicate_round（round 编号重复）

---

## §MON-C · Monitor Pipe C 类 AI 判断（5 项）

无法用代码完成，需 AI 判断。阶段2 前由 Master Agent 手动做，阶段2 后由 Monitor Exec Devin 做。

| 编号 | 检查项 | AI 需要检查什么 | 通过标准 | 来源 | 状态 |
|---|---|---|---|---|---|
| MON-C1 | proof_quality | proof.md 的数学正确性——答案对不对、证明逻辑是否完整 | 答案正确且证明逻辑完整 | spec §2.3 | [ ] |
| MON-C2 | proof_hallucination | proof.md 是否有幻觉——编造的定理、不存在的引用、虚假的计算 | 无幻觉 | spec §2.3 | [ ] |
| MON-C3 | answer_leak | proof.md 是否答案泄漏——直接从题目描述抄答案而非推导 | 答案是通过推导得到的 | spec §2.3 | [ ] |
| MON-C4 | handover_quality | HANDOVER.md 是否准确总结上一轮思考——有无遗漏关键结论、有无编造 | 准确总结、无遗漏、无编造 | spec §2.3 | [ ] |
| MON-C5 | continuation_direction | 续传方向是否正确——在上一轮基础上继续还是从头重复 | 在上一轮基础上继续 | spec §2.3 | [ ] |

**C 类执行方式**：
- 阶段2 前：Monitor Pipe Python 部分每 3 轮抽样 2 条，标记 `needs_ai_review=True`，Master Agent 通过查询脚本发现后手动检查
- 阶段2 后：Monitor Exec Devin 读 `needs_ai_review` 标记，做真正的 AI 判断，PASS 的 resolve 标记，FAIL 的写新 alert

---

## §EXEC · Monitor Exec Devin（阶段2）

Monitor Pipe 执行 devin 架构——定时启动 devin cli 做 C 类 AI 检查 + 代码 bug 修复，实现自愈循环。

### §EXEC-CONF · 配置与模板

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| EXEC-01 | `MONITOR_EXEC_CONCURRENCY = 1` 常量 | spec §C.2.1 | [ ] | `continuation_config.py` 中存在 |
| EXEC-02 | `MONITOR_EXEC_INTERVAL = 300` 常量（两轮最小间隔，秒） | spec §C.2.1 | [ ] | 同上 |
| EXEC-03 | `MONITOR_EXEC_EXPORT_BASE = Path("/Volumes/data/p27-monitor-exec")` 常量 | spec §C.2.1 | [ ] | 同上 |
| EXEC-04 | `MONITOR_EXEC_MAX_RUNTIME_SECONDS = 900` 常量（一轮最多 15 分钟） | spec §C.2.1 | [ ] | 同上 |
| EXEC-05 | `templates/monitor_exec_prompt.md` 创建——自包含 SOP prompt | spec §B.5/§C.2.1 | [ ] | Monitor Exec Devin 读完 prompt 就知道该做什么 |
| EXEC-06 | `p27_sessions` 的 type 字段支持 `monitor_exec` 值 | spec §C.2.1 | [ ] | schema 确认或修改 |
| EXEC-07 | `create_session_record` 的 extra 参数可传 `exec_seq` 和 `triggered_by_alert` 字段 | spec §C.2.1 | [ ] | 函数调用成功 |

### §EXEC-LAUNCH · 启动器

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| EXEC-08 | `should_launch_monitor_exec(db, batch_id) -> bool`——无 running 的 monitor_exec + 距上次完成已过 interval | spec §C.2.2 | [ ] | 单元测试 |
| EXEC-09 | `build_monitor_exec_prompt(exec_seq, db) -> str`——读模板 + 替换 `{exec_seq}` + 从上一轮复制 WORKLOG.md | spec §B.5/§C.2.2 | [ ] | prompt 包含正确 exec_seq 和 work_dir |
| EXEC-10 | `launch_monitor_exec(db, batch_id) -> session_name`——分配 seq + 创建 work_dir + 写 prompt + 创建注册表记录 + 启动 devin cli | spec §C.2.2 | [ ] | 注册表有记录 + tmux 有 session |
| EXEC-11 | `check_monitor_exec_completion(db, batch_id) -> list[completed]`——检查 DONE.md 出现 | spec §C.2.2 | [ ] | 完成的 session status 更新为 done |
| EXEC-12 | 复用 `launch_solve` 的 DONE.md 检测机制和 tmux log 机制 | spec §C.2.2 | [ ] | 代码 review |
| EXEC-13 | 超时（`MONITOR_EXEC_MAX_RUNTIME_SECONDS`）标记 stuck，不 kill | spec §B.6/§C.2.2 | [ ] | 超时后 session 留在 tmux |
| EXEC-14 | WORKLOG.md 跨轮跨目录传递——上一轮的 WORKLOG.md 复制到本轮 work_dir | AnalysisSystem.md §6.1/§B.5 | [ ] | 第二轮 work_dir 有上一轮的 WORKLOG 内容 |

### §EXEC-INTEGRATION · Pipe 集成

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| EXEC-15 | `monitor_continuation.py` 主循环每轮 A/B 检查后调 `should_launch_monitor_exec`，True 则 `launch_monitor_exec` | spec §C.2.3 | [ ] | 日志有 `[monitor_exec_start]` |
| EXEC-16 | 每轮调 `check_monitor_exec_completion`，完成的写 `monitor_exec_completed` alert（含 REPORT 路径 + commit hash） | spec §C.2.3 | [ ] | DB 有 alert 记录 |
| EXEC-17 | Monitor Exec Devin 超时标记 stuck + 写 `monitor_exec_timeout` alert | spec §C.2.3 | [ ] | DB 有 alert 记录 |
| EXEC-18 | C 类 `flag_for_ai_review()` 改为只做抽样标记（不再等 Master Agent），标记包含 proof.md/HANDOVER.md 路径 | spec §C.2.3 | [ ] | 标记字段完整 |
| EXEC-19 | `p27_monitor_spec.md` 新增 §4 Monitor Exec Devin 规范 | spec §C.2.3 | [ ] | 文档更新 |
| EXEC-20 | `monitor_check_continuation.sh` 行动清单精简——去掉"AI_REVIEW 需 Master Agent 检查"，改为"有 monitor_exec_completed 时可选读 REPORT" | spec §C.2.3 | [ ] | 脚本输出更新 |

### §EXEC-VIEW · export 与 report 查看

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| EXEC-21 | `monitor_check_continuation.sh` 第 2 项 alerts 中 `monitor_exec_completed` 显示 REPORT 路径 + commit hash + 修复 alert 数 | spec §C.2.4 | [ ] | 脚本输出包含这些信息 |
| EXEC-22 | `continuation_control.py` 新增 `view-exec <session_key>` 命令——展示 REPORT + git log -3 | spec §C.2.4 | [ ] | 命令可用 |

### §EXEC-VERIFY · 阶段2 端到端验证

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| EXEC-23 | 完整流程跑通：检查→判断→修复→报告→退出 | spec §C.2.5 | [ ] | 观察一轮完整运行 |
| EXEC-24 | export 完整保留：conversation.json/DONE.md/MONITOR_EXEC_REPORT.md/WORKLOG.md/tmux.log 5 个文件都存在 | spec §C.2.5 | [ ] | 文件存在性检查 |
| EXEC-25 | prompt 约束生效：不改 AGENTS.md/specs/、不 push 代码 | spec §C.2.5 | [ ] | git diff 确认 |
| EXEC-26 | 防重复启动：running 时不启动新的 | spec §C.2.5 | [ ] | 同时只有一个 monitor_exec running |
| EXEC-27 | C 类 AI 判断真正发生（读 proof.md 做判断，不是只写标记） | spec §C.2.5 | [ ] | REPORT 有判断详情 |
| EXEC-28 | 自愈能力：构造一个代码 bug，Monitor Exec Devin 自己发现并修复 | spec §C.2.5 | [ ] | 下一轮不再报告此 bug |

---

## §SELF · Monitor Exec Devin self-check（17 项）

Monitor Exec Devin 对自己的检查——确保自己的运行正确、不引入新问题。这是新的检查类别，不属于 A/B/C 类。

### §SELF-RUN · 运行完整性（S1-S4）

| 编号 | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|---|---|---|---|
| SELF-S1 | export 完整性 | 检查自己的 conversation.json 是否存在且非空 | 文件存在且>1KB | [ ] |
| SELF-S2 | DONE.md 写入 | 退出前确认 echo 命令正确 | 自动（prompt 中的 exit 命令） | [ ] |
| SELF-S3 | REPORT 完整性 | 检查 MONITOR_EXEC_REPORT.md 包含必需章节 | 包含§检查结果摘要/§C 类 AI 判断详情/§修复操作/§未修复问题 | [ ] |
| SELF-S4 | session 注册 | 检查自己 session 在 p27_sessions 中 | type=monitor_exec 记录存在 | [ ] |

### §SELF-FIX · 修复正确性（S5-S8）

| 编号 | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|---|---|---|---|
| SELF-S5 | py_compile 通过 | 修复代码后运行 `python -m py_compile <修改的文件>` | 无语法错误 | [ ] |
| SELF-S6 | git commit 成功 | 修复后 git add + git commit | commit 成功 | [ ] |
| SELF-S7 | 未修改第二级架构级规范 | `git diff --name-only` | 不包含 AGENTS.md/.devin/rules/*.md/MonitorPipe.md/AnalysisSystemDesign.md §5§6 | [ ] |
| SELF-S8 | git add 规范 | `git diff --cached --name-only` | 只 add 具体路径，无 `git add -A/. /-u` | [ ] |

### §SELF-BEHAVIOR · 行为正确性（S9-S12）

| 编号 | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|---|---|---|---|
| SELF-S9 | 只修本轮发现的问题 | 回顾修复操作 | 无重构/改架构/顺便修其他 | [ ] |
| SELF-S10 | 未 spawn subagent | 回顾工具调用 | 无 run_subagent 调用 | [ ] |
| SELF-S11 | 未 push 代码 | 回顾 git 操作 | 无 git push | [ ] |
| SELF-S12 | C 类判断有依据 | 回顾 C 类判断 | 每个判断都有读了 proof.md/HANDOVER.md 的记录 | [ ] |

### §SELF-LOOP · 循环检测（S13-S14）

| 编号 | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|---|---|---|---|
| SELF-S13 | 是否陷入重复修复 | 读最近 3 轮的 MONITOR_EXEC_REPORT.md | 同一问题没有连续 3 轮修 | [ ] |
| SELF-S14 | 同一 alert 是否反复出现 | 查 DB 中同一 alert_type 的创建历史 | 同一 alert_type 没有在最近 5 轮中反复创建 | [ ] |

### §SELF-DOC · 文档同步（S15-S17）

| 编号 | 检查项 | 检查方法 | 通过标准 | 状态 |
|---|---|---|---|---|
| SELF-S15 | 第一级文档同步 | 改了代码就改了对应文档（同一 commit 中） | git diff 包含对应文档修改 | [ ] |
| SELF-S16 | 第二级规范建议记录 | 涉及第二级规范需更新时 | 在 REPORT 和 WORKLOG 中记录"建议 Master Agent 同步更新 X" | [ ] |
| SELF-S17 | 同步清单完整性 | 对照 §4.5 第一级文档清单 | 该改的都改了 | [ ] |

**第一级文档清单**（Monitor Exec Devin 必须同步修改）：
- `docs/architecture.md` · `docs/operational-concerns.md` · `docs/graceful-shutdown.md` · `docs/dynamic-concurrency.md` · `docs/framework-checklist.md` · `docs/monitor-pipe-pattern.md` · `docs/solver-harness-borrowing.md`
- `AnalysisSystemDesign.md` §4 代码资产索引
- `specs/p27_monitor_spec.md` §2/§3 · `specs/p27_monitor_pipe_operations.md` §3/§4 · `specs/p27_session_management_and_polish_spec.md` §A/§B

**第二级规范清单**（Monitor Exec Devin 不能改，只记录建议）：
- `AGENTS.md` · `.devin/rules/*.md` · `MonitorPipe.md` 三层架构定义/设计原则 · `AnalysisSystemDesign.md` §5 设计原则/§6 关键设计决策

---

## §CTRL · 控制命令与查看支持

`continuation_control.py` 的子命令和查看支持功能。

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| CTRL-01 | `start --batch-id <id> --concurrency <n>` 启动系统 | AnalysisSystem.md §6.2 | [x] | 系统启动 |
| CTRL-02 | `stop`（优雅）/ `stop --force`（分类处理） | spec §A.6 | [x] | running/stuck 保留，done 清理 |
| CTRL-03 | `status --batch-id <id>` 状态查看 | AnalysisSystem.md §3.2 | [x] | 输出 prepared/completed/running 等计数 |
| CTRL-04 | `health --batch-id <id>` 健康检查 | AnalysisSystem.md §6.2 | [x] | 输出健康维度 |
| CTRL-05 | `sessions` 列出所有 session | spec §A.6 | [x] | 输出 session 列表 |
| CTRL-06 | `sessions --status running` / `--type monitor_exec` 过滤 | spec §A.6 | [x] | 过滤生效 |
| CTRL-07 | `sessions --consistency-check` 对比注册表 vs tmux | spec §A.6 | [x] | 能发现不一致 |
| CTRL-08 | `sessions --clean-done` 批量清理 done 的 session | spec §A.6 | [x] | done 的被清理 |
| CTRL-09 | `view-exec <session_key>` 展示 Monitor Exec Devin 的 REPORT + git log -3 | spec §C.2.4 | [ ] | 命令可用 |

---

## §RUN · POC-2.7 运行与监控

POC-2.7 续传系统的实际运行和监控。

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| RUN-01 | 系统以并发 1 稳定运行 | WP-09 | [ ] | 长时间运行无崩溃 |
| RUN-02 | 进度持续推进（completed 数在增长） | WP-09 | [ ] | 监控脚本显示增长 |
| RUN-03 | 失败率≤15%（超过需降并发或检查 rate limit） | WP-09/MON-A7 | [ ] | 失败率统计 |
| RUN-04 | 无新 dead_session 新增（有的需重新入队） | WP-09 | [ ] | dead_session 计数稳定 |
| RUN-05 | proof.md 质量（存在数 vs COMPLETED 数，有 boxed 数 vs 存在数） | WP-09 | [ ] | 质量统计 |
| RUN-06 | 阶段2 集成后：Monitor Exec Devin 自动启动 | WP-09 §4 | [ ] | 日志有 monitor_exec_start |
| RUN-07 | 阶段2 集成后：alert 被自动处理（不再堆积） | WP-09 §4 | [ ] | alert 数量下降 |
| RUN-08 | 所有题 completed 或 failed，通过率≥50% | WP-09/AnalysisSystemDesign.md §7.1 | [ ] | 最终统计 |

---

## §AUDIT · 系统审计

POC-2.7 运行结束后的系统审计。

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| AUDIT-01 | A 类 12 项检查审计（A1-A12） | WP-10 | [ ] | 逐项验证检查结果 |
| AUDIT-02 | B 类 9 项检查审计（B1-B9） | WP-10 | [ ] | 逐项验证检查结果 |
| AUDIT-03 | C 类 5 项 AI 判断审计（C1-C5） | WP-10 | [ ] | 逐项验证判断结果 |
| AUDIT-04 | 循环完整性审计（三个推动关系是否都成立） | WP-10 | [ ] | Grove 核心循环检查 |
| AUDIT-05 | 数据完整性审计（tree_nodes/tree_edges/ai_instances/problems） | WP-10 | [ ] | DB 完整性验证 |
| AUDIT-06 | 通过率判定（COMPLETED/total ≥50%） | WP-10 | [ ] | 最终统计 |
| AUDIT-07 | 审计报告产出（含结论或改进建议） | WP-10 | [ ] | 报告文件存在 |

---

## §DOC · 文档同步（阶段3）

阶段1 和阶段2 都完成并验证后的文档同步更新。

| 编号 | 需求点 | 来源 | 状态 | 验证方法 |
|---|---|---|---|---|
| DOC-01 | `AnalysisSystemDesign.md` §2 文档体系加入 p27_session_management_and_polish_spec.md | spec §C.3 | [ ] | 文档索引更新 |
| DOC-02 | `AnalysisSystemDesign.md` §5 设计原则更新——Monitor Pipe 执行层包含 Python+devin cli 两部分 | spec §C.3 | [ ] | 设计原则更新 |
| DOC-03 | `AnalysisSystemDesign.md` §4 代码资产索引加入 session_registry.py/monitor_exec_launcher.py/templates/monitor_exec_prompt.md | spec §C.3 | [ ] | 索引更新 |
| DOC-04 | `MonitorPipe.md` §2.2 修正——去掉"Monitor Pipe 不是 devin cli 实例"的错误澄清，改为执行层两层架构定义 | spec §C.3 | [ ] | 架构定义修正 |
| DOC-05 | `MonitorPipe.md` 新增 Monitor Exec Devin 工作循环说明 | spec §C.3 | [ ] | 新增章节 |
| DOC-06 | `AGENTS.md` POC-2.7 章节更新——加入 session 管理和 Monitor Exec Devin 简要说明 | spec §C.3 | [ ] | 章节更新 |
| DOC-07 | `docs/architecture.md` 加入 session 注册表和 Monitor Exec Devin 架构 | spec §C.3 | [ ] | 架构文档更新 |
| DOC-08 | `docs/framework-checklist.md` 加入 session 管理和 Monitor Exec Devin 检查项 | spec §C.3 | [ ] | 检查清单更新 |

---

## §HARD · 硬约束（贯穿全程）

从 AnalysisSystem.md §7 提取的最重要的硬约束，所有 WP 都必须遵守。

| 编号 | 硬约束 | 来源 | 验证方法 |
|---|---|---|---|
| HARD-01 | 启动任何连 ArangoDB 的脚本前，确认 `ARANGO_DB=xishujuzhen_math_glm52` | §7-1 | `echo $ARANGO_DB` |
| HARD-02 | 只在 `glm5.2` 分支工作；显式路径 add；改前 clean+改后立即 commit；push 需用户授权 | §7-2 | git status/review |
| HARD-03 | Solver 的 devin cli 必须在外部目录运行（`/Volumes/data/math-agent-glm5.2-tmux-agents-dir/`），不能在本 repo 内 | §7-3 | work_dir 路径检查 |
| HARD-04 | 生产实验运行解题 AI 用 `noninteractive-solver-run` skill（`devin -p --prompt-file ... --export ...`） | §7-4 | 启动命令检查 |
| HARD-05 | Monitor Pipe 执行 devin 的 cwd 在外部目录（`/Volumes/data/p27-monitor-exec/{exec_seq}/`） | §7-5 | work_dir 路径检查 |
| HARD-06 | 绝不 kill 无 DONE.md 的 session——rate_limited/timeout/stall 标记 stuck 不 kill | §7-6 | 代码 review |
| HARD-07 | 长时间命令用 tmux，不用 nohup/background | §7-7 | 启动方式检查 |
| HARD-08 | 禁止 inline 脚本——超过 3 行的逻辑写成文件 | §7-8 | 代码 review |
| HARD-09 | 人话铁律——所有文档/回复/注释/commit message 用人话写 | §7-9 | 文档 review |
| HARD-10 | 给选项必含利弊+推荐+推荐理由 | §7-10 | 文档 review |

---

## §DECISION · 待决策问题

以下问题规范暂不决定，留待实施时由用户确认（来自 spec §G）。

| 编号 | 待决策问题 | 当前默认 | 需要决策的时机 |
|---|---|---|---|
| DEC-01 | Monitor Exec Devin 的 model | 与 Solver 相同（glm-5-2-high） | WP-04 实施时 |
| DEC-02 | Monitor Exec Devin 的 permission_mode | dangerous（需 exec+git） | WP-04 实施时 |
| DEC-03 | stuck session 自动清理阈值 | >5 warning, >10 critical | WP-09 运行中调整 |
| DEC-04 | Monitor Exec Devin 能否修改 docs/ 下的模块文档 | 允许（code-doc-sync rule 要求） | WP-07 验证时观察 |
| DEC-05 | Monitor Exec Devin 的修复是否自动触发系统重启 | 不自动重启（只 commit，REPORT 中建议） | WP-07 验证时观察 |
| DEC-06 | Monitor Exec Devin 的启动间隔 | 300 秒（5 分钟） | WP-09 运行中调整 |
| DEC-07 | 自愈循环的 escalation 机制（连续多轮修不好同一问题何时 escalate） | 未定义 | WP-07 验证后定义 |

---

## 使用说明

### 开发前
1. 通读本 CheckList，确认对系统全貌有认识
2. 对照要做的 WP，找到相关的门类，确认需求点编号
3. 把要做的需求点编号写进 WP 的任务清单引用

### 开发中
1. 每完成一个需求点，更新本文件的状态标记（`[ ]` → `[x]`）
2. commit message 中引用需求点编号（如 `实现 EXEC-10 launch_monitor_exec`）
3. 发现新需求点时，追加到对应门类（编号续接，不重排）

### 验收时
1. 逐门类逐项检查状态标记
2. `[!]` 标记的问题必须有对应 WP 或 commit 说明
3. `[-]` 标记的必须有决策记录说明为什么不做

### 跨 session
1. 新 AI 接手时读本文件 = 一眼看清系统全貌
2. 状态标记反映当前进度，不需要读 git log 倒推

---

## 维护规则

本文件是活文件——系统需求变化时必须同步更新。以下定义"什么变了要更新什么"。

### 规则1：系统需求发生变化时

**触发条件**：新增功能需求、修改功能定义、删除功能、阈值调整、通过标准变化。

**更新内容**：

| 变化类型 | 本文件的更新 | 同步更新的文件 |
|---|---|---|
| 新增需求点 | 对应门类追加新行，编号续接（不重排） | 对应的 spec/docs/WP |
| 修改需求点定义 | 更新对应行的描述 | 权威来源 spec（见下方"check points 变化"规则） |
| 删除需求点 | 标记 `[-]`，不删除行（保留历史） | 对应的 spec/docs |
| 需求点完成 | 状态 `[ ]`→`[x]` | 不需要同步（状态是本文件独有） |
| 发现需求点有问题 | 状态 `[ ]`→`[!]`，加说明 | 对应的 WP（记录 bug） |

**编号规则**：编号稳定，不随文档重组而变。新增续接（如 MON-A 已有 A12，新增为 A13）。删除标记 `[-]` 不回收编号。

### 规则2：Monitor Pipe 的 AI（Exec Devin）应该检查的 check points 发生变化时

**这是最常见的变化场景**——check points 的信息散落在多个文件中，变更必须同步整条链条，否则 Exec Devin 读到的认知资产就是过时的。

**check points 信息的分布**：

| 文件 | 节 | 角色 |
|---|---|---|
| `p27_monitor_spec.md` | §2（分类表）+ §3（详细标准） | **权威来源**——check points 定义从这里出发 |
| `p27_monitor_pipe_operations.md` | §3（A/B/C 速查表） | Exec Devin 读的速查版 |
| `p27_monitor_pipe_operations.md` | §3.1.1（A 类已知问题） | 已知问题专表 |
| `p27_monitor_pipe_operations.md` | §4（self-check S1-S17） | self-check 定义 |
| `p27_session_management_and_polish_spec.md` | §A.7（A10/A11/A12） | session 相关检查的权威来源 |
| `CheckList.md` | MON-A/B/C/SELF 门类 | 需求点清单视角（编号+状态） |
| `CheckList-ExecDevin.md` | MON-A/B/C/SELF 门类 | Exec Devin 必读视角（编号+状态+已知问题速查） |

**更新链条**（按顺序执行）：

```
第1步：源头更新（check points 的权威来源）
  │
  ├── A/B/C 类变化 → p27_monitor_spec.md §2（分类表）+ §3（详细标准）
  ├── A10/A11/A12 变化 → p27_session_management_and_polish_spec.md §A.7
  └── S 类变化 → p27_monitor_pipe_operations.md §4（self-check 表）
  │
  ▼
第2步：速查表同步（Exec Devin 读的版本）
  │
  └── p27_monitor_pipe_operations.md §3（A/B/C 速查表）——从 spec 同步
  │
  ▼
第3步：CheckList 同步（需求点清单视角）
  │
  ├── CheckList.md 对应门类（MON-A/MON-B/MON-C/SELF）——更新定义和状态
  └── CheckList-ExecDevin.md 子集——如果变化的 check point 在子集范围内
  │
  ▼
第4步：已知问题特殊处理（如涉及）
  │
  ├── 新增已知问题 → p27_monitor_pipe_operations.md §3.1.1 + CheckList.md MON-A!XX + CheckList-ExecDevin.md 速查
  └── 已知问题修复 → 状态 [!]→[x]，从 §3.1.1 当前问题区移到"已修复"记录
  │
  ▼
第5步：迭代记录
  │
  └── p27_monitor_pipe_operations.md §6 加版本号+日期+修改内容摘要
```

**变化类型与更新对照**：

| 变化类型 | 第1步 | 第2步 | 第3步 | 第4步 | 第5步 |
|---|---|---|---|---|---|
| 新增检查项（如 A13） | spec §2/§3 加行 | operations §3 加行 | CheckList 加行 | — | 加 v 记录 |
| 修改阈值（如 A11 >5 改 >3） | spec §3 改 | operations §3 改 | CheckList 改 | — | 加 v 记录 |
| 删除检查项 | spec §2/§3 标记删除 | operations §3 删行 | CheckList 标记 `[-]` | — | 加 v 记录 |
| 新增已知问题 | — | — | CheckList 加 `[!]` 行 | operations §3.1.1 加行 + ExecDevin 速查加行 | 加 v 记录 |
| 已知问题被修复 | — | — | CheckList `[!]`→`[x]` | operations §3.1.1 移到已修复 + ExecDevin 速查更新 | 加 v 记录 |
| 新增 self-check（如 S18） | operations §4 加行 | — | CheckList SELF 加行 | — | 加 v 记录 |

### 规则3：谁负责更新

**CheckList 内容的两层性质**：

| 内容 | 性质 | Exec Devin 能不能改 | Master Agent/开发者能不能改 |
|---|---|---|---|
| 需求点**定义**（检查项是什么、阈值是多少、通过标准） | **第二级**（架构级——定义系统应该检查什么） | **不能**——在 REPORT 中建议，Master Agent 决定 | 能 |
| 需求点**状态标记**（`[ ]`/`[x]`/`[!]`/`[-]`） | **第一级**（事实性——反映代码/系统实际状态） | **能**——SELF-S15 第一级文档同步的一部分 | 能 |
| 已知问题**条目**（MON-A!XX 的存在和内容） | **第一级**（事实性——反映已知的未修复问题） | **能**——发现问题就记录，修复了就更新状态 | 能 |

**分工**：

| 场景 | 谁做 | 做什么 |
|---|---|---|
| Master Agent/开发者主动变更检查项 | Master Agent/开发者 | 执行第1-5步全部链条 |
| Exec Devin 修复了已知问题 | Exec Devin | 更新状态 `[!]`→`[x]`（第3步）+ 移到已修复（第4步）+ 加 v 记录（第5步）——这是第一级文档同步 |
| Exec Devin 发现需要新增/修改检查项 | Exec Devin | **不自己改**——在 REPORT 和 WORKLOG 中建议，Master Agent 决定后执行链条 |
| Exec Devin 发现新的已知问题 | Exec Devin | 在 REPORT 中记录 + 更新 CheckList 状态 `[ ]`→`[!]` + 建议加入 §3.1.1（Master Agent 确认后加入） |

### 规则4：不更新的情况

- **单个 bug 修复**（不涉及检查项定义变化）→ 不需要更新 CheckList，只更新状态标记（如果该需求点状态变了）
- **代码内部重构**（不改变对外行为）→ 不需要更新 CheckList
- **阈值微调**（如 A11 从 >5 改为 >6，属于运行中调参）→ 只更新 spec §3 + CheckList 对应行，不需要加 v 记录（v 记录留给有架构影响的变更）

---

## 版本记录

- **v1 · 2026-08-19** · 初始版本——13 门类 127 需求点。整合自 AnalysisSystem.md §6/§7 + p27 三个 spec + WP-01~WP-10 + 2026-08-19 审计发现的遗漏点。
- **v1.1 · 2026-08-19** · 新增"维护规则"节（规则1-4）——定义系统需求变化时和 check points 变化时的更新链条、谁负责更新、不更新的情况。
