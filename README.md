# README.md — AI工作引导地图

> **强制声明**：AI必须确保本文件内容在自己的上下文中，才能回答用户的问题或进行后续操作。如果上下文中没有本文件的完整内容，必须先用read工具完整加载本文件，然后再回答问题或操作。
>
> 本文件不是知识，是引导地图。它用inline方式描述每个文档讲什么、覆盖哪些问题场景、和其他文档的关系。AI读完本文件后，判断"用户问的这个问题，我需要加载哪几个文档"，然后用read加载，再工作。

---

## 一、系统认知层——核心入口与全景

### `docs/AnalysisSystem.md` — 新Session接手AI的完整加载指南

新Session AI接手数学大师系统时的入口文档。讲"你在哪、系统是什么状态、要读什么、要做什么"——基本信息（工作目录/Git分支/Python环境/数据库）、项目一句话和三句话定义、当前系统状态（正在进行的核心工作、POC进度）、工作类型分类。

**覆盖问题场景**：
- 新session接手时——"我刚来，这是什么项目，现在做到哪了"
- 确认环境配置——ARANGO_DB是否设置、.venv是否就绪
- 了解当前POC状态——POC-2.7续传Pipe系统进展
- 判断下一步要做什么——工作类型分类指引

**依赖关系**：读完后通常需要加载 `docs/AnalysisSystemDesign.md`（设计总索引）或 `docs/AnalysisSystemOps.md`（运行操作手册），取决于要设计还是运行。

### `docs/AnalysisSystemDesign.md` — 错题分析系统设计总索引

错题分析系统（`analysis-devin-failure-system/`）的设计总索引。快速入口（创建新Pipe/运行现有Pipe/停止系统）、架构决策、组件职责、设计原则。与 Ops 分工：Design=设计总索引/架构/决策，Ops=运行操作/SOP/检查清单。

**覆盖问题场景**：
- 创建新Pipe时——12项必查清单入口、11步操作指南入口
- 运行现有Pipe时——4个Pipe的启动/检查/停止命令速查
- 停止系统时——优雅停止/强制停止/收尾停止命令
- 理解架构决策时——4个Pipe的演进、组件解耦设计
- 查找设计文档时——索引所有需要看的文档和代码资产

**依赖关系**：创建新Pipe时另读 `analysis-devin-failure-system/docs/framework-checklist.md` + `docs/MonitorPipe.md` §6；涉及多轮续传时另读 `docs/续传规范文档.md`；运行操作细节另读 `docs/AnalysisSystemOps.md`。

### `docs/AnalysisSystemOps.md` — 错题分析系统运行操作手册

错题分析系统（`analysis-devin-failure-system/`）的运行操作手册。SOP、检查清单、打磨记录。5组件架构详解（data_collector/feeder/analysis_launcher/result_collector/aggregator）、运行监控操作、问题排查SOP、历史打磨记录。从原 AGENTS.md 第3518-4216行外移（2026-08-19瘦身工程）。

**覆盖问题场景**：
- 运行/监控/调试错题分析系统时
- 理解5组件架构的详细职责和数据流时
- 执行运行操作SOP时——启动/检查/停止/调整并发
- 排查运行问题时——rate limit/stall/zombie/session管理
- 查阅历史打磨记录时——已知问题和修复历史

**依赖关系**：涉及系统设计时另读 `docs/AnalysisSystemDesign.md`；涉及Monitor Pipe检查时另读 `analysis-devin-failure-system/specs/p27_monitor_spec.md`；涉及续传时另读 `docs/续传规范文档.md`。

---

## 二、设计范式层——跨项目元方法论

### `docs/MonitorPipe.md` — Monitor Pipe设计范式

跨项目的"连续工作系统Monitor Pipe+检查脚本"设计范式。定义如何写检查规范、如何实现Monitor Pipe、如何写检查脚本的三层架构（规范层/实现层/查询层）。不是某个具体系统的文档，是元范式。具体系统的检查规范是系统资产（如 `specs/p27_monitor_spec.md`）。

**覆盖问题场景**：
- 设计新系统的Monitor Pipe时——三层架构、A/B/C类检查定义
- 实现Monitor Pipe时——11步操作指南
- 编写检查脚本时——查询脚本设计模式
- 理解Master AI在连续工作系统中的检查者角色时

**依赖关系**：具体系统的检查规范是该系统的系统资产（如 `analysis-devin-failure-system/specs/p27_monitor_spec.md`）；本地版见 `analysis-devin-failure-system/docs/monitor-pipe-pattern.md`。

### `docs/续传规范文档.md` — HANDOFF标准（交接文档续传方案）

定义交接文档（HANDOFF.md）的标准结构、提取规则、循环操作流程。八个必填章节、续传不是"拼接thinking"而是"交接研究"的核心认知、截断/完成判定标准、prompt模板。源自POC-2.6续传机制v1方案（机械拼接reasoning_content）的改进。

**覆盖问题场景**：
- 实现多轮续传机制时——HANDOFF.md八章节结构
- 编写续传prompt模板时
- 判定AI是否被截断/是否完成时
- 理解续传的核心认知转变时——从"拼接thinking"到"交接研究"

**依赖关系**：续传实现代码在 `analysis-devin-failure-system/`（Pipe 4）；运行操作见 `docs/AnalysisSystemOps.md`。

---

## 三、子系统——analysis-devin-failure-system/

### `analysis-devin-failure-system/README.md` — 子系统快速导航

批量并发devin cli实例运行框架的入口。4个Pipe（分析/审计/选题/续传）快速导航、创建新Pipe流程、运行现有Pipe命令速查、停止/调整并发操作、文档体系索引、架构概览、共享基础设施、设计原则。

**覆盖问题场景**：
- 第一次进入子系统时——了解4个Pipe和整体架构
- 创建新Pipe时——必读清单入口
- 运行/停止/调整现有Pipe时——命令速查
- 查找子系统内文档时——docs/specs/templates索引

**依赖关系**：创建新Pipe时另读 `docs/framework-checklist.md`；运行操作细节另读根目录 `docs/AnalysisSystemOps.md`；Monitor Pipe设计另读根目录 `docs/MonitorPipe.md`。

### `analysis-devin-failure-system/docs/` — 架构设计文档（8个）

子系统本地架构设计文档集。每个文档覆盖一个设计方面：

- **`framework-checklist.md`** — 新Pipe必读的12项必查清单。**覆盖场景**：创建新Pipe前。**依赖**：配合 `docs/MonitorPipe.md` §6 使用。
- **`architecture.md`** — 4个Pipe的演进与组件职责。**覆盖场景**：理解系统整体架构时。**依赖**：设计总索引见根目录 `docs/AnalysisSystemDesign.md`。
- **`graceful-shutdown.md`** — 优雅停止设计（信号处理、不kill devin实例）。**覆盖场景**：实现停止功能时。
- **`dynamic-concurrency.md`** — 动态并发设计（运行期调整并发数）。**覆盖场景**：实现并发调整时。
- **`monitor-pipe-pattern.md`** — Monitor Pipe设计范式（本地版）。**覆盖场景**：实现Monitor Pipe时。**依赖**：完整范式见根目录 `docs/MonitorPipe.md`。
- **`operational-concerns.md`** — 运维关注点（rate limit/stall/zombie/多轮续传/断点续传）。**覆盖场景**：实现launcher核心逻辑时。**依赖**：运行操作SOP见根目录 `docs/AnalysisSystemOps.md`。
- **`selfrun-workflow.md`** — selfrun工作流。**覆盖场景**：使用selfrun模式时。**依赖**：selfrun任务模板见 `templates/selfrun_subagent_task.md`。
- **`solver-trajectory-schema.md`** — trajectory数据schema。**覆盖场景**：处理trajectory数据时。
- **`solver-harness-borrowing.md`** — 解题系统借鉴分析（7个值得借鉴的设计）。**覆盖场景**：从解题系统借鉴设计到错题分析系统时、理解多模块解耦/独立服务设计时。

### `analysis-devin-failure-system/specs/` — 检查规范（系统资产，3个）

POC-2.7续传Pipe的检查规范集，Monitor Pipe和Monitor Exec Devin的执行依据：

- **`p27_monitor_spec.md`** — Pipe 4续传的检查规范（A类9项自动检查/B类9项续传质量/C类5项AI判断）。**覆盖场景**：实现Monitor Pipe检查逻辑时、查阅检查标准时。**依赖**：设计范式见根目录 `docs/MonitorPipe.md`。
- **`p27_session_management_and_polish_spec.md`** — Session编号化管理与打磨devin架构规范。**覆盖场景**：实现session编号化管理时、实现Monitor Exec Devin自动修复架构时。**依赖**：前置依赖 `p27_monitor_spec.md`。
- **`p27_monitor_pipe_operations.md`** — Monitor Pipe操作规范（Monitor Exec Devin的认知资产入口）。**覆盖场景**：Monitor Exec Devin启动时加载、查找所有认知资产入口时。**依赖**：检查规范详情见 `p27_monitor_spec.md`、session管理见 `p27_session_management_and_polish_spec.md`。

### `analysis-devin-failure-system/templates/` — 模板（4个）

各Pipe的AGENTS.md模板和selfrun任务模板：

- **`analysis_agents_md.md`** — 分析Pipe的AGENTS.md模板（devin cli分析失败题的prompt）。**覆盖场景**：构造分析任务AGENTS.md时。
- **`audit_agents_md.md`** — 审计Pipe的AGENTS.md模板。**覆盖场景**：构造审计任务AGENTS.md时。
- **`selection_agents_md.md`** — 选题Pipe的AGENTS.md模板。**覆盖场景**：构造选题任务AGENTS.md时。
- **`selfrun_subagent_task.md`** — selfrun模式subagent任务执行规范（v3）。**覆盖场景**：使用selfrun模式替代devin cli载体时。**依赖**：selfrun工作流见 `docs/selfrun-workflow.md`。

---

## 四、开发工作包管理——AnalysisSystem开发/

### `AnalysisSystem开发/README.md` — 目录说明（静态）

`AnalysisSystem开发/` 目录的结构说明+使用指南。目录结构图、文件类型说明、README与INDEX的关系、编号规则（需求点编号/工作包编号）、新AI接手时的阅读顺序、维护规则。静态文档，很少改。

**覆盖问题场景**：
- 第一次进入开发工作包目录时——了解这里有什么、怎么导航
- 查询编号规则时——门类代号、需求点编号格式、工作包编号格式
- 确认阅读顺序时——README→INDEX→CheckList→WP→CheckPoints
- 确认维护规则时——什么时候改哪个文件

**依赖关系**：读完后读 `INDEX.md` 了解当前进度；读 `CheckList.md` 了解全部需求点。

### `AnalysisSystem开发/INDEX.md` — 工作包跟踪表（动态）

10个工作包（WP-01~WP-10）的清单+依赖图+执行顺序+当前系统状态。动态文档，经常改。包含WP状态（待执行/进行中/完成）、优先级（P0/P1/P2）、依赖关系图、执行顺序建议、当前系统状态快照、铁律提醒。

**覆盖问题场景**：
- 了解当前工作包状态时——哪个WP做到哪了
- 规划执行顺序时——依赖图和执行顺序建议
- 查看当前系统状态时——DB状态、已完成commit、已知未修复问题
- 确认铁律提醒时——改代码同步文档、git显式路径add、不kill无DONE.md的session

**依赖关系**：执行某个WP时读对应的 `WP-XX-*.md`；了解需求点详情读 `CheckList.md`。

### `AnalysisSystem开发/CheckList.md` — 需求点全集

错题分析系统全部功能需求点的分门别类清单。13门类127+个需求点，编号+状态标记。用途：开发前确认无遗漏、开发中WP和commit可引用编号、验收时逐项打勾、跨session新AI一眼看清全貌。状态标记：`[ ]`待做/`[~]`进行中/`[x]`已完成/`[!]`已知有问题/`[-]`决定不做。

**覆盖问题场景**：
- 开发前确认功能无遗漏时
- 开发中引用需求点编号时（WP和commit message可引用）
- 验收时逐项打勾判定系统是否完成时
- 跨session新AI了解系统全貌时

**依赖关系**：需求点详情读 `CheckPoints/<门类>/<编号>.md`（如存在）；Exec Devin必读子集见 `CheckList-ExecDevin.md`。

### `AnalysisSystem开发/CheckList-ExecDevin.md` — Exec Devin必读子集

从CheckList全集提取的Exec Devin必读需求点（约68个，第一档+第二档）。Monitor Exec Devin的执行依据。

**覆盖问题场景**：
- Monitor Exec Devin启动时加载——知道自己要检查什么
- 确认Exec Devin的必读需求点时

**依赖关系**：完整需求点见 `CheckList.md`；检查规范见 `analysis-devin-failure-system/specs/p27_monitor_pipe_operations.md`。

### `AnalysisSystem开发/WP-01~WP-10` — 工作包实施计划（10个）

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

**依赖关系**：WP状态和执行顺序见 `INDEX.md`；WP引用的需求点详情见 `CheckList.md` 和 `CheckPoints/`。

---

## 附录：快速开始与Git历史

### 快速开始

1. `cp .env.example .env` 并填入真实配置
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install python-arango redis pyarrow pandas`
4. `source .env`
5. `cd analysis-devin-failure-system && python -m monitoring.continuation_control status --batch-id p27-full`

### 目录结构

见 `AnalysisSystem开发/README.md`

### git 历史

本 repo 从数学大师 repo（`/Users/user/glm5.2-math-worktree/`）用 git filter-repo 拆分而来，
保留了 `analysis-devin-failure-system/`、`AnalysisSystem开发/`、5 个设计文档、POC-2.7 数据、
conversation_mapper.py 的完整 commit 历史。
