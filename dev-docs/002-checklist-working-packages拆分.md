# checklist/ 和 working-packages/ 拆分到根目录

**日期**：2026-08-19
**性质**：方案+执行记录——将 dev/ 拆解为 `checklist/` 和 `working-packages/` 两个根目录级子目录
**前置**：001-目录结构扁平化重组方案已完成（commit `a4f3a61`），dev/ 目录已从 `AnalysisSystem开发/` 改名而来
**commit**：`f1ca691`

---

## §1 背景与动机

### 001重组后的状态

001重组把 `analysis-devin-failure-system/` 嵌套消除，代码提到根目录，`AnalysisSystem开发/` 改名 `dev/`。但 `dev/` 内部结构没有动：

```
dev/
  README.md                 ← 目录说明+编号规则+文件类型说明
  INDEX.md                  ← WP状态跟踪表
  CheckList.md              ← 522行大表格，13门类127个point，每point一行
  CheckList-ExecDevin.md    ← 22KB，Exec Devin必读子集
  CheckPoints/              ← 153个文件，每个point一个详情，按14门类分目录
    ENV/ENV-01.md
    SESS/SESS-01.md
    ...
  WP-01~10.md
```

### 问题

1. **内容重复**——CheckList.md 的表格行和 CheckPoints/ 的详情文件包含相同信息（需求描述+验证方法），改一处要同步两处
2. **关系平级不清晰**——CheckList.md 是"索引"，CheckPoints/ 是"详情"，但目录结构上它们是平级的，看不出从属关系
3. **CheckList.md 会越来越大**——用户明确"以后checklist是重头戏"，point 会增长，522行会变成1000行+
4. **generate_checkpoints.py 单向生成**——从 CheckList.md 生成 CheckPoints/，但如果直接改了 CheckPoints/ 的文件，CheckList.md 不会反向更新
5. **dev/ 定位模糊**——dev/ 混装了需求点清单（CheckList/CheckPoints）和工作包管理（WP/INDEX），两者是不同关注点

### 用户的核心诉求

> "以后checklist是重头戏，每一个point要建立一个单独的文档。checklist.md可能只是一个checklist目录的README.md。"
> "用checklist来推进、管理我们的整个项目的研发。每个checkpoint要记录它所涉及的文档和代码。"

---

## §2 目标结构

```
AI-Math-Competition-Problem-Solving-System/
  src/
  monitoring/
  scripts/
  docs/
    system/ patterns/ architecture/ specs/ templates/
  checklist/                    ← 新建，根目录级，研发管理的核心驱动力
    README.md                   ← 原 CheckList.md，精简为索引
    ExecDevin.md                ← 原 CheckList-ExecDevin.md
    ENV-01.md                   ← 153个checkpoint扁平化
    ENV-02.md
    ...
    SESS-01.md
    ...
    MON-A1.md
    ...
  working-packages/             ← 新建，根目录级
    README.md                   ← 原 dev/README.md 中WP相关部分
    INDEX.md                    ← 原 dev/INDEX.md
    WP-01~10.md
  data/ dev-docs/
```

### 关键设计决策

1. **checklist/ 扁平化，不设门类子目录**
   - 153个文件直接平铺在 checklist/ 下
   - 编号前缀已自带门类分类（ENV-、SESS-、MON-A等），目录分是冗余
   - `ls checklist/` 时同门类文件自然排在一起（编号前缀排序）
   - 用户明确质疑"checklist目录为什么还有一个ENV目录？扁平化不行吗？"——确认扁平化

2. **checklist/README.md 只做索引**
   - 保留：门类索引表（14门类汇总）+ 编号规则 + 状态标记说明
   - 去掉：127行point表格（那些信息在单独文件中）
   - 单一数据源——每个 point 的信息只在一个地方

3. **每个 checkpoint 文件记录涉及的文档和代码**
   - 原有字段：需求描述、验证方法、状态、负责的WP、来源、变更记录
   - 新增字段模板：涉及的文档和代码（`scripts/generate_checkpoint.py` 生成的模板包含此字段）

4. **dev/ 整体删除，内容拆到两个新目录**
   - CheckList.md + CheckPoints/ + CheckList-ExecDevin.md → checklist/
   - WP-01~10 + INDEX.md → working-packages/
   - README.md 内容拆分：编号规则→checklist/README.md，WP说明→working-packages/README.md

5. **generate_checkpoints.py 改造为 generate_checkpoint.py**
   - 旧脚本：从 CheckList.md 表格批量生成 CheckPoints/ 文件（数据源已消失）
   - 新脚本：生成单个 checkpoint 模板文件，适配扁平化结构
   - 用法：`python3 scripts/generate_checkpoint.py ENV-07`

---

## §3 执行步骤

### 步骤1：创建目录
```bash
mkdir -p checklist working-packages
```

### 步骤2：移动153个checkpoint文件扁平化
```bash
find dev/CheckPoints -name "*.md" | while read f; do
  basename=$(basename "$f")
  git mv "$f" "checklist/$basename"
done
```
- 153个文件从 `dev/CheckPoints/<门类>/<编号>.md` 移到 `checklist/<编号>.md`
- 清理空的 CheckPoints 目录

### 步骤3：CheckList.md → checklist/README.md
- `git rm dev/CheckList.md`（删除原文件）
- 新建 `checklist/README.md`，只保留门类索引表+编号规则+状态标记说明
- 去掉522行point表格

### 步骤4：CheckList-ExecDevin.md → checklist/ExecDevin.md
```bash
git mv dev/CheckList-ExecDevin.md checklist/ExecDevin.md
```

### 步骤5：WP + INDEX → working-packages/
```bash
git mv dev/INDEX.md working-packages/INDEX.md
for f in dev/WP-*.md; do git mv "$f" working-packages/; done
```

### 步骤6：dev/README.md 拆分
- 编号规则（需求点编号格式、门类代号）→ 并入 `checklist/README.md`
- WP相关说明（目录结构、文件类型、阅读顺序、维护规则）→ 新建 `working-packages/README.md`

### 步骤7：删除 dev/
```bash
git rm dev/README.md
```
dev/ 目录自动删除（git rm 删除最后一个文件后目录消失）

### 步骤8：脚本改造
- 新建 `scripts/generate_checkpoint.py`——生成单个 checkpoint 模板文件
- 删除 `scripts/generate_checkpoints.py`——旧批量生成脚本（数据源已消失）
- 验证：`python3 scripts/generate_checkpoint.py ENV-99` 生成模板正常

### 步骤9：批量更新文档引用路径
- 153个checkpoint文件中的 `dev/CheckList.md` → `checklist/README.md`（308处）
- 153个checkpoint文件中的 `dev/CheckList-ExecDevin.md` → `checklist/ExecDevin.md`（308处）
- `docs/specs/p27_monitor_pipe_operations.md` 中的 ExecDevin 路径
- 用 sed 批量替换

### 步骤10：更新 README.md 引导地图 + AGENTS.md
- README.md 第四节"开发工作包管理——dev/"重写为两节：
  - 四、需求点清单——checklist/
  - 五、工作包管理——working-packages/
- AGENTS.md 外部文档索引表补充 checklist/ 和 working-packages/ 条目
- 附录中 `dev/README.md` → `working-packages/README.md 和 checklist/README.md`

### 步骤11：验证
- 无残留 `dev/CheckList`、`dev/CheckPoints`、`dev/WP-`、`dev/INDEX`、`dev/README` 路径引用
- 无残留 `CheckPoints/` 旧路径引用
- checklist/ 155个文件（153个checkpoint + README.md + ExecDevin.md）
- working-packages/ 12个文件（10个WP + README.md + INDEX.md）
- dev/ 不存在

### 步骤12：commit
```
f1ca691 — checklist/和working-packages/拆分到根目录，dev/目录删除
174 files changed, 686 insertions(+), 1316 deletions(-)
```

---

## §4 产出文件清单

### 新建文件
| 文件 | 内容 |
|---|---|
| `checklist/README.md` | 需求点清单索引（门类索引表+编号规则+状态标记） |
| `working-packages/README.md` | 工作包目录说明（目录结构+文件类型+阅读顺序+维护规则） |
| `scripts/generate_checkpoint.py` | 生成单个checkpoint模板文件 |
| `dev-docs/002-checklist-working-packages拆分.md` | 本文件 |

### 移动文件（git rename）
| 原路径 | 新路径 |
|---|---|
| `dev/CheckPoints/*/*.md`（153个） | `checklist/*.md`（扁平化） |
| `dev/CheckList-ExecDevin.md` | `checklist/ExecDevin.md` |
| `dev/INDEX.md` | `working-packages/INDEX.md` |
| `dev/WP-01~10.md`（10个） | `working-packages/WP-01~10.md` |

### 删除文件
| 文件 | 原因 |
|---|---|
| `dev/CheckList.md` | 内容精简后并入 `checklist/README.md` |
| `dev/README.md` | 内容拆分到 `checklist/README.md` 和 `working-packages/README.md` |
| `scripts/generate_checkpoints.py` | 数据源（CheckList.md表格）已消失，改造为 `generate_checkpoint.py` |

### 修改文件
| 文件 | 修改内容 |
|---|---|
| `README.md` | 引导地图第四节重写为checklist+working-packages两节，附录路径更新 |
| `AGENTS.md` | 外部文档索引表补充checklist和working-packages条目 |
| `docs/specs/p27_monitor_pipe_operations.md` | ExecDevin路径从 `../../dev/CheckList-ExecDevin.md` → `../../checklist/ExecDevin.md` |
| `checklist/*.md`（153个） | 关联文件路径从 `dev/CheckList.md` → `checklist/README.md` 等 |

---

## §5 设计原则

1. **checklist/ 是研发管理的核心驱动力**——不是 dev/ 下的子工具，而是和 src/、docs/ 平级的项目核心目录
2. **扁平化优于分层**——编号前缀已自带门类分类，目录分是冗余。153个文件平铺不影响查找
3. **单一数据源**——每个 checkpoint 的信息只在一个文件中，checklist/README.md 只做索引不重复内容
4. **每个 checkpoint 独立可追踪**——记录涉及的文档和代码，支持用 checklist 推进整个项目研发
5. **关注点分离**——checklist/（需求点）和 working-packages/（工作包）是不同关注点，分开管理
