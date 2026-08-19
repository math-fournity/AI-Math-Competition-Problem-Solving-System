# AnalysisSystem.md — 新Session接手AI的完整加载指南

> **这份文档是给你的**——你是新Session的AI，接手数学大师系统的开发、运行、维护、修正工作。
>
> **你被指定的路径**：用户会让你读这份文档，然后按这里的指示加载所需内容，继续工作。
>
> **这份文档不是百科全书**——它是指南和入口，指向其他文档和代码。读完后你应该知道：你在哪、系统是什么状态、要读什么、要做什么。

---

## §1. 你在哪——基本信息

- **工作目录**：`/Users/user/glm5.2-math-worktree/`
- **Git分支**：`glm5.2`
- **origin**：`/Volumes/data/glm5.2-math-worktree`（fetch/push都指向它）
- **Python环境**：`.venv/`（python3.14，独立venv，被gitignore）
- **数据库**：ArangoDB `localhost:8529`，数据库名 `xishujuzhen_math_glm52`（通过`.env`文件设置`ARANGO_DB`环境变量）

**⚠️ 启动前必须确认**：`echo $ARANGO_DB` 输出 `xishujuzhen_math_glm52`。如果没设置，先 `source .env` 或 `export ARANGO_DB=xishujuzhen_math_glm52`。

---

## §2. 这个项目在做什么——一句话和三句话

**一句话**：把数学大师"知道此刻应该想什么"的能力变成可积累、可计算、可审计、可验证、可持续演化的AI研究导航系统。

**三句话**：
1. **工作系统**（元系统）管理AI怎么工作、怎么反思、怎么迭代——确保AI在每个检查点都对数学大师系统做了必要的反思
2. **数学大师系统**（对象系统）做数学研究——被工作系统打磨的对象
3. 两层系统不独立：工作系统通过反思确保数学大师系统持续迭代，数学大师系统的研究结果反哺工作系统的新认知

**详见**：`用户需求.md`（完整需求）和 `系统探讨.md`（全景复盘）。

---

## §3. 当前系统状态（2026-08-19）

### 3.1 正在进行的核心工作

**POC-2.7续传Pipe系统**——错题分析系统（`analysis-devin-failure-system/`）的Pipe 4，对919道DIRECTION_ERROR题启动续传机制，验证续传能否大规模解决截断问题。通过标准COMPLETED≥50%。

**最近完成的工作**（Session编号化管理，阶段1代码实现）：
- 新建 `src/session_registry.py`——所有devin cli实例的tmux session编号化管理
- 修改 `continuation_launcher.py`——rate_limited/timeout/stall从kill改为标记stuck（绝不kill无DONE.md）
- 修改 `continuation_control.py`——stop --force分类处理 + 新增sessions子命令
- 修改 `monitor_continuation.py`——新增A10/A11/A12检查
- 7项端到端测试全部通过

**下一步**：阶段1需要在真实运行中验证，然后做阶段2（Monitor Pipe执行devin架构）。

### 3.2 系统运行状态

**检查系统当前是否在运行**：
```bash
cd analysis-devin-failure-system
/Users/user/glm5.2-math-worktree/.venv/bin/python3 -m monitoring.continuation_control status --batch-id p27-full
```

**检查session注册表**：
```bash
cd analysis-devin-failure-system
/Users/user/glm5.2-math-worktree/.venv/bin/python3 -m monitoring.continuation_control sessions
/Users/user/glm5.2-math-worktree/.venv/bin/python3 -m monitoring.continuation_control sessions --consistency-check
```

**检查进度**：
```bash
cd /Users/user/glm5.2-math-worktree
bash analysis-devin-failure-system/scripts/monitor_check_continuation.sh p27-full
```

### 3.3 最近的commit脉络

```bash
git log --oneline -20
```

最近20个commit围绕两条线：
1. **POC-2.7续传系统稳定性修复**（export缺失/完成判定/session管理）
2. **Session编号化管理+Monitor Pipe执行devin架构**（方案文档+代码实现）

---

## §4. 你必须读的文档（按优先级排序）

### 第一优先级——理解你的角色和硬约束

| 序号 | 文档 | 路径 | 为什么必须读 |
|---|---|---|---|
| 1 | **项目AGENTS.md** | `AGENTS.md` | 项目的硬约束、工作系统规则、所有POC状态。**320KB很大，分段读**——先读前500行（硬约束+角色说明+基本信息），需要时再读后面的具体章节 |
| 2 | **全局AGENTS.md** | `~/.config/devin/AGENTS.md` | 跨项目的硬约束和行为规范。**只读前200行**（硬约束区），后面的skill索引按需读 |

**⚠️ 注意**：AGENTS.md太大时可能无法自动注入。用 `read` 工具分段读取。

### 第二优先级——理解错题分析系统（当前工作的主战场）

| 序号 | 文档 | 路径 | 什么时候读 |
|---|---|---|---|
| 3 | **AnalysisSystemDesign.md** | `AnalysisSystemDesign.md` | **必读**——错题分析系统的设计总索引，索引所有文档/规范/代码资产/设计原则/关键决策 |
| 4 | **MonitorPipe.md** | `MonitorPipe.md` | **必读**——Monitor Pipe三层架构设计范式（2026-08-19修正：执行层=Python+devin cli两层） |
| 5 | **续传规范文档.md** | `续传规范文档.md` | 涉及续传工作时必读——HANDOFF.md结构/截断判定/prompt模板 |

### 第三优先级——理解Monitor Pipe执行devin架构（正在开发的新特性）

| 序号 | 文档 | 路径 | 什么时候读 |
|---|---|---|---|
| 6 | **p27_monitor_pipe_operations.md** | `analysis-devin-failure-system/specs/p27_monitor_pipe_operations.md` | **必读**——Monitor Exec Devin的认知资产入口+检查项目完整清单+self检查+工作流程 |
| 7 | **p27_session_management_and_polish_spec.md** | `analysis-devin-failure-system/specs/p27_session_management_and_polish_spec.md` | **必读**——Session编号化管理+Monitor Exec Devin架构规范（§A session管理+§B Exec Devin+§C实施Checklist） |
| 8 | **p27_monitor_spec.md** | `analysis-devin-failure-system/specs/p27_monitor_spec.md` | 检查规范详情——A类12项/B类9项/C类5项的详细标准 |

### 第四优先级——按需读取

| 序号 | 文档 | 路径 | 什么时候读 |
|---|---|---|---|
| 9 | POC.md | `POC.md` | 需要了解所有POC测试的状态时 |
| 10 | 000号文档 | `000-v0-2026-08-08-引导树闭环-识别端结构定义.md` | 需要理解tell/hint二元组（系统架构的根定义） |
| 11 | docs/下的模块文档 | `analysis-devin-failure-system/docs/*.md` | 修复特定模块bug时（architecture/graceful-shutdown/operational-concerns等） |
| 12 | conversation-map.md | `conversation-map.md` | 处理conversation.json时（面包屑地图方案） |
| 13 | devin-cli-export-conversation.md | `devin-cli-export-conversation.md` | 需要理解conversation.json的schema时 |
| 14 | trajectory-schema.md | `trajectory-schema.md` | 需要理解trajectory.jsonl的schema时 |

---

## §5. 你必须了解的代码结构

### 5.1 错题分析系统（`analysis-devin-failure-system/`）——当前主战场

```
analysis-devin-failure-system/
  src/
    continuation_config.py          # 配置常量
    continuation_db_schema.py       # ArangoDB集合+索引
    continuation_redis_queue.py     # Redis队列操作
    continuation_collector.py       # 数据收集
    continuation_feeder.py          # 入Redis队列
    continuation_launcher.py        # ★核心★——并发启动devin cli+多轮续传
    continuation_result_collector.py # 结果收集
    session_registry.py             # ★新增★——Session编号化管理
    monitor_continuation.py         # Monitor Pipe（Python部分，A1-A12+B1-B9+C1-C5）
    monitor_exec_launcher.py        # ★待实现★——Monitor Exec Devin启动器（阶段2）
    # Pipe 1/2/3的代码也在src/下（analysis_*/audit_*/selection_*）
  monitoring/
    continuation_control.py         # 统一控制工具（start/stop/status/health/sessions）
    shared_logger.py                # 日志
    graceful_shutdown.py            # 优雅退出
  scripts/
    monitor_check_continuation.sh   # 检查脚本
    continuation_watchdog.sh        # watchdog
  specs/
    p27_monitor_spec.md             # 检查规范（A/B/C类详细标准）
    p27_monitor_pipe_operations.md  # ★Monitor Exec Devin认知资产入口★
    p27_session_management_and_polish_spec.md  # Session管理+Exec Devin架构
  docs/
    architecture.md                 # 4个Pipe的演进+架构
    graceful-shutdown.md            # 优雅停止设计
    operational-concerns.md         # 运维关注点
    framework-checklist.md          # 框架检查清单
    # ... 其他模块文档
  templates/
    monitor_exec_prompt.md          # ★待创建★——Monitor Exec Devin的prompt模板（阶段2）
```

### 5.2 数学大师系统其他部分

| 目录 | 用途 | 何时需要 |
|---|---|---|
| `system/` | 第六代系统代码（两棵树/Grove核心循环） | 涉及第六代系统开发时 |
| `seven-system/` | 非特化证据工厂 | 涉及Seven System时 |
| `xishujuzhen/solver_harness/pipe/` | 解题系统pipe | 错题分析系统借鉴解题系统时 |
| `Tell分类学研究过程文档/` | 非特化研究过程文档+POC数据资产 | 涉及POC方案/数据时 |
| `dev-docs/` | 工作文档（编号001-391+） | 查找历史工作记录时 |
| `第六代系统研发过程文档/` | 第六代系统研发过程 | 涉及第六代系统设计时 |
| `第六代系统技术说明书/` | 第六代系统技术规格 | 涉及第六代系统实现时 |

---

## §6. 你可能要做的工作类型

### 6.1 继续阶段2：Monitor Pipe执行devin架构

**当前进度**：阶段1（Session编号化管理）代码实现完成，阶段2（Monitor Exec Devin）尚未开始。

**要读**：`p27_session_management_and_polish_spec.md` §B + §C.2（实施Checklist）

**要做**：
1. 新建 `src/monitor_exec_launcher.py`——定时启动Monitor Exec Devin
2. 新建 `templates/monitor_exec_prompt.md`——Monitor Exec Devin的prompt模板
3. 修改 `monitor_continuation.py`——主循环加入Monitor Exec Devin启动逻辑
4. WORKLOG.md跨目录传递机制实现
5. 验证完整流程

### 6.2 运行和监控POC-2.7

**要读**：`AnalysisSystemDesign.md` §1快速入口 + `p27_monitor_spec.md`

**要做**：
- 启动系统：`cd analysis-devin-failure-system && .venv/bin/python3 -m monitoring.continuation_control start --batch-id p27-full --concurrency 5`
- 检查健康：`continuation_control health --batch-id p27-full`
- 循环监控：`bash analysis-devin-failure-system/scripts/monitor_check_continuation.sh p27-full`
- 停止：`continuation_control stop`（优雅）或 `stop --force`（强制，分类处理不kill running）

### 6.3 修复bug

**要读**：相关代码文件 + `p27_monitor_pipe_operations.md` §4.5（文档同步分级）

**铁律**：
- 改代码必须同步更新第一级文档（docs/*.md + AnalysisSystemDesign.md §4 + specs实现细节）
- 第二级架构级规范（AGENTS.md/MonitorPipe.md架构定义/.devin/rules/）不能自己改，记录建议给Master Agent
- git显式路径add，禁止 `git add -A/. /-u`
- commit message格式见全局AGENTS.md

### 6.4 审计系统运行

**要读**：`p27_monitor_spec.md`（检查标准）+ `MonitorPipe.md`（设计范式）

**要做**：按检查规范逐项验证产出质量、循环完整性、数据一致性。

---

## §7. 硬约束（从AGENTS.md提取的最重要的几条）

1. **数据库**：启动任何连ArangoDB的脚本前，确认 `ARANGO_DB=xishujuzhen_math_glm52`
2. **Git**：只在 `glm5.2` 分支工作；显式路径add；改前clean+改后立即commit；push需用户授权
3. **Solver工作目录隔离**：Solver的devin cli必须在外部目录运行（`/Volumes/data/math-agent-glm5.2-tmux-agents-dir/`），不能在本repo内运行——否则AGENTS.md工作系统规则会劫持Solver行为
4. **生产实验运行解题AI**：用全局 `noninteractive-solver-run` skill（`devin -p --prompt-file ... --export ...`）
5. **Monitor Pipe执行devin**：cwd在外部目录（`/Volumes/data/p27-monitor-exec/{exec_seq}/`），不在worktree内
6. **绝不kill无DONE.md的session**——rate_limited/timeout/stall标记stuck不kill，等Master Agent在用户授意下处理
7. **长时间命令用tmux**——不用nohup/background
8. **禁止inline脚本**——超过3行的逻辑写成文件
9. **人话铁律**——所有文档/回复/注释/commit message用人话写
10. **给选项必含利弊+推荐+推荐理由**

---

## §8. 加载顺序建议

当你被要求"读AnalysisSystem.md然后继续工作"时，按以下顺序加载：

```
第1步：读本文档（AnalysisSystem.md）——知道你在哪、要做什么
  │
第2步：确认环境
  ├── echo $ARANGO_DB → 应该是 xishujuzhen_math_glm52
  ├── git branch --show-current → 应该是 glm5.2
  └── git log --oneline -10 → 了解最近做了什么
  │
第3步：读第一优先级文档
  ├── AGENTS.md 前500行（硬约束+角色+基本信息）
  └── ~\.config\devin\AGENTS.md 前200行（全局硬约束）
  │
第4步：读第二优先级文档
  ├── AnalysisSystemDesign.md（错题分析系统总索引）
  ├── MonitorPipe.md §2（三层架构——注意2026-08-19修正：执行层=Python+devin cli两层）
  └── 续传规范文档.md（如涉及续传工作）
  │
第5步：读第三优先级文档（如涉及Monitor Pipe执行devin）
  ├── p27_monitor_pipe_operations.md（Monitor Exec Devin认知资产入口）
  ├── p27_session_management_and_polish_spec.md §B+§C（Exec Devin架构+实施Checklist）
  └── p27_monitor_spec.md（检查规范详情）
  │
第6步：检查系统当前状态
  ├── continuation_control status --batch-id p27-full
  ├── continuation_control sessions
  └── bash monitor_check_continuation.sh p27-full
  │
第7步：根据用户指示或系统状态，开始工作
```

---

## §9. 持续维护这份文档

这份文档是活文档——系统演进时必须同步更新。

### 什么时候更新

- **系统状态变化时**（阶段完成/POC状态变化/新的大工作线开始）→ 更新§3
- **新增核心文档时** → 更新§4
- **新增核心代码时** → 更新§5
- **硬约束变化时** → 更新§7
- **加载顺序需要调整时** → 更新§8

### 什么时候不更新

- 具体检查项的阈值调整 → 更新 `p27_monitor_spec.md`（那是详情，本文件是入口）
- 具体代码逻辑的修改 → 更新对应的 `docs/*.md`（那是事实性文档，本文件是指南）
- 单个bug修复 → 不需要更新本文件（除非修复暴露了新的硬约束）

### 版本记录

- **v1 · 2026-08-19** · 初始版本——新Session接手AI的完整加载指南。覆盖项目基本信息/当前状态/必读文档/代码结构/工作类型/硬约束/加载顺序。
