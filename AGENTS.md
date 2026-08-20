# AGENTS.md — 错题分析系统

## ⚠️ 启动指令（最前面，不可截断）

### 触发短语 → 动作对照

| 用户说 | 你做什么 |
|---|---|
| `开启系统` / `启动系统` / `开启解题系统` / `启动解题系统` | **启动解题系统 + 启动 SOP 监控循环**（完整流程，见下方） |
| `启动监控` / `开启监控` / `开始监控` / `开始工作` | **只启动 SOP 监控循环**（不启动解题系统，假设系统已在运行，见下方） |
| `停止` / `停` / `结束` / `停止监控` | **停止 SOP 循环 + 停止解题系统**（见下方停止命令） |
| `查看SOP状态` / `SOP状态` | **查看 SOP 流程状态**（`python -m scripts.sop._set_next status`） |

---

### 动作1：启动解题系统 + SOP 监控（触发：开启系统/启动系统/开启解题系统/启动解题系统）

1. **启动解题系统**（如果尚未运行）：
   ```
   source .env
   python -m monitoring.continuation_control start --batch-id p27-full --concurrency 5
   ```
   确认 launcher/monitor/watchdog 三个 tmux session 都在运行。

2. **启动 SOP 监控循环**：
   ```
   python -m scripts.sop.run
   ```

3. **持续循环**——用 `todo_write` 建 todo list，最后一项固定是"执行 `python -m scripts.sop.run`"。完成当前阶段所有 todo 后，执行最后一项自动触发下一阶段。7 步循环（01→02→03→04→05→06→Z→01...）持续运行，这就是 7x24 监控。

4. **停止条件**——只有以下情况停止循环：
   - 用户说"停止"/"停"/"结束"→ 执行停止命令
   - 检查脚本显示"所有任务已完成"（pending=0, running=0）→ 执行停止命令
   - 系统出现无法自动修复的严重故障需用户介入

### 动作2：只启动 SOP 监控循环（触发：启动监控/开启监控/开始监控/开始工作）

假设解题系统已在运行，只启动 SOP 循环：
```
python -m scripts.sop.run
```
然后同样用 `todo_write` 自驱动持续循环。

### 停止命令

```
# 优雅停止（推荐）——launcher收到SIGINT后不再启动新run，等running自然完成
python -m monitoring.continuation_control stop

# 强制停止——停服务+清理done session+清空Redis队列（stuck/running不kill，等DONE.md）
python -m monitoring.continuation_control stop --force
```

### SOP 流程状态查看和跳步控制

```
# 查看当前 SOP 流程状态（上一个/下一个步骤/循环轮次）
python -m scripts.sop._set_next status

# 强制设定下一步（跳步用——正常情况下不需要，SOP自动推进）
python -m scripts.sop._set_next 03        # 跳到步骤03（alert分类）
python -m scripts.sop._set_next 01        # 回到循环开始（系统健康检查）
python -m scripts.sop._set_next Z         # 跳到元/整体检查
```
有效步骤编号：`01` `02` `03` `04` `05` `06` `Z`

### 其他控制命令

```
python -m monitoring.continuation_control status --batch-id p27-full    # 查看系统状态
python -m monitoring.continuation_control health --batch-id p27-full    # 健康检查
python -m monitoring.continuation_control set-concurrency --batch-id p27-full --concurrency 3  # 动态调并发
python -m monitoring.continuation_control sessions --status stuck       # 查看stuck session
python -m monitoring.continuation_control sessions --clean-done         # 批量清理done session
python -m monitoring.continuation_control sessions --consistency-check  # 注册表vs tmux一致性
```

---

## ⚠️ Master Agent SOP 流程控制机制

**你是错题分析系统的 Monitor AI。系统运行时，你通过 7 步 SOP 循环持续检查+判断+修复+报告+自我审查。**

### 核心理念

Master Agent 自己（不是独立 devin cli）作为 Monitor Pipe 的承载者。7x24 持续循环通过**自驱动 todo list 机制**实现——每个 SOP 脚本输出末尾要求用 `todo_write` 建 todo list，最后一项固定是"执行下一个脚本"，完成 todo 自动触发下一阶段。不依赖 devin -p 定时启动，因为本 repo 上下文负担小（无 .devin/rules/，AGENTS.md 聚焦），Master Agent 直接做比独立 cli 更简单且能力更强。方案详情见 `dev-docs/013-Master-Agent-SOP流程控制机制方案.md`。

### 启动循环

用户说"开始工作"时，执行 SOP 入口脚本：
```
python -m scripts.sop.run
```

### 7 步循环（6 工作 + 1 元/整体检查）

| 步骤 | 名称 | 检查什么 |
|---|---|---|
| 01 | 系统存活+进度+Session | 进程状态/进度统计/session注册表一致性/stuck/done |
| 02 | 数据完整性 | 产出文件存在性/rounds_log 7字段/DB-文件一致性/Redis-DB一致性 |
| 03 | alert分类 | 读未处理alert，分类为代码bug/数据/基础设施/需重跑/需清理 |
| 04 | C类AI判断 | 读proof.md/HANDOVER.md做C1-C5判断（数学正确性/幻觉/泄漏/质量/方向） |
| 05 | 代码修复 | 修分类为代码bug的问题+py_compile+git commit+文档同步 |
| 06 | 报告+WORKLOG+Self-check | 写报告+续写WORKLOG+执行SELF-S1~S17+resolve alert |
| Z | 元检查+整体检查 | 每个SOP步骤合理性+整体系统是否需要调整 |

**自我进化机制**：Z 步骤检查整个 SOP 系统本身是否需要调整——SOP 系统不仅能修目标系统，还能修自己。

### 自驱动机制

每个脚本的输出末尾要求你用 `todo_write` 建立 todo list，**最后一项固定是"执行 `python -m scripts.sop.run`"**。完成当前阶段所有 todo 后，执行最后一项 → 自动触发下一阶段。Z 步骤的最后一项回到 01——循环回到开始。这就是 7x24 持续循环。

### 顺序校验

脚本通过 `scripts/sop/_state.json` 记录上一个/下一个应该执行的步骤。错误执行其他步骤时，脚本会拒绝并提示正确的下一步。需要跳步时：
```
python -m scripts.sop._set_next 03        # 强制设定下一步为步骤03
python -m scripts.sop._set_next Z         # 跳到元/整体检查
python -m scripts.sop._set_next status    # 查看当前状态
```
有效编号：`01` `02` `03` `04` `05` `06` `Z`

### SOP 文档

每个脚本会读取并完整打印对应的 SOP 文档到 stdout——这些内容进入你的最近上下文，不依赖 AGENTS.md 的 always-on 注入。SOP 文档**自包含**——含认知闭包（前提知识）+ 执行指令 + todo 指令，打印出来后你知道该做什么。

SOP 文档目录：`docs/sop/`（SOP_01~06 + SOP_Z，共 7 个）
SOP 脚本目录：`scripts/sop/`（run + checks + report + sop_state + _set_next + _state.json）

**报表系统**：每次SOP步骤执行后，脚本自动在D盘生成报表目录，并把报表模板复制过去：
`/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-sop-reports/cycle_{NNN}/step_{XX}/{timestamp}/`
- `report.md` — 从模板复制过来的报表，AI必须填写（检查项打勾+发现+操作）
- `snapshot.json` — 系统快照（聚合统计）
- `snapshot_runs.json` — 全量per-run数据（每道题的status/round/完成情况）
- `check_output.txt` — 脚本输出原文

**报表模板是项目运行期资产**，存放在 `docs/sop/templates/report_step_{XX}.md`（7个模板文件，每个step一个）。模板中包含每个检查项的检查方法、填写位置、格式要求。和给解题devin cli的提示词模板文件一样，是AI运行用资产。

**每次检查必须填写 report.md**——加载D盘报表目录中的report.md，按模板中的检查方法逐项检查并填写，填写完用edit写回。这是审计痕迹，回头可以grep到某一轮检查某个step中AI查了什么、结果是什么。不填写报表 = 检查没有完成。

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
| AnalysisSystemDesign.md | `docs/system/` | 错题分析系统设计总索引（§6关键设计决策） |
| AnalysisSystemOps.md | `docs/system/` | 错题分析系统运行操作手册 |
| MonitorPipe.md | `docs/patterns/` | Monitor Pipe设计范式（§2.2已改为Master Agent SOP循环） |
| 续传规范文档.md | `docs/patterns/` | HANDOFF标准（SOP_04 C4判断依据） |
| p27_monitor_spec.md | `docs/specs/` | A/B/C类检查详细标准（SOP_03/04引用） |
| p27_session_management_and_polish_spec.md | `docs/specs/` | §A Session管理（有效）/ §B Exec Devin（已废弃） |
| ~~p27_monitor_pipe_operations.md~~ | `docs/specs/` | 已废弃（Exec Devin认知资产入口） |
| architecture/*.md | `docs/architecture/` | 9个架构文档（运维/优雅停止/动态并发/框架检查清单等，SOP_01/05引用） |
| continuation_control.py | `monitoring/` | **解题系统控制脚本**——start/stop/status/health/set-concurrency/sessions |
| monitor_check_continuation.sh | `scripts/` | 续传检查脚本（SOP_01 调用它） |
| SOP_01~06 + Z | `docs/sop/` | Master Agent SOP 文档（7个，自包含+认知闭包） |
| run + checks + sop_state + _set_next + dry_run + sop_log | `scripts/sop/` | Master Agent SOP 脚本（单入口+检查逻辑库+状态管理+dry-run验证+日志） |
| log/ | `log/` | SOP 日志目录（循环覆盖，最多500个文件，每个最大1MB，总上限500MB） |
| 013-Master-Agent-SOP流程控制机制方案 | `dev-docs/` | SOP机制方案文档（理念/架构/决策理由） |
| README.md | `checklist/` | 需求点清单索引（14门类134个checkpoint） |
| MasterAgentCheck.md | `checklist/` | Master Agent SOP 索引（内容已迁移到 docs/sop/） |
| ExecDevin.md | `checklist/` | ~~历史参考~~（Exec Devin已废弃） |
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
10. **devin cli model 必须显式指定**——所有启动 devin cli 的代码必须显式传 `--model` 参数，值必须是 `devin models list` 中的有效名。当前用 `glm-5-2`（GLM-5.2 High, 200K, Free）。详见 `.devin/rules/devin-cli-model-must-be-specified.md`

---

## 快速开始

1. `cp .env.example .env` 并填入真实配置
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install python-arango redis pyarrow pandas`
4. `source .env`
5. `python -m monitoring.continuation_control status --batch-id p27-full`

启动前必须确认：`echo $ARANGO_DB` 输出 `xishujuzhen_math_glm52`。如果没设置，先 `source .env`。
