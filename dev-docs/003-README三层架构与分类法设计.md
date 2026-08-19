# README.md三层架构：从引导地图到分类法索引

**日期**：2026-08-19
**性质**：设计方案——定义README.md的三层架构和7个分类法
**前置**：002-checklist-working-packages拆分.md（checklist/和working-packages/已拆到根目录）
**状态**：方案待实施

---

## §1 问题诊断

### 当前README.md的问题

当前README.md是"所有文档的详细描述铺平在6个章节里"——每个文档一段描述（讲什么/覆盖问题场景/依赖关系），共15个描述条目。这有两个问题：

1. **无限膨胀**——文档增多时README.md会越来越大。现在15个条目还可控，但项目继续增长到50+文档时不可持续
2. **没有抽象到"看法"层**——README.md直接跳到"每个文档讲什么"，跳过了"有哪些视角可以看这个项目"这一层。AI读完README.md后知道有哪些文档，但不知道"我当前的问题应该用哪种视角来看"

### 根因

README.md的定位不够清晰。它试图同时做两件事：
- 索引"有哪些视角可以看这个项目"（分类法层）
- 描述"每个文档讲什么"（文档层）

这两层应该分开——README.md只做分类法索引，文档描述移到对应的看法文件中。

---

## §2 三层架构

### 第一层：AGENTS.md — 铁律 + 最小索引

- **always-on**，每个session自动加载
- 只放硬约束、行为规范、最小文档索引表
- 不放文档详细描述、不放分类法详细描述
- **当前状态**：已就绪

### 第二层：README.md — 分类法索引

- AI接手时加载，判断"我当前的问题需要哪种分类法"
- 每个分类法一段描述：视角是什么、加载能得到什么、看法文件在哪里
- **不描述具体文档**——具体文档的描述在第三层（看法文件）中
- **当前状态**：需要重构（从"文档描述"改为"分类法索引"）

### 第三层：看法文件 — 某种视角下的文档/代码/资产索引

- 每种分类法一个看法文件
- 说清楚：加载能得到什么、索引了哪些文件、那些文件分别讲什么
- AI加载看法文件后，再判断"需要加载哪些具体文档"
- **当前状态**：7个分类法中2个已有看法文件，5个待建

### 三层之间的关系

```
AGENTS.md（铁律+最小索引）
  ↓ 引导
README.md（分类法索引——"有哪些视角"）
  ↓ 引导
看法文件（某种视角下的文档索引——"这个视角下有哪些文档"）
  ↓ 引导
具体文档/代码/资产
```

AI的工作流：
1. 读AGENTS.md——知道硬约束
2. 读README.md——判断当前问题需要哪种分类法
3. 读对应的看法文件——判断需要哪些具体文档
4. 读具体文档——工作

---

## §3 核心概念：分类法

### 什么是分类法

分类法 = 同一批知识的不同切片视角。就像数据库的视图——底层数据一样，按不同维度组织展示。

同一个项目的全部知识（代码、文档、数据、需求、工作包、变更历史），可以从不同维度去组织理解。每种分类法是对同一批知识的不同组织方式。

### 分类法的性质

1. **视图重叠**——同一个文档可能被多个分类法索引。如 `docs/system/AnalysisSystemOps.md` 既属于"系统认知分类法"（了解系统状态），也属于"运行操作分类法"（运行操作SOP）。这不是问题——视图之间本来就有重叠。

2. **不是所有分类法都覆盖全部知识**——每种分类法只索引"从该视角看时有意义"的知识。如"历史分类法"只索引变更记录，不索引checkpoint详情。

3. **分类法可以新增**——项目演进中可能出现新的视角。新增分类法时，在README.md中加一段描述，创建对应的看法文件。

---

## §4 7个分类法设计

### 当前项目的全部知识资产

- `src/`（30个Python文件）+ `monitoring/`（16个文件）+ `run_*.py`（4个入口）+ `scripts/`（8个脚本）
- `docs/system/`（3个）、`docs/patterns/`（2个）、`docs/architecture/`（9个）、`docs/specs/`（3个）、`docs/templates/`（4个）
- `checklist/`（155个文件：README + ExecDevin + 153个checkpoint）
- `working-packages/`（12个文件：README + INDEX + 10个WP）
- `dev-docs/`（2个方案文档）
- `data/poc_2.7/`（数据）

### 7个分类法

#### 1. 系统认知分类法 — "系统是什么、当前什么状态"

- **视角**：新AI接手时，需要快速了解"这是什么项目、当前做到哪了、环境是什么"
- **索引内容**：
  - `docs/system/AnalysisSystem.md`（接手指南：工作目录/Git分支/Python环境/数据库/项目定义/当前状态/工作类型分类）
  - `docs/system/AnalysisSystemDesign.md`（设计总索引：快速入口/架构决策/组件职责/设计原则）
  - `AGENTS.md`（项目级：硬约束/快速开始）
- **看法文件**：待建（建议放 `docs/system/README.md`）
- **和其他分类法的关系**：和"运行操作分类法"有重叠（AnalysisSystemOps.md既属于系统认知也属于运行操作）

#### 2. 设计决策分类法 — "为什么这样设计"

- **视角**：理解架构决策、设计原则、范式、否决方案
- **索引内容**：
  - `docs/architecture/`（9个架构决策文档：framework-checklist/architecture/graceful-shutdown/dynamic-concurrency/monitor-pipe-pattern/operational-concerns/selfrun-workflow/solver-trajectory-schema/solver-harness-borrowing）
  - `docs/patterns/MonitorPipe.md`（跨项目Monitor Pipe设计范式）
  - `docs/patterns/续传规范文档.md`（HANDOFF标准）
  - `dev-docs/`（2个重组方案：目录结构扁平化、checklist拆分——记录"为什么是现在这个结构"）
- **看法文件**：待建（建议放 `docs/architecture/README.md`）
- **和其他分类法的关系**：和"历史分类法"有重叠（dev-docs既属于设计决策也属于历史）

#### 3. 需求分类法 — "系统要满足什么需求"

- **视角**：从需求点角度看系统——每个需求点是什么、验证方法、状态、涉及哪些文档和代码
- **索引内容**：
  - `checklist/README.md`（门类索引：14门类134个checkpoint）
  - `checklist/ExecDevin.md`（Exec Devin必读子集）
  - 153个checkpoint文件（每个独立文件，记录需求描述/验证方法/涉及的文档和代码/状态/负责的WP/来源/变更记录）
- **看法文件**：`checklist/README.md`（**已有**）
- **和其他分类法的关系**：和"工作流分类法"有重叠（checkpoint的"负责的WP"字段指向working-packages）

#### 4. 源码分类法 — "代码怎么实现的"

- **视角**：从代码角度理解系统——模块结构、组件职责、数据流、调用关系、入口点
- **索引内容**：
  - `src/`（30个Python文件：data_collector/feeder/analysis_launcher/result_collector/aggregator + continuation_* + selection_* + audit_* + selfrun_* + config/db_schema/session_registry等）
  - `monitoring/`（16个文件：analysis_control/continuation_control/redis_queue/monitor_pipe/monitor_continuation/graceful_shutdown/runtime_health_check等）
  - `run_*.py`（4个入口：run_pipeline/run_audit_pipeline/run_selection_pipeline/run_continuation_pipeline）
  - `scripts/`（8个脚本：monitor_check*.sh/continuation_watchdog.sh/generate_checkpoint.py/fetch_poc0*.py）
  - `docs/architecture/architecture.md`（4个Pipe的演进与组件职责——这是源码视角的设计文档）
  - `docs/architecture/solver-trajectory-schema.md`（trajectory数据schema——源码视角的数据结构）
- **看法文件**：待建（建议放 `src/README.md` 或新建 `docs/code/README.md`）
- **当前问题**：**完全缺失**——没有任何文档从源码视角索引代码结构。这是最大的盲区。
- **和其他分类法的关系**：和"设计决策分类法"有重叠（architecture.md既属于源码也属于设计决策）

#### 5. 工作流分类法 — "怎么开发推进"

- **视角**：从开发流程角度看——工作包、依赖关系、执行顺序、当前进度
- **索引内容**：
  - `working-packages/README.md`（目录说明：结构/文件类型/阅读顺序/维护规则）
  - `working-packages/INDEX.md`（WP跟踪表：状态/依赖图/执行顺序/当前系统状态）
  - `working-packages/WP-01~10`（10个工作包实施计划）
  - `checklist/ExecDevin.md`（Exec Devin的工作流——它的工作循环）
- **看法文件**：`working-packages/README.md`（**已有**）
- **和其他分类法的关系**：和"需求分类法"有重叠（WP引用checkpoint编号）

#### 6. 运行操作分类法 — "怎么运行/监控/调试"

- **视角**：从运行操作角度看——启动/检查/停止/调整并发/问题排查
- **索引内容**：
  - `docs/system/AnalysisSystemOps.md`（运行操作手册：SOP/检查清单/5组件架构详解/问题排查/打磨记录）
  - `docs/specs/p27_monitor_spec.md`（Pipe 4续传检查规范：A类9项/B类9项/C类5项）
  - `docs/specs/p27_session_management_and_polish_spec.md`（Session编号化管理与打磨规范）
  - `docs/specs/p27_monitor_pipe_operations.md`（Monitor Pipe操作规范：Exec Devin认知资产入口）
  - `scripts/monitor_check.sh`（Pipe 1/2检查脚本）
  - `scripts/monitor_check_selection.sh`（Pipe 3检查脚本）
  - `scripts/monitor_check_continuation.sh`（Pipe 4检查脚本）
  - `scripts/continuation_watchdog.sh`（看门狗）
  - `monitoring/`（监控代码：analysis_control/continuation_control/runtime_health_check等）
  - `docs/architecture/operational-concerns.md`（运维关注点：rate limit/stall/zombie/多轮续传/断点续传）
  - `docs/architecture/graceful-shutdown.md`（优雅停止设计）
  - `docs/architecture/dynamic-concurrency.md`（动态并发设计）
- **看法文件**：待建（建议放 `docs/specs/README.md` 或新建 `docs/ops/README.md`）
- **和其他分类法的关系**：和"系统认知分类法"有重叠（AnalysisSystemOps.md既属于系统认知也属于运行操作）；和"源码分类法"有重叠（monitoring/代码既属于源码也属于运行操作）

#### 7. 历史分类法 — "怎么演变过来的"

- **视角**：从演变历史角度看——重组方案、决策记录、废弃方案
- **索引内容**：
  - `dev-docs/001-目录结构扁平化重组方案.md`（取消嵌套、代码提到根目录、文档分层）
  - `dev-docs/002-checklist-working-packages拆分.md`（dev/拆解为checklist/和working-packages/）
  - git历史（commit message记录每次变更）
- **看法文件**：待建（建议放 `dev-docs/README.md`）
- **当前问题**：内容单薄——只有2个重组方案，没有更早的演变记录
- **和其他分类法的关系**：和"设计决策分类法"有重叠（dev-docs既属于设计决策也属于历史）

### 分类法总览

| # | 分类法 | 视角 | 看法文件 | 状态 | 和哪些分类法重叠 |
|---|---|---|---|---|---|
| 1 | 系统认知 | 系统是什么、当前什么状态 | `docs/system/README.md`（待建） | 缺失 | 运行操作 |
| 2 | 设计决策 | 为什么这样设计 | `docs/architecture/README.md`（待建） | 缺失 | 历史、源码 |
| 3 | 需求 | 系统要满足什么需求 | `checklist/README.md` | **已有** | 工作流 |
| 4 | 源码 | 代码怎么实现的 | `src/README.md`或`docs/code/README.md`（待建） | 完全缺失 | 设计决策、运行操作 |
| 5 | 工作流 | 怎么开发推进 | `working-packages/README.md` | **已有** | 需求 |
| 6 | 运行操作 | 怎么运行/监控/调试 | `docs/specs/README.md`或`docs/ops/README.md`（待建） | 缺失 | 系统认知、源码 |
| 7 | 历史 | 怎么演变过来的 | `dev-docs/README.md`（待建） | 内容单薄 | 设计决策 |

---

## §5 实施方案

### 阶段1：重构README.md为分类法索引

将当前README.md从"所有文档的详细描述"重构为"7个分类法的索引"——每个分类法一段描述（视角/能得到什么/看法文件路径），具体文档描述移到对应的看法文件中。

README.md新结构：
```markdown
# README.md — 项目认知地图

> 强制声明...

## 分类法索引

本项目可以从以下7种视角理解。每种视角是一个"分类法"——对同一批知识的不同组织方式。判断你当前的问题需要哪种视角，加载对应的看法文件。

### 1. 系统认知分类法 — "系统是什么、当前什么状态"
<视角描述2-3句>
**看法文件**：`docs/system/README.md`
**覆盖场景**：新AI接手时、确认环境配置时、了解当前POC状态时

### 2. 设计决策分类法 — "为什么这样设计"
...

### 3. 需求分类法 — "系统要满足什么需求"
...
**看法文件**：`checklist/README.md`（已有）

### 4. 源码分类法 — "代码怎么实现的"
...

### 5. 工作流分类法 — "怎么开发推进"
...
**看法文件**：`working-packages/README.md`（已有）

### 6. 运行操作分类法 — "怎么运行/监控/调试"
...

### 7. 历史分类法 — "怎么演变过来的"
...

## 附录：快速开始与Git历史
...
```

### 阶段2：新建5个看法文件

为5个缺失的分类法新建看法文件。每个看法文件的结构：
```markdown
# <分类法名> — <视角一句话>

> 加载本文件能得到什么：<这个视角下能看到什么>

## 索引的文件

### `<文件路径>` — <一句话标题>
<讲什么，2-3句>
**覆盖问题场景**：...
**依赖关系**：...
```

5个待建看法文件：
1. `docs/system/README.md` — 系统认知分类法
2. `docs/architecture/README.md` — 设计决策分类法
3. `src/README.md`（或`docs/code/README.md`） — 源码分类法
4. `docs/specs/README.md`（或`docs/ops/README.md`） — 运行操作分类法
5. `dev-docs/README.md` — 历史分类法

### 阶段3：更新已有2个看法文件

`checklist/README.md`和`working-packages/README.md`已存在，但需要确认它们符合看法文件的结构（加载能得到什么/索引了哪些文件/那些文件分别讲什么）。如果不符，调整。

### 阶段4：同步read-sync skill

更新read-sync skill，使其反映三层架构：
- README.md是分类法索引（第二层），不是文档描述
- 看法文件是第三层，由read-sync的"创建看法文件"流程维护
- 验证步骤增加"分类法覆盖性检查"

### 阶段5：验证

- README.md只索引7个分类法，不描述具体文档
- 每个分类法有对应的看法文件
- 每个看法文件索引该视角下的文档/代码/资产
- AI读完README.md后能判断"需要哪种分类法"
- AI读看法文件后能判断"需要加载哪些具体文档"

---

## §6 设计原则

1. **三层分离**——AGENTS.md（铁律）/ README.md（分类法索引）/ 看法文件（文档索引）各司其职，不越层
2. **分类法是视图，不是分区**——同一个文档可以被多个分类法索引，视图重叠是正常的
3. **README.md不描述具体文档**——只描述分类法（视角/能得到什么/看法文件路径）
4. **看法文件描述具体文档**——讲什么/覆盖问题场景/依赖关系
5. **分类法可扩展**——项目演进中可新增分类法，在README.md中加一段描述+创建看法文件
6. **每个分类法独立可用**——AI只需要某一种视角时，只加载对应的看法文件，不需要加载所有看法文件

---

## §7 待决策问题

1. **源码分类法的看法文件放哪里**——`src/README.md`（和代码同目录）还是`docs/code/README.md`（和文档同目录）？
   - `src/README.md`的好处：看法文件和它索引的代码在同一目录
   - `docs/code/README.md`的好处：所有看法文件都在docs/下，统一管理
   - 建议：`src/README.md`——和代码同目录更自然，AI找代码时顺手就能看到源码视角的索引

2. **运行操作分类法的看法文件放哪里**——`docs/specs/README.md`还是`docs/ops/README.md`？
   - `docs/specs/README.md`：运行操作的核心是检查规范，specs/是自然归属
   - `docs/ops/README.md`：新建ops/目录，更明确地表达"运行操作"视角
   - 建议：`docs/specs/README.md`——不新建目录，specs/已经是运行操作视角的核心

3. **已有看法文件是否需要调整**——`checklist/README.md`和`working-packages/README.md`当前结构是否符合作法文件规范？
   - 需要在实施阶段检查
