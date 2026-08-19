# 幂等追溯分类法 — repo全资产追溯关系视角

> **加载本文件能得到什么**：了解 trace.csv 追溯体系的全貌——用什么工具查询/录入、数据在哪里、怎么验证幂等性、体系是怎么设计建立起来的。当你需要追溯任何资产的关系、或维护 trace.csv 时，从这里出发。
> **看法文件位置**：`views/idempotency.md`

---

## 索引的文件

### `scripts/trace.py` — 全维度追溯工具

trace.csv 的查询/录入/统计工具。支持 add/remove/query/trace/stats 等命令，管理13种资产类型和20种关系类型。是 trace.csv 的唯一操作入口。

**覆盖问题场景**：
- 查某资产的所有追溯关系（`query`/`query-prefix`/`query-relation`）
- 录入新关系（`add`）
- 统计全局覆盖情况（`stats`）
- 递归追溯关系链（`trace`）

**依赖关系**：数据存储在 `trace.csv`；资产清单见 `scripts/asset_inventory.csv`

---

### `trace.csv` — 追溯关系数据（3910条）

整个 repo 所有资产之间的有向关系表。13种资产类型（code/document/checkpoint/wp/dev-doc/script/config/template/db-collection/runtime-asset/commit/data/view-file）× 20种关系类型。给定任何 commit 时间点，trace.csv = repo 状态的精确镜像。

**覆盖问题场景**：
- 追溯任何资产的关系链
- 验证 repo 幂等性（全资产覆盖、全关系覆盖）
- 跨 session AI 了解资产间依赖

**依赖关系**：用 `scripts/trace.py` 操作；用 `scripts/trace_verify.py` 验证覆盖率

---

### `scripts/asset_inventory.csv` — 全资产清单（394个）

repo 中所有资产的底表，列：asset_type, asset_id, file_path, description。由 `enumerate_assets.py` 自动扫描产出，是 trace.csv 关系录入的基础——确保每个资产都被覆盖。

**覆盖问题场景**：
- 确认 repo 有哪些资产
- 幂等验证时对比 trace.csv 覆盖率

**依赖关系**：由 `scripts/enumerate_assets.py` 生成；被 `scripts/trace_verify.py` 用于覆盖率验证

---

### `scripts/enumerate_assets.py` — 资产枚举脚本

自动扫描 repo 文件树，产出 `asset_inventory.csv`。扫描范围：src/*.py、monitoring/*.py、scripts/*、docs/**/*.md、checklist/*.md、working-packages/WP-*.md、dev-docs/*.md、docs/templates/*.md、配置文件、git log、DB collection 名（从 config.py 静态提取）、运行资产常量。

**覆盖问题场景**：
- 重新生成全资产清单（repo 结构变化后）
- 确认资产数量

**依赖关系**：产出 `scripts/asset_inventory.csv`

---

### `scripts/trace_contains.py` — contains关系录入脚本

扫描所有代码文件的 `def`/`class` 行和所有文档文件的 `##`/`###` 行，录入文件→函数/章节的 contains 关系。产出 1823 条关系。

**覆盖问题场景**：
- 重新录入函数级/章节级 contains 关系（代码/文档结构变化后）

**依赖关系**：调用 `scripts/trace.py add`；依赖 `scripts/asset_inventory.csv` 确定扫描范围

---

### `scripts/trace_checkpoints.py` — checkpoint关系录入脚本

从每个 checkpoint 文件提取"负责的WP"（→part-of）、"来源"（→specified-by）、门类前缀（→implements 按门类推断），录入 checkpoint 的三种关系。产出 587 条关系。

**覆盖问题场景**：
- 重新录入 checkpoint 关系（checkpoint 文件变化后）
- 补充新 checkpoint 的追溯关系

**依赖关系**：调用 `scripts/trace.py add`；读取 `checklist/*.md`

---

### `scripts/trace_wp_devdoc.py` — dev-doc/wp关系录入脚本

从已有 part-of 关系反推 creates 关系（WP→checkpoint）；扫描 WP 文件内容中的 dev-docs/ 引用生成 comes-from 关系；扫描 dev-doc 内容中的文件路径引用补充 produces/changes 关系。产出 366 条关系。

**覆盖问题场景**：
- 重新录入 dev-doc/wp 关系（WP 或 dev-doc 变化后）

**依赖关系**：调用 `scripts/trace.py add`；读取 `trace.csv`（反推 creates）

---

### `scripts/trace_commits.py` — changed-in关系录入脚本

用 `git log --name-only --all` 提取每个 commit 改动的文件，自动推断资产类型，录入资产→commit 的 changed-in 关系。产出 876 条关系。

**覆盖问题场景**：
- 重新录入 changed-in 关系（新 commit 产生后）

**依赖关系**：调用 `scripts/trace.py add`；依赖 git log

---

### `scripts/trace_infra.py` — DB/配置/模板/运行资产关系录入脚本

扫描代码中的 DB collection 引用（→reads-from/writes-to）、config import 引用（→configures）、运行资产常量引用（→generates）、模板常量引用（→uses-template）。产出 220 条关系。

**覆盖问题场景**：
- 重新录入基础设施关系（代码/配置/DB 变化后）

**依赖关系**：调用 `scripts/trace.py add`；依赖 `src/config.py`、`src/continuation_config.py` 中的常量定义

---

### `scripts/trace_verify.py` — 幂等验证+孤立资产检查脚本

对比 `asset_inventory.csv` 和 `trace.csv`，找出仍然孤立的资产（在清单中但不在任何关系中的资产）。产出覆盖率报告和孤立资产清单。

**覆盖问题场景**：
- 验证 trace.csv 幂等性（全资产覆盖）
- 找出需要补全关系的孤立资产

**依赖关系**：读取 `scripts/asset_inventory.csv` 和 `trace.csv`

---

### `dev-docs/004-幂等追溯体系与工作包自包含设计.md` — 幂等体系设计

定义幂等追溯体系的设计理念——为什么要建立 trace.csv、资产分层方案（XPath-like寻址）、工作包自包含设计。是 trace.py 和 trace.csv 的设计源头。

**覆盖问题场景**：
- 理解幂等追溯体系为什么这样设计
- 理解资产分层和寻址方案

**依赖关系**：设计实现见 `scripts/trace.py`

---

### `dev-docs/008-全repo全资产幂等关系终极trace.csv.md` — 终极trace.csv需求

提出"终极 trace.csv"需求——从文档到代码、到数据库、到 git log、到运行资产的全幂等关系。包含资产类型范围、关系类型范围、差距分析、验收标准。

**覆盖问题场景**：
- 理解终极 trace.csv 的需求范围
- 查验收标准

**依赖关系**：方案见 `dev-docs/009`；执行结果见 `dev-docs/010`

---

### `dev-docs/009-全repo全资产幂等关系终极trace.csv方案.md` — 终极trace.csv方案

制定终极 trace.csv 的执行方案——trace.py 扩展设计（4新资产类型+6新关系类型）、资产枚举脚本设计、关系录入策略（7批）、工作包拆解预案、工作量估计。

**覆盖问题场景**：
- 理解 trace.py 扩展设计
- 理解关系录入策略和工作包拆解

**依赖关系**：需求见 `dev-docs/008`；工作包见 `working-packages/WP-TRACE.md`

---

### `dev-docs/010-全repo全资产幂等关系终极trace.csv执行结果.md` — 终极trace.csv执行结果

记录终极 trace.csv 的执行结果——53条→3910条，验收标准5条逐条验证通过，各子工作包执行结果，trace.csv 变更记录，遗留问题。

**覆盖问题场景**：
- 查执行结果和验收验证
- 查遗留问题和后续建议

**依赖关系**：方案见 `dev-docs/009`

---

### `working-packages/WP-TRACE.md` — 幂等追溯工作包

7个子工作包（WP-TRACE-01~07）的拆解：trace.py扩展+资产枚举 → contains关系 → checkpoint关系 → dev-doc/wp关系 → changed-in关系 → DB/配置/模板关系 → 幂等验证。每个子WP自包含，明确要求执行AI利用/维护/修复幂等关系。

**覆盖问题场景**：
- 理解幂等追溯体系的工作包拆解
- 重新执行某个子WP时了解其任务清单

**依赖关系**：方案见 `dev-docs/009`；执行结果见 `dev-docs/010`
