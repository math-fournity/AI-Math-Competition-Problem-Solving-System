# RESTORE-GUIDE — 从公开仓库族恢复完整工作环境

> **目的**：任何用户/未来 AI 在**任意路径布局**的机器上，仅凭 math-fournity 组织下这 5 个
> GitHub 仓库 + 本指南，即可复原一套与原作者本地等价（但不要求路径相同）的解题系统工作环境。
> 仓库可以放在你选择的任何目录——系统运行时读 `.env` 中的路径，**不依赖任何硬编码位置**。

## 〇、仓库族总览（恢复所需全部远程资产）

| 仓库 | 恢复角色 |
|---|---|
| `AI-Math-Competition-Problem-Solving-System`（主 repo） | 系统代码（src/monitoring/scripts）、SOP、架构文档、`.env.example`、本指南 |
| `AI-Math-Solving-Databases` | ArangoDB 三库全量导出（**含全部题目与解答本体**）+ manifest（sha256）+ 恢复/重映射脚本 + 题库目录索引 |
| `AI-Math-Solving-Trajectories` | 当前世代（p27 续传/v2）每题运行现场：轨迹侧 + 工作目录侧 + SOP 报表 |
| `AI-Math-Solving-Trajectories-Archive` | 早期世代全部运行现场（约 4.9 万组 run） |
| `AI-Math-Normal-Solver` | 平凡解题系统（早期管线代码，历史复现用） |

## 一、推荐目录布局（示例——你可以用任何等价布局）

```
<你的根目录>/
  system/                      # clone 主 repo
  data-repo/                   # clone AI-Math-Solving-Databases
  traj-repo/                   # clone AI-Math-Solving-Trajectories
  archive-repo/                # clone AI-Math-Solving-Trajectories-Archive
  normal-solver/               # clone AI-Math-Normal-Solver
  env/
    solver-base/               # 工作目录基座（SOLVER_BASE）
    trajectory-base/           # 轨迹基座（TRAJECTORY_BASE）
```

**关键映射**（原环境两个基座内的内容就是两个轨迹仓库的内容）：

| 原环境位置 | 来源 |
|---|---|
| `$TRAJECTORY_BASE/p27-continuation/*` | traj-repo 的 `p27-continuation/` |
| `$TRAJECTORY_BASE/v2-continuation/*` | traj-repo 的 `v2-continuation/` |
| `$TRAJECTORY_BASE/p27-sop-reports/*` | traj-repo 的 `p27-sop-reports/` |
| `$TRAJECTORY_BASE/<早期世代 run 目录>` | archive-repo 的 `runs/` 下同名目录 |
| `$SOLVER_BASE/p27-continuation/*` | traj-repo 的 `p27-workdirs/` |
| `$SOLVER_BASE/<早期世代>` | archive-repo 的 `workdirs/` |
| `$KNOWLEDGE_BASE`（题库目录） | data-repo 的 `problem-bank-catalogs/`（题目本体已在 DB，目录仅作索引） |

两种做法等价：① 直接把 `.env` 的 `SOLVER_BASE`/`TRAJECTORY_BASE` 指向 clone 出的仓库内
对应子目录的上层；② 或用符号链接把仓库子目录按上表挂进你自己的基座布局。**不要复制**——
保持 git 工作树可 `git pull` 更新。

## 二、依赖服务与安装

```bash
# 1) Python 3.12+ + 依赖
cd system && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 2) ArangoDB（任意可用实例，版本 3.11+ 均可）
# 3) Redis（空实例即可——队列是瞬态的，无需恢复任何内容）
```

## 三、恢复数据库（核心步骤）

```bash
cd data-repo
python scripts/restore_arangodb_dump.py \
    --host http://<你的arango>:8529 --user root --password <pass>
# 恢复三库：xishujuzhen_math_glm52（主库 79 表，含 246 万题全文）/ xishujuzhen_math / p27sim
# 演练/并行恢复用 --suffix _restored 恢复到带后缀的库名，绝不覆盖既有库
# 校验：脚本逐文件核对 manifest 的 sha256，逐表打印导入行数，与 manifest docs 对账
```

- **题目本体就在库里**：`problem_extraction_progress` 全字段导出（含 `problem_text`/
  `solution_text`），无需再从上游数据集拉取即可完整重建题库状态。
- **历史路径字段语义**：库内 `solver_dir` 等字段是溯源记录，导出时已统一中性化
  （原始机器路径 → `/Volumes/data/...`、`/Users/user/...`，规则见 manifest `_substitutions`）。
  系统运行读 `.env`，不读这些字段；如希望它们指向你本机真实布局，运行：
  `python scripts/remap_paths.py --password <pass> --map /Volumes/data=</你的路径>`（支持 --dry-run）。

## 四、配置 `.env` 并验证

```bash
cd system && cp .env.example .env   # 按你的实际布局填写（.env.example 内有逐项说明）
source .env
python -m monitoring.continuation_control status --batch-id p27-full   # 应能连通 DB/Redis 并报状态
```

**恢复自检清单**（全部通过即环境等价）：

1. `data-repo`：restore 脚本逐表行数 == manifest `docs` 字段；
2. `ls $TRAJECTORY_BASE/p27-continuation | wc -l` ≈ 10k（生产轨迹目录）；
3. 抽一个 run：`$SOLVER_BASE/p27-continuation/<run>/problem.txt` 存在且与 DB 中
   `p27_continuation_runs` 该题记录对得上；
4. 主 repo `python -m scripts.sop.run`（SOP 循环第一步）可执行。

## 五、边界： intentionally 未随仓库发布的内容

| 内容 | 原因 | 影响 |
|---|---|---|
| `DATASET_BASE`（上游原始数据集 62GB） | 全部为公开开源数据集，按 README 所列 URL 自取 | 无——题目已全量在 DB |
| mitm 代理原始流量捕获 | 可能含请求头凭据 | 无——对话录/轨迹已完整保留 |
| devin 失败分析 `_logs` 原始日志 | 无引用价值 | 无——分析结论在 dev-docs |
| `email_project` 等其他项目库 | 密钥材料/无关项目 | 无 |
| Redis 内容 | 瞬态队列，按设计可丢弃 | 无 |

## 六、数据许可

代码 MIT（各仓库 LICENSE）。**题目与解答数据遵循各上游数据集许可**
（如 Omni-MATH=Apache-2.0、ODA-Math-460k=CC-BY-NC-4.0），详见 data-repo README
"Data Licensing"；本仓库族整体为非商业研究归档用途。
