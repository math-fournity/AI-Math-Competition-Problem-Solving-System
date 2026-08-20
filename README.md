# README.md — AI工作引导地图

> **强制声明**：AI必须确保本文件内容在自己的上下文中，才能回答用户的问题或进行后续操作。如果上下文中没有本文件的完整内容，必须先用read工具完整加载本文件，然后再回答问题或操作。
>
> 本文件不是知识，是引导地图。它用inline方式描述每个文档讲什么、覆盖哪些问题场景、和其他文档的关系。AI读完本文件后，判断"用户问的这个问题，我需要加载哪几个文档"，然后用read加载，再工作。

---

## 一、系统认知层——核心入口与全景

### `docs/system/AnalysisSystem.md` — 新Session接手AI的完整加载指南

新Session AI接手数学大师系统时的入口文档。讲"你在哪、系统是什么状态、要读什么、要做什么"——基本信息（工作目录/Git分支/Python环境/数据库）、项目一句话和三句话定义、当前系统状态（正在进行的核心工作、POC进度）、工作类型分类。

**覆盖问题场景**：
- 新session接手时——"我刚来，这是什么项目，现在做到哪了"
- 确认环境配置——ARANGO_DB是否设置、.venv是否就绪
- 了解当前POC状态——POC-2.7续传Pipe系统进展
- 判断下一步要做什么——工作类型分类指引

**依赖关系**：读完后通常需要加载 `docs/system/AnalysisSystemDesign.md`（设计总索引）或 `docs/system/AnalysisSystemOps.md`（运行操作手册），取决于要设计还是运行。

### `docs/system/AnalysisSystemDesign.md` — 错题分析系统设计总索引

错题分析系统的设计总索引。快速入口（创建新Pipe/运行现有Pipe/停止系统）、架构决策、组件职责、设计原则。与 Ops 分工：Design=设计总索引/架构/决策，Ops=运行操作/SOP/检查清单。

**覆盖问题场景**：
- 创建新Pipe时——12项必查清单入口、11步操作指南入口
- 运行现有Pipe时——4个Pipe的启动/检查/停止命令速查
- 停止系统时——优雅停止/强制停止/收尾停止命令
- 理解架构决策时——4个Pipe的演进、组件解耦设计
- 查找设计文档时——索引所有需要看的文档和代码资产

**依赖关系**：创建新Pipe时另读 `docs/architecture/framework-checklist.md` + `docs/patterns/MonitorPipe.md` §6；涉及多轮续传时另读 `docs/patterns/续传规范文档.md`；运行操作细节另读 `docs/system/AnalysisSystemOps.md`。

### `docs/system/AnalysisSystemOps.md` — 错题分析系统运行操作手册

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

### `docs/patterns/续传规范文档.md` — HANDOFF标准（交接文档续传方案）

定义交接文档（HANDOFF.md）的标准结构、提取规则、循环操作流程。八个必填章节、续传不是"拼接thinking"而是"交接研究"的核心认知、截断/完成判定标准、prompt模板。源自POC-2.6续传机制v1方案（机械拼接reasoning_content）的改进。

**覆盖问题场景**：
- 实现多轮续传机制时——HANDOFF.md八章节结构
- 编写续传prompt模板时
- 判定AI是否被截断/是否完成时
- 理解续传的核心认知转变时——从"拼接thinking"到"交接研究"

**依赖关系**：续传实现代码在 `src/continuation_*.py`（Pipe 4）；运行操作见 `docs/system/AnalysisSystemOps.md`。

---

## 三、架构设计——docs/architecture/

### `docs/architecture/` — 架构设计文档（9个）

架构设计文档集。每个文档覆盖一个设计方面：

- **`framework-checklist.md`** — 新Pipe必读的12项必查清单。**覆盖场景**：创建新Pipe前。**依赖**：配合 `docs/patterns/MonitorPipe.md` §6 使用。
- **`architecture.md`** — 4个Pipe的演进与组件职责。**覆盖场景**：理解系统整体架构时。**依赖**：设计总索引见根目录 `docs/system/AnalysisSystemDesign.md`。
- **`graceful-shutdown.md`** — 优雅停止设计（信号处理、不kill devin实例）。**覆盖场景**：实现停止功能时。
- **`dynamic-concurrency.md`** — 动态并发设计（运行期调整并发数）。**覆盖场景**：实现并发调整时。
- **`monitor-pipe-pattern.md`** — Monitor Pipe设计范式（本地版）。**覆盖场景**：实现Monitor Pipe时。**依赖**：完整范式见根目录 `docs/patterns/MonitorPipe.md`。
- **`operational-concerns.md`** — 运维关注点（rate limit/stall/zombie/多轮续传/断点续传）。**覆盖场景**：实现launcher核心逻辑时。**依赖**：运行操作SOP见根目录 `docs/system/AnalysisSystemOps.md`。
- **`selfrun-workflow.md`** — selfrun工作流。**覆盖场景**：使用selfrun模式时。**依赖**：selfrun任务模板见 `docs/templates/selfrun_subagent_task.md`。
- **`solver-trajectory-schema.md`** — trajectory数据schema。**覆盖场景**：处理trajectory数据时。
- **`solver-harness-borrowing.md`** — 解题系统借鉴分析（7个值得借鉴的设计）。**覆盖场景**：从解题系统借鉴设计到错题分析系统时、理解多模块解耦/独立服务设计时。

### `docs/specs/` — 检查规范（系统资产，3个）

POC-2.7续传Pipe的检查规范集，Monitor Pipe和Monitor Exec Devin的执行依据：

- **`p27_monitor_spec.md`** — Pipe 4续传的检查规范（A类9项自动检查/B类9项续传质量/C类5项AI判断）。**覆盖场景**：实现Monitor Pipe检查逻辑时、查阅检查标准时。**依赖**：设计范式见根目录 `docs/patterns/MonitorPipe.md`。
- **`p27_session_management_and_polish_spec.md`** — Session编号化管理与打磨devin架构规范。**覆盖场景**：实现session编号化管理时、实现Monitor Exec Devin自动修复架构时。**依赖**：前置依赖 `docs/specs/p27_monitor_spec.md`。
- **`p27_monitor_pipe_operations.md`** — Monitor Pipe操作规范（Monitor Exec Devin的认知资产入口）。**覆盖场景**：Monitor Exec Devin启动时加载、查找所有认知资产入口时。**依赖**：检查规范详情见 `docs/specs/p27_monitor_spec.md`、session管理见 `docs/specs/p27_session_management_and_polish_spec.md`。

### `docs/templates/` — 模板（4个）

各Pipe的AGENTS.md模板和selfrun任务模板：

- **`analysis_agents_md.md`** — 分析Pipe的AGENTS.md模板（devin cli分析失败题的prompt）。**覆盖场景**：构造分析任务AGENTS.md时。
- **`audit_agents_md.md`** — 审计Pipe的AGENTS.md模板。**覆盖场景**：构造审计任务AGENTS.md时。
- **`selection_agents_md.md`** — 选题Pipe的AGENTS.md模板。**覆盖场景**：构造选题任务AGENTS.md时。
- **`selfrun_subagent_task.md`** — selfrun模式subagent任务执行规范（v3）。**覆盖场景**：使用selfrun模式替代devin cli载体时。**依赖**：selfrun工作流见 `docs/architecture/selfrun-workflow.md`。

---

## 四、需求点清单——checklist/

### `checklist/README.md` — 需求点清单索引

错题分析系统全部功能需求点的索引。14个门类134个需求点，每个需求点（checkpoint）一个独立文件，文件名即编号。README.md 只保留门类索引表+编号规则+状态标记说明，不重复每个 checkpoint 的内容。用 checklist 推进和管理整个项目研发，每个 checkpoint 记录它涉及的文档和代码。

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

### `checklist/MasterAgentCheck.md` — Master Agent 检查工作清单

Master Agent 接管 Monitor Pipe 检查工作后使用的检查清单（取代 ExecDevin.md 的角色）。从 ExecDevin.md 提取 Master Agent 需要执行的检查项，重新组织为"Master Agent 视角"。包含6个部分：C类AI判断（MON-C1~C5）、self-check（SELF-S1~S17）、新alert分类处理、已知问题诊断（MON-A-issue-01~05）、落盘完整性检查、修复操作规范。

**覆盖问题场景**：
- Master Agent 检查系统状态时——运行 `./scripts/monitor_check_continuation.sh <batch_id>` 后全文加载本文件逐项处理
- 确认 Master Agent 需要执行哪些检查项时
- 查找某个检查项的处理方式时

**依赖关系**：完整需求点索引见 `checklist/README.md`；检查规范见 `docs/specs/p27_monitor_spec.md`；来源（历史参考）见 `checklist/ExecDevin.md`；需求来源见 `dev-docs/005-Master-Agent接管Monitor-Pipe检查工作.md` + `dev-docs/006-Master-Agent接管Monitor-Pipe检查工作方案.md`。

### `checklist/<编号>.md` — 单个checkpoint详情（153个）

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

基础设施研发的概念演进视角。认知闭包体系是对三层体系/trace/akash/read/make-plan 背后的概念基础的系统升级——从认知闭包概念定义（006）到工程优化（007）到迭代逼近（008）到孤岛修正（009）到 trace 幂等边界（010）到文档形态（011）到协同可见性困境（012），以及七篇的综述（013）和论证（014）。当你需要理解这些 skill 背后的概念基础、或推进认知闭包体系的落地时，从这分类法出发。

**覆盖问题场景**：
- 理解认知闭包是什么、为什么是底层必要条件
- 理解如何高效获取闭包（最小 M 问题）和复杂 N 的迭代逼近
- 理解孤岛认知危机和递归 README 遍历的解法
- 理解 trace 幂等的实用边界和粒度决策
- 理解闭包和认知包的文档形态（面相3综述论文）
- 理解协同可见性困境和应对方向
- 推进认知闭包体系的落地（闭包遍历算法/xpath行范围映射/递归README规范等）

**依赖关系**：看法文件 `views/cognitive-closure.md` 索引了 basement/ 下的9篇文档（006-014）。文档间有递进依赖（006→007→008→009→010→011→012→013/014）。

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

**依赖关系**：无前置依赖，可独立阅读。

---

## 附录：快速开始与Git历史

### 快速开始

1. `cp .env.example .env` 并填入真实配置
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install python-arango redis pyarrow pandas`
4. `source .env`
5. `python -m monitoring.continuation_control status --batch-id p27-full`

### 目录结构

见 `working-packages/README.md` 和 `checklist/README.md`

### git 历史

本 repo 从数学大师 repo（`/Users/user/glm5.2-math-worktree/`）用 git filter-repo 拆分而来，
保留了 `src/`、`monitoring/`、`checklist/`、`working-packages/`、5 个设计文档、POC-2.7 数据、
conversation_mapper.py 的完整 commit 历史。
