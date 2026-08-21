# SYSTEM_CLOSURE — 系统级认知闭包（每次SOP执行前注入）

> 这是每次 SOP 执行前**前置注入**的系统级认知闭包。它告诉你"整个系统正常工作时
> 是怎样的"，让你在任何步骤、任何 Gate 触发时都能推理"系统现在工作得对不对"。
> 各步骤 SOP（L1）只补充该步骤特有的增量知识——系统级知识全在这里，不重复。
> Gate 论证依据（L2）引用本闭包的 §3 生命周期 / §6 判定框架。

---

## 1. 系统使命

对失败的数学题启动续传解题管线——通过多轮 handover→solve 循环，让 devin cli
接力解题，直至题目解出、AI 放弃、或达到最大轮次（默认5轮）。

一句话：**续传解题，判定截断 vs 思维错误**。截断=token不够（续传能救）；思维错误=
方向出错（续传救不了）。每道题是一条管线，管线内部顺序调用 devin cli（handover
和 solve 不会同时跑），故**系统并发数 = 同时在跑的管线条数 = devin cli 实例数上限**。
详见 `docs/architecture/solve-pipeline.md` 和 AGENTS.md"核心概念"段。

## 2. 续传解题管线架构 + 数据流

```
continuation_collector → continuation_feeder → continuation_launcher → continuation_result_collector
   收集失败题入DB          入Redis队列         并发启动devin cli解题       汇总最终结果
                                               ↑ 并发解题                    ↑ 结果
                         monitor_continuation（监控Pipe，每120s检查写alert到DB）
                         session_registry（session编号化管理）
                         step_gate（步进门闸，13个语义动作可hold/step）
                         observability（行为流水黑匣子，log/flow/）

=== Pipe 5 审计 Pipe（dev-docs/029）===
proof_audit_collector → proof_audit_launcher → proof_audit_result_collector
  收集completed题入审计队列  并发启动devin cli审计   解析审计结果更新DB
                             ↑ 并发审计               ↑ audit_passed=True/False
  审计AI不受防作弊约束，严格审计解题AI的数学正确性+作弊检测
  审计通过=进入选题池；审计失败=排除或重做（FAIL_INCOMPLETE→prepared）
```

支撑模块（不在主管线上但被各模块依赖）：
- `continuation_config` — 全局配置常量（DB集合名/Redis key/模型/路径/门闸ID/判定阈值）
- `continuation_db_schema` — DB连接+集合管理+AQL封装
- `continuation_redis_queue` — Redis队列操作（pending/running/原子转移）
- `proof_audit_config` — 审计Pipe配置常量（集合名/Redis key/门闸ID/审计结果枚举）
- `proof_audit_db_schema` — 审计Pipe DB集合管理（p27_proof_audit_runs/p27_proof_audits）
- `proof_audit_redis_queue` — 审计Pipe Redis队列操作（paudit:前缀）

数据流：collector 把失败题入 DB(prepared) → continuation_feeder 入 Redis pending →
launcher 并发 dequeue 启动 devin cli → result_collector 汇总。本系统只有这一条
管线（Pipe 1/2/3 分析/审计/选题已删除）。

## 3. 一道题的完整生命周期（正常工作模式）

```
prepared（DB，等入队）
  ↓ feeder feed_enqueue（priority=0，NX幂等）
pending（Redis ZSET）
  ↓ launcher dequeue_pending（zpopmin，取最低score）
running（DB+Redis，占并发槽）
  ↓ launch_solve 启动 devin cli（tmux session）
  ↓ devin 跑完，写 export + DONE.md
  ↓ launcher judge：
     ├─ is_completed（proof有boxed+mtime本轮）→ finalize_run_completed → COMPLETED（终态）
     ├─ is_truncated（comp≥24000+rc>1000+msg=0）+ round<max → requeue_truncated → 回pending
     ├─ round==max → TRUNCATED_AT_MAX（终态）
     └─ 既非完成也非截断 → dead_session → FAILED（终态）
```

**正常生命周期**：prepared → pending → running → [截断→重入队→再running]循环
（最多 max_rounds 轮）→ COMPLETED 或 TRUNCATED_AT_MAX 或 FAILED。

**round-1 是 seed 预检轮**：launcher 首次取件时对 seed export 重判截断/完成，补录
rounds_log 条目。R2 起才是真正的续传轮（有 prompt/handover/proof）。正常轮序 [1,2,3..]
连续；出现重复轮号(如[2,2,3])=旧数据或 bug 复发。

## 4. 各模块职责

| 模块 | 职责 | 异常时的表现 |
|---|---|---|
| continuation_collector | 收集失败题入 DB（prepared 状态） | 题目未入 DB=管线无输入 |
| continuation_feeder | 把 prepared 入 Redis pending（NX幂等） | 死循环重喂（016：队列永远清不空） |
| continuation_launcher | 并发引擎：dequeue→launch→judge→requeue/done | 失控循环（016：同题高频启动） |
| continuation_result_collector | 收集终态 run 的产出，proof 入库双写 | 结果未归档=数据丢失风险 |
| continuation_config | 全局配置常量（DB集合名/Redis key/模型/路径/门闸ID） | 配置漂移=各模块引用不一致 |
| continuation_db_schema | DB连接+集合管理+AQL封装 | 连接失败=全系统不可用 |
| continuation_redis_queue | Redis队列操作（pending/running/原子转移） | 队列原子性破坏=重复启动 |
| monitor_continuation | 每120s检查写 alert（A类自动/B类质量） | 不写alert=检查失效 |
| session_registry | session 编号化管理（p27-s{seq}） | 注册表脱节（A13：tmux vs DB vs Redis） |
| step_gate | 13个语义动作可hold/step（9续传+4审计，DB信号单步跟踪） | — |
| observability | 行为流水黑匣子（log/flow/flow-*.jsonl） | 无记录=看不见流动（016根因） |
| **proof_audit_collector** | 收集completed题入审计队列（p27_proof_audit_runs） | completed题未入审计=选题池准入失效 |
| **proof_audit_launcher** | 并发启动devin cli审计proof.md（门闸GATE-AUDIT-LAUNCH/KILL）；优雅停止（SIGINT，should_stop）+收尾即收集（completed判定后立即collect_one入库，三条退出路径统一兜底收集） | 审计失控=API配额浪费 |
| **proof_audit_result_collector** | 解析审计XML，写audit_passed，更新选题池准入（门闸GATE-AUDIT-FINALIZE-PASS/FAIL） | 审计结果未归档=选题池无准入门槛 |

## 5. 数据产出全景

每道题每轮产生：conversation.json（export，devin的thinking）/ proof.md（解题产出，
含boxed）/ round{N}_HANDOVER.md（交接文档）/ round{N}_conversation_map.md（面包屑地图）
/ round{N}_prompt.txt / DONE.md（退出标记）/ tmux.log

DB 集合：p27_continuation_runs（每题续传记录，含rounds_log/status/final_status/audit_status/audit_passed）/
p27_continuation_events（事件流）/ p27_continuation_results（最终结果，含proof文本双写）/
p27_sessions（session注册表）/ p27_step_gates（门闸状态，13个门闸）/ p27_monitor_alerts（alert，含审计6种alert_type）/
p27_continuation_batches（批次记录，存concurrency等批次级配置）/
p27_proof_audit_runs（审计run记录）/ p27_proof_audits（审计结果，含check_results/cheating_analysis/proof_text备份）

> **完整 DB schema 文档**：`/Users/user/database/AI-Math-Competition-Problem-Solving-System.md`（全局rule database-schema-doc 要求）

rounds_log 每条=5基础字段（round/export/truncated/completed/reason）+R2起补
method/handover_success + 6个路径字段（export/prompt_path/proof_path/handover_path/
map_path/prev_export）。round-1 只有5基础字段。

**p27_sessions 文档字段**（session_registry.py:148-178，SOP_02 2c 检查依据）：
`_key`(p27-s{seq}) / `seq`(全局序号，unique) / `session_name`(tmux名，unique) /
`type`(solve/handover/monitor_exec) / `batch_id` / `started_at`/`started_at_ts` /
`done_md`(bool)/`done_md_at` / `export_path`/`work_dir`/`tmux_log_path`/`report_path`/
`worklog_path`/`prev_worklog_path` / `status`(running/done/stuck/cleaned) /
`tmux_alive`(bool) / `pid`/`exit_code` / `notes` /
可选：`run_key`/`round`(solve/handover) / `exec_seq`/`triggered_by_alert`(monitor_exec)
> session_counter 文档（_key=p27_session_counter）存 counter 字段（原子递增分配 seq）。

**p27_monitor_alerts 文档字段**（monitor_continuation.py:98-179，SOP_03 分诊依据）：
`_key`(p27-alert-{type}-{hash10}，确定性hash=sha1(type+summary)[:10]，2026-08-21去重修复) /
`alert_type`(34种，见§6清单) / `severity`(critical/warning/info) /
`details`({summary,...}) / `status`(new/resolved) /
`created_at`/`first_seen_at`(=created_at)/`last_seen_at`(最近检测时间) /
`occurrence_count`(同状态重复检测累加) / `resolved_at` /
可选：`reopened`(bool，resolved后状态回归重开) / `resolution_note`(批量resolve时写)
> alert 生命周期（2026-08-21去重修复）：留库不删；同type+summary未resolve只保留一条，
> 重复检测只刷occurrence_count/last_seen_at；resolve后状态回归→reopen同文档（key不变）。

**Redis 队列 key 结构**（continuation_config.py:115-129）：
- v2 方案（当前使用）：`p27:pending_handover`/`p27:pending_solve`（ZSET，score=优先级）/
  `p27:running_handover`/`p27:running_solve`/`p27:completed_handover`/`p27:completed_solve`/
  `p27:failed_handover`/`p27:failed_solve`/`p27:stats`(hash)
- v1 方案（备用）：`p27:pending`/`p27:running`/`p27:completed`/`p27:failed`
> feeder 入队用 NX 模式（016 P0-3：已存在不覆盖 score），priority=0 最高；
> 截断/防抖重入队 priority=round_num 或 9999（排队尾）。

**关键配置参数**（continuation_config.py，SOP_01/05 判断依据）：
| 参数 | 值 | 含义 |
|---|---|---|
| `DEFAULT_CONCURRENCY` | 5 | 默认并发数（可被 DB batch 记录覆盖） |
| `DEFAULT_MAX_RUNTIME_SECONDS` | 1800 | 单轮最大运行时间（30分钟） |
| `DEFAULT_STALL_SECONDS` | 600 | 无活动判定 stall 阈值（10分钟） |
| `DEFAULT_POLL_SECONDS` | 15 | launcher 轮询间隔 |
| `DEFAULT_MAX_ROUNDS` | 5 | 最多续传轮次 |
| `HANDOVER_TIMEOUT_SECONDS` | 600 | handover devin cli 超时（10分钟） |
| `TRUNC_COMP_TOKENS_MIN` | 24000 | completion_tokens≥此值判定截断 |
| `DEVIN_MODEL` | glm-5-2 | devin cli 模型（必须显式指定） |
| `SIM_MODE` | env=1 开启 | 全流程模拟开关（生产绝不设） |

**门闸 ID 全清单**（13个，step_gate.py + continuation_launcher.py + continuation_feeder.py + proof_audit_launcher.py + proof_audit_result_collector.py）：
| gate_id | 模块 | 动作 |
|---|---|---|
| `GATE-FEED-ENQUEUE` | feeder | 初次入队（priority=0，NX模式） |
| `GATE-REMOVE-OLD-PROOF` | launcher | 删旧 proof.md（新一轮清场） |
| `GATE-START-HANDOVER` | launcher | 启动 handover devin cli |
| `GATE-LAUNCH-SOLVE` | launcher | 启动解题 devin cli（最重动作） |
| `GATE-REQUEUE-SKIP` | launcher | 防抖拦截后低优先级重入队（9999） |
| `GATE-OVERWRITE-ROUND1-SEED` | launcher | 覆盖 round1_export.json |
| `GATE-KILL-SESSION` | launcher | kill tmux session（不可逆） |
| `GATE-REQUEUE-TRUNCATED` | launcher | 截断轮低优先级重入队（多轮续传核心流转） |
| `GATE-FINALIZE-RUN-COMPLETED` | launcher | 写整题终态 COMPLETED（几乎不可逆） |
| `GATE-AUDIT-LAUNCH` | proof_audit_launcher | 启动审计 devin cli（dev-docs/029） |
| `GATE-AUDIT-KILL-SESSION` | proof_audit_launcher | kill 审计 session（不可逆） |
| `GATE-AUDIT-FINALIZE-PASS` | proof_audit_result_collector | 写 audit_passed=True（进入选题池） |
| `GATE-AUDIT-FINALIZE-FAIL` | proof_audit_result_collector | 写 audit_passed=False + 改 status |
> 操作：`python -m src.step_gate --hold GATE-ID` / `--step GATE-ID --reason '...'` / `--auto GATE-ID`

**HANDOFF 8章节合格标准**（HANDOVER.md，续传规范文档.md §2.1——SOP_04 C4判断依据）：
1.题目 / 2.答案猜想(含置信度) / 3.已确认的结论(独立数学事实+推导概要) /
4.已尝试的方向(✅/❌/⚠️+失败原因，避免下个AI走死胡同) / 5.关键文献(URL+定理内容) /
6.已有中间产物(无则明确说"没写出任何脚本") / 7.当前卡在哪(做什么时被截断+为什么困难) /
8.建议的下一步(具体可执行步骤，非"继续思考")
> C4判断：HANDOVER缺章节/结论无推导/方向无结果/下一步不具体=不合格。

**Session编号化管理12需求点**（SESS-01~12，详见p27_session_management_and_polish_spec.md §A）：
session注册(p27-s{seq})/查询/清理/一致性检查/状态流转(stuck/done)/注册表vs tmux对账。
SOP_01的SESS深度检查覆盖这12点——注册表脱节(A10/A13)是重点。

## 6. 正常工作判定框架（时刻推理用这个）

**正常工作的四个特征**（任何时候都该满足）：
1. **进度推进**：completed/failed 在增加，pending 在减少（不无限堆积）
2. **无失控循环**：行为流水 `observability --stats` 的 churn_suspects 为空
   （同题1小时启动<5次）
3. **四源一致**：tmux实际进程数 ≈ DB running数 ≈ Redis running数 ≈ batch设定concurrency
   （A13审计）
4. **数据完整**：每轮 export/proof/handover 都落盘，rounds_log 字段齐全

**各阶段正常状态**：
- prepared：不该无限堆积（feeder该入队）；prepared>0但pending=0=feeder没工作（critical）
- running：不超concurrency；每个running有对应tmux session和DB记录
- 截断重入队：判定有据（comp≥24000+rc>1000+msg=0）；score=round_num排队尾
  （NX不被feeder重置）
- completed：proof有boxed+mtime本轮；proof文本已入库（双写）；audit_passed决定是否进入选题池

**审计 Pipe 正常状态**（dev-docs/029，SOP_01 A15-A18检查）：
- paudit:pending：不该无限堆积（collector该入队后launcher该dequeue）
- paudit:running：不超concurrency；每个running有对应tmux session
- p27_proof_audits：审计完成后持续增长；失败率<20%
- GATE-AUDIT-* 门闸：auto模式静默通过；hold模式时SOP_01会提醒Y在等

**Monitor A类检查14项的正常标准**（monitor_continuation每120s自动执行，alert写DB p27_monitor_alerts）：
- A1 session_health: session数≈DB running≈设定并发（不匹配=launcher挂/孤儿）
- A2 queue_stalled: pending在减少（15分钟无变化=critical）
- A3 no_completions: completed在增加（15分钟无增加=warning）
- A4 rate_limit: rate_limited<3个（≥3=critical）
- A5 zombie_sessions: 无空pane僵尸session（≥2=warning）
- A6 export_landing: completed的run都有export（缺失>10%=critical）
- A7 failure_rate: 失败率<15%（>15%=warning）
- A8 launcher_dead: launcher活着（消失但有任务=critical）
- A9 stall_detection: 单轮<30分钟（超时=warning）
- A10 session_registry: 注册表≈tmux实际（不一致=critical/warning）
- A11 stuck_sessions: stuck<5（>5=warning，>10=critical）
- A12 done_uncleaned: done未清理<20（>20=info）
- A13 real_concurrency: 四源一致（见上方特征3，任何不一致=critical，016新增）
- A14 launch_churn: churn_suspects为空（同题1小时≥5次=critical，016新增）
> 时刻推理：拿到检查输出后逐项对照——哪项偏离正常标准=那个维度有问题。
> 全景视图（`system_panorama`，023方案）把行为流水组织成4层过程叙事
> （L1现状/L2流畅性/L3流程合规/L4趋势），是"从过程视角推理系统运行"的数据源——
> SOP_01每轮自动输出，在认知闭包背景下阅读做分析推理（不是逐项打勾）。

**alert_type 完整清单**（SOP_03 分类依据——代码中实际产生的 alert_type 字符串，共34种）：

> ⚠️ **alert生命周期（2026-08-21去重修复）**：alert留库不删（痕迹保留）；同 type+summary
> 且未resolve只保留一条（`_key`=hash，重复检测只刷 occurrence_count/last_seen_at，
> 不再每轮膨胀——修复前1788个stuck残留一夜灌5.8万条）；处理后 status→resolved，
> 查询都过滤 resolved。持续未处理的条件=一条持续计权的未resolve alert（正常状态）。

> ⚠️ 命名映射：A9 检查项名 `stall_detection`，但代码 alert_type=`long_running`；
> B6 检查项名 `truncation_pattern`，但代码 alert_type=`all_rounds_truncated`；
> B8 检查项名 `rounds_log_integrity`，但代码产生 6 个细分 alert_type（见下表）。
> SOP_03 分类时以**alert_type 字符串**为准，不是检查项名。
> B类编号以 `p27_monitor_spec.md` §2.2 为准（=checklist MON-B1~B9）。

| alert_type 字符串 | 对应检查项 | severity | 分类 | 处理方式 |
|---|---|---|---|---|
| `session_health` | A1 | critical/warning | 代码bug或配置 | 查launcher并发配置 |
| `queue_stalled` | A2 | critical | 需判断 | 查launcher是否在dequeue |
| `no_completions` | A3 | warning | 需判断 | 查completed是否在增加 |
| `rate_limit` | A4 | critical/warning | 基础设施 | 等恢复，不修 |
| `zombie_sessions` | A5 | warning | 需清理 | kill空session |
| `export_missing` | A6 | critical | 代码bug | 查launcher的export路径逻辑 |
| `export_missing_rate` | A6 | critical | 代码bug | export缺失率>10% |
| `failure_rate` | A7 | warning | 需判断 | 查failure_breakdown |
| `launcher_dead` | A8 | critical | 基础设施 | 重启launcher |
| `long_running` | A9（stall_detection） | warning | 需判断 | 查具体原因（单轮超30分钟） |
| `session_registry_inconsistency` | A10 | critical/warning | 代码bug或数据 | 查注册表vs tmux不一致 |
| `stuck_session_accumulated` | A11 | critical/warning | 需清理 | 判断是否需清理 |
| `done_session_uncleaned` | A12 | info | 需清理 | 清理done session |
| `real_concurrency_mismatch` | A13 | critical | 代码bug或基础设施 | 查四源差异+observability，清理孤儿（016新增） |
| `real_concurrency_exceeded` | A13 | critical | 代码bug或基础设施 | 实际并发>设定 |
| `launch_churn` | A14 | critical | 代码bug | **立即按016报告§5**：kill launcher→清空Redis队列→查根因（016新增） |
| `proof_missing` | B1 | critical | 数据问题 | 判断是模型能力还是代码bug |
| `proof_too_small` | B3 | warning | 数据问题 | 记录 |
| `proof_no_boxed` | B2 | warning | 数据问题 | proof存在但无boxed答案 |
| `handover_missing` | B4 | critical | 数据问题 | 判断handover devin是否失败 |
| `handover_too_small` | B5 | warning | 数据问题 | 记录 |
| `all_rounds_truncated` | B6（truncation_pattern） | warning | 需判断 | 5轮全截断→可能token不够 |
| `status_anomaly` | B7（final_status_distribution） | info | 需判断 | 分析具体异常 |
| `rounds_log_duplicate_round` | B8 | critical | 代码bug | 重复轮号=旧数据或bug复发 |
| `rounds_log_missing_field` | B8 | warning | 代码bug | 查make_round_log_entry |
| `rounds_log_export_missing` | B8 | critical | 代码bug | rounds_log中export字段指向文件不存在 |
| `rounds_log_handover_missing` | B8 | critical | 代码bug | rounds_log中handover_path指向文件不存在 |
| `rounds_log_proof_missing` | B8 | critical | 代码bug | rounds_log中proof_path指向文件不存在 |
| `rounds_log_no_proof_path` | B8 | warning | 代码bug | rounds_log中proof_path字段为空 |
| `intermediate_product_collision` | B9 | critical | 代码bug | 中间产物路径重复，查路径生成逻辑 |
| `work_dir_collision` | B9 | critical | 代码bug | work_dir路径重复 |
| `redis_connection` | 基础设施 | critical | 基础设施 | Redis不可达，等恢复 |
| `flow_ledger_unavailable` | 基础设施 | warning | 基础设施 | 行为流水DB不可达 |
| `ai_review_sample` | C类抽样 | info | 需AI判断 | 抽样标记needs_ai_review，SOP_04处理 |
| `audit_queue_stalled` | 审计Pipe | critical | 需判断 | paudit:pending 15分钟无变化（dev-docs/029） |
| `audit_completion_slow` | 审计Pipe | warning | 需判断 | 审计完成慢，可能需加并发 |
| `audit_failure_rate_high` | 审计Pipe | warning | 需判断 | 审计失败率>20%，检查AGENTS.md模板 |
| `cheating_detected` | 审计Pipe | critical | 数据问题 | FAIL_CHEATING的题需人工复查 |
| `audit_parse_error` | 审计Pipe | warning | 需判断 | 审计AI无法解析proof，人工处理 |
| `audit_gate_waiting` | 审计Pipe | info | 需AI判断 | 审计门闸在等放行，Master Agent查看--pending |

**异常信号**（看到就警觉）：
- 016失控循环：churn_suspects非空 / session数暴涨 / 同题高频launch → 立即kill launcher+清队列
- A13四源不一致：孤儿进程/注册表脱节 → `sessions --consistency-check` 清理
- 截断误判：真实截断被当dead_session（017 P0，截断引擎此前不可达）→ 检查is_truncated是否先于dead
- proof残留：旧proof被误判完成（016 P0-2）→ 检查mtime归属

## 7. 关键铁律索引

> 完整14条见 `docs/sop/SOP_OP_operations_knowledge.md`"硬约束"段（10基础+016/017/018新增4条）。本索引列出全部14条。

**10条基础硬约束**：
1. 绝不 kill 无 DONE.md 的 session（dead_session是唯一例外：DONE.md已出现但无proof）
2. git 显式路径 add（禁止 git add -A/. /-u）
3. 改代码同步更新第一级文档（docs/architecture/*.md + docs/specs/*.md + docs/sop/SYSTEM_CLOSURE.md）
4. 长时间命令用 tmux（下载/编译/同步/daemon必须在tmux中运行）
5. 禁止 inline 脚本（超过3行的逻辑必须写成文件，放到项目内脚本目录）
6. 人话铁律（所有文档/回复/注释/commit message用人话写）
7. DB-文件双向可追溯（DB中run记录指向工作目录，工作目录有产出文件）
8. 痕迹保留（alert写入ArangoDB，全过程可审计）
9. 禁止绝对路径依赖（代码用Path(__file__).resolve().parent动态获取根目录；环境变量是允许的绝对路径来源）
10. devin cli model 必须显式指定（所有启动devin cli的代码必须显式传--model参数，当前用glm-5-2）

**016/017/018新增4条**：
11. 成果文件双写（proof入库continuation_results，不依赖盘上单点——018教训）
12. 改调度逻辑后跑 sim 发布门禁（solve3+chaos_016——016 P0-1引入新死循环的教训）
13. Gate 放行必须附 --reason 理由（落盘flow流水，没有理由=审计断点）
14. 每轮 SOP_01 必查行为流水（observability --stats，016根因：存量没变但流动病态）

**029新增2条（审计Pipe+防作弊）**：
15. completed题必须审计后才能进入选题池（audit_passed=True是选题池准入条件——dev-docs/029）
16. 解题AI受防作弊约束（可用工具但不能靠"找到答案"解题，遇到解答相关内容须在proof.md主动声明作弊风险；审计AI不受此约束，严格审计数学正确性+作弊检测）

---

> 下方是该步骤的 SOP 文档（L1 增量知识）+ 自动化检查输出（含 Gate Y 通道的 L2 论证依据）。
> 三层结合：你先有系统整体认知（本闭包），再看该步骤做什么，再看检查结果——
> 任何时候都能推理"系统现在工作得对不对"。