# 005-Master-Agent接管Monitor-Pipe检查工作

**日期**：2026-08-19
**性质**：需求记录和分析文档（akash 阶段1）
**状态**：需求已记录，待进入阶段2（方案制定）

---

## §1 用户原话

> 我们这个系统，是一个做题的系统，曾经它是一个错题分析系统，经过打磨，觉得还挺好用，所以后来就用来做题了。做题这个事情以前是用裸模型直接上。但是后来，我们发明了续传技术，通过续传技术，可以让AI做出来原本直接上做不出来的题目，可是，当续传技术被引入之后，其实系统有很多bug，需要连续的打磨，也就是说，需要一个AI不停地观察整个做题过程的各个pipe的输出、输入，甚至包括整个系统代码的运行，是不是合理的。有很多checklist需要AI去检查，最重要的，就是整个做题过程是完整落盘的，可能需要很多round，每个round都要落盘。这个不停打磨系统的AI，本来是由你——Master Agent来承担的，但是以为你长期运行的过程中，会遗忘之前立下的约定和要求，尤其是在之前的repo中它的AGENTS.md非常巨大，以至于无法把必要的内容放入，从而保证AI的跨越Session的认知一致性。所以这一次，我的想法是，不排除，把那个Monitor Pipe中的devin cli的工作，完全交到你这边，也就是说把它要进行的检查，全部让你做，我认为是可以的，不是要膨胀项目内的AGENTS.md，恰恰相反，我们可以利用之前的一种策略：有一个检查脚本，检查所有可以用脚本检查的内容。这个脚本会输出提示，提示你进行后续的检查和修复操作。而这些操作，完全可以是让你全文加载一个checklist，然后逐项处理。而脚本运行完成之后，要全文加载一个checklist文件并逐项处理这件事，也是可以放入项目内的AGENTS.md的最前面的，记住，这些要放在最前面，放在后面会被截断，可能在连续的运行过程中，你就看不到了。全文记录我的需求。

---

## §2 需求解读

### 背景

系统从"错题分析系统"演进为"做题系统"。引入续传技术后，AI 能做出原本做不出的题，但系统复杂度大增，产生很多 bug，需要持续打磨。

### 核心问题

原来有一个独立的 Monitor Pipe（devin cli 实例）负责检查系统运行状态。但它存在认知一致性问题：长期运行的 AI 会遗忘约定，且 AGENTS.md 太大无法完整注入。

### 解决方案

**把 Monitor Pipe 的检查工作交给 Master Agent（即当前 AI）**。具体策略：

1. **检查脚本**——编写一个脚本，检查所有可以用脚本检查的内容（自动化部分）
2. **脚本输出提示**——脚本运行后输出提示，提示 Master Agent 进行后续的检查和修复操作（需要 AI 判断的部分）
3. **全文加载 checklist 逐项处理**——脚本运行完后，Master Agent 全文加载一个 checklist 文件，逐项处理
4. **项目 AGENTS.md 最前面放指令**——"脚本运行完成后全文加载 checklist 并逐项处理"这个指令放在项目 AGENTS.md 的**最前面**，因为放在后面会被截断，连续运行中可能看不到

### 关键约束

- **不膨胀项目 AGENTS.md**——恰恰相反，要利用检查脚本+checklist 的策略来避免 AGENTS.md 膨胀
- **放在最前面**——项目 AGENTS.md 中关于"脚本运行后加载 checklist 逐项处理"的指令必须放在文件最前面，防止截断
- **完整落盘**——整个做题过程可能需要很多 round，每个 round 都要完整落盘

---

## §3 需求分析（利用 trace.csv 追溯）

### 现有相关元素

**检查脚本（已有）**：
- `scripts/monitor_check.sh` — 标准化 Monitor Pipe 检查脚本（4项检查：pane输出/alerts/进程状态/进度）
- `scripts/monitor_check_continuation.sh` — 续传检查脚本
- `scripts/monitor_check_selection.sh` — 选题检查脚本

**监控代码（已有）**：
- `monitoring/runtime_health_check.py` — 运行时健康检查（10个维度 A-J：Redis原子性/DB-Redis一致性/重复run/并发上限/devin进程数/网络/异常退出率/落盘完整性/批次进度/日志健康）
- `monitoring/analysis_control.py` — 分析控制（A类检查项的实现）
- `monitoring/continuation_control.py` — 续传控制
- `monitoring/verify_completeness.py` — 完整性验证
- `monitoring/verify_result_integrity.py` — 结果完整性验证

**检查需求点（已有 checkpoint）**：
- MON-A1~A12 — Monitor Pipe A类自动检查（12项）
- MON-B1~B9 — Monitor Pipe B类检查（9项）
- MON-C1~C5 — Monitor Pipe C类检查（5项）
- 共 26 个 MON 检查需求点

**ExecDevin 子集（已有）**：
- `checklist/ExecDevin.md` — Monitor Exec Devin 必读需求点子集（从127个需求点中提取的检查相关子集）

**规范文档（已有）**：
- `docs/specs/p27_monitor_spec.md` — Monitor Pipe 规范
- `docs/specs/p27_monitor_pipe_operations.md` — Monitor Pipe 操作规范
- `docs/patterns/MonitorPipe.md` — Monitor Pipe 设计范式

### 分析

1. **已有基础**：系统已有大量检查脚本和检查需求点（MON-A/B/C 共26项），已有 `monitor_check.sh` 标准化检查脚本，已有 `runtime_health_check.py` 10维度健康检查。不是从零开始。

2. **核心变化**：原来这些检查由独立的 Monitor Pipe devin cli 实例执行，现在要由 Master Agent（当前 AI）执行。这意味着：
   - 检查脚本可以直接复用，但执行者变了
   - 检查结果的后续处理（判断+修复）由 Master Agent 做
   - 不需要独立的 Monitor Pipe devin cli 实例

3. **AGENTS.md 策略**：
   - 项目 AGENTS.md 最前面放"脚本运行后加载 checklist 逐项处理"的指令
   - 不把所有检查项放 AGENTS.md（那会膨胀）
   - 检查项放 checklist 文件中，AI 按需全文加载

4. **可能的新 checkpoint**：这个需求可能产生新的 checkpoint——关于"Master Agent 接管检查工作"本身的功能需求点。但需要阶段2方案制定时确认。

---

## §4 是否产生新的 checkpoint

**初步判断**：可能产生新 checkpoint，但需要在阶段2方案制定时确认。

**可能的新 checkpoint 方向**：
- MAMON（Master Agent Monitor）门类——关于 Master Agent 执行检查工作的功能需求点
- 或者扩展现有 MON-A/B/C 门类

**不急于建立**——先在阶段2方案中分析清楚再决定。

---

## §5 验收标准

1. **检查脚本**——有一个（或复用已有的）检查脚本，能检查所有可以用脚本检查的内容
2. **脚本输出提示**——脚本运行后输出提示，提示 Master Agent 进行后续检查和修复
3. **checklist 文件**——有一个 checklist 文件，包含需要 Master Agent 逐项处理的所有检查项
4. **项目 AGENTS.md 最前面**——有明确指令："脚本运行完成后，全文加载 checklist 文件并逐项处理"，放在 AGENTS.md 最前面
5. **Master Agent 能执行**——Master Agent 按指令执行：运行脚本 → 看提示 → 加载 checklist → 逐项处理
6. **不膨胀 AGENTS.md**——项目 AGENTS.md 保持精简，检查项不在 AGENTS.md 中，在 checklist 文件中

---

## §6 涉及的元素

**会改动的文件**：
- `AGENTS.md`（项目）——最前面加指令
- `scripts/`——可能新建或改进检查脚本
- `checklist/`——可能新建 checklist 文件（Master Agent 检查清单）

**会涉及的现有元素**：
- `scripts/monitor_check.sh` — 可能复用或改进
- `scripts/monitor_check_continuation.sh` — 可能复用或改进
- `monitoring/runtime_health_check.py` — 可能复用或改进
- `checklist/ExecDevin.md` — 可能参考或合并
- `checklist/MON-A*.md` ~ `MON-C*.md` — 检查项来源
- `docs/specs/p27_monitor_spec.md` — 检查规范来源

**trace.csv 中需要记录的关系**：
- 新检查脚本 → 依赖的现有脚本/代码
- 新 checklist 文件 → 来源的 MON-A/B/C 检查项
- AGENTS.md 变更 → commit
