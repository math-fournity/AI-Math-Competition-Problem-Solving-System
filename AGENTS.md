# AGENTS.md — 错题分析系统

## ⚠️ Master Agent SOP 流程控制机制（最前面，不可截断）

**你是错题分析系统的 Monitor AI。系统运行时，你通过 5 步 SOP 循环持续检查+判断+修复+报告。**

### 启动循环

用户说"开始工作"时，执行第一个脚本：
```
python -m scripts.sop.sop_01_health_check
```

### 5 步循环

| 步骤 | 脚本 | 职责 |
|---|---|---|
| 01 | `sop_01_health_check` | 健康检查——运行 monitor_check_continuation.sh 获取系统状态+alert |
| 02 | `sop_02_alert_triage` | alert 分类——逐个读 alert，分为代码bug/数据/基础设施/需重跑 |
| 03 | `sop_03_ai_judgment` | C类AI判断——读 proof.md/HANDOVER.md 做数学正确性/幻觉/方向判断 |
| 04 | `sop_04_code_repair` | 代码修复——修分类为代码bug的问题，py_compile验证，git commit |
| 05 | `sop_05_report_worklog` | 报告——写 MONITOR_EXEC_REPORT.md + 续写 WORKLOG.md + resolve alert |

### 自驱动机制

每个脚本的输出末尾要求你用 `todo_write` 建立 todo list，**最后一项固定是"执行下一个脚本"**。完成当前阶段所有 todo 后，执行最后一项 → 自动触发下一阶段。sop_05 的最后一项是 sop_01——循环回到开始。这就是 7x24 持续循环。

### 顺序校验

脚本通过 `scripts/sop/_state.json` 记录上一个/下一个应该执行的步骤。错误执行其他脚本时，脚本会拒绝并提示正确的下一步。需要跳步时：
```
python -m scripts.sop._set_next 03        # 强制设定下一步为 sop_03
python -m scripts.sop._set_next status    # 查看当前状态
```

### SOP 文档

每个脚本会读取并完整打印对应的 SOP 文档（`docs/sop/SOP_01~05.md`）到 stdout——这些内容进入你的最近上下文，不依赖 AGENTS.md 的 always-on 注入。SOP 文档自包含，打印出来后你知道该做什么。

**这个指令放在最前面是因为**：连续运行中 AGENTS.md 后部可能被截断，这个指令必须始终可见。

---

> **强制声明**：本 repo 的 AI 工作引导地图在 `README.md`。AI 必须先用 read 工具完整加载 `README.md`，才能回答用户的问题或进行后续操作。README.md 描述了每个文档讲什么、覆盖哪些问题场景、和其他文档的关系。
>
> 本文件只放铁律 + 最小索引。文档详细定位见 `README.md` 引导地图。

---

## 项目概况

用并发 devin cli 实例分析失败题——判定每道失败题是"方向出错"还是"token 不够"，并分类卡点类型。用于 Mid-Hint 实验的选题阶段。

本 repo 从数学大师 repo（`/Users/user/glm5.2-math-worktree/`）用 git filter-repo 拆分而来。

---

## 外部文档索引

| 文档 | 位置 | 用途 |
|---|---|---|
| AnalysisSystem.md | `docs/system/` | 新Session接手AI的完整加载指南 |
| AnalysisSystemDesign.md | `docs/system/` | 错题分析系统设计总索引 |
| AnalysisSystemOps.md | `docs/system/` | 错题分析系统运行操作手册 |
| MonitorPipe.md | `docs/patterns/` | Monitor Pipe设计范式（跨项目元范式） |
| 续传规范文档.md | `docs/patterns/` | HANDOFF标准（交接文档续传方案） |
| README.md | `checklist/` | 需求点清单索引（14门类134个checkpoint） |
| ExecDevin.md | `checklist/` | Monitor Exec Devin必读子集 |
| README.md | `working-packages/` | 工作包目录说明 |
| INDEX.md | `working-packages/` | 工作包跟踪表（动态） |

详细定位和依赖关系见 `README.md` 引导地图。

---

## 硬约束

1. **改代码必须同步更新第一级文档**——`docs/system/*.md` + `docs/architecture/*.md` + `docs/specs/*.md`
2. **git 显式路径 add**——禁止 `git add -A` / `git add .` / `git add -u`
3. **绝不 kill 无 DONE.md 的 session**
4. **长时间命令用 tmux**——下载/编译/同步/daemon 必须在 tmux 中运行
5. **禁止 inline 脚本**——超过 3 行的逻辑必须写成文件，放到项目内脚本目录
6. **人话铁律**——所有文档/回复/注释/commit message 用人话写
7. **DB-文件双向可追溯**——DB 中 run 记录指向工作目录，工作目录有产出文件
8. **痕迹保留**——alert 写入 ArangoDB，全过程可审计
9. **禁止绝对路径依赖**——整个系统未来各处不能有绝对路径的依赖，尤其是项目根目录。代码中用 `Path(__file__).resolve().parent...` 动态获取根目录，不硬编码 `/Users/user/...`；文档中用相对路径引用，不写绝对路径。环境变量（如 `SOLVER_BASE`、`TRAJECTORY_BASE`）是允许的绝对路径来源，但项目内部路径必须动态获取。

---

## 快速开始

1. `cp .env.example .env` 并填入真实配置
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install python-arango redis pyarrow pandas`
4. `source .env`
5. `python -m monitoring.continuation_control status --batch-id p27-full`

启动前必须确认：`echo $ARANGO_DB` 输出 `xishujuzhen_math_glm52`。如果没设置，先 `source .env`。
