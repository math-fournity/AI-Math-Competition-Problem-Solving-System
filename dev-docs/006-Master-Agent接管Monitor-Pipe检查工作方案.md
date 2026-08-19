# 006-Master-Agent接管Monitor-Pipe检查工作方案

**日期**：2026-08-19
**性质**：方案文档（akash 阶段2）
**需求引用**：`dev-docs/005-Master-Agent接管Monitor-Pipe检查工作.md`

---

## §1 现状分析（利用 trace.csv 追溯链）

### 1.1 现有检查体系全貌

通过 trace.csv 追溯和文档加载，当前检查体系的全貌：

**检查脚本（3个）**：
- `scripts/monitor_check.sh` — 标准化检查脚本（4项：pane输出/alerts/进程状态/进度），每项后附"需要检查"提示
- `scripts/monitor_check_continuation.sh` — 续传检查脚本
- `scripts/monitor_check_selection.sh` — 选题检查脚本

**监控代码（16个 .py 文件）**：
- `monitoring/runtime_health_check.py` — 10维度运行时健康检查（A-J）
- `monitoring/analysis_control.py` — A类检查项实现（含 `run_analysis`、`check_status` 函数）
- `monitoring/continuation_control.py` — 续传控制
- `monitoring/verify_completeness.py` — 完整性验证
- `monitoring/verify_result_integrity.py` — 结果完整性验证
- （其余11个为支持性代码）

**检查需求点（26个 checkpoint）**：
- MON-A1~A12 — A类自动检查（12项，Python自动执行，AI读alert做分类处理）
- MON-B1~B9 — B类续传质量检查（9项，含B8的6个子项）
- MON-C1~C5 — C类AI判断（5项，**必须由AI做判断**，Python做不了）

**ExecDevin 子集**：
- `checklist/ExecDevin.md` — Monitor Exec Devin 必读需求点子集（约68个需求点）
- 包含：MON-A/B/C + SELF（17项self-check）+ HARD（5条硬约束）+ SESS/LAUNCH/EXEC-CONF（概念）+ EXEC-VERIFY（验证标准）

**规范文档**：
- `docs/specs/p27_monitor_spec.md` — Monitor Pipe 规范（定义A/B/C类检查项）
- `docs/specs/p27_monitor_pipe_operations.md` — Monitor Pipe 操作规范
- `docs/patterns/MonitorPipe.md` — Monitor Pipe 设计范式

### 1.2 原来的工作模式

```
Monitor Pipe（独立 devin cli 实例）
  → 启动后读 WORKLOG.md（跨轮记忆）
  → 读认知资产（6个文档）
  → 读 ExecDevin.md（检查清单子集）
  → 执行工作循环：检查→判断→修复→报告→退出
  → 每轮写 MONITOR_EXEC_REPORT.md + WORKLOG.md
```

**问题**：
1. 独立 devin cli 实例长期运行会遗忘约定
2. AGENTS.md 太大无法完整注入，认知一致性无法保证
3. 跨 session 记忆依赖 WORKLOG.md，但 WORKLOG 可能丢失或不完整

### 1.3 trace.csv 追溯发现的差距

通过 trace.csv 追溯发现：
- `monitor_check_continuation.sh` 和 `monitor_check_selection.sh` **没有任何追溯关系**——孤立资产
- `monitoring/runtime_health_check.py` **没有任何追溯关系**——孤立资产
- `checklist/ExecDevin.md` **没有任何追溯关系**——孤立资产
- `docs/specs/p27_monitor_pipe_operations.md` **没有任何追溯关系**——孤立资产
- MON-A2~A12、MON-B1~B9、MON-C1~C5 **只有 part-of WP-09，没有 implements 关系**——只记录了归属，没记录实现

**这说明**：trace.csv 的幂等关系目前还不完整，很多资产是孤立的。这正是需要在本方案中补全的。

---

## §2 方案设计

### 2.1 核心架构变化

```
原来：
  Monitor Pipe（独立 devin cli）→ 检查 → 判断 → 修复 → 报告

现在：
  检查脚本（自动化）→ 输出提示 → Master Agent（当前AI）
    → 全文加载 checklist → 逐项处理 → 修复 → 记录
```

**关键变化**：
1. 检查脚本负责"可以用脚本检查的内容"——自动化
2. 脚本输出提示，提示 Master Agent 进行后续检查和修复——人机协作
3. Master Agent 全文加载 checklist 文件，逐项处理——AI判断
4. 项目 AGENTS.md 最前面放指令——确保连续运行中不丢失

### 2.2 检查脚本设计

**策略**：不新建脚本，**扩展现有 `scripts/monitor_check.sh`**。

现有 `monitor_check.sh` 已经是标准化检查脚本，4项检查+每项附"需要检查"提示+末尾行动清单。需要扩展：

1. **整合 `runtime_health_check.py` 的10维度检查**——在 monitor_check.sh 中调用 `python -m monitoring.runtime_health_check --batch-id <id>`，输出10维度健康检查结果
2. **整合续传检查**——调用 `monitor_check_continuation.sh` 的核心逻辑
3. **输出"AI后续检查清单"**——脚本末尾输出一个明确的清单，列出需要 Master Agent 逐项处理的项目，指向 checklist 文件

**扩展后的 monitor_check.sh 输出结构**：
```
=== 自动化检查结果 ===
1. Monitor Pipe pane输出（最近5轮）
2. alerts集合（新alert）
3. 进程状态
4. 进度
5. 运行时健康检查（10维度 A-J）  ← 新增
6. 续传检查                       ← 新增

=== AI后续检查清单 ===
>> 以下项目需要 Master Agent 全文加载 checklist/MasterAgentCheck.md 逐项处理：
   - MON-C1~C5：C类AI判断（读proof.md/HANDOVER.md做判断）
   - SELF-S1~S17：self-check（每轮必须执行）
   - 新alert的分类处理（如有）
   - 已知问题的诊断进展（如有未诊断的）
```

### 2.3 Master Agent 检查清单文件

**新建**：`checklist/MasterAgentCheck.md`

**内容**：从 `ExecDevin.md` 中提取 Master Agent 需要执行的所有检查项，重新组织为"Master Agent 视角"的检查清单。

**和 ExecDevin.md 的关系**：
- `ExecDevin.md` 是给独立 Monitor Pipe devin cli 用的——现在不用了
- `MasterAgentCheck.md` 是给 Master Agent 用的——取代 ExecDevin.md 的角色
- 内容有重叠但视角不同：ExecDevin 是"独立AI的视角"，MasterAgentCheck 是"Master Agent的视角"

**MasterAgentCheck.md 包含**：
1. **C类AI判断**（MON-C1~C5）——读proof.md/HANDOVER.md做判断
2. **self-check**（SELF-S1~S17）——对自己的检查
3. **新alert分类处理**——读自动化检查输出，逐个recheck
4. **已知问题诊断**——MON-A!01~A!05 中未诊断的优先诊断
5. **落盘完整性检查**——每个round的完整落盘验证
6. **修复操作规范**——修复后同步更新文档+commit

### 2.4 项目 AGENTS.md 最前面指令

在项目 `AGENTS.md` 的**最前面**（在所有其他内容之前）加入：

```markdown
## ⚠️ Master Agent 检查工作指令（最前面，不可截断）

**当你在做题系统工作中需要检查系统状态时**：

1. 运行检查脚本：`./scripts/monitor_check.sh <batch_id>`
2. 仔细阅读脚本输出的"AI后续检查清单"部分
3. 全文加载 `checklist/MasterAgentCheck.md`
4. 逐项处理清单中的每一项
5. 每完成一项立即 commit（含 trace.csv 同步）
6. 全部处理完后写执行结果记录

**这个指令放在最前面是因为**：连续运行中 AGENTS.md 后部可能被截断，
这个指令必须始终可见。
```

### 2.5 checkpoint 建立/更新

**判断**：这个需求**不产生新的系统功能 checkpoint**。

理由：
- MON-A/B/C 检查项是系统功能需求点，已经存在，不需要新增
- "Master Agent 接管检查工作"是工作模式变化，不是系统功能变化
- 需要的是：新建 `MasterAgentCheck.md` 检查清单文件 + 修改 AGENTS.md + 扩展检查脚本

**但需要更新 trace.csv**：补全孤立资产的追溯关系。

---

## §3 认知准备

### 执行本方案需要的认知

| 步骤 | 需要加载的文档 | 为什么需要 |
|---|---|---|
| 扩展 monitor_check.sh | `scripts/monitor_check.sh`（已加载） | 了解现有结构 |
| | `monitoring/runtime_health_check.py`（已加载头部） | 了解10维度检查的调用方式 |
| 新建 MasterAgentCheck.md | `checklist/ExecDevin.md`（已加载） | 提取检查项，重新组织 |
| | `docs/specs/p27_monitor_spec.md` | MON-A/B/C 详细标准 |
| 修改 AGENTS.md | `AGENTS.md`（已加载） | 了解现有结构，在最前面加指令 |
| 补全 trace.csv | trace.csv 现有内容 | 了解哪些资产是孤立的 |

### 不需要加载的

- `docs/patterns/MonitorPipe.md` — 设计范式，不影响具体操作
- `docs/specs/p27_monitor_pipe_operations.md` — 操作规范，ExecDevin 用的，Master Agent 不需要
- `docs/specs/p27_session_management_and_polish_spec.md` — session管理细节

---

## §4 元数据更新计划

### 会改动的文件

| 文件 | 改动 | 层级 |
|---|---|---|
| `AGENTS.md`（项目） | 最前面加检查工作指令 | 文件级 |
| `scripts/monitor_check.sh` | 扩展：加runtime_health_check调用+续传检查+AI后续检查清单 | 文件级 |
| `checklist/MasterAgentCheck.md` | 新建 | 文件级 |
| `trace.csv` | 补全孤立资产的追溯关系 | 数据级 |

### 需要同步的看法文件

- `checklist/README.md` — 需要加入 MasterAgentCheck.md 的索引
- `README.md`（项目） — 引导地图中加入 MasterAgentCheck.md

### trace.csv 需要补全的关系

```
# 孤立资产补全
monitor_check_continuation.sh → implements → RUN-02（或对应checkpoint）
monitor_check_selection.sh → implements → RUN-03（或对应checkpoint）
runtime_health_check.py → implements → MON-A*（10维度对应A类检查）
ExecDevin.md → specified-by → p27_monitor_spec.md
p27_monitor_pipe_operations.md → specified-by → MON-A*/MON-B*/MON-C*

# 新资产记录
MasterAgentCheck.md → comes-from → ExecDevin.md
MasterAgentCheck.md → specified-by → p27_monitor_spec.md
monitor_check.sh（扩展后） → changed-in → <commit>
AGENTS.md（修改后） → changed-in → <commit>
```

---

## §5 工作包拆解预案

**初步判断**：2个工作包

**WP-A：检查脚本扩展 + MasterAgentCheck.md 创建**
- 扩展 monitor_check.sh（加runtime_health_check+续传检查+AI后续检查清单）
- 新建 checklist/MasterAgentCheck.md
- 更新 checklist/README.md 索引
- 更新 README.md 引导地图

**WP-B：AGENTS.md 修改 + trace.csv 补全**
- 项目 AGENTS.md 最前面加检查工作指令
- 补全 trace.csv 孤立资产追溯关系
- 记录新资产到 trace.csv

**依赖关系**：WP-A 和 WP-B 可以并行，但 WP-B 中 trace.csv 的补全依赖 WP-A 产出的新文件路径。

**建议**：先 WP-A，后 WP-B。

---

## §6 验收标准（对照阶段1）

| 阶段1验收标准 | 方案中的实现 |
|---|---|
| 检查脚本能检查所有可自动化的内容 | 扩展 monitor_check.sh，整合 runtime_health_check.py 10维度 + 续传检查 |
| 脚本输出提示 | 脚本末尾输出"AI后续检查清单"，指向 MasterAgentCheck.md |
| checklist 文件 | 新建 checklist/MasterAgentCheck.md，包含 C类判断/self-check/alert处理/已知问题诊断 |
| AGENTS.md 最前面有指令 | 在项目 AGENTS.md 最前面加"Master Agent 检查工作指令" |
| Master Agent 能执行 | 运行脚本→看提示→加载MasterAgentCheck.md→逐项处理→commit |
| 不膨胀 AGENTS.md | 检查项在 MasterAgentCheck.md 中，AGENTS.md 只有最前面的指令（约10行） |
