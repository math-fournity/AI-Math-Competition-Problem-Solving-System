# WP-TRACE: 全repo全资产幂等关系终极trace.csv

> **依据**：dev-docs/008（需求）+ dev-docs/009（方案）
> **优先级**：P1（基础设施建设工程）
> **前置条件**：无
> **预估工作量**：大（~1300条关系录入，7个工作包）

---

## 总览

本工作包群建立整个 repo 从文档到代码、到数据库、到 git log、到运行资产的全幂等关系。包含7个子工作包，按依赖顺序执行：

| 子WP | 标题 | 依赖 | 估计关系数 |
|---|---|---|---|
| WP-TRACE-01 | trace.py扩展 + 资产枚举 | 无 | 基础设施 |
| WP-TRACE-02 | contains关系录入 | 01 | ~325 |
| WP-TRACE-03 | checkpoint关系录入 | 02 | ~462 |
| WP-TRACE-04 | dev-doc/wp关系录入 | 02 | ~100 |
| WP-TRACE-05 | changed-in关系录入 | 02 | ~218 |
| WP-TRACE-06 | DB/配置/模板/运行资产关系录入 | 01 | ~100 |
| WP-TRACE-07 | 幂等验证 + 孤立资产补全 | 02~06 | 收尾 |

**依赖图**：01 → 02 → (03, 04, 05, 06 可并行) → 07

---

## 执行 AI 通用规范（所有子WP适用）

### 幂等关系利用（执行前）

每个子WP执行前，必须用 `trace.py` 追溯本工作包涉及的元素：
```bash
python3 scripts/trace.py query <type> <id>       # 查某资产现有关系
python3 scripts/trace.py query-prefix <type> <prefix>  # 查某文件下所有子资产
python3 scripts/trace.py stats                    # 查当前全局覆盖情况
```

**特殊情况说明**：本工作包群的目的就是建设 trace.csv，所以执行 WP-TRACE-01~06 时 trace.csv 正在被填充。执行前利用已有部分 + `scripts/asset_inventory.csv`（WP-TRACE-01产出）了解当前覆盖情况。

### 幂等关系维护（执行中）

每次 commit 前必须维护 trace.csv，commit 同时包含 repo 变更和 trace.csv 变更：
```bash
git add <改动文件> trace.csv
git commit -m "..."
```

### 幂等关系修复（执行中）

如发现孤立资产（无追溯关系的资产），主动补全。用 `trace.py stats` 检查覆盖分布，用 `asset_inventory.csv` 对比找出孤立资产。

### 密集 git 提交

每完成一个逻辑单元（如一个代码文件的函数级 contains 关系录入）就 commit。不要攒一批最后一起提交。

---

## WP-TRACE-01: trace.py扩展 + 资产枚举

### 目标

1. 扩展 `scripts/trace.py`：新增4个资产类型 + 6个关系类型
2. 新建 `scripts/enumerate_assets.py`：自动扫描 repo 产出全资产清单
3. 产出 `scripts/asset_inventory.csv`：全资产底表

### 要读的文档

- `dev-docs/009` §3.2（trace.py扩展设计）+ §3.3（资产枚举脚本设计）
- `scripts/trace.py` 全文（了解现有 ASSET_TYPES 和 RELATION_TYPES）

### 任务清单

- [ ] 扩展 `scripts/trace.py`：
  - ASSET_TYPES 新增：`db-collection`、`runtime-asset`、`template`、`config`
  - RELATION_TYPES 新增：`reads-from`、`writes-to`、`configures`、`generates`、`uses-template`、`indexes`
  - 验证：`python3 scripts/trace.py list-types` 显示新增类型
- [ ] 新建 `scripts/enumerate_assets.py`：
  - 扫描 src/*.py、monitoring/*.py → code
  - 扫描 scripts/*.sh、scripts/*.py → script
  - 扫描 docs/**/*.md → document
  - 扫描 checklist/*.md → checkpoint（从文件名提取编号）
  - 扫描 working-packages/WP-*.md → wp
  - 扫描 dev-docs/*.md → dev-doc
  - 扫描 docs/templates/*.md → template
  - 扫描 .env.example、src/config.py、src/continuation_config.py → config
  - `git log --oneline --all` → commit
  - 从 config.py/continuation_config.py 静态提取 → db-collection、runtime-asset
  - 产出 `scripts/asset_inventory.csv`（列：asset_type, asset_id, file_path, description）
- [ ] 运行 `python3 scripts/enumerate_assets.py` 生成 asset_inventory.csv
- [ ] 验证 asset_inventory.csv 覆盖所有资产类型
- [ ] trace.csv 记录新增脚本 + commit

### 验证标准

- `python3 scripts/trace.py list-types` 显示新增4个资产类型 + 6个关系类型
- `scripts/asset_inventory.csv` 存在且包含所有资产类型
- 资产数量与方案§2.3枚举结果一致

---

## WP-TRACE-02: contains关系录入

### 目标

录入文件→函数/章节的 contains 关系：
- 代码文件 → 函数（`def ` 行提取）
- 文档文件 → 章节（`^##` 行提取）

### 要读的文档

- `dev-docs/009` §3.4（关系录入方法）
- `scripts/asset_inventory.csv`（资产底表）

### 任务清单

- [ ] 写录入脚本 `scripts/trace_contains.py`：
  - 扫描所有 code 类型资产的 `def ` 行，提取函数名
  - 生成 contains 关系：`code <file> contains code <file>::<function>`
  - 扫描所有 document 类型资产的 `^##` 行，提取章节名
  - 生成 contains 关系：`document <file> contains document <file>#<section>`
- [ ] 运行脚本录入 contains 关系
- [ ] 验证：`python3 scripts/trace.py query-relation contains` 显示新增关系
- [ ] trace.csv 已更新（脚本直接写入）+ commit

### 验证标准

- contains 关系数量 ~325条（代码函数 ~225 + 文档章节 ~100）
- `python3 scripts/trace.py query-prefix code src/config.py` 显示 config.py 的所有函数

---

## WP-TRACE-03: checkpoint关系录入

### 目标

录入 checkpoint 的三种关系：
- `implements`：checkpoint → code/function（需求实现为代码）
- `specified-by`：checkpoint → document/section（需求由文档规范定义）
- `part-of`：checkpoint → wp（需求属于工作包）

### 要读的文档

- `checklist/README.md`（门类索引）
- 各 `checklist/<编号>.md` 文件的"涉及的代码"字段
- `scripts/asset_inventory.csv`

### 任务清单

- [ ] 写录入脚本 `scripts/trace_checkpoints.py`：
  - 遍历 156 个 checkpoint 文件
  - 提取每个 checkpoint 的"涉及的代码"字段 → 生成 implements 关系
  - 提取每个 checkpoint 的"涉及的文档"字段 → 生成 specified-by 关系
  - 提取每个 checkpoint 的"负责的WP"字段 → 生成 part-of 关系
  - 对于文件中没有明确字段的 checkpoint，根据 checkpoint 编号前缀推断门类，关联到对应文档
- [ ] 运行脚本录入 checkpoint 关系
- [ ] 验证：`python3 scripts/trace.py query checkpoint ENV-01` 显示完整关系
- [ ] commit

### 验证标准

- checkpoint 关系数量 ~462条（154 checkpoint × 平均3条）
- 154 个 checkpoint 中至少 140 个有至少一条关系（覆盖率 ≥90%）

---

## WP-TRACE-04: dev-doc/wp关系录入

### 目标

录入 dev-doc 和 wp 的四种关系：
- `produces`：dev-doc/wp → document（产生文档）
- `changes`：dev-doc/wp → code（改动代码）
- `comes-from`：wp → dev-doc（工作包来自方案）
- `creates`：wp → checkpoint（创建需求点）

### 要读的文档

- 各 `dev-docs/*.md` 文件内容
- 各 `working-packages/WP-*.md` 文件内容
- `scripts/asset_inventory.csv`

### 任务清单

- [ ] 遍历 8 个 dev-doc 文件，提取产出/改动的文件 → 生成 produces/changes 关系
- [ ] 遍历 12 个 WP 文件，提取来源方案 → 生成 comes-from 关系
- [ ] 遍历 12 个 WP 文件，提取创建的 checkpoint → 生成 creates 关系
- [ ] 录入到 trace.csv
- [ ] 验证：`python3 scripts/trace.py query dev-doc dev-docs/001-目录结构扁平化重组方案.md` 显示完整关系
- [ ] commit

### 验证标准

- dev-doc/wp 关系数量 ~100条
- 8 个 dev-doc 和 12 个 wp 都有至少一条关系

---

## WP-TRACE-05: changed-in关系录入

### 目标

录入资产→commit 的 changed-in 关系：逐 commit 分析改动的文件。

### 要读的文档

- `git log --name-only --all` 输出

### 任务清单

- [ ] 写录入脚本 `scripts/trace_commits.py`：
  - `git log --name-only --all` 提取每个 commit 改动的文件
  - 对每个改动文件，生成 changed-in 关系：`<type> <file> changed-in commit <hash>`
  - 文件类型推断：.py → code/script，.md → document/checklist/wp/dev-doc/template/config
- [ ] 运行脚本录入 changed-in 关系
- [ ] 验证：`python3 scripts/trace.py query-relation changed-in` 显示新增关系
- [ ] commit

### 验证标准

- changed-in 关系数量 ~218条（109 commit × 平均2个文件）
- 109 个 commit 中至少 100 个有至少一条 changed-in 关系

---

## WP-TRACE-06: DB/配置/模板/运行资产关系录入

### 目标

录入基础设施层关系：
- `reads-from`：code → db-collection（代码读哪些DB表）
- `writes-to`：code → db-collection（代码写哪些DB表）
- `configures`：config → code（配置项被哪些代码引用）
- `generates`：code → runtime-asset（代码生成哪些运行时产物）
- `uses-template`：code → template（launcher用哪个prompt模板）

### 要读的文档

- `src/config.py`、`src/continuation_config.py`（配置常量定义）
- `src/db_schema.py`、`src/continuation_db_schema.py`（DB collection 定义）
- 各 launcher 代码（模板引用）
- `scripts/asset_inventory.csv`

### 任务清单

- [ ] 写录入脚本 `scripts/trace_infra.py`：
  - grep 代码中的 collection 常量引用 → 生成 reads-from/writes-to 关系
  - grep 代码中的 `from .config import` / `from .continuation_config import` → 生成 configures 关系
  - grep 代码中的路径常量引用（SOLVER_BASE等）→ 生成 generates 关系
  - grep 代码中的模板常量引用（AGENTS_MD_TEMPLATE等）→ 生成 uses-template 关系
- [ ] 运行脚本录入基础设施关系
- [ ] 验证：`python3 scripts/trace.py query db-collection analysis_runs` 显示哪些代码读写它
- [ ] commit

### 验证标准

- 基础设施关系数量 ~100条
- 11 个 DB collections 都有至少一条 reads-from 或 writes-to 关系
- 11 个运行资产都有至少一条 generates 关系
- 4 个模板文件都有至少一条 uses-template 关系

---

## WP-TRACE-07: 幂等验证 + 孤立资产补全

### 目标

验证 trace.csv 幂等性，补全孤立资产。

### 要读的文档

- `dev-docs/009` §8（验收标准）
- `scripts/asset_inventory.csv`

### 任务清单

- [ ] `python3 scripts/trace.py stats` 查看全局覆盖分布
- [ ] 对比 `asset_inventory.csv` 与 trace.csv，找出仍然孤立的资产
- [ ] 对孤立资产逐个分析，补全关系
- [ ] 抽查关键资产：`python3 scripts/trace.py query <type> <id>` 确认追溯链完整
- [ ] 验收标准逐条验证（dev-docs/009 §8）
- [ ] 写执行结果文档 + commit

### 验证标准（继承自dev-docs/009 §8）

1. 全资产覆盖——asset_inventory.csv 中每个资产在 trace.csv 中有至少一条关系
2. 全关系覆盖——16种关系类型都有记录（除 indexes 因 views/ 不存在暂为0）
3. 全层级覆盖——代码精确到函数级，文档精确到章节级
4. 幂等验证——trace.py stats 显示所有资产类型都有分布，无孤立资产
5. 可查询——给定任何一个资产，trace.py query 能追溯到它的所有关系

---

## 验证记录

（各子WP执行时在此记录结果）
