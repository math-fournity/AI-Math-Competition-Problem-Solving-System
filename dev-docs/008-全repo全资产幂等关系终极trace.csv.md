# 008-全repo全资产幂等关系终极trace.csv

**日期**：2026-08-19
**性质**：需求记录文档（akash 阶段1）
**状态**：需求已记录

---

## §1 用户原话

> 我忽然发现，我们出现了一个需求：整个repo从文档到代码，所有的所有的，到数据库，到git log，到运行资产，它们的全幂等关系的建立，也就是得到一张终极的trace.csv。

---

## §2 需求解读

### 核心需求

dev-docs/007 只覆盖了 checkpoint→code 的 implements 关系（154个 checkpoint 中的 107 个）。但用户发现这还不够——真正的幂等关系应该覆盖**整个 repo 中所有资产类型之间的所有关系**。

"终极的 trace.csv" = 给定任何一个 commit 时间点，trace.csv 精确反映 repo 中**所有资产**及其**所有关系**。

### 资产类型范围

不只是 checkpoint 和 code，而是：

| 资产类型 | 数量 | 说明 |
|---|---|---|
| 代码文件 | 45 | `src/*.py` + `monitoring/*.py` |
| 脚本文件 | 12 | `scripts/*.sh` + `scripts/*.py` |
| 文档文件 | 21 | `docs/**/*.md` |
| checklist | 156 | `checklist/*.md`（含 README 和 ExecDevin） |
| working-packages | 12 | `working-packages/*.md` |
| dev-docs | 8 | `dev-docs/*.md`（含本文件） |
| 模板文件 | 4 | `docs/templates/*.md` |
| 配置文件 | 3+ | `.env.example`, `src/config.py`, `src/continuation_config.py` |
| git commits | 108 | git log 中的所有 commit |
| DB collections | 15+7 | 15个 analysis/audit/selection/solver collections + 7个 continuation collections |
| 运行资产 | 多个目录 | SOLVER_BASE, TRAJECTORY_BASE, CONTINUATION_SOLVER_BASE, CONTINUATION_TRAJECTORY_BASE, MONITOR_EXEC_EXPORT_BASE, OUTPUT_BASE |
| checkpoint | 154 | 14个门类的功能需求点 |

### 关系类型范围

不只是 implements/specified-by/part-of，而是所有可能的关系：

| 关系类型 | 已有 | 需要补充 |
|---|---|---|
| implements | 11 | checkpoint→code 函数级 |
| specified-by | 3 | checkpoint→document 章节级 |
| part-of | 4 | checkpoint→wp |
| contains | 10 | 文件→函数/章节 |
| changed-in | 5 | 资产→commit |
| changes | 5 | wp/dev-doc→code |
| produces | 8 | wp/dev-doc→document |
| comes-from | 2 | wp→dev-doc |
| depends-on | 2 | 资产→配置/依赖 |
| verifies | 1 | document→checkpoint |
| **reads-from** | 0 | code→DB collection（代码读哪些表） |
| **writes-to** | 0 | code→DB collection（代码写哪些表） |
| **configures** | 0 | config→code（配置项被哪些代码引用） |
| **generates** | 0 | code→运行资产（代码生成哪些运行时产物） |
| **uses-template** | 0 | launcher→template（launcher用哪个prompt模板） |
| **indexes** | 0 | view-file→document（看法文件索引哪些文档） |
| **traces-to** | 0 | 通用追溯 |

### "终极"的含义

1. **全资产覆盖**——repo 中每一个资产都在 trace.csv 中有记录
2. **全关系覆盖**——资产之间的每一种关系都在 trace.csv 中有记录
3. **全层级覆盖**——从文件级到函数级到章节级，所有层级都有记录
4. **幂等**——给定任何 commit 时间点，trace.csv = repo 状态的精确镜像

---

## §3 需求分析（利用 trace.csv 追溯）

### 3.1 现有 trace.csv 覆盖情况

```
追溯关系总数：51
```

### 3.2 差距分析

| 维度 | 现有 | 需要 | 差距 |
|---|---|---|---|
| checkpoint 追溯 | 5/154 | 154 | 149 个孤立 |
| 代码文件追溯 | ~8/45 | 45 | ~37 个孤立 |
| 脚本文件追溯 | ~2/12 | 12 | ~10 个孤立 |
| 文档文件追溯 | ~3/21 | 21 | ~18 个孤立 |
| working-packages 追溯 | 1/12 | 12 | 11 个孤立 |
| dev-docs 追溯 | 7/8 | 8 | 1 个孤立 |
| 模板文件追溯 | 0/4 | 4 | 4 个孤立 |
| 配置文件追溯 | 2/3 | 3 | 1 个孤立 |
| git commits 追溯 | 5/108 | 108 | 103 个孤立 |
| DB collections 追溯 | 0/22 | 22 | 22 个孤立 |
| 运行资产追溯 | 0/6 | 6 | 6 个孤立 |

**总差距**：51 条现有关系 vs 估计需要 1000+ 条关系

### 3.3 需要新增的关系类型

| 关系类型 | 方向 | 说明 | 估计数量 |
|---|---|---|---|
| reads-from | code→DB collection | 代码读哪些 DB 表 | ~30 |
| writes-to | code→DB collection | 代码写哪些 DB 表 | ~30 |
| configures | config→code | 配置项被哪些代码引用 | ~20 |
| generates | code→运行资产 | 代码生成哪些运行时产物 | ~15 |
| uses-template | launcher→template | launcher 用哪个 prompt 模板 | ~5 |
| indexes | view-file→document | 看法文件索引哪些文档 | ~20 |

---

## §4 是否产生新的 checkpoint

**判断**：不产生新的系统功能 checkpoint。

理由：这是一个基础设施建设工程，不是系统功能需求。trace.csv 本身是基础设施，不是系统功能。

---

## §5 验收标准

1. **全资产覆盖**——repo 中每一个资产（代码/脚本/文档/checklist/wp/dev-doc/模板/配置/commit/DB/运行资产）都在 trace.csv 中有至少一条关系
2. **全关系覆盖**——资产之间的每一种关系都有记录
3. **全层级覆盖**——代码精确到函数级，文档精确到章节级
4. **幂等验证**——`trace.py stats` 显示所有资产类型都有分布，无孤立资产
5. **可查询**——给定任何一个资产，`trace.py query` 能追溯到它的所有关系

---

## §6 涉及的元素

**会改动的文件**：
- `trace.csv`——大量新增关系记录
- `scripts/trace.py`——可能需要新增关系类型（reads-from/writes-to/configures/generates/uses-template）
- `dev-docs/`——可能需要分批记录工作进展

**会涉及的现有元素**：
- 整个 repo 的所有文件
- 所有 DB collections
- 所有运行资产目录
- 所有 git commits

---

## §7 和 dev-docs/007 的关系

dev-docs/007 是这个需求的**子集**——007 只覆盖 checkpoint→code 的 implements 关系（107个 checkpoint）。本需求（008）覆盖**所有资产类型的所有关系**。

007 中的 15 个工作包（WP-TRACE-01~15）将被纳入 008 的更大工作包拆解中。
