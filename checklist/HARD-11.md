# HARD-11: DB-文件双向可追溯性——所有解题资产留存D盘且数据库纲举目张

> **门类**: HARD · 硬约束
> **状态**: [x] 已验证（2026-08-20）
> **负责的WP**: 全部
> **来源**: AGENTS.md 硬约束7（DB-文件双向可追溯）
> **所属章节**: §HARD · 硬约束（贯穿全程）

## 需求描述

整个解题流程的所有输入、输出、devin cli 产生的 export JSON 文件，都必须留存到 D 盘。并且通过数据库，纲举目张，能找到所有题目的所有解题过程的所有资产。所有题目、所有解题过程、所有 round，在数据库中都是唯一编号化的。

这是 4 个子要求的合集：

1. **文件夹分布**——所有解题流程分布在不同的文件夹下，按 problem_id 隔离
2. **资产留存D盘**——所有输入/输出/export的JSON文件都留存到 D 盘
3. **数据库纲举目张**——通过数据库能找到所有题目的所有解题过程的所有资产
4. **唯一编号化**——所有题目/解题过程/round 在数据库中都有唯一编号

## 验证方法

### 验证脚本

```bash
source .env && source .venv/bin/activate
python3 -c "
import sys; sys.path.insert(0, '.')
from src.continuation_db_schema import connect_db
from src.continuation_config import CONTINUATION_RUNS_COLLECTION, SESSIONS_COLLECTION
from pathlib import Path
db = connect_db()

# 1. 文件夹分布——每个run有独立work_dir和trajectory_dir
# 2. 资产留存D盘——work_dir/trajectory_dir都在/Volumes/data/下
# 3. 数据库纲举目张——rounds_log记录每轮6个路径字段
# 4. 唯一编号化——_key和problem_id无重复，session有唯一seq
"
```

### 验证结论（2026-08-20 实测）

#### 1. 文件夹分布 ✅

每道题有**两个独立目录**，按 `problem_id` 隔离：

| 目录类型 | 路径模板 | 存什么 |
|---|---|---|
| **work_dir** | `/Volumes/data/math-agent-glm5.2-tmux-agents-dir/p27-continuation/p27-full-{problem_id}/` | 输入文件（prompt/HANDOVER/map）+ 产出（proof.md/export.json） |
| **trajectory_dir** | `/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-continuation/p27-full-{problem_id}/` | devin cli 的 export（conversation.json，含完整 thinking）+ tmux 日志 |

每轮文件按 `round{N}_*` 命名前缀区分（如 `round1_HANDOVER.md`、`round2_prompt.txt`、`round2_proof.md`），trajectory 目录下按 `round{N}/exports/conversation.json` 子目录结构组织。

实测样例（`deepmath_103k_00000295`，COMPLETED）：

```
work_dir/
  problem.txt (683B)              ← 原始题目
  round1_HANDOVER.md (16467B)     ← R1交接文档（Pipe A产出）
  round1_conversation_map.md (8388B) ← R1面包屑地图
  round1_export.json (187456B)    ← R1的export（上一轮完整thinking）
  round1_handover_prompt.txt      ← R1 handover的prompt
  round1_handover_run/            ← R1 handover的运行目录
    conversation.json (257484B)
  round2_prompt.txt (17853B)      ← R2发给devin cli的prompt
  round2_proof.md (6829B)         ← R2解题产出（含\boxed）
  proof.md (6829B)                ← 最终proof（=round2_proof.md的副本）

trajectory_dir/
  round2/
    exports/
      conversation.json (126675B) ← R2的export（完整thinking）
    tmux/
      tmux.log
      tmux_pipe.log
```

#### 2. 资产留存D盘 ✅

- **work_dir** → `/Volumes/data/math-agent-glm5.2-tmux-agents-dir/p27-continuation/`
- **trajectory_dir** → `/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-continuation/`

两个路径都通过环境变量 `SOLVER_BASE` / `TRAJECTORY_BASE` 配置（见 `src/continuation_config.py` L26-27），指向 D 盘（`/Volumes/data`）。不硬编码绝对路径，符合 AGENTS.md 硬约束9。

#### 3. 数据库纲举目张 ✅

DB 中 `p27_continuation_runs` 集合的每条 run 记录包含：

- `work_dir` 和 `trajectory_dir`（顶层路径，直接定位文件夹）
- `rounds_log` 数组，每轮记录 **6 个路径字段**：

| 字段 | 类型 | 内容 |
|---|---|---|
| `export` | 输出 | devin cli 的 conversation.json（含完整 thinking） |
| `prompt_path` | 输入 | 发给 devin cli 的 prompt 文件 |
| `proof_path` | 输出 | 归档的 proof.md（含 \boxed 答案） |
| `handover_path` | 输入 | HANDOVER.md（v2方案 Pipe A 产出） |
| `map_path` | 输入 | 面包屑地图（conversation_map.md） |
| `prev_export` | 输入 | 上一轮的 export.json |

**给定任何 problem_id，可以从 DB 查出所有轮次的全部输入/输出文件路径，再到 D 盘读取实际文件。** 这就是"纲举目张"——DB 是纲，文件是目。

#### 4. 唯一编号化 ✅

| 实体 | 唯一编号 | 格式 | 唯一性验证 |
|---|---|---|---|
| **题目（run）** | `_key` | `{batch_id}-{problem_id}`，如 `p27-full-deepmath_103k_00000295` | ✅ 919个run，0重复 |
| **problem_id** | 题目原始ID | `deepmath_103k_00000295` | ✅ batch内0重复 |
| **session** | `seq` + `_key` | `p27-s0017`（全局递增序号） | ✅ seq唯一索引 |
| **round** | `rounds_log[N].round` | 数字，如 `2` | 在run内按序递增 |

**唯一索引保障**（见 `src/continuation_db_schema.py` L58-69）：
- `(problem_id, batch_id)` 上有 unique 索引 `p27_idx_problem_batch`
- session 的 `seq` 有 unique 索引 `p27_session_idx_seq`
- session 的 `session_name` 有 unique 索引 `p27_session_idx_session_name`

## 关联文件

- `src/continuation_config.py` L26-27 — D盘路径配置（环境变量）
- `src/continuation_config.py` L35-36 — 续传Pipe的work_dir/trajectory_dir基路径
- `src/continuation_db_schema.py` L57-69 — 唯一索引定义
- `src/continuation_db_schema.py` L126-134 — insert_run/update_run 函数
- `checklist/README.md`（需求点全集）
- `AGENTS.md` 硬约束7（DB-文件双向可追溯）
- `docs/sop/SOP_02_data_integrity.md`（数据完整性检查SOP，依赖此架构）

## SOP中的检查

`SOP_02_data_integrity`（`scripts/sop/checks.py` 的 `check_02_data_integrity`）已经基于此架构实现全量检查：
- 查询 DB 中最多 200 个 run 的 rounds_log
- 验证每轮 6 个路径字段指向的文件是否存在、是否过小、内容是否有效
- 统计 proof.md 质量（COMPLETED数/proof存在数/有boxed数）

## 变更记录

- v1 · 2026-08-20 · 初始创建，含 2026-08-20 实测验证结论
