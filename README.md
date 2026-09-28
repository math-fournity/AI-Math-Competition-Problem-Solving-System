# AI-Math-Competition-Problem-Solving-System

AI 数学竞赛题持续解题系统——一个面向竞赛数学题的**长期自动化解题工程**：AI 解题实例
（GLM-5.2 via devin cli / OpenCode ACP）对每道题执行多轮"交接—解题"循环，Master Agent
以 9 步 SOP 循环 7×24 监控与修复，配合 proof 审计、全流程模拟和行为流水观测；所有运行
资产（对话录、提示词、交接文档、证明、数据表）全程保留，构成可回溯的解题工程数据集。

> 核心理念：**一道题的解题是一条完整管线（Solve Pipeline），不是一次调用**。AI 某一轮
> 放弃、预算耗尽或窗口额度用完，都不是题目寿命的终点——系统保存现场、释放资源，未来
> 可从下一个绝对轮次继续。

## 相关仓库

| 仓库 | 内容 |
|---|---|
| **本仓库** | 系统代码（src/scripts/monitoring）+ 架构文档（docs/dev-docs）+ SOP + 工作包执行证据 |
| [AI-Math-Solving-Trajectories](https://github.com/math-fournity/AI-Math-Solving-Trajectories) | 当前世代解题运行现场：p27 生产续传现场、v2 管线运行、SOP 报表 |
| [AI-Math-Solving-Trajectories-Archive](https://github.com/math-fournity/AI-Math-Solving-Trajectories-Archive) | 早期世代归档：5 万+ 每题运行现场（对话录/会话轨迹/终端日志/工作目录）与 devin 失败分析现场 |
| [AI-Math-Solving-Databases](https://github.com/math-fournity/AI-Math-Solving-Databases) | 系统数据表整体导出（ArangoDB 三库全部数据表，JSONL + manifest + 恢复脚本）与题库目录 |
| [AI-Math-Normal-Solver](https://github.com/math-fournity/AI-Math-Normal-Solver) | 平凡解题系统（solver pipe）——早期世代的解题管线代码 |

## 整体架构

```
                    ┌──────────────────────────────────────────────┐
                    │            Master Agent（SOP 9 步循环）         │
                    │   01存活 02数据完整性 03alert分类 04AI判断      │
                    │   05代码修复 06报告 07审计健康 Z元检查 OP运营知识 │
                    └──────────────┬───────────────────────────────┘
                                   │ 驱动/判定/修复
        ┌──────────────────────────┼──────────────────────────────┐
        ▼                          ▼                              ▼
┌────────────────┐        ┌────────────────┐             ┌────────────────┐
│  解题管线       │        │  审计管线       │             │  全流程模拟     │
│  (p27 续传)    │        │  (proof audit) │             │  (src/sim)     │
└───────┬────────┘        └────────────────┘             └────────────────┘
        │
        ▼
①入题 continuation_collector → ②入队 continuation_feeder(Redis)
→ ③启动 continuation_launcher（handover→solve 两阶段，tmux 会话承载 devin cli）
→ ④监控 monitor_continuation（session 健康/僵尸/rate_limit + alert）
→ ⑤收集 continuation_result_collector → ⑥控制 continuation_control
→ ⑦看门狗 continuation_watchdog（自动重启 launcher/monitor）
```

### 关键设计

- **并发模型**：`并发数 = 同时运行的解题管线条数 = 解题工作实例数上限`。管线内部严格串行
  （一道题任意时刻最多 1 个解题实例，handover 与 solve 共享并发槽）。并发数存 DB 的
  batch 记录，launcher 每轮 poll 动态读取——**改并发不改代码**；代码中禁止写死并发默认值。
- **终态语义**：`proof.md` 出现 `\boxed` 只是"候选成功"，数学正确需形式化包 + 独立审计
  确认；AI 输出放弃信号仅代表本轮放弃（`ai_gave_up`），题目未来仍可继续；窗口额度用完
  写 `window_exhausted` 保存现场，未来从下一绝对 Round 继续（非永久终态）。
- **可观测三件套**：
  - 行为流水（`log/flow/*.jsonl`）：launcher 每个状态转移落盘，`churn_suspects` 非空即
    失控循环预警（A14）；
  - 步进门闸（`src/step_gate.py`）：启动/杀会话/重入队等 9 个语义动作可冻结为断点，
    放行必须附理由；
  - alert 体系：系统检测异常但不自动修复，交给 Master Agent 判定（A13 并发四源一致性
    对账、PARSE_ERROR 标记 `audit_passed=None` 待人工）。
- **三层验证铁律**：判断系统状态必须 DB（结果）→ 日志/行为流水（过程）→ 硬盘实物
  （证据）三层交叉，DB 与实物不一致即状态同步 bug（历史上曾出现 DB 报 138 题完成、
  硬盘仅 14 个 proof 的教训）。
- **资产保留铁律**：每个 run/round 的 `conversation.json`（含思考过程的对话录）、
  `round{N}_prompt.txt`、`HANDOVER.md`、归档 proof、tmux 日志一律保留——失败轮的对话
  录是分析 AI 能力边界最有价值的数据。

### 目录导览

| 路径 | 内容 |
|---|---|
| `src/` | 管线实现：collector/feeder/launcher/monitor/result_collector + 观测/门闸/DB schema + 全流程模拟 `src/sim/`（详见 `src/README.md`） |
| `monitoring/` | 运维控制面：`continuation_control`（start/stop/status/set-concurrency/resolve-alert）|
| `scripts/sop/` + `docs/sop/` | Master Agent 9 步 SOP 循环脚本 + 对应执行指令文档 |
| `docs/architecture/`、`docs/specs/`、`docs/patterns/` | 架构概念、监控规范、设计范式 |
| `dev-docs/` | 编号演进文档：001~068（设计方案/复盘/最终成品认知包/工作包体系；068 为公开版整理与上传操作记录） |
| `dev-docs/workpackages/`、`dev-docs/final-system-workpackages/` | 工作包执行体系（依赖图/状态表/exec-log） |
| `templates/` | 三角色提示词模板 + 轮次资产合同（WP-03 冻结） |
| `data/poc_2.7/` | 题单与早期结果 |
| `tmp/` | 实验现场与证据暂存（约定见 `tmp/README.md`） |
| `docs/dev/AI-GUIDE.md` | AI 协作内部引导地图（Session 接手第一步） |

## 使用方法

### 环境准备

> **在新机器上从零复原完整工作环境**（任意路径布局）：按 [docs/RESTORE-GUIDE.md](docs/RESTORE-GUIDE.md)
> 执行——拉取本仓库族的 5 个仓库、恢复 ArangoDB 三库（含全部题目本体）、挂接运行现场目录、配置 `.env`。

```bash
# 依赖：Python 3.12+（.venv）、Redis、ArangoDB、devin cli（或 OpenCode ACP 后端）
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # 如无则按 src/README.md 依赖清单安装

cp .env.example .env              # 填入 ArangoDB 连接与外部数据路径
```

`.env` 关键项：`ARANGO_HOST/DB/USER/PASS`（运行记录库）、`SOLVER_BASE`（解题工作目录）、
`TRAJECTORY_BASE`（轨迹导出目录）、`DATASET_BASE`、`KNOWLEDGE_BASE`（题库目录）。

### 启动 / 停止

```bash
# 启动解题系统 + SOP 监控循环（launcher/monitor 各自进入独立 tmux session）
python -m monitoring.continuation_control start --batch-id p27-full --concurrency 1

# 动态调并发（launcher 下次 poll 自动生效，无需重启）
python -m monitoring.continuation_control set-concurrency --batch-id p27-full --concurrency 3

# 查看状态 / 健康检查
python -m monitoring.continuation_control status --batch-id p27-full
python -m monitoring.continuation_control health --batch-id p27-full

# 优雅停止（不再启动新 run，等 running 自然完成）
python -m monitoring.continuation_control stop
```

SOP 监控循环由 Master Agent 自驱动：执行 `python -m scripts.sop.run`（每轮一个步骤），
9 步循环 01→…→07→Z→OP 往复，即 7×24 监控。

### 日常观测

```bash
python -m src.observability --stats --since 1h        # 行为流水：失控嫌疑/启动Top10/判定分布
python -m src.observability --run-key <run_key>       # 单题完整生命周期
python -m src.step_gate --pending                     # 步进门闸：待放行动作与论证依据
python -m scripts.sop.log_search --problem-id <pid>   # 日志检索
python -m scripts.query_progress.py                   # 进度查询（DB）
```

## 数据资产与数据表

- **运行记录数据表**（ArangoDB `xishujuzhen_math_glm52`：p27_continuation_runs/sessions/
  events/results、devin_problem_runs 5 万+、audit 全链、problem_extraction_progress 246 万条
  等 79 张表；`p27sim` 模拟库；早期 `xishujuzhen_math` 库）→ 整体导出见
  [AI-Math-Solving-Databases](https://github.com/math-fournity/AI-Math-Solving-Databases)
  （JSONL + sha256 manifest + 恢复脚本）。
- **每题运行现场**（对话录 exports、会话轨迹 sessions_db、终端日志 tmux、collector 快照、
  工作目录 prompt/HANDOVER/proof）→ 当前世代见
  [AI-Math-Solving-Trajectories](https://github.com/math-fournity/AI-Math-Solving-Trajectories)，
  早期世代 5 万+ run 归档见
  [AI-Math-Solving-Trajectories-Archive](https://github.com/math-fournity/AI-Math-Solving-Trajectories-Archive)。
- 敏感性说明：上述数据为 AI 解题对话与程序运行记录，不含 API 密钥/凭据（上传前已做
  凭据模式扫描）；mitm 代理原始流量捕获因可能含请求头凭据而未纳入上传。
- 本次公开版整理与上传的操作细节（仓库划分、数据甄别与排除、批次拆分、历史身份改写、
  故障处置与终验结果）见 [dev-docs/068-公开版整理与上传操作记录-2026-09-27.md](dev-docs/068-公开版整理与上传操作记录-2026-09-27.md)。

## 题库（开源数据集）

**题目与解答本体已全量在数据仓库中**（`problem_extraction_progress` 表，246 万题全文，
含早期 13 个来源，覆盖矩阵与逐数据集许可见
[AI-Math-Solving-Databases](https://github.com/math-fournity/AI-Math-Solving-Databases)
README 的"数据集覆盖矩阵"与"Data Licensing"节）。主要题源的上游地址（供对账版本与署名）：

| 数据集 | 上游地址 | 库内文档量 |
|---|---|---|
| OpenMathReasoning | https://huggingface.co/datasets/nvidia/OpenMathReasoning | 724,666（CC-BY-4.0） |
| AoPS-Instruct | https://huggingface.co/datasets/DeepStudentLlama/AoPS-Instruct | 538,954（⚠️ 上游未标注许可，见 Data Licensing） |
| OpenR1-Math | https://huggingface.co/datasets/open-r1/OpenR1-Math-220k | 515,928（Apache-2.0） |
| NuminaMath 系列 | https://huggingface.co/datasets/AI-MO/NuminaMath-CoT | 414,032（Apache-2.0） |
| ODA-Math-460k | https://huggingface.co/datasets/OpenDataArena/ODA-Math-460k | 65,615（CC-BY-NC-4.0） |
| DeepMath-103K | https://huggingface.co/datasets/zwhe99/DeepMath-103K | 32,392（MIT） |
| 其余 33 个来源 | 见 Databases 仓库覆盖矩阵 | ~10 万 |

完整题库索引（10,063 个 HF 数据集的目录元数据，含 URL/tier/题量/许可字段）随
AI-Math-Solving-Databases 仓库发布。

## License

MIT License，见 [LICENSE](LICENSE)。
