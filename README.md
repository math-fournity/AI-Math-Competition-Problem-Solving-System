# README.md — AI工作引导地图

> **强制声明**：AI必须确保本文件内容在自己的上下文中，才能回答用户的问题或进行后续操作。如果上下文中没有本文件的完整内容，必须先用read工具完整加载本文件，然后再回答问题或操作。
>
> 本文件不是知识，是引导地图。它用inline方式描述每个文档讲什么、覆盖哪些问题场景、和其他文档的关系。AI读完本文件后，判断"用户问的这个问题，我需要加载哪几个文档"，然后用read加载，再工作。

---

## 〇、核心资产——先知道 repo 有什么

本 repo 以 SOP/src/docs 为三大运行支柱，并有历史工作包、v2 方法论和最终成品认知包。
AI 接手时先建立这个全景，再往下读各分类法详情：

| 资产 | 位置 | 是什么 | 入口 |
|---|---|---|---|
| **SOP** | `scripts/sop/` + `docs/sop/` | Master Agent 7x24 监控循环——9步循环脚本（01~07+Z+OP）+ 对应执行指令文档 + 系统级认知闭包 | `AGENTS.md`"Master Agent SOP 流程控制机制"段 → `python -m scripts.sop.run` |
| **src** | `src/` + `src/sim/` | 续传解题管线实现代码——主管线4模块 + 支撑6模块 + 监控治理4模块 + 全流程模拟6模块 | `src/README.md`（4分组导航地图） |
| **docs** | `docs/` | 架构/规范/模式/模板文档集——系统认知层 + 设计范式 + 架构设计 + 检查规范 + 模板 + SOP 文档 | 下方分类法第一~三节 |
| **工作包** | `dev-docs/workpackages/` | 030~037 审计链收敛后的最终执行体系——总控 README（依赖图/铁律/状态表）+ 各 WP 执行文档 + exec-log 执行记录 | `dev-docs/workpackages/README.md` |
| **v2 续传架构** | `dev-docs/053*.md` + `053a-*.md` | v2 观察者/解题者递归消化链——技术说明书(053)+设计简版+三模板+驱动器参考实现(053a系列) + 影响评估与行动方案(054) | `dev-docs/053-v2续传编排技术说明书-观察者做题者递归消化链.md` → `dev-docs/054-v2架构影响评估与行动方案.md` |
| **提示词/资产合同** | `templates/v3/` + `src/prompt_contract.py` + `docs/architecture/round-artifact-contract.md` | WP-03 冻结的三角色模板、严格渲染接口、每轮资产合同和无答案1962离线回归 | `templates/README.md` |
| **最终成品认知包** | `dev-docs/057~064` + `dev-docs/final-system-workpackages/` | 用户最终需求、大图、Feature List、无限Round、1962编排、形式化真理性、key池、Master监督/Gate及12个自包含未来实施包 | `dev-docs/057-最终成品系统大图与产品定义.md` → `dev-docs/final-system-workpackages/README.md` |

> 三大运行支柱的关系：**src 实现**解题管线 → **docs 描述**架构和规范 → **SOP 监控**src 的运行。
> AI 工作时按需加载：改代码先读 `src/README.md` 找模块 → 查规范读 `docs/specs/` → 运行监控走 `scripts/sop/`。

> **当前态/目标态警示（2026-08-22）**：WP-01 已把最大 Round 数迁移为非永久调度窗口，
> WP-03 已冻结三角色提示词、轮次资产合同和1962离线回归，WP-04 已实现解题侧形式化
> 归档/运行/日志接口；历史 `TRUNCATED_AT_MAX` 仍只读兼容。生产观察者/解题者、形式化
> 充分性审计、系统 key 池、目标
> 并发30和 Supervisor stuck 闭环尚未完成。057~064 是目标认知；事实差距以064和新工作包
> 状态表为准。

---

## 一、系统认知层——核心入口与全景

> ⚠️ **重要（2026-08-20）**：下方三个 `docs/system/AnalysisSystem*.md` 文档描述的是
> 删除 Pipe 1/2/3 前的 4 Pipe 架构，已过时。**当前系统只有 Pipe 4 续传解题管线**。
> 新 Session 接手时应优先读：
> 1. `AGENTS.md` — 核心概念：解题管线 + 启动指令 + SOP 流程控制
> 2. `dev-docs/057-最终成品系统大图与产品定义.md` — 最终目标大图；未来实现必读
> 3. `dev-docs/058-最终成品系统Feature-List与需求追踪.md` — 用户需求冻结表
> 4. `dev-docs/064-当前实现差距与实施路线总图.md` — 当前代码与目标差距
> 5. `docs/sop/SYSTEM_CLOSURE.md` — 当前系统级认知闭包（架构/生命周期/判定框架）
> 6. `docs/architecture/solve-pipeline.md` — 当前解题管线概念详解
> 7. `docs/sop/SOP_OP_operations_knowledge.md` — 运营知识（硬约束/外部索引/快速开始）
>
> 下方三个 AnalysisSystem*.md 保留作历史参考。

### `docs/system/AnalysisSystem.md` — 新Session接手AI的完整加载指南（⚠️ 过时）

新Session AI接手数学大师系统时的入口文档。讲"你在哪、系统是什么状态、要读什么、要做什么"——基本信息（工作目录/Git分支/Python环境/数据库）、项目一句话和三句话定义、当前系统状态（正在进行的核心工作、POC进度）、工作类型分类。

**覆盖问题场景**：
- 新session接手时——"我刚来，这是什么项目，现在做到哪了"
- 确认环境配置——ARANGO_DB是否设置、.venv是否就绪
- 了解当前POC状态——POC-2.7续传Pipe系统进展
- 判断下一步要做什么——工作类型分类指引

**依赖关系**：读完后通常需要加载 `docs/system/AnalysisSystemDesign.md`（设计总索引）或 `docs/system/AnalysisSystemOps.md`（运行操作手册），取决于要设计还是运行。

### `docs/system/AnalysisSystemDesign.md` — 错题分析系统设计总索引（⚠️ 过时）

错题分析系统的设计总索引。快速入口（创建新Pipe/运行现有Pipe/停止系统）、架构决策、组件职责、设计原则。与 Ops 分工：Design=设计总索引/架构/决策，Ops=运行操作/SOP/检查清单。

**覆盖问题场景**：
- 创建新Pipe时——12项必查清单入口、11步操作指南入口
- 运行现有Pipe时——4个Pipe的启动/检查/停止命令速查
- 停止系统时——优雅停止/强制停止/收尾停止命令
- 理解架构决策时——4个Pipe的演进、组件解耦设计
- 查找设计文档时——索引所有需要看的文档和代码资产

**依赖关系**：创建新Pipe时另读 `docs/architecture/framework-checklist.md` + `docs/patterns/MonitorPipe.md` §6；涉及多轮续传时另读 `docs/patterns/续传规范文档.md`；运行操作细节另读 `docs/system/AnalysisSystemOps.md`。

### `docs/system/AnalysisSystemOps.md` — 错题分析系统运行操作手册（⚠️ 过时）

错题分析系统的运行操作手册。SOP、检查清单、打磨记录。5组件架构详解（data_collector/feeder/analysis_launcher/result_collector/aggregator）、运行监控操作、问题排查SOP、历史打磨记录。从原 AGENTS.md 第3518-4216行外移（2026-08-19瘦身工程）。

**覆盖问题场景**：
- 运行/监控/调试错题分析系统时
- 理解5组件架构的详细职责和数据流时
- 执行运行操作SOP时——启动/检查/停止/调整并发
- 排查运行问题时——rate limit/stall/zombie/session管理
- 查阅历史打磨记录时——已知问题和修复历史

**依赖关系**：涉及系统设计时另读 `docs/system/AnalysisSystemDesign.md`；涉及Monitor Pipe检查时另读 `docs/specs/p27_monitor_spec.md`；涉及续传时另读 `docs/patterns/续传规范文档.md`。

---

## 二、设计范式层——跨项目元方法论

### `docs/patterns/MonitorPipe.md` — Monitor Pipe设计范式

跨项目的"连续工作系统Monitor Pipe+检查脚本"设计范式。定义如何写检查规范、如何实现Monitor Pipe、如何写检查脚本的三层架构（规范层/实现层/查询层）。不是某个具体系统的文档，是元范式。具体系统的检查规范是系统资产（如 `docs/specs/p27_monitor_spec.md`）。

**覆盖问题场景**：
- 设计新系统的Monitor Pipe时——三层架构、A/B/C类检查定义
- 实现Monitor Pipe时——11步操作指南
- 编写检查脚本时——查询脚本设计模式
- 理解Master AI在连续工作系统中的检查者角色时

**依赖关系**：具体系统的检查规范是该系统的系统资产（如 `docs/specs/p27_monitor_spec.md`）；本地版见 `docs/architecture/monitor-pipe-pattern.md`。

### `docs/patterns/StepGate.md` — 步进门闸设计范式（DB信号单步跟踪）

让 Master Agent 能够"卡住"自动化系统的关键动作、检查之前的工作、再放行的通用设计范式。核心三条：①DB信号变量（动作前wait proceed 0→1，代码自清零再执行，信号由Master Agent置1）；②`@gated`装饰器统一封装（注册/流水/等待/DB降级）；③定位用函数名+docstring不用行号（函数名=日志标志grep直达，docstring=自包含文档经inspect自动收集进DB注册表，永不漂移）。范围铁律：只对**语义动作**设闸（有独立正确性标准、checklist写得出来的业务动作），底层I/O封装不设闸（多调用方标准不同），只读判定靠行为流水——全部等放行吞吐归零。起源于016事故（失控循环跑了18分钟Master Agent拦不住）。**覆盖问题场景**：需要单步调试/审计自动化系统时、给新Pipe加门闸时、理解hold/step/auto模式时。**依赖关系**：首次实现在 `src/step_gate.py`（9个语义动作闸；详见 `src/README.md`）；配套行为流水 `src/observability.py`；操作文档在 `docs/sop/SOP_01_system_health.md` §8.5（SOP_01例程已接线Y通道）。

### `docs/patterns/续传规范文档.md` — HANDOFF标准（交接文档续传方案）

定义交接文档（HANDOFF.md）的标准结构、提取规则、循环操作流程。八个必填章节、续传不是"拼接thinking"而是"交接研究"的核心认知、截断/完成判定标准、prompt模板。源自POC-2.6续传机制v1方案（机械拼接reasoning_content）的改进。

**覆盖问题场景**：
- 实现多轮续传机制时——HANDOFF.md八章节结构
- 编写续传prompt模板时
- 判定AI是否被截断/是否完成时
- 理解续传的核心认知转变时——从"拼接thinking"到"交接研究"

**依赖关系**：续传实现代码见 `src/README.md`（Pipe 4 全模块导航）；运行操作见 `docs/system/AnalysisSystemOps.md`。

---

## 三、架构设计——docs/architecture/

### `docs/architecture/` — 架构设计文档（12个）

架构设计文档集。每个文档覆盖一个设计方面：

- **`solve-pipeline.md`** — 解题管线核心概念（并发=管线条数=devin cli实例数；终态判定）。**覆盖场景**：讨论系统并发/devin cli实例数时（必读）。**依赖**：AGENTS.md"核心概念"段引用它。
- **`framework-checklist.md`** — 新Pipe必读的12项必查清单（⚠️ 已标过时：Pipe 1/2/3 已删，不计划新增 Pipe）。**覆盖场景**：创建新Pipe前。**依赖**：配合 `docs/patterns/MonitorPipe.md` §6 使用。
- **`architecture.md`** — 4个Pipe的演进与组件职责（⚠️ 已标过时：描述删除前的 4 Pipe 架构）。**覆盖场景**：理解系统演进历史时。
- **`graceful-shutdown.md`** — 优雅停止设计（信号处理、不kill devin实例）。**覆盖场景**：实现停止功能时。
- **`dynamic-concurrency.md`** — 动态并发设计（运行期调整并发数）。**覆盖场景**：实现并发调整时。
- **`monitor-pipe-pattern.md`** — Monitor Pipe设计范式（本地版，⚠️ 已标过时）。**覆盖场景**：理解演进历史时。**依赖**：现行范式见根目录 `docs/patterns/MonitorPipe.md`。
- **`operational-concerns.md`** — 运维关注点（rate limit/stall/zombie/多轮续传/断点续传）。**覆盖场景**：实现launcher核心逻辑时。**依赖**：运行操作SOP见根目录 `docs/system/AnalysisSystemOps.md`。
- **`selfrun-workflow.md`** — selfrun工作流（⚠️ 已废弃：selfrun代码已删）。**覆盖场景**：历史参考。
- **`solver-trajectory-schema.md`** — trajectory数据schema。**覆盖场景**：处理trajectory数据时。
- **`solver-harness-borrowing.md`** — 解题系统借鉴分析（7个值得借鉴的设计）。**覆盖场景**：从解题系统借鉴设计到错题分析系统时、理解多模块解耦/独立服务设计时。
- **`round-artifact-contract.md`** — v3 每轮角色/资产合同（prompt、通知流、笔记、proof/partial、formal、日志、mtime归属）。**覆盖场景**：接生产 observer/solver、形式化交付、ACP回收或资产sim时。**依赖**：模板入口 `templates/README.md`。
- **`formal-delivery.md`** — 解题侧形式化源码归档、命令执行、版本/日志、逃逸口扫描和 rounds_log 字段接口。**覆盖场景**：WP-02 接候选成功、WP-04验证、WP-05独立重跑时。**边界**：结构完整/退出0不等于数学充分。

### `docs/specs/` — 检查规范（系统资产，3个）

POC-2.7续传Pipe的检查规范集，Monitor Pipe和Monitor Exec Devin的执行依据：

- **`p27_monitor_spec.md`** — Pipe 4续传的检查规范（A类14项自动检查/B类9项续传质量/C类6项AI判断，alert_type 全集34种的权威来源）。**覆盖场景**：实现Monitor Pipe检查逻辑时、查阅检查标准时。**依赖**：设计范式见根目录 `docs/patterns/MonitorPipe.md`。
- **`p27_session_management_and_polish_spec.md`** — Session编号化管理与打磨devin架构规范（§A Session管理有效 / §B Exec Devin已废弃）。**覆盖场景**：实现session编号化管理时。**依赖**：前置依赖 `docs/specs/p27_monitor_spec.md`。
- **`p27_monitor_pipe_operations.md`**（⚠️ 已废弃 2026-08-19）— 原Monitor Exec Devin的认知资产入口，该角色已由 Master Agent SOP 循环取代（现行入口是 `docs/sop/`）。保留作历史参考。

### `docs/templates/` — 模板（4个，⚠️ 均为已删除Pipe/已废弃方案的历史模板）

分析/审计/选题三个 Pipe 及 selfrun 方案均已删除/废弃（2026-08-20），以下模板保留作历史参考，当前系统不再使用：

- **`analysis_agents_md.md`** — 分析Pipe的AGENTS.md模板（历史）。**覆盖场景**：历史参考。
- **`audit_agents_md.md`** — 审计Pipe的AGENTS.md模板（历史）。**覆盖场景**：历史参考。
- **`selection_agents_md.md`** — 选题Pipe的AGENTS.md模板（历史）。**覆盖场景**：历史参考。
- **`selfrun_subagent_task.md`** — selfrun模式subagent任务执行规范（v3，⚠️ 已废弃）。**覆盖场景**：历史参考。**依赖**：selfrun工作流见 `docs/architecture/selfrun-workflow.md`（已废弃）。

---

## 四、需求点清单——checklist/

### `checklist/README.md` — 需求点清单索引

错题分析系统全部功能需求点的索引。14个门类163个需求点（另含5个MON-A-issue已知问题文件，checkpoint文件共168个），每个需求点（checkpoint）一个独立文件，文件名即编号。README.md 只保留门类索引表+编号规则+状态标记说明，不重复每个 checkpoint 的内容。用 checklist 推进和管理整个项目研发，每个 checkpoint 记录它涉及的文档和代码。

**覆盖问题场景**：
- 开发前确认功能无遗漏时——查门类索引表
- 开发中引用需求点编号时（WP和commit message可引用）
- 验收时逐项打勾判定系统是否完成时
- 跨session新AI了解系统全貌时
- 查找某个checkpoint详情时——按编号直接读 `checklist/<编号>.md`
- 按状态筛选checkpoint时——`grep -l '\[ \]' checklist/*.md` 找所有待做的

**依赖关系**：执行某个WP时读对应的 `working-packages/WP-XX-*.md`；Exec Devin必读子集见 `checklist/ExecDevin.md`。

### `checklist/ExecDevin.md` — Monitor Exec Devin必读子集

从全集134个需求点中提取的 Monitor Exec Devin 必读子集（约68个需求点）。Exec Devin 启动后读这个文件，知道自己本轮要检查什么、要遵守什么约束、对自己做什么 self-check。

**覆盖问题场景**：
- Monitor Exec Devin启动时加载——知道自己要检查什么
- 确认Exec Devin的必读需求点时

**依赖关系**：完整需求点索引见 `checklist/README.md`；检查规范见 `docs/specs/p27_monitor_pipe_operations.md`。

**注意**：该角色已由 Master Agent 接管，本文件保留作为历史参考。Master Agent 现在使用 `checklist/MasterAgentCheck.md`。

### `checklist/MasterAgentCheck.md` — Master Agent SOP 索引

Master Agent 接管 Monitor Pipe 检查工作后的检查清单索引。**2026-08-21 扩展为 9 步（WP-C 新增 07 审计健康）**：从"按需检查清单"升级为 7x24 持续循环的 SOP 脚本机制。检查内容已迁移到 `docs/sop/SOP_01~07+Z+OP.md`（9 个文档），由 `scripts/sop/run.py` 单一入口驱动（读取 `scripts/sop/checks.py` 中 9 个检查函数）。本文件保留为 SOP 文档索引。

**覆盖问题场景**：
- Master Agent 开始 7x24 监控循环时——执行 `python -m scripts.sop.run` 进入循环
- 查找某个 SOP 步骤的内容时——看 `docs/sop/SOP_XX.md`
- 查看当前 SOP 流程状态时——`python -m scripts.sop._set_next status`

**依赖关系**：SOP 文档见 `docs/sop/`（8 个 + SYSTEM_CLOSURE.md 认知闭包）；SOP 脚本见 `scripts/sop/`（run/checks/sop_state/_set_next/dry_run/report/sop_log/log_search）；检查规范见 `docs/specs/p27_monitor_spec.md`；需求来源见 `dev-docs/013-Master-Agent-SOP流程控制机制方案.md`；完备性审计见 `dev-docs/021-SOP认知闭包完备性审计报告.md`。

### `docs/sop/` — Master Agent SOP 文档（8个+1个认知闭包）

9 步 SOP 循环的自包含执行指令文档（01-06 工作 + 07 审计健康 + Z 元检查 + OP 运营知识），加 1 个系统级认知闭包（SYSTEM_CLOSURE.md，每步前置注入）。脚本运行时读取并完整打印到 stdout——内容进入 Master Agent 最近上下文，不依赖 AGENTS.md always-on 注入。

| 文档 | 脚本检查函数 | 职责 |
|---|---|---|
| `SYSTEM_CLOSURE.md` | （每步前置注入，L0 认知闭包） | 系统级认知闭包（架构/生命周期/判定框架） |
| `SOP_01_system_health.md` | `check_01_system_health` | 系统存活+进度+Session+门闸Y+行为流水+全景视图 |
| `SOP_02_data_integrity.md` | `check_02_data_integrity` | 数据完整性（全量文件+DB集合级+题源完成率） |
| `SOP_03_alert_triage.md` | `check_03_alert_triage` | alert 分类处理 |
| `SOP_04_ai_judgment.md` | `check_04_ai_judgment` | C 类 AI 判断（C1-C6） |
| `SOP_05_code_repair.md` | `check_05_code_repair` | 代码修复+sim 发布门禁 |
| `SOP_06_report_worklog_selfcheck.md` | `check_06_report_worklog_selfcheck` | 报告+WORKLOG+Self-check S1-S22 |
| `SOP_Z_meta_system_review.md` | `check_Z_meta_system_review` | 元检查+整体检查+方向性判断+审计 |
| `SOP_OP_operations_knowledge.md` | `check_OP_operations_knowledge` | 运营知识刷新+环境验证 |

**覆盖问题场景**：Master Agent 在 SOP 循环的某个步骤时，脚本打印对应 SOP 文档，知道该做什么。

### `scripts/sop/` — Master Agent SOP 脚本（8个模块）

9 步 SOP 循环的脚本模块集。`run.py` 是单一入口（读取 `_state.json` 决定当前步骤→打印 L0+L1→执行 `checks.py` 对应函数→生成报表→推进状态→打印 todo 指令）。脚本按顺序执行，通过 `_state.json` 记录上一个/下一个步骤，防止跳步。每个脚本输出末尾要求 Master Agent 用 `todo_write` 建立 todo list，最后一项是"执行 `python -m scripts.sop.run`"——自驱动 7x24 持续循环。

| 脚本 | 职责 |
|---|---|
| `run.py` | 单一入口（每次执行当前步骤） |
| `checks.py` | 8 个步骤的自动化检查逻辑 |
| `sop_state.py` | 状态管理（_state.json + 顺序校验 + L0/L1 文档加载） |
| `_set_next.py` | 强制设定下一步（跳步用） |
| `dry_run.py` | SOP 循环完整性验证（6 项测试） |
| `report.py` | 报表+快照生成（D盘目录） |
| `sop_log.py` | 循环日志（500 文件×1MB） |
| `log_search.py` | 结构化日志检索（event/problem_id/session_key/level/module/时间范围） |

**覆盖问题场景**：用户说"开始工作"时启动循环（`python -m scripts.sop.run`）；流程状态查询/跳步修正时用 `_set_next.py`；完整性验证时用 `dry_run.py`；日志检索时用 `log_search.py`。

### `checklist/<编号>.md` — 单个checkpoint详情（168个）

每个需求点一个独立文件，文件名即编号（如 `ENV-01.md`、`MON-A1.md`、`SELF-S1.md`）。扁平化存放，不设门类子目录——编号前缀已自带门类分类。每个文件包含：需求描述、验证方法、涉及的文档和代码、状态、负责的WP、来源、变更记录。

**覆盖问题场景**：
- 需要了解某个需求点详情时——按编号直接读
- 修改需求点状态时——直接改文件中的状态标记
- 新增需求点时——用 `scripts/generate_checkpoint.py <编号>` 生成模板文件

**依赖关系**：需求点索引见 `checklist/README.md`；需求点所属的WP见 `working-packages/WP-XX-*.md`。

---

## 五、工作包管理——working-packages/

### `working-packages/README.md` — 目录说明（静态）

`working-packages/` 目录的结构说明+使用指南。目录结构图、文件类型说明、README与INDEX的关系、编号规则、新AI接手时的阅读顺序、维护规则。静态文档，很少改。

**覆盖问题场景**：
- 第一次进入工作包目录时——了解这里有什么、怎么导航
- 确认阅读顺序时——README→INDEX→WP
- 确认维护规则时——什么时候改哪个文件

**依赖关系**：读完后读 `INDEX.md` 了解当前进度；读 `checklist/README.md` 了解全部需求点。

### `working-packages/INDEX.md` — 工作包跟踪表（动态）

10个工作包（WP-01~WP-10）的清单+依赖图+执行顺序+当前系统状态。动态文档，经常改。包含WP状态（待执行/进行中/完成）、优先级（P0/P1/P2）、依赖关系图、执行顺序建议、当前系统状态快照、铁律提醒。

**覆盖问题场景**：
- 了解当前工作包状态时——哪个WP做到哪了
- 规划执行顺序时——依赖图和执行顺序建议
- 查看当前系统状态时——DB状态、已完成commit、已知未修复问题
- 确认铁律提醒时——改代码同步文档、git显式路径add、不kill无DONE.md的session

**依赖关系**：执行某个WP时读对应的 `WP-XX-*.md`；了解需求点详情读 `checklist/<编号>.md`。

### `working-packages/WP-01~WP-10` — 工作包实施计划（10个）

10个工作包的实施计划文件。每个WP包含：目标、要读的文档、任务清单（带打勾）、验证标准、依赖关系。WP编号稳定不重排。

| WP | 标题 | 优先级 | 覆盖场景 |
|---|---|---|---|
| WP-01 | 阶段1真实运行验证 | P0 | 验证Session编号化管理功能 |
| WP-02 | 已知bug修复 | P0 | 修复动态并发/session_counter/launcher覆盖等问题 |
| WP-03 | 阶段2配置与模板 | P1 | 阶段2配置和模板准备 |
| WP-04 | 阶段2Monitor Exec Devin启动器 | P1 | 实现Monitor Exec Devin启动器 |
| WP-05 | 阶段2Monitor Pipe集成 | P1 | Monitor Pipe集成 |
| WP-06 | 阶段2export与report查看支持 | P2 | export和report查看功能 |
| WP-07 | 阶段2端到端验证 | P1 | 端到端验证 |
| WP-08 | 阶段3文档同步 | P2 | 文档同步 |
| WP-09 | POC-2.7并发1运行和监控 | P0 | 以并发1启动系统运行 |
| WP-10 | 系统审计 | P2 | 所有工作完成后审计 |

**依赖关系**：WP状态和执行顺序见 `INDEX.md`；WP引用的需求点详情见 `checklist/<编号>.md`。

---

## 六、幂等追溯体系——全资产追溯关系

### `views/idempotency.md` — 幂等追溯分类法

repo 全资产追溯关系的视角。trace.csv 记录整个 repo 中所有资产（代码/文档/checkpoint/wp/dev-doc/脚本/配置/模板/commit/DB/运行资产）之间的所有关系（3910条，20种关系类型）。当你需要追溯任何资产的关系、维护 trace.csv、或验证 repo 幂等性时，从这分类法出发。

**覆盖问题场景**：
- 追溯任何资产的关系链——"这个代码文件实现了哪些checkpoint？被哪些commit改动？"
- 维护 trace.csv——代码/文档变更后更新追溯关系
- 验证 repo 幂等性——全资产覆盖、全关系覆盖、孤立资产检查
- 理解幂等追溯体系的设计——为什么这样设计、怎么建立起来的

**依赖关系**：看法文件 `views/idempotency.md` 索引了15个文件（trace.py/trace.csv/6个录入脚本/验证脚本/4个dev-docs/WP-TRACE）。映射数据库 `scripts/view-index.csv` 跟踪看法文件与文档的双向映射。

---

## 七、认知闭包体系——basement/

### `views/cognitive-closure.md` — 认知闭包体系分类法

基础设施研发的概念演进视角。认知闭包体系是对三层体系/trace/akash/read/make-plan 背后的概念基础的系统升级——从认知闭包概念定义（006）到工程优化（007）到迭代逼近（008）到孤岛修正（009）到 trace 幂等边界（010）到文档形态（011）到协同可见性困境（012），七篇的综述（013）和论证（014），以及 README 与 view 的统一（015）。当你需要理解这些 skill 背后的概念基础、或推进认知闭包体系的落地时，从这分类法出发。

**覆盖问题场景**：
- 理解认知闭包是什么、为什么是底层必要条件
- 理解如何高效获取闭包（最小 M 问题）和复杂 N 的迭代逼近
- 理解孤岛认知危机和递归 README 遍历的解法
- 理解 trace 幂等的实用边界和粒度决策
- 理解闭包和认知包的文档形态（面相3综述论文）
- 理解协同可见性困境和应对方向
- 推进认知闭包体系的落地（闭包遍历算法/xpath行范围映射/递归README规范等）
- 理解 README 和看法文件的本质关系（都是 view，分类法不同）

**依赖关系**：看法文件 `views/cognitive-closure.md` 索引了 basement/ 下的10篇文档（006-015）。文档间有递进依赖（006→007→008→009→010→011→012→013/014→015）。

---

## 八、变更历史与方案记录——dev-docs/

### `dev-docs/` — 重组方案与执行记录

记录repo目录结构和文档体系变更的方案文档。每个文档记录一次变更：问题诊断、目标结构、设计决策（包括否决的方案）、执行步骤、产出文件清单。下一个AI遇到"要不要改结构"类问题时，先读这里找历史决策，避免重新提议已否决的方案。

**覆盖问题场景**：
- 理解为什么当前目录结构是这样时——读对应的方案文档
- 考虑改目录结构时——先读历史方案，确认不是已否决的方案
- 接手时想了解项目演进过程时——按编号读dev-docs/下的文档

**当前文档**：
- `dev-docs/001-目录结构扁平化重组方案.md`——取消`analysis-devin-failure-system/`嵌套，代码提到根目录，文档统一归入`docs/`分层，`AnalysisSystem开发/`改名`dev/`
- `dev-docs/002-checklist-working-packages拆分.md`——`dev/`拆解为`checklist/`（需求点清单，扁平化）和`working-packages/`（工作包管理），checklist成为研发核心驱动力
- `dev-docs/003-README三层架构与分类法设计.md`——README.md从"文档描述"重构为"分类法索引"的三层架构设计（AGENTS.md→README.md→看法文件），定义7个分类法
- `dev-docs/017-全流程模拟系统设计方案.md`——全流程模拟（src/sim/）：devin命令行层注入剧本演员fake_devin，launcher/feeder/门闸100%真代码真跑于隔离环境（独立DB/Redis前缀/文件根）。7剧本对应launcher全部分支。首日运行捕获5个真bug（含P0：截断→重入队引擎不可达，真实截断被误判dead_session）。用法：`.venv/bin/python -m src.sim.run_sim --scenario solve3`
- `dev-docs/018-teardown误删生产目录事故报告.md`——sim收尾清理时teardown护栏不对称误删生产D盘目录的事故报告：124份proof永久丢失、5958 work_dir已重建、teardown护栏补全+proof入库加固。防再犯规则：清场默认值不指向生产、破坏性操作先预览、成果文件必须双写
- `dev-docs/057-最终成品系统大图与产品定义.md`——最终产品一句话、根原则、长期生命周期、资源模型和完成判据
- `dev-docs/058-最终成品系统Feature-List与需求追踪.md`——全部用户需求的Feature ID冻结表，工作包追踪权威
- `dev-docs/059-无限Round与调度窗口语义规范.md`——默认Round数是本次处理窗口，不是题目寿命；未解题理论无限继续
- `dev-docs/060-观察者解题者核心编排与1962经验基线.md`——原始1962 v1失败/v2成功证据、角色合同和回归要求
- `dev-docs/061-数学真理性形式化验证与审计合同.md`——候选成功、形式化包、审计充分性和最终Gate
- `dev-docs/062-OpenCode-Key池与ACP实例生命周期规范.md`——外部active→deactive、内部capacity/lease、目录opencode.json和secret边界
- `dev-docs/063-Master-Agent监督-stuck处置-SOP与Gate协作规范.md`——程序给证据、SOP发现、Master判断、现有Gate执行
- `dev-docs/064-当前实现差距与实施路线总图.md`——当前HEAD事实、差距、依赖和12包路线
- `dev-docs/final-system-workpackages/`——未来实现AI的自包含工作包总控、启动提示词和WP-01~12

**依赖关系**：无前置依赖，可独立阅读。

---

## 附录：快速开始与Git历史

### 快速开始

1. `cp .env.example .env` 并填入真实配置
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install python-arango redis pyarrow pandas`
4. `source .env`
5. `python -m monitoring.continuation_control status --batch-id p27-full`

### 常用查询命令

| 用途 | 命令 |
|---|---|
| 查询续传系统进度（status分布 + 硬盘验证） | `python -m scripts.query_progress` |
| completed 题硬盘验证明细（有/无 proof.md） | `python -m scripts.query_progress --verify-disk` |
| 查询 completed 题按 source 分布 | `python -m scripts.query_progress --by-source` |
| 查询 completed 题按 round 分布 | `python -m scripts.query_progress --by-round` |
| 全部维度 | `python -m scripts.query_progress --detail` |
| 系统运行状态 | `python -m monitoring.continuation_control status` |
| 题目来源导出（增量） | `python -m scripts.export_new_problems --batch-id p27-full` |
| 题目来源重建（全量） | `python -m scripts.export_new_problems --batch-id p27-full --rebuild` |
| 清洗不符合条件的 run | `python -m scripts.cleanup_continuation_runs --dry-run` |

> 运行前必须 `source .env`（或 `source /Users/user/glm5.2-math-worktree/.env`）。
> 目标题量 10,069 题（405 报告定义的 tier=1 模型能力失败题）。

### 目录结构

见 `working-packages/README.md` 和 `checklist/README.md`

### git 历史

本 repo 从数学大师 repo（`/Users/user/glm5.2-math-worktree/`）用 git filter-repo 拆分而来，
保留了 `src/`、`monitoring/`、`checklist/`、`working-packages/`、5 个设计文档、POC-2.7 数据、
conversation_mapper.py 的完整 commit 历史。
