# SOP_OP：运营知识刷新（每轮循环末尾注入）

## 认知闭包（每轮刷新——AI作为Master Agent应时刻知道的repo+运营知识）

> 本步骤在每轮SOP循环末尾（Z之后、01之前）执行。AGENTS.md受16K限制只保留
> 启动指令核心，运营知识（硬约束/外部索引/快速开始/SOP机制细节/项目概况）
> 在这里每轮由run.py反复注入，确保AI跨session压缩边界后仍时刻知道这些。
> L0（SYSTEM_CLOSURE）每步注入系统级认知（架构/生命周期/判定框架），
> 本步骤补充运营级知识（铁律/文档索引/环境配置）——两者互补不冗余。

### 项目概况

对失败的数学题启动续传解题管线——通过多轮 handover→solve 循环让 devin cli 接力
解题，直至解出、AI 放弃、或达到最大轮次（默认5轮）。每道题是一条管线，管线内部
顺序调用 devin cli，故并发数 = 管线条数 = devin cli 实例数上限。
本系统只有这一条续传解题管线（Pipe 1/2/3 分析/审计/选题已删除）。
本repo从数学大师repo用git filter-repo拆分而来。

### 硬约束（10条基础 + 016/017/018新增4条）

1. **改代码必须同步更新第一级文档**——`docs/architecture/*.md` + `docs/specs/*.md` + `docs/sop/SYSTEM_CLOSURE.md`
2. **git显式路径add**——禁止`git add -A` / `.` / `-u`
3. **绝不kill无DONE.md的session**（dead_session是唯一例外：DONE.md已出现但无proof）
4. **长时间命令用tmux**——下载/编译/同步/daemon必须在tmux中运行
5. **禁止inline脚本**——超过3行的逻辑必须写成文件，放到项目内脚本目录
6. **人话铁律**——所有文档/回复/注释/commit message用人话写
7. **DB-文件双向可追溯**——DB中run记录指向工作目录，工作目录有产出文件
8. **痕迹保留**——alert写入ArangoDB，全过程可审计
9. **禁止绝对路径依赖**——代码用`Path(__file__).resolve().parent`动态获取根目录；环境变量(SOLVER_BASE/TRAJECTORY_BASE)是允许的绝对路径来源，但项目内部路径必须动态获取
10. **devin cli model必须显式指定**——所有启动devin cli的代码必须显式传`--model`参数，当前用`glm-5-2`

016/017/018新增（详见`checklist/HARD-13~16` + L0 §7铁律索引）：
- 成果文件必须双写入库（proof入库continuation_results，018教训）
- 改调度逻辑后跑sim发布门禁（solve3+chaos_016，016 P0-1教训）
- Gate放行必须附--reason落盘论证（门闸，016教训）
- 每轮SOP_01必查行为流水（observability --stats，016根因）

### 外部文档索引

| 文档 | 位置 | 用途 |
|---|---|---|
| solve-pipeline.md | `docs/architecture/` | **解题管线核心概念**（并发=管线条数=devin cli实例数） |
| dynamic-concurrency.md | `docs/architecture/` | 动态并发设计（DB记录方案，set-concurrency机制） |
| MonitorPipe.md | `docs/patterns/` | Monitor Pipe设计范式（§2.2已改为Master Agent SOP循环） |
| StepGate.md | `docs/patterns/` | 步进门闸设计范式（@gated/hold-step/落盘论证） |
| 续传规范文档.md | `docs/patterns/` | HANDOFF标准8章节（SOP_04 C4依据） |
| p27_monitor_spec.md | `docs/specs/` | A/B/C类检查详细标准（A1~A14，SOP_03/04引用） |
| p27_session_management_and_polish_spec.md | `docs/specs/` | §A Session管理（有效）/ §B Exec Devin（已废弃） |
| ~~AnalysisSystem.md~~ | `docs/system/` | ⚠️ 过时（描述4 Pipe架构，Pipe 1/2/3已删） |
| ~~AnalysisSystemDesign.md~~ | `docs/system/` | ⚠️ 过时（同上） |
| ~~AnalysisSystemOps.md~~ | `docs/system/` | ⚠️ 过时（同上） |
| ~~p27_monitor_pipe_operations.md~~ | `docs/specs/` | 已废弃 |
| ~~selfrun-workflow.md~~ | `docs/architecture/` | 已废弃（selfrun代码已删） |
| continuation_control.py | `monitoring/` | 解题系统控制脚本（start/stop/status/health/set-concurrency/sessions） |
| monitor_check_continuation.sh | `scripts/` | 续传检查脚本（SOP_01调用） |
| SOP_01~06+Z+OP | `docs/sop/` | Master Agent SOP文档（8个，自包含+认知闭包） |
| SYSTEM_CLOSURE.md | `docs/sop/` | 系统级认知闭包L0（run.py每次前置注入） |
| run+checks+sop_state+_set_next+dry_run+sop_log | `scripts/sop/` | SOP脚本（单入口+检查+状态+dry-run+日志） |
| log/ | `log/` | SOP日志（循环覆盖，最多500文件/500MB） |
| 013-Master-Agent-SOP流程控制机制方案 | `dev-docs/` | SOP机制方案 |
| 017-全流程模拟系统设计方案 | `dev-docs/` | 全流程模拟（src/sim/，7剧本，首日捕获5bug） |
| 018-teardown误删生产目录事故报告 | `dev-docs/` | 018事故（成果双写教训） |
| 019-删除Pipe123后系统全面检查分析报告 | `dev-docs/` | 删除Pipe1/2/3后的残留引用检查报告 |
| README.md | `checklist/` | 需求点清单索引（14门类147checkpoint） |

详细定位见`README.md`引导地图。

### 快速开始

1. `cp .env.example .env` 并填入真实配置
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install python-arango redis pyarrow pandas`
4. `source .env`
5. `python -m monitoring.continuation_control status --batch-id p27-full`

启动前必须确认：`echo $ARANGO_DB` 输出 `xishujuzhen_math_glm52`。如果没设置，先`source .env`。

### SOP文档与报表系统

每个SOP脚本读取并完整打印对应文档到stdout——内容进入最近上下文，不依赖AGENTS.md always-on。SOP文档自包含（认知闭包+执行指令+todo指令）。

报表系统：每次SOP步骤执行后，脚本自动在D盘生成报表目录：
`/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-sop-reports/cycle_{NNN}/step_{XX}/{timestamp}/`
- `report.md` — 从模板复制，AI必须填写（检查项打勾+发现+操作）
- `snapshot.json` — 系统快照（聚合统计）
- `snapshot_runs.json` — 全量per-run数据
- `check_output.txt` — 脚本输出原文

报表模板在`docs/sop/templates/report_step_{XX}.md`（8个模板）。**每次检查必须填写report.md**——审计痕迹，不填写=检查没完成。

---

## 执行指令

### 1. 环境验证（ENV-01~07需求点）

```bash
echo $ARANGO_DB    # 必须输出 xishujuzhen_math_glm52，如果为空先source .env
```

检查项：
- **ArangoDB连接**——`python3 -c "from src.continuation_db_schema import connect_db; db=connect_db(); print(db.properties())"` 能连接
- **Redis连接**——`python3 -c "from src.continuation_redis_queue import ping; print(ping())"` 输出True
- **D盘挂载**——`ls /Volumes/data/` 能列出内容
- **.env已source**——`echo $ARANGO_DB` 不为空

如果任何基础设施不正常，记录为critical——系统无法正常运行。

### 2. 确认运营知识已读

上方认知闭包（项目概况/硬约束/外部索引/快速开始/SOP文档说明）每轮刷新。读一遍确认无变化或记录变化。

---

## 你需要建立的todo list

- 环境验证（ENV-01~07）
- 运营知识已读
- **填写report.md报表**（read加载→打勾填发现→edit写回）
- **最后一项固定是**：`执行下一个脚本: python -m scripts.sop.run`

完成所有todo后，自动触发步骤01（新一轮循环开始）。**OP是循环末尾——完成后cycle+1回到01**。