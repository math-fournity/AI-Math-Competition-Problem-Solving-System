# 024 — AGENTS/docs 与 SOP/src 全面对齐审计报告

> **日期**：2026-08-21
> **触发**：用户担心两件事——①AGENTS.md 辅助 Master Agent 运行，必须与 SOP/src 对齐；
> ②docs 帮 AI 理解系统设计，必须与 SOP/src 对齐。要求全面加载所有 sop/src/docs 内容做对齐分析，
> 冲突时用 git log + 文件创建/修改时间 + dev-docs/checklist 综合判定"谁是对的"。

## 1. 方法

- 全量加载：8个SOP文档+SYSTEM_CLOSURE、scripts/sop 全部脚本、src 全部模块（launcher 1998行全文）、
  monitoring 3个模块、docs/architecture(10)/specs(3)/patterns(3)/system(3)、README三层、checklist索引。
- ground truth 裁定依据：**代码实际行为 > 最新设计意图（git时间线）> 文档声称**。
  关键 commit 交叉验证：01f8be6(删Pipe123, 08-20 11:54)、6a87d97(solve-pipeline文档, 11:51——早于删除3分钟)、
  b3a7e76(13:46, 引入watchdog错误声称)、c2be5d4(13:50)、e51e231(08-21 01:23, 已修AGENTS 8步表5处)。

## 2. 发现与裁定（按严重度）

### P0 — 事实性错误（会直接误导运行决策）

| # | 位置 | 错误声称 | ground truth | 裁定依据 |
|---|---|---|---|---|
| 1 | AGENTS.md 动作1 + SOP_01 §3注 | "`start` 内部把 launcher/monitor/**watchdog** 三个长服务放进 tmux"；"确认三个session都在运行" | `cmd_start` 只调 `start_service` 两次（launcher+monitor）；watchdog 靠 launchd/手动启动，control health 自己都注明"watchdog可选" | git 全历史中 cmd_start 从未有第三个 start_service |
| 2 | SYSTEM_CLOSURE §6 + SOP_03 alert表 | B类编号偏移一位（如 all_rounds_truncated=B5、rounds_log_*=B7、collision=B8/B9） | spec §2.2 + checklist MON-B1~B9 + monitor 代码注释一致：B6=truncation、B7=status_anomaly、B8=rounds_log(6细分)、B9=intermediate(2型) | 三方一致的编号为准，SYSTEM_CLOSURE 是单点漂移 |
| 3 | operational-concerns §2 | stall "默认300秒"、"kill-session + failed_stall" | `DEFAULT_STALL_SECONDS=600`；代码**不kill**——标记stuck等DONE.md（铁律1） | continuation_launcher.py:1774-1809 + config |

### P1 — 过时描述（描述已删除/已变更的设计）

| # | 位置 | 过时内容 | 现实 |
|---|---|---|---|
| 4 | solve-pipeline.md §3/§4/§7 | 把 analysis/audit/selection/solver_launcher 描述为现存消费者（表格无删除标记）、"919题" | 四个launcher已删（01f8be6）；problem_list.json 现6083题 |
| 5 | AGENTS 8步表 + README sop表 | 01行缺"全景视图"、05行缺"sim发布门禁"、Z行缺"方向性判断+审计"、02行"7字段" | checks.py check_01 接了 _check_system_panorama（5406360）；SOP_05 §4（1452299）；SOP_Z §7/第三部分；rounds_log 实为6路径字段 |
| 6 | README specs区 | p27_monitor_pipe_operations 当有效文档、templates 4个当可用模板、architecture "9个"缺solve-pipeline条目 | 三者文件内已有/应有废弃标记；architecture 实为10个 |
| 7 | spec §4 alert结构 | status枚举 "new/reviewing/fixed/wontfix" | 代码实际 new/resolved（resolve-alert 写 resolved） |
| 8 | spec §3.3 + checklist MON-C + SOP_06 S12 + SOP_Z + AUDIT-03 + monitor check_items + monitor_check_continuation.sh | C类只有 C1-C5 | SOP_04/AGENTS 已是 C1-C6（C6 export_semantics，020审计 6f134e4 加入 SOP 但未同步 spec/checklist/代码元数据） |
| 9 | SYSTEM_CLOSURE §6 + src/README | "alert_type 共30种" | 代码实际 **34种**（16A+7B+6rounds_log+2collision+2infra+1抽样），表格自己也列了34行 |
| 10 | checklist/README 合计147 / 根README 134+153 / SOP_OP 147 | 需求点计数三方四个数互相矛盾 | 实际=162需求点+5issue文件（各门类行数与文件数全部吻合，仅合计数字漂移）；补MON-C6后=163+5=168文件 |
| 11 | session spec §B 废弃说明 | "7 步自驱动循环" | SOP 已是 8 步（37c691e 加 OP） |
| 12 | dynamic-concurrency/framework-checklist | 引用 launcher "645-656行"/"488-497行" | 行号已漂移至 1041-1052（launcher 长大） |
| 13 | graceful-shutdown §3.2 代码片段 | while 条件缺 handover_pending | 017 修复后为 `len(running)+len(handover_pending) < concurrency` |
| 14 | src注释类 | config头部仍描述4Pipe架构；requeue_truncated门闸docstring"max_rounds默认3"；collector"919道"；watchdog引用不存在的recover_from_crash.py | 分别改为单管线描述/默认5/不写死题数/指向sessions --consistency-check |

### P2 — 顺带发现的代码级问题（本次一并修）

| # | 位置 | 问题 | 修复 |
|---|---|---|---|
| 15 | continuation_control cmd_health | alert 查询过滤 `a.resolved == false`——alert 文档没有该字段，health 永远显示"无未解决alert ✅" | 改为 `a.status != 'resolved'`（与 resolve-alert/check_03 一致） |
| 16 | continuation_control set-concurrency | `--poll-seconds` 默认30 与 launcher 实际 DEFAULT_POLL_SECONDS=15 不符（AGENTS 说"通常15秒内"才是对的） | 默认改15 |

### 验证为正确、未改动的关键声称（抽样）

- AGENTS.md 四处行号引用全部精确命中：launcher:1172/1223/1041-1052/964-969、config:95、control:158-161、run.py:48-113。
- SYSTEM_CLOSURE `DEFAULT_CONCURRENCY=5` 正确（c2be5d4 只改了文档示例和 monitor expected 默认，config/control 代码默认就是5——commit message"全量"有误导性但代码与闭包一致）。
- 门闸9个（launcher 8 + feeder 1）、`--hold-resource`、`--reason` 落盘、round-1 seed 预检轮、C类"每3轮抽2条"、A类14项、`stop --force` 分类处理session——均与代码一致。
- StepGate.md / MonitorPipe.md(§2.2) / 续传规范8章节 / 报表四件套+模板8个 / p27_monitor_spec A类表(含A13/A14)——与代码一致。

## 3. 修复清单（本次 commit）

**AGENTS.md**：watchdog声称×2、8步表01/02/05/Z四行。
**docs/sop**：SOP_01(watchdog×2)、SOP_02(字段结构表述)、SOP_03(B编号表)、SOP_04(指针C1-C6)、SOP_06(S12)、SOP_Z(10个run/7字段/C1-C5/A类12项/AUDIT-03)、SOP_OP(163)、SYSTEM_CLOSURE(34种/B编号+映射注/字段结构)。
**docs/specs**：p27_monitor_spec(§2.3+§3.3加C6、§4 status枚举+key随机后缀注)、session spec(8步)。
**docs/architecture**：solve-pipeline(§3删除标记+§4/§7改写+6083)、dynamic-concurrency(行号)、graceful-shutdown(代码片段)、operational-concerns(stall 600s+不kill+continuation_config)、framework-checklist(行号×2)。
**README三层**：根README(architecture 10个+solve-pipeline条目、specs废弃标记、templates废弃标注、A类14/C类6/34种、sop表01行、checkpoint 163/168)、docs/README(10个)、src/README(C类6项+34种)。
**checklist**：新建MON-C6.md、MON-C1~C5所属章节"（6项）"、README(MON-C=6、合计163+5)。
**代码**：config头部docstring、launcher门闸docstring默认值、monitor C6进docstring+check_items、collector题数、watchdog.sh引用、control health过滤bug+poll默认。
**trace.csv**：补MON-C6四行关系（implements/specified-by/part-of×2，与MON-C5同构）。

## 4. 残留观察（未修，留给SOP_05/后续）

1. `_state.json` 停在 08-20 06:08 的 last=Z/next=01（OP加入前的旧状态；next=01 合法可跑，仅历史痕迹）。
2. monitor_continuation argparse `--concurrency` default=5 而函数签名 default=1（c2be5d4 只改了后者，CLI 显式传参使后者永不生效——WP-02 已知bug的缓解不完整，根本修复应从DB读）。
3. launcher docstring 首行"复用analysis_launcher.py的架构模式"等历史来源引用仍指向已删文件（保留：属设计溯源，不是现状声称；config头部已加历史注范式）。
4. monitor 文件头 A 类列表仍是最初8项的摘要（未列A10-A14）——摘要性质，§6有全表兜底。
5. docs/system/AnalysisSystem*.md 三个过时文档已有 ⚠️ 标记+根README引导，未再动。
6. 观察项：`operational-concerns.md` 末尾"循环监控SOP(2026-08-18)"节是 SOP 机制的前身描述（7项检查/monitor_check.sh for Pipe1/2/3），已被 SOP 循环取代——保留作历史，未标废弃（低风险，SOP_Z 可评估）。

## 5. 防再犯

计数类事实（checkpoint数、alert_type数、文档数）在多处复制时只留**一处权威+其他处引用**（本次已尽量指向 SYSTEM_CLOSURE/spec/checklist-README），改数时 grep 全 repo 同步。B编号/C编号以 spec §2 为唯一权威。
