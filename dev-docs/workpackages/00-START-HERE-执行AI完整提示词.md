# 00-START-HERE — 执行 AI 完整启动提示词（100 万上下文版）

> **写给**: 实现全部工作包的 AI（你有约 100 万 token 上下文——本提示词要求你**先装载
> 认知再动手**，装载量按本文档清单执行，宁多勿少）
> **写于**: 2026-08-21，工作包体系 v2（commit cc741d5）之后
> **你的审计者**: 用户将在你完成后指派审计链 AI（dev-docs/031/033/036 的作者）全盘
> 审计你的工作——本文档 §四的记录规约就是审计契约，§七提前亮牌审计重点

---

## 一、你是谁，你的使命

你是「续传解题系统」工作包体系的**执行 AI**。这个 repo 用并发 devin cli 对数学失败题
做多轮续传解题（POC-2.7），配独立审计 Pipe，Master Agent 通过 8 步 SOP 循环 7x24 监控。
系统经历了 016/018/028 三次事故与 030→037 八轮审计链的打磨，所有教训都已凝结成
`dev-docs/workpackages/` 下的 **33 份工作包文档**（线 1 修复 17 包 + 线 2 双 ACP 管线
U/V 系列 15 包 + 总控）。

你的使命：**按总控 README 的依赖顺序，逐个实现全部工作包**。每个包都有自包含文档
（认知加载清单/现场基线/任务分解/禁止事项/验收 checklist/审计对照）——文档是你的
施工图，总控 README 是你的工作宪法。

三条用户级洞察贯穿所有工作包（违背任何一条=审计不通过）：
1. **直接检查**——判断状态必须看到最底层实物（硬盘文件/tmux/进程/通知日志），
   不能只看 DB/Redis 字段（028 教训：DB 说 138 题完成，硬盘只有 14 个 proof.md）
2. **适度依赖 Master Agent**——可靠判定（能写成确定性函数并单测覆盖）进代码；
   语义判断标"待人工"+alert。不为"自动化"把不完美判定硬塞进代码
3. **资产保留**——每个 round 的所有产出（含失败的、含部分证明）都是资产，禁止删除；
   ACP 时代的通知日志 jsonl 同为资产

---

## 二、启动加载协议（四阶段认知装载——动手前完成 Phase A 全量）

### Phase A：全局基线（**立即一次性全载**，约 25-30 万 token）

**A1. 工作包体系（你的施工图全集，全部通读）**
```
dev-docs/workpackages/README.md                    ← 总控 v2：依赖图/铁律/状态表（先读）
dev-docs/workpackages/WP-N*.md WP-P*.md WP-H*.md WP-G*.md    （线1第一批）
dev-docs/workpackages/WP-A*.md WP-B*.md WP-S*.md WP-I*.md WP-J*.md WP-K*.md WP-L*.md WP-R*.md （线1第二批）
dev-docs/workpackages/WP-C*.md WP-D*.md WP-E*.md WP-Q*.md WP-F*.md          （线1第三批）
dev-docs/workpackages/WP-U1*.md ~ WP-U8*.md        （线2调查系列）
dev-docs/workpackages/WP-V1*.md ~ WP-V7*.md        （线2实现系列·框架版，🔶槽位待U8）
dev-docs/workpackages/WP-U-ACP改造调查.md          （已废止——读废止头了解史即可）
```
通读目的：建立全局索引（哪个包改哪个文件/依赖谁/验收什么），执行某包时再精读该包。

**A2. repo 认知底盘**
```
AGENTS.md                    ← 工作规范+全部硬约束（含并发/适度依赖/资产保留三铁律）
README.md                    ← repo 引导地图（三套核心资产导航）
docs/sop/SYSTEM_CLOSURE.md   ← L0 系统级认知闭包（架构/生命周期/判定框架/alert清单）
docs/sop/SOP_01~06+Z+OP 共8份 ← SOP 全套（你将改造其中 SOP_01/04 并新建 SOP_07）
docs/sop/templates/ 全部     ← 报表模板（你将新建 report_step_07）
```

**A3. src 全量代码（通读；两巨头精读到行级）**
```
src/continuation_launcher.py（2031行）   ← 精读：主循环/判定链/门闸/优雅停止（线1多包+V3的对象）
src/proof_audit_launcher.py（452行）     ← 精读：审计主循环（WP-H/J/R/V4的对象）
src/proof_audit_result_collector.py      ← 精读（WP-N 的对象）
src/proof_audit_collector.py / proof_audit_config.py / proof_audit_db_schema.py / proof_audit_redis_queue.py
src/continuation_config.py / continuation_db_schema.py / continuation_feeder.py /
src/continuation_collector.py / continuation_result_collector.py / continuation_redis_queue.py
src/session_registry.py（465行）         ← 重点 tmux_alive 体系（U3/V6 对象）
src/step_gate.py / src/observability.py / src/monitor_continuation.py（1247行，重点A1/A13）
src/sim/ 全部                            ← sim 发布门禁（V2 的对象；铁律12）
monitoring/continuation_control.py（750行）/ graceful_shutdown.py / shared_logger.py
scripts/sop/ 全部（run/checks/sop_state/report/_set_next 等）
scripts/run_proof_audit_pipeline.py / scripts/continuation_watchdog.sh / scripts/monitor_check_continuation.sh
scripts/test_acp_signals.py（399行）     ← 已验证的 Devin ACP 客户端（U/V 系列的代码起点）
```

**A4. docs 其余 + git 全史**
```
docs/architecture/ 全部（solve-pipeline / dynamic-concurrency / graceful-shutdown /
  operational-concerns 是多篇 WP 的施工参照；标注过时的 system/ 三份跳读即可）
docs/patterns/（StepGate.md / MonitorPipe.md / 续传规范文档.md）
docs/specs/（p27_monitor_spec.md 的 §A13/A14 / session_management spec）
checklist/README.md（需求点索引——WP-F 对齐时用）
git log --oneline 全量 + 关键 commit 细读：
  c2be5d4（并发5→1文档化）/ f5d89e7（017五修复+门闸9个）/ 62a4cc0（并发硬约束）/
  424f62d+029ef14（两条新硬约束）/ 79fb811+cc741d5（工作包体系v1+v2）
```

**A5. 审计链全部 8 份（理解每个 WP 的"为什么"——执行时你才知道边界在哪）**
```
dev-docs/030（用户8条需求原文）→ 031（核查修正）→ 032（审计+新需求）→ 033（审计+
  partial proof 漏洞）→ 034（审计+thinking检测四轮调查）→ 035（ACP实测）→
  036（审计+三修正：检测≠采集/035§六矛盾/平凡系统is_thinking失效）→
  037（双ACP管线策略——OpenCode默认+Devin备用）
```
**特别注意 036 的三个裁定**（U/V 系列的设计依据）：ACP 的信号存在性≠内容完整性
（U2 实验的由来）；035 §六 已过时弃用；平凡系统 is_thinking 在 -p 下系统性失效。

### Phase B：线 1 执行期附加（进入线 1 各包时加载；各 WP 文档清单优先）

```
WORKLOG.md / MONITOR_REPORT.md 现状（你将续写）
log/ 目录结构 + log/flow/ 行为流水抽样（observability 的产物形态）
D 盘产物树抽样：/Volumes/data/math-agent-glm5.2-tmux-agents-dir/p27-continuation/ 与
  .../p27-proof-audit/ 各 ls 3 个 run 的 work_dir；trajectory 树同查（资产保留的实物）
DB/Redis 实查命令集（每包"现场基线复核"通用）：
  python -m monitoring.continuation_control status --batch-id p27-full
  redis-cli ZCARD p27:pending / HLEN p27:running / LLEN p27:completed / LLEN p27:failed
  redis-cli ZCARD paudit:pending / HLEN paudit:running / LLEN paudit:completed / LLEN paudit:failed
  tmux list-sessions | grep -E '^p27-|^paudit-'
  python3 -c "…AQL 查 p27_continuation_runs status 分布 / p27_proof_audit_runs / p27_proof_audits…"
```

### Phase C：线 2 执行期附加（进入 U 系列前全载；V 系列再加 V1 后的 src/acp/）

```
C1. ACP 知识（5 份 skill，U/V 的协议权威）：
  ~/.config/opencode/skills/opencode-acp-protocol/SKILL.md
  ~/.config/opencode/skills/opencode-acp-protocol/references/full-sop.md（21KB 全文——
    §6 完成检测是 OpenCode 管线的命门：prompt response 可能不返回）
  ~/.config/devin/skills/devin-acp-protocol/SKILL.md
  /Users/user/skills-devin/devin-acp-protocol.md（19KB）
  /Users/user/skills-devin/opencode-acp-protocol.md（20KB，含 11 维度对比）
C2. ACP 实测资产：
  /tmp/acp_test1~5.jsonl（Devin 五轮实测原始数据；若被清理，用 test_acp_signals.py 复测）
  ~/.config/opencode/opencode.json（读结构：openrouter/stealth-ox-alpha/permission——
    ⚠️ 绝不把 auth.json 的 key 内容写进任何日志/报告/commit）
C3. 外部 repo（平凡解题系统——WP-I/L 的模式母本 + U 系列的对照组）：
  /Users/user/database/AI-Math-Normal-Solver.md（DB 表设计：§2.3 十六终态）
  /Users/user/database/AI-Math-Competition-Problem-Solving-System.md（本系统 DB schema 文档）
  /Users/user/AI-Math-Normal-Solver/xishujuzhen/solver_harness/pipe/
    collector.py（classify 函数+PATTERNS）/ retry_infrastructure.py / graceful_shutdown.py /
    runner.py（注意 :615 的 -p 模式——is_thinking 失效反噬的证据）
C4. 037 全文重读（U 系列的需求权威：16 项调查点/双管线不变量/决策理由）
```

### Phase D：按需运行资产（执行中随时查，不预载）

DB 深查（AQL）、log/sop 日志、observability --stats、具体 run 的 rounds_log/
export/proof 文件、sessions.db（32GB SQLite——只做聚合查询带 LIMIT，绝不全表扫）。

---

## 三、执行纪律

### 3.1 包级流程（每个 WP 都走，总控 §五的同款+强化）

```
1. 精读该 WP 文档全文 + 其"前置认知加载清单"逐项装载
2. 复核"现场事实基线"（文档给的命令重跑）——漂移按"基线漂移预期"节理解，
   **意外漂移 → 停下报告用户**（§五停止点）
3. 按"任务分解"执行，逐项对照"禁止事项"
4. 填"验收 checklist"逐项勾选 + 贴命令输出
5. 写执行记录（§四规约）+ 填总控状态表 + EXECUTION-LOG 总账追加一行
6. git commit（显式路径；一包一个或少数几个逻辑 commit；message 含 WP 编号）
7. 自检一遍 §六红线 → 领下一个包
```

### 3.2 会话与上下文管理

- 你有 100 万上下文：Phase A 全量装载后，线 1 可在一个长会话连续执行多个包；
  **但每个包的独立性纪律不松**（独立记录/独立 commit/独立验收）
- 建议会话切分：线 1 三批各 1-2 会话；U 系列 2-3 会话（U1 先行，U2/U3/U6 并行内容
  可同会话）；V 系列**严格每包至少独立提交段**，V3/V7 各自专会话
- 若经历上下文压缩：压缩后先重读 总控 README + 当前 WP 文档 + EXECUTION-LOG 总账
  （恢复位置感），再继续

### 3.3 dev-docs 编号分配表（防冲突——037 已被占用是前车之鉴）

| 编号 | 用途 |
|---|---|
| 037 | 已用（双管线策略）——**任何 WP 不得再写 037** |
| 038 | WP-S 存量资产盘点报告 |
| 039 | WP-L dry-run 报告 |
| 040 | WP-F 线 1 文档对齐报告 |
| 041 | 空置（原 WP-U 报告号随废止保留不用） |
| 042~048 | WP-U1~U7 各自报告 |
| 049 | WP-U8 总报告（**V 系列启动闸门物**） |
| 050 | WP-V7 灰度与切换报告 |
| 051 | WP-G 审计并发实验记录（v2 修正：原写 037 已改） |
| 052+ | 执行中新文档按序取号，取号后在本表登记 |

### 3.4 与 WP 文档的分歧处理

执行中发现 WP 文档与代码事实不符：**以代码为准**（ground truth=代码>git时间线>文档，
024 方法论），但必须：①执行记录"基线漂移"节记录差异 ②小偏差按文档精神继续 ③结构性
矛盾（文档方案行不通）→ 停下报告用户。**不允许静默改方案**。

---

## 四、工作记录规约（审计契约——你的记录就是未来审计的证据链）

### 4.1 每包执行记录 `dev-docs/workpackages/exec-log/WP-{X}-执行记录.md`

**必含七节**（缺任何一节=该包验收不通过）：
```
## 1. 任务执行清单        — WP 文档"任务分解"逐项：做了/怎么做的/跳过（跳过必须给原因）
## 2. 改动文件清单        — 每文件：路径/改动性质（新增|修改|删除）/±行数/一句话说明
## 3. 关键决策与依据      — 每个偏离 WP 文档原文的决策：是什么/为什么/替代方案考量
                            （无偏离也写"无偏离"——显式声明）
## 4. 验收 checklist 执行 — WP 文档 §6 逐项复制+勾选状态+每项的命令与输出原文
## 5. 基线漂移记录        — 复核"现场事实基线"的实测值 vs 文档值；每处差异的解释
## 6. 验证证据            — 测试输出全文/sim 输出/真跑数据/截图性内容（命令输出原文）
## 7. 遗留问题与建议      — 发现未修的 bug/待下包处理项/对 WP 文档的修订建议
+ 尾部：commit hash 清单（本包全部 commit）
```

### 4.2 总账 `dev-docs/workpackages/EXECUTION-LOG.md`（随每包追加一行）

```
| 日期时间 | WP | 状态 | commit | 执行记录路径 | 一句话结果 | 遗留 |
```
（首行由你创建文件时写表头；审计者第一眼看这个文件纵览全程。）

### 4.3 痕迹保留的额外要求

- WORKLOG.md：每个涉及数据操作/系统状态变更的包（尤其 WP-P/V7）追加人话段落
- alert/flow：代码改动产生的 alert_type/flow 事件新形态，在执行记录 §2 列出（V6
  会登记进 SYSTEM_CLOSURE）
- **原始数据不删**：实验 jsonl/灰度数据放 tmp/（不 commit）但路径必须写进执行记录
  （审计者会按路径复验）；报告引用的数据可复制关键表进 dev-docs

---

## 五、拍板闸门与停止点（必须停下等用户，越权=红线违规）

| # | 停止点 | 你能做的 | 你不能做的 |
|---|---|---|---|
| 1 | **U8 之后：049 决策点拍板** | 完成 U1~U8 + 049 报告（含每点推荐） | 启动任何 V 包（哪怕"看起来很小"） |
| 2 | **V7 默认切换** | 灰度阶梯到门槛，数据进 050 | set-backend opencode_acp 设为默认批次值 |
| 3 | WP-L 实跑 | dry-run + 039 报告 | --once 实跑（除非用户对 039 明确批复） |
| 4 | auto-fallback 启用 | V5 机制实现+默认关+演示 | 把默认值设为开 |
| 5 | 意外基线漂移 | 记录+评估影响 | 按自己的理解继续（必须报告） |
| 6 | 灰度门槛不达标 | 停在该级+050 记录原因 | 放水量/调门槛继续 |
| 7 | WP 文档结构性矛盾 | 分析+替代方案建议 | 静默改方案执行 |
| 8 | 配额/凭据异常（API key 失效/Ox Alpha 下线等外部条件变化） | 记录+评估对 U/V 的影响 | 绕过/换 key 自行尝试 |

拍板等待时**不空转**：可切换到无依赖的另一线/另一包继续（如 U8 后等待期做线 1
未完成包）。

---

## 六、红线汇总（审计者必查，违反=对应包重做）

1. 硬约束全集：AGENTS.md 的全部硬约束 + 总控 §三的 14 条（git 显式路径/文档同步/
   绝不 kill 无 DONE.md 的 session/tmux 长命令/禁 inline/人话/痕迹/DB-文件可追溯/
   sim 门禁/禁写死并发+窗口+模型+backend/适度依赖/资产保留/py_compile+测试归位/
   直接检查/**U 系列零生产代码改动**）
2. 两条闸门红线：V 系列不得在"U8+用户拍板"前启动；V7 默认切换与 auto-fallback
   启用不得无拍板执行
3. scope 纪律：diff 里不出现 WP 文档没让做的改动（发现 bug→记录另立，不顺手修）
4. 数据纪律：验收/灰度的所有数字可复算（命令+输出贴记录；判据先写后测——U6 的
   底线判据在数据出来前已定，不得事后调）
5. 凭据纪律：API key/密码永不进日志/报告/commit
6. 判定链完整性：ACP 产物走原生 is_truncated/is_completed，无 backend 特例分支（V4）
7. 行为零变化：V3 重构的产物与重构前逐字段一致（等价性 diff 是命门）

---

## 七、完成标准与交接（全部工作包完成时）

1. 总控状态表全绿（或标注"停在 N 级/待拍板"的诚实状态）+ EXECUTION-LOG 完整
2. 全部执行记录七节齐全（§4.1）
3. dev-docs 新增报告齐备（038~051 按分配表，取号登记）
4. 最后向用户交付一份 **`dev-docs/052-全部工作包执行总结.md`**（编号按当时取号表）：
   - 执行全景（线 1/线 2 各包状态一览表）
   - 与 WP 文档的全部偏差清单（汇总各执行记录 §3）
   - 系统终态快照（并发/后端/门闸/SOP 步数/alert 清单/资产结构——ACP 化前后的对比）
   - 遗留问题全集（汇总 §7）+ 建议的下一批工作包候选
   - **给审计者的导航**：建议抽验的包清单与抽验点（你自己标出最没把握的三处——
     诚实自评是执行记录可信度的加分项）
5. 然后停下等审计。审计者将：重跑关键验收命令、抽实物核验（直接检查）、查闸门
   红线、逐包比对 checklist、并复核你在执行记录里自标的三处弱项。

---

**现在开始**：执行 §二 Phase A 全量装载 → 读总控 README 确认第一包（线 1 的 WP-N；
若线 1 已被其他会话完成则按状态表领 U1）→ 按 §三流程执行。祝顺利——记住体系里的
一句老话：**没有理由的放行=审计断点；没有数据的结论=瞎说。**
