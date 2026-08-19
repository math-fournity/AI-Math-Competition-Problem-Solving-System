# 009-全repo全资产幂等关系终极trace.csv方案

**日期**：2026-08-19
**性质**：方案文档（akash 阶段2）
**状态**：方案已制定
**需求引用**：`dev-docs/008-全repo全资产幂等关系终极trace.csv.md`

---

## §1 需求引用

本方案承接 `dev-docs/008` 的需求：建立整个 repo 从文档到代码、到数据库、到 git log、到运行资产的全幂等关系，得到一张终极的 trace.csv。

008 已完成需求分析（资产类型范围、关系类型范围、差距分析、验收标准）。本方案制定具体的执行路径。

---

## §2 现状分析（利用 trace.csv 追溯）

### 2.1 现有 trace.csv 规模

```
追溯关系总数：53
含commit id的记录：10
```

### 2.2 追溯链抽查结果（阶段2幂等检查——充分利用追溯链）

对关键资产做 `trace.py query`，确认覆盖差距：

| 资产 | 现有关系 | 差距 |
|---|---|---|
| `src/config.py` | 1 outgoing (changed-in) + 2 incoming | 无 configures 关系（应被几十个代码文件 depends-on） |
| `monitoring/continuation_control.py` | 1 outgoing (changed-in) | 无 reads-from/writes-to DB 关系，无 implements 关系 |
| `docs/system/AnalysisSystem.md` | **0 条关系（完全孤立）** | 应有 changed-in、indexed-by、被 README.md organizes |
| `WP-01` | 1 incoming (part-of) | 无 comes-from dev-doc、无 creates checkpoint |
| `ENV-01` | 1 outgoing (part-of WP-01) | 无 implements、无 specified-by |

### 2.3 资产枚举结果（阶段2追溯工作产出）

通过 `ls`/`find`/`git log`/读配置文件，枚举出 repo 全部资产：

| 资产类型 | 数量 | 枚举来源 |
|---|---|---|
| 代码文件 (src/*.py) | 29 | `ls src/*.py` |
| 代码文件 (monitoring/*.py) | 16 | `ls monitoring/*.py` |
| 脚本文件 (scripts/*.sh) | 4 | `ls scripts/*.sh` |
| 脚本文件 (scripts/*.py) | 8 | `ls scripts/*.py` |
| 文档文件 (docs/**/*.md) | 21 | `find docs -name '*.md'` |
| checklist 文件 | 156 | `ls checklist/*.md` |
| working-packages 文件 | 12 | `ls working-packages/*.md` |
| dev-docs 文件 | 8 | `ls dev-docs/*.md` |
| 模板文件 | 4 | `ls docs/templates/*.md` |
| 配置文件 | 3 | `.env.example` + `src/config.py` + `src/continuation_config.py` |
| git commits | 109 | `git log --oneline --all` |
| DB collections | 11 | 读 config.py + continuation_config.py + db_schema.py |
| 运行资产（路径常量） | 11 | 读 config.py + continuation_config.py |
| views/ 看法文件 | 0 | `ls views/`（目录不存在） |

**DB collections 完整清单**（11个，修正008的"15+7"估算）：
1. `analysis_batches`（db_schema.py 定义）
2. `analysis_runs`（config.py 定义）
3. `analysis_events`（config.py 定义）
4. `analysis_results`（config.py 定义）
5. `analysis_counters`（db_schema.py 定义）
6. `p27_continuation_batches`（continuation_config.py 定义）
7. `p27_continuation_runs`（continuation_config.py 定义）
8. `p27_continuation_events`（continuation_config.py 定义）
9. `p27_continuation_results`（continuation_config.py 定义）
10. `p27_monitor_alerts`（continuation_config.py 定义）
11. `p27_sessions`（continuation_config.py 定义）

**运行资产完整清单**（11个路径常量）：
- 环境变量输入：`SOLVER_BASE`、`TRAJECTORY_BASE`、`DATASET_BASE`、`KNOWLEDGE_BASE`
- 派生路径（config.py）：`ANALYSIS_SOLVER_BASE`、`ANALYSIS_TRAJECTORY_BASE`、`OUTPUT_BASE`
- 派生路径（continuation_config.py）：`CONTINUATION_SOLVER_BASE`、`CONTINUATION_TRAJECTORY_BASE`、`MONITOR_EXEC_EXPORT_BASE`、`POC_2_7_DIR`

### 2.4 孤立资产识别

**完全孤立的资产类型**（trace.csv 中 0 条关系）：
- 全部 11 个 DB collections
- 全部 11 个运行资产
- 全部 4 个模板文件
- `views/` 看法文件（目录不存在，0个资产）
- 109 个 git commits 中只有 5 个有 changed-in 关系

**大量孤立的资产类型**：
- 21 个文档文件中只有 4 个有关系（README.md、checklist/README.md、docs/specs/p27_monitor_spec.md、dev-docs 自引用）
- 156 个 checkpoint 中只有 5 个有关系（ENV-01、ENV-07、MON-A1、MON-A2、RUN-01）
- 12 个 working-packages 中只有 WP-01、WP-09 有关系
- 45 个代码文件中只有 ~8 个有关系

### 2.5 幂等关系现有差距分析

| 差距类型 | 说明 | 影响 |
|---|---|---|
| 资产类型缺失 | trace.py 无 `db-collection`/`runtime-asset`/`template`/`config` 类型 | DB和运行资产无法录入 |
| 关系类型缺失 | trace.py 无 `reads-from`/`writes-to`/`configures`/`generates`/`uses-template`/`indexes` | 6种关系无法表达 |
| checkpoint 覆盖率低 | 5/156 = 3.2% | 151个checkpoint孤立 |
| 代码覆盖率低 | ~8/45 = 17.8% | 37个代码文件孤立 |
| 文档覆盖率低 | 4/21 = 19% | 17个文档孤立 |
| commit 覆盖率低 | 5/109 = 4.6% | 104个commit孤立 |
| 函数级覆盖缺失 | 只有10个contains关系 | 代码函数级追溯几乎空白 |
| 文档章节级覆盖缺失 | 只有1个contains关系 | 文档章节级追溯几乎空白 |

---

## §3 方案设计

### 3.1 总体策略

**分两步走**：
1. **第一步：扩展 trace.py 基础设施**——新增资产类型和关系类型，否则新关系无法录入
2. **第二步：分批次录入关系**——按关系类型/资产类型分工作包，每批录入后 commit

### 3.2 trace.py 扩展设计

#### 新增资产类型

| 类型 | 说明 | id格式 |
|---|---|---|
| `db-collection` | ArangoDB集合 | 集合名（如 `analysis_runs`） |
| `runtime-asset` | 运行时路径资产 | 路径常量名（如 `SOLVER_BASE`） |
| `template` | prompt模板文件 | 文件路径（如 `docs/templates/analysis_agents_md.md`） |
| `config` | 配置文件 | 文件路径（如 `src/config.py`） |

> `template` 和 `config` 也可以复用 `document` 类型，但它们语义不同（模板是被launcher使用的，配置是被代码引用的），独立类型更清晰。

#### 新增关系类型

| 关系 | 方向 | 说明 |
|---|---|---|
| `reads-from` | code→db-collection | 代码读哪些DB表 |
| `writes-to` | code→db-collection | 代码写哪些DB表 |
| `configures` | config→code | 配置项被哪些代码引用 |
| `generates` | code→runtime-asset | 代码生成哪些运行时产物 |
| `uses-template` | code→template | launcher用哪个prompt模板 |
| `indexes` | view-file→document | 看法文件索引哪些文档 |

> `indexes` 是 `indexed-by` 的反向关系。当前 `views/` 目录不存在，此关系类型预留，待看法文件建立后录入。

#### 扩展实现

修改 `scripts/trace.py` 的 `ASSET_TYPES` 和 `RELATION_TYPES` 字典，新增上述条目。这是纯字典扩展，不涉及逻辑改动，`asset_level` 函数已能处理任意字符串id。

### 3.3 资产枚举脚本设计

新建 `scripts/enumerate_assets.py`——自动扫描 repo 产出全资产清单（CSV格式），作为关系录入的基础底表。

**产出**：`scripts/asset_inventory.csv`，列：`asset_type, asset_id, file_path, description`

**扫描范围**：
- `src/*.py`、`monitoring/*.py` → code
- `scripts/*.sh`、`scripts/*.py` → script
- `docs/**/*.md` → document
- `checklist/*.md` → checkpoint（从文件名提取编号）
- `working-packages/WP-*.md` → wp
- `dev-docs/*.md` → dev-doc
- `docs/templates/*.md` → template
- `.env.example`、`src/config.py`、`src/continuation_config.py` → config
- `git log --oneline --all` → commit
- 从 config.py/continuation_config.py 静态提取 → db-collection、runtime-asset

### 3.4 关系录入策略

**按关系类型分批，每批一个工作包**。录入顺序按依赖关系：

1. **contains 关系**（文件→函数/章节）——基础层，其他关系引用函数级id
2. **checkpoint 关系**（implements + specified-by + part-of）——需求层
3. **dev-doc/wp 关系**（produces + changes + comes-from + creates）——方案层
4. **changed-in 关系**（资产→commit）——历史层，需要逐commit分析
5. **DB 关系**（reads-from + writes-to）——运行时层
6. **配置/模板/运行资产关系**（configures + generates + uses-template）——基础设施层
7. **幂等验证 + 孤立资产补全**——收尾

### 3.5 关系录入方法

**半自动**：
- `contains`（代码函数）：用 `grep` 提取 `def ` 行，生成函数清单，批量录入
- `contains`（文档章节）：用 `grep` 提取 `^##` 行，生成章节清单，批量录入
- `implements`（checkpoint→code）：读 checkpoint 文件中的"涉及的代码"字段 + 人工核对
- `reads-from`/`writes-to`（code→DB）：grep 代码中的 collection 常量引用
- `configures`（config→code）：grep 代码中的 `from .config import` / `from .continuation_config import`
- `generates`（code→运行资产）：grep 代码中的路径常量引用
- `uses-template`（launcher→template）：grep 代码中的 `AGENTS_MD_TEMPLATE` 等模板常量
- `changed-in`（资产→commit）：`git log --name-only` 提取每个commit改动的文件

**录入脚本**：为每批关系写一个录入脚本（放 `scripts/`），从代码/文档中自动提取关系，调用 `trace.py add` 录入。避免手工逐条录入的错误。

---

## §4 checkpoint 建立/更新

**不产生新 checkpoint**（已在008§4判断）。这是基础设施建设工程，不是系统功能需求。

---

## §5 认知准备

每个工作包的执行 AI 需要加载的认知：

| 工作包 | 需要的认知 |
|---|---|
| trace.py 扩展 | `scripts/trace.py` 全文、本方案§3.2 |
| 资产枚举脚本 | 本方案§3.3、repo 目录结构 |
| contains 关系 | 代码文件结构（def行）、文档结构（##行） |
| checkpoint 关系 | `checklist/README.md` 门类索引、各 checkpoint 文件的"涉及代码"字段 |
| dev-doc/wp 关系 | 各 dev-doc 和 wp 文件内容 |
| changed-in 关系 | `git log --name-only` 输出 |
| DB 关系 | `src/config.py`、`src/continuation_config.py`、`src/db_schema.py`、`src/continuation_db_schema.py` |
| 配置/模板/运行资产 | config.py、continuation_config.py、launcher 代码 |

---

## §6 元数据更新计划

本方案本身会大量新增 trace.csv 关系。需要同步更新的看法文件：

| 会改动的资产 | 需要同步的看法文件 | 同步内容 |
|---|---|---|
| `scripts/trace.py` | 无（trace.py 自身是基础设施） | — |
| `trace.csv` | 无（trace.csv 自身是追溯索引） | — |
| `README.md` | 无（README 是引导地图，不涉及追溯细节） | — |
| `AGENTS.md` | 可能需要更新（如果新增脚本要索引） | 新脚本路径索引 |

**本方案不改动代码和文档内容**，只扩展 trace.py 和填充 trace.csv。因此元数据更新范围很小。

---

## §7 工作包拆解预案

初步判断需要 **8个工作包**：

| WP | 标题 | 内容 | 依赖 |
|---|---|---|---|
| WP-TRACE-01 | trace.py 扩展 | 新增4个资产类型 + 6个关系类型 | 无 |
| WP-TRACE-02 | 资产枚举脚本 + 全资产清单 | enumerate_assets.py + asset_inventory.csv | WP-TRACE-01 |
| WP-TRACE-03 | contains 关系录入 | 代码函数级 + 文档章节级 | WP-TRACE-02 |
| WP-TRACE-04 | checkpoint 关系录入 | implements + specified-by + part-of（154个checkpoint） | WP-TRACE-03 |
| WP-TRACE-05 | dev-doc/wp 关系录入 | produces + changes + comes-from + creates | WP-TRACE-03 |
| WP-TRACE-06 | changed-in 关系录入 | 逐commit分析，109个commit | WP-TRACE-03 |
| WP-TRACE-07 | DB/配置/模板/运行资产关系录入 | reads-from + writes-to + configures + generates + uses-template | WP-TRACE-01 |
| WP-TRACE-08 | 幂等验证 + 孤立资产补全 | trace.py stats + 抽查 + 补全 | WP-TRACE-03~07 |

**依赖关系**：WP-TRACE-01 → WP-TRACE-02 → WP-TRACE-03 → (WP-TRACE-04, 05, 06, 07 可并行) → WP-TRACE-08

**工作量估计**（基于资产数量的有理有据推理）：
- WP-TRACE-01：trace.py 字典扩展，~20行改动
- WP-TRACE-02：枚举脚本 ~100行 + 扫描产出 ~300行CSV
- WP-TRACE-03：代码函数 ~225条 + 文档章节 ~100条 = ~325条关系
- WP-TRACE-04：154 checkpoint × 平均3条关系 = ~462条
- WP-TRACE-05：8 dev-doc + 12 wp × 平均5条 = ~100条
- WP-TRACE-06：109 commit × 平均2条 = ~218条
- WP-TRACE-07：~100条（reads-from ~30 + writes-to ~30 + configures ~20 + generates ~15 + uses-template ~5）
- WP-TRACE-08：验证 + 补全

**总估计**：~1300条关系（修正008的"1000+"估计，基于资产枚举的精确推理）

---

## §8 验收标准（继承自008§5）

1. **全资产覆盖**——`asset_inventory.csv` 中每个资产在 trace.csv 中有至少一条关系
2. **全关系覆盖**——§3.2 定义的16种关系类型都有记录（除 `indexes` 因 views/ 不存在暂为0）
3. **全层级覆盖**——代码精确到函数级，文档精确到章节级
4. **幂等验证**——`trace.py stats` 显示所有资产类型都有分布，无孤立资产
5. **可查询**——给定任何一个资产，`trace.py query` 能追溯到它的所有关系

---

## §9 遗留问题

1. **`views/` 目录不存在**——008提到的 view-file/indexes 关系目前无法录入。这是 read-sync skill 的产物，需要单独建立看法文件后才能录入 indexes 关系。本方案预留关系类型，不强制建立看法文件。
2. **`continuation_config.py` 的 DEVIN_MODEL 违规**——已有 trace.csv 记录（`depends-on` 关系，note标注"违规！缺少.high"），本方案不修复此违规，只记录关系。
3. **commit 级 changed-in 关系工作量**——109个commit逐个分析改动文件，是工作量最大的一批。可考虑用 `git log --name-only` 批量提取后半自动录入。
