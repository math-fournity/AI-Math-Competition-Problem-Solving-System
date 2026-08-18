# Monitor Pipe设计范式——连续工作系统的AI智能检查架构

**用途**：定义"连续工作系统的Monitor Pipe+检查脚本"设计范式。当一个系统连续运行（如批量解题、批量分析、批量审计），其中有些检查必须由AI来完成（产出质量、语义正确性、方向是否跑偏），这些检查项就使用本范式落地。

**定位**：这是跨项目的设计范式文档，不是某个具体系统的文档。具体系统的检查规范是该系统的系统资产（如`specs/p27_monitor_spec.md`），本文件定义的是"如何写检查规范、如何实现Monitor Pipe、如何写检查脚本"的元范式。

---

## 1. 问题背景

### 1.1 连续工作系统的检查难题

一个连续工作的系统（如批量解题Pipe、批量分析Pipe）在长时间运行中需要持续检查：

- **基础设施健康**——进程是否活着、队列是否推进、是否触发rate limit、是否有僵尸session
- **产出完整性**——文件是否生成、字段是否齐全、格式是否正确
- **产出质量**——proof的数学正确性、分析判定的合理性、是否有幻觉、是否答案泄漏
- **方向正确性**——AI是在上一轮基础上继续还是从头重复、续传方向是否正确

前两类（基础设施健康、产出完整性）可以代码化——脚本自动判定。后两类（产出质量、方向正确性）必须由AI判断——代码无法判定proof的数学正确性。

### 1.2 不能干等——需要持续监控

连续工作系统运行时间可能长达数小时到数天。不能等跑完再检查——运行中出现问题（如rate limit、launcher挂了、队列stall）如果不及时发现，会浪费大量API配额和时间。

### 1.3 Master AI不是旁观者

Master AI（你——正在读这个文档的AI）在系统运行时的角色是**检查者**，不是旁观者。你需要定期检查系统健康状态，发现问题后对正在运行的系统进行调整、优化、排错。

但Master AI不能每分钟都手动检查——需要有一个自动化的监控机制持续运行，把问题收集起来，让Master AI定期查看并处理。

---

## 2. 设计范式——三层架构

```
┌─────────────────────────────────────────────────────────┐
│  规范层（系统资产，提前落盘）                              │
│  specs/{system}_monitor_spec.md                         │
│    ├── 定义检查什么（A类自动检查/B类质量检查/C类AI检查）    │
│    ├── 定义检查标准（阈值、通过/不通过判定）               │
│    └── 定义alert结构、运行规范、查询脚本输出规范           │
└──────────────────────┬──────────────────────────────────┘
                       │ 规范驱动
┌──────────────────────▼──────────────────────────────────┐
│  执行层（Monitor Pipe——devin cli非交互模式守护进程）      │
│  src/monitor_{system}.py                                │
│    ├── 按规范执行A类+B类自动检查                          │
│    ├── C类AI检查项抽样→标记needs_ai_review               │
│    ├── 发现问题→写alert到DB（p27_monitor_alerts集合）     │
│    └── 在tmux中持续运行，所有任务完成后自动退出            │
└──────────────────────┬──────────────────────────────────┘
                       │ alert写入DB
┌──────────────────────▼──────────────────────────────────┐
│  查询层（检查脚本——Master AI每次检查都调用）              │
│  scripts/monitor_check_{system}.sh                      │
│    ├── 输出N项检查结果（pane/alerts/进程/进度/质量/判定） │
│    ├── 能够规则化和代码化检查的内容，全面地进行检查        │
│    └── 最后附行动清单——提醒Master AI:                    │
│        "开启对Monitor Pipe输出结果的检查，                │
│         并作出相应的对正在运行的系统的修改"                │
└─────────────────────────────────────────────────────────┘
```

### 2.1 规范层——系统资产，提前落盘

**文件**：`specs/{system}_monitor_spec.md`

**内容**：
1. **模块职责**——Monitor Pipe监控什么
2. **检查项目分类**：
   - A类自动检查（脚本判定，不需要AI）——session健康、队列推进、rate limit、僵尸session、export落地、失败率、launcher存活、stall检测
   - B类质量检查（脚本判定，系统特有）——产出完整性、格式正确性、字段填写率、值分布、逻辑一致性
   - C类AI review抽样（需Master AI判断）——产出质量、语义正确性、方向正确性、幻觉检测、答案泄漏
3. **检查标准**——每项的阈值、通过/不通过判定
4. **alert结构**——alert_type/severity/details/status
5. **运行规范**——检查间隔、退出条件、tmux session命名
6. **查询脚本输出规范**——输出几项检查、行动清单内容

**为什么提前落盘**：检查规范是系统资产（第2级资产，见`six-asset-grading.md`）。Monitor Pipe代码按规范实现，查询脚本按规范输出。规范文件和代码是"标准-实现"关系。Master AI处理alert时也参照规范中的检查标准。

### 2.2 执行层——Monitor Pipe守护进程

**承载方式**：devin cli非交互模式（`devin -p`），在独立tmux session中运行。

**为什么用devin cli非交互模式**：Monitor Pipe本身是一个需要持续运行的守护进程。用devin cli非交互模式承载，意味着Monitor Pipe可以：
- 在tmux中持续运行，不依赖Master AI的session保持
- 独立于Master AI的上下文窗口——Monitor Pipe的检查逻辑在代码中，不在prompt中
- 所有任务完成后自动退出

**实现**：`src/monitor_{system}.py`，Python脚本（不是devin cli的prompt——是普通Python脚本，在tmux中用`python -m src.monitor_{system}`运行）。

> **澄清**：Monitor Pipe的承载是"在tmux中持续运行的Python脚本"。它不是devin cli实例——它是一个普通的Python守护进程。但它监控的对象（被监控的连续工作系统）中的每个工作单元是devin cli非交互模式实例。Monitor Pipe本身用Python实现是因为它需要操作Redis、ArangoDB、tmux，这些用Python比用devin cli的prompt更合适。

**核心逻辑**（每轮循环）：
```
while True:
    1. 执行A类自动检查 → 发现问题生成alert
    2. 执行B类质量检查 → 发现问题生成alert
    3. 每3轮执行C类AI review抽样 → 标记needs_ai_review
    4. 创建alerts（写入DB的monitor_alerts集合）
    5. 状态报告（print到tmux pane）
    6. 检查退出条件（所有任务完成→退出）
    7. sleep(interval)
```

**alert写入DB**：alert存储在ArangoDB的独立集合中（如`p27_monitor_alerts`），每个alert有：
- `alert_type`：检查项类型
- `severity`：critical/warning/info
- `details`：问题详情（含problem_id便于定位）
- `status`：new/reviewing/fixed/wontfix

### 2.3 查询层——检查脚本

**文件**：`scripts/monitor_check_{system}.sh`

**Master AI每次检查都调用此脚本**——不是inline编写检查命令，而是用标准化脚本。

**输出N项检查**：
1. Monitor Pipe的tmux pane输出（最近几轮的ALERT/AI_REVIEW/status）
2. alerts集合（所有新alert的详情）
3. 进程状态（launcher + monitor + tmux session数）
4. 进度（DB状态分布 + 通过率）
5. 质量汇总（产出统计）
6. 通过率判定（对照方案的通过标准）

**最后附行动清单**——这是核心设计：
```
>> 行动清单（按顺序执行）：
   1. 仔细阅读第1项Monitor Pipe pane输出中的每轮ALERT和AI_REVIEW
   2. 有新alert时逐个recheck（第2项），处理完用--resolve-alert标记
   3. 进程NOT RUNNING时重启launcher/monitor（第3项）
   4. 有新增失败时重新入队（第4项）
   5. 进度停滞时检查launcher日志和rate_limit_pause状态
   6. 从alert的problem_ids字段获取需重跑的题，改status为prepared后重新launch
   7. AI_REVIEW抽样的结果——读产出文件，按检查规范中C类标准逐项检查
   8. 对照通过率判定——如果达到通过标准，POC通过
```

**行动清单的作用**：提醒调用它的Master AI——"你现在要去检查Monitor Pipe留下的检查结果（alerts），并作出相应的对正在运行的系统的修改"。

---

## 3. 三层配合关系

### 3.1 规范层 ↔ 执行层

规范层定义"检查什么、标准是什么"，执行层按规范实现检查代码。

- 规范说"A4. rate_limit_detection: ≥3个critical" → 代码中`RATE_LIMIT_CRITICAL_THRESHOLD = 3`
- 规范说"C1. proof_quality: AI检查proof.md的数学正确性" → 代码中`flag_for_ai_review()`抽样proof.md预览写入alert的details

### 3.2 执行层 ↔ 查询层

执行层把检查结果（alert）写入DB，查询层聚合展示这些alert。

- Monitor Pipe发现3个rate_limited → 写alert到`p27_monitor_alerts`集合
- 查询脚本运行`--check-alerts` → 读取所有`status='new'`的alert → 输出到终端
- Master AI看到alert → 处理问题 → 用`--resolve-alert <key>`标记为fixed

### 3.3 查询层 ↔ Master AI

查询脚本的输出最后附行动清单，提醒Master AI去处理alerts。

**Master AI的处理可能引发对正在运行的系统的操作**：
- **调整**——rate_limit alert → 修改batch.concurrency降低并发
- **优化**——failure_rate alert → 检查failure_breakdown，判断是AI能力问题还是基础设施问题
- **排错**——launcher_dead alert → 重启launcher进程
- **重跑**——proof_missing alert → 从alert的problem_ids获取题号，改status为prepared后重新入队
- **AI review**——ai_review_sample alert → 读proof.md和HANDOVER.md，按C类标准逐项检查，发现质量问题则标记需重跑

### 3.4 能够规则化和代码化检查的内容

查询脚本中，能够规则化和代码化检查的内容，全面地进行检查。这些不需要AI判断：

- 进程是否存在（`pgrep`）
- tmux session数量（`tmux list-sessions | grep`）
- DB状态分布（AQL查询）
- Redis队列计数（`r.zcard`/`r.llen`）
- 文件存在性（`os.path.exists`）
- 文件大小（`os.path.getsize`）
- 字段填写率（AQL + Counter）
- 值分布（AQL + Counter）
- 通过率计算（completed/total）

这些全部在检查脚本中用代码完成，Master AI不需要重复检查这些——Master AI只需要检查脚本无法判定的C类项目。

---

## 4. 代码资产引用——错题分析系统的实现

错题分析系统（`analysis-devin-failure-system/`）是本设计范式的完整实现。未来的AI可以看着这些代码和运行资产，理解本范式是如何实现的、工作的。

### 4.1 三个Pipe的Monitor Pipe实现

| Pipe | Monitor Pipe代码 | 检查脚本 | 检查规范 | alert集合 |
|---|---|---|---|---|
| Pipe 1 分析 | `src/monitor_pipe.py` (634行) | `scripts/monitor_check.sh` (124行) | —（内嵌在代码中） | `monitor_alerts` |
| Pipe 2 审计 | `src/monitor_pipe.py`（复用Pipe 1） | `scripts/monitor_check.sh`（复用Pipe 1） | — | `monitor_alerts` |
| Pipe 3 选题 | `src/monitor_selection.py` (683行) | `scripts/monitor_check_selection.sh` (174行) | —（内嵌在代码中） | `monitor_alerts` |
| Pipe 4 续传 | `src/monitor_continuation.py` (748行) | `scripts/monitor_check_continuation.sh` (241行) | `specs/p27_monitor_spec.md` (242行) | `p27_monitor_alerts` |

**演进**：Pipe 1/2/3的检查规范内嵌在代码中（没有独立的spec文件）。Pipe 4是第一个把检查规范提前落盘为独立系统资产的实现——这是本范式的要求。

### 4.2 解题系统的Monitor Pipe实现

解题系统（`xishujuzhen/solver_harness/pipe/`）也实现了本范式：

| 文件 | 行数 | 用途 |
|---|---|---|
| `pipe/monitor_pipe.py` | 958行 | Monitor Pipe守护进程（8项自动检查+AI review抽样） |
| `pipe/scripts/monitor_check.sh` | 225行 | 标准化检查脚本（5项检查+行动清单） |

**设计文档**：`dev-docs/391-v0-2026-08-17-解题系统MonitorPipe-参考错题分析系统的持续监控方案.md`

### 4.3 关键代码片段——理解本范式的入口

#### Monitor Pipe的主循环（`monitor_continuation.py`）

```
src/monitor_continuation.py:run_monitor_loop()
  ├── check_session_health()      # A1: tmux session数 vs DB running数
  ├── check_queue_progress()      # A2/A3: Redis队列推进
  ├── check_rate_limit()          # A4: rate_limited数量
  ├── check_zombie_sessions()     # A5: 空pane僵尸session
  ├── check_export_landing()      # A6: completed的run有export文件
  ├── check_failure_rate()        # A7: 失败率
  ├── check_launcher_dead()       # A8: launcher进程存活
  ├── check_long_running()        # A9: 单轮>30分钟
  ├── check_proof_completeness()  # B1/B2/B3: proof.md完整性
  ├── check_handover_completeness()# B4/B5: HANDOVER.md完整性
  ├── check_truncation_pattern()  # B6: 5轮全截断
  ├── check_status_anomaly()      # B7: final_status分布异常
  ├── flag_for_ai_review()        # C1-C5: 抽样标记needs_ai_review
  ├── create_alert()              # 写alert到DB
  └── 检查退出条件
```

#### 检查脚本的行动清单（`monitor_check_continuation.sh`）

```bash
# scripts/monitor_check_continuation.sh 最后部分
echo ">> 行动清单（按顺序执行）："
echo "   1. 仔细阅读第1项Monitor Pipe pane输出中的每轮ALERT和AI_REVIEW"
echo "   2. 有新alert时逐个recheck（第2项），处理完用--resolve-alert标记"
echo "   3. 进程NOT RUNNING时重启launcher/monitor（第3项）"
echo "   4. 有新增失败时重新入队（第4项）"
echo "   5. 进度停滞时检查launcher日志和rate_limit_pause状态"
echo "   6. 从alert的problem_ids字段获取需重跑的题，改status为prepared后重新launch"
echo "   7. AI_REVIEW抽样的结果——读产出文件，按检查规范中C类标准逐项检查"
echo "   8. 对照通过率判定——如果达到通过标准，POC通过"
```

#### alert结构（`monitor_continuation.py:create_alert()`）

```python
doc = {
    "_key": f"p27-alert-{ts}-{alert_type}",
    "alert_type": alert_type,        # session_health / rate_limit / proof_missing / ...
    "severity": severity,            # critical / warning / info
    "details": details,              # 含summary + problem_id + 上下文字段
    "status": "new",                 # new → reviewing → fixed / wontfix
    "created_at": _utc_now(),
    "resolved_at": None,
}
```

### 4.4 运行资产——可以查看的实际运行结果

| 资产 | 位置 | 用途 |
|---|---|---|
| Monitor Pipe的tmux pane输出 | `tmux capture-pane -t monitor-p27 -p` | 查看最近几轮的检查结果 |
| ArangoDB中的alerts | `db.collection("p27_monitor_alerts").find({"status": "new"})` | 查看所有未处理的alert |
| 检查脚本输出 | `bash scripts/monitor_check_continuation.sh p27-full` | Master AI每次检查的入口 |
| 391号设计文档 | `dev-docs/391-v0-2026-08-17-解题系统MonitorPipe-参考错题分析系统的持续监控方案.md` | 解题系统Monitor Pipe的设计文档 |
| p27检查规范 | `analysis-devin-failure-system/specs/p27_monitor_spec.md` | POC-2.7续传Pipe的检查规范（本范式的第一个独立spec实现） |

---

## 5. 实施Checklist

当你要为一个连续工作系统实现Monitor Pipe时，按以下步骤：

### 5.1 写检查规范（系统资产，提前落盘）

- [ ] 创建`specs/{system}_monitor_spec.md`
- [ ] 定义A类自动检查（哪些基础设施健康检查适用于本系统）
- [ ] 定义B类质量检查（本系统特有的产出质量检查）
- [ ] 定义C类AI review抽样（哪些检查必须由AI判断）
- [ ] 定义每项的检查标准（阈值、通过/不通过判定）
- [ ] 定义alert结构
- [ ] 定义运行规范（检查间隔、退出条件）
- [ ] 定义查询脚本输出规范（几项检查、行动清单内容）

### 5.2 实现Monitor Pipe守护进程

- [ ] 创建`src/monitor_{system}.py`
- [ ] 实现A类自动检查函数（每个检查项一个函数）
- [ ] 实现B类质量检查函数
- [ ] 实现`flag_for_ai_review()`——C类抽样
- [ ] 实现`create_alert()`/`get_new_alerts()`/`resolve_alert()`——alert管理
- [ ] 实现`run_monitor_loop()`——主循环
- [ ] 用独立的alert集合（如`{system}_monitor_alerts`）避免与现有Pipe冲突

### 5.3 实现检查脚本

- [ ] 创建`scripts/monitor_check_{system}.sh`
- [ ] 实现N项检查输出（pane/alerts/进程/进度/质量/判定）
- [ ] 能够规则化和代码化检查的内容，全面地进行检查（用代码完成，不需要AI）
- [ ] 最后附行动清单——提醒Master AI去检查Monitor Pipe的alerts并处理
- [ ] `chmod +x` 脚本

### 5.4 运行

- [ ] 在tmux中启动连续工作系统的launcher
- [ ] 在独立tmux session中启动Monitor Pipe：`tmux new-session -d -s monitor-{system} "python -m src.monitor_{system} --batch-id {id}"`
- [ ] Master AI定期运行检查脚本：`bash scripts/monitor_check_{system}.sh {batch_id}`
- [ ] Master AI按行动清单处理alerts，处理完用`--resolve-alert`标记

---

## 6. 如何参考错题分析系统实现新Pipe——具体操作指南

未来的AI要为一个新的连续工作系统实现Pipe+Monitor Pipe时，按本节操作。错题分析系统（`analysis-devin-failure-system/`）有4个Pipe的完整实现，是本范式的参考样板。

### 6.1 先读懂现有Pipe的架构——4个Pipe的演进

4个Pipe代表了从"共享基础设施"到"独立自包含"的演进：

| Pipe | 模式 | 共享什么 | 独立什么 |
|---|---|---|---|
| Pipe 1 分析 | 共享基础设施 | config.py, db_schema.py, redis_queue.py, monitor_pipe.py | data_collector, analysis_launcher, result_collector, aggregator |
| Pipe 2 审计 | 共享+扩展 | config.py, db_schema.py（复用connect_db） | audit_collector, audit_launcher, audit_result_collector, audit_aggregator, audit_redis_queue.py |
| Pipe 3 选题 | 共享+扩展 | config.py, db_schema.py（复用connect_db） | selection_collector, selection_launcher, selection_result_collector, monitor_selection.py |
| Pipe 4 续传 | **独立自包含** | 仅shared_logger.py | continuation_config, continuation_db_schema, continuation_redis_queue, continuation_collector, continuation_feeder, continuation_launcher, continuation_result_collector, monitor_continuation.py |

**推荐**：新Pipe采用Pipe 4的"独立自包含"模式——不修改现有Pipe的任何代码，所有组件独立。这样不会影响已有Pipe的运行。

### 6.2 新Pipe需要的文件清单（11个文件）

以Pipe 4为模板，一个新Pipe（假设叫`{name}`）需要：

| 序号 | 文件 | 对标Pipe 4 | 用途 | 参考行数 |
|---|---|---|---|---|
| 1 | `src/{name}_config.py` | `continuation_config.py` | 配置常量（路径/DB/并发/阈值/Redis前缀/tmux命名） | ~90行 |
| 2 | `src/{name}_db_schema.py` | `continuation_db_schema.py` | ArangoDB集合定义+索引+CRUD辅助函数 | ~120行 |
| 3 | `src/{name}_redis_queue.py` | `continuation_redis_queue.py` | Redis队列操作封装（{name}:前缀） | ~170行 |
| 4 | `src/{name}_collector.py` | `continuation_collector.py` | 数据收集——从数据源取题+构造run记录+创建工作目录 | ~170行 |
| 5 | `src/{name}_feeder.py` | `continuation_feeder.py` | 入Redis队列 | ~60行 |
| 6 | `src/{name}_launcher.py` | `continuation_launcher.py` | **核心**——并发启动devin cli+stall/rate_limit/zombie检测 | ~580行 |
| 7 | `src/{name}_result_collector.py` | `continuation_result_collector.py` | 结果收集+通过率判定+Markdown汇总报告 | ~130行 |
| 8 | `src/monitor_{name}.py` | `monitor_continuation.py` | Monitor Pipe守护进程——按检查规范执行检查 | ~750行 |
| 9 | `specs/{name}_monitor_spec.md` | `specs/p27_monitor_spec.md` | **检查规范（系统资产，提前落盘）** | ~240行 |
| 10 | `scripts/monitor_check_{name}.sh` | `scripts/monitor_check_continuation.sh` | 检查脚本——Master AI每次检查都调用 | ~240行 |
| 11 | `run_{name}_pipeline.py` | `run_continuation_pipeline.py` | 端到端入口（collect→feed→launch→collect-results） | ~100行 |

**可选**：如果新Pipe的devin cli需要AGENTS.md模板，还需要第12个文件`templates/{name}_agents_md.md`（参考`templates/analysis_agents_md.md`或`templates/selection_agents_md.md`）。

### 6.3 具体操作步骤——以复制Pipe 4为例

#### 步骤1：复制config并修改常量

```bash
cp src/continuation_config.py src/{name}_config.py
```

**必须修改的常量**：
- `PENDING_KEY = "{name}:pending"`——Redis队列前缀（避免与现有Pipe冲突）
- `CONTINUATION_RUNS_COLLECTION = "{name}_runs"`——ArangoDB集合名
- `CONTINUATION_BATCHES_COLLECTION = "{name}_batches"`
- `CONTINUATION_EVENTS_COLLECTION = "{name}_events"`
- `CONTINUATION_RESULTS_COLLECTION = "{name}_results"`
- `CONTINUATION_SOLVER_BASE` / `CONTINUATION_TRAJECTORY_BASE`——工作目录和trajectory目录
- `DEFAULT_CONCURRENCY` / `DEFAULT_MAX_RUNTIME_SECONDS` / `DEFAULT_STALL_SECONDS`——根据任务调整
- `DEVIN_MODEL` / `DEVIN_PERMISSION_MODE`——通常不变
- `TMUX_PREFIX = "{name}"`——tmux session命名前缀
- `RATE_LIMIT_PATTERNS` / `CONNECTION_PATTERNS`——通常不变（复用config.py的）

**参考`continuation_config.py`的§1-§5**，理解每个常量的用途。

#### 步骤2：复制db_schema并修改集合名

```bash
cp src/continuation_db_schema.py src/{name}_db_schema.py
```

**必须修改**：
- import从`continuation_config`改为`{name}_config`
- 集合名常量改为步骤1中定义的新名称
- 索引名前缀改为`{name}_idx_`（避免与现有Pipe的索引名冲突）
- `ensure_schema()`中创建的集合列表

**参考`continuation_db_schema.py`的`ensure_schema()`函数**——它创建集合+索引，是DB初始化的入口。

#### 步骤3：复制redis_queue并修改前缀

```bash
cp src/continuation_redis_queue.py src/{name}_redis_queue.py
```

**必须修改**：
- 所有`PENDING_KEY`/`RUNNING_KEY`/`COMPLETED_KEY`/`FAILED_KEY`/`STATS_KEY`的前缀从`p27:`改为`{name}:`
- 如果有v2双队列（handover/solve），修改对应的前缀

**参考`continuation_redis_queue.py`**——它封装了enqueue/dequeue/add_running/remove_running/add_completed/add_failed/update_stats等操作。

#### 步骤4：复制collector并修改数据源

```bash
cp src/continuation_collector.py src/{name}_collector.py
```

**必须修改**：
- `load_problem_list()`——数据源从problem_list.json改为你的数据源（可能是ArangoDB查询、CSV文件、API等）
- `extract_problem_text()`——题目文本提取逻辑（你的数据源格式可能不同）
- `collect_and_prepare()`——创建DB run记录的逻辑，字段根据你的任务调整
- import从`continuation_config`/`continuation_db_schema`改为`{name}_config`/`{name}_db_schema`

**参考`continuation_collector.py`的`collect_and_prepare()`函数**——它加载数据源→为每道题创建工作目录→创建DB run记录（status=prepared）。

#### 步骤5：复制feeder（基本不用改）

```bash
cp src/continuation_feeder.py src/{name}_feeder.py
```

**必须修改**：
- import改为`{name}_config`/`{name}_db_schema`/`{name}_redis_queue`
- 集合名常量改为新名称

feeder的逻辑很简单——从DB取prepared的run，入Redis pending队列。通常不需要改逻辑。

#### 步骤6：复制launcher并修改核心逻辑（最复杂）

```bash
cp src/continuation_launcher.py src/{name}_launcher.py
```

**必须修改**：
- import改为`{name}_config`/`{name}_db_schema`/`{name}_redis_queue`
- **prompt构造模板**——`INITIAL_PROMPT_TEMPLATE`/`CONTINUE_PROMPT_TEMPLATE`等，改为你的任务的prompt
- **完成判定逻辑**——`is_completed()`函数，Pipe 4检查proof.md有boxed答案，你的任务可能检查XML标记、JSON输出等
- **截断判定逻辑**——`is_truncated()`函数，通常不需要改（截断判定逻辑是通用的）
- **多轮逻辑**——如果你的任务不需要多轮续传，删除`generate_handover()`和v2方案相关代码
- **tmux session命名**——`tmux_session_name()`函数，前缀改为`{name}`

**不需要修改的核心逻辑**（直接复用）：
- `launch_batch()`的主循环结构——从Redis dequeue→启动tmux session→检查状态→处理完成/失败
- stall检测——pane_hash变化+idle>stall_seconds
- rate_limit检测——RATE_LIMIT_PATTERNS匹配+自动暂停20分钟
- zombie session清理——完成后kill-session+dead_session检测
- 动态并发——从DB读取batch.concurrency支持运行中调整

**参考`continuation_launcher.py`的`launch_batch()`函数（第155-590行）**——这是整个Pipe的核心，复用analysis_launcher.py的成熟检测模式。

#### 步骤7：复制result_collector并修改汇总逻辑

```bash
cp src/continuation_result_collector.py src/{name}_result_collector.py
```

**必须修改**：
- import改为新的模块名
- 通过率判定标准——Pipe 4对照415号§7.1（COMPLETED≥50%），你的任务有不同的通过标准
- Markdown汇总报告的内容——根据你的任务的产出调整

#### 步骤8：写检查规范（系统资产，提前落盘）

```bash
cp specs/p27_monitor_spec.md specs/{name}_monitor_spec.md
```

**必须修改**：
- §1模块职责——改为你的系统的职责
- §2.1 A类自动检查——选择适用于你的系统的检查项（通常A1-A9都适用）
- §2.2 B类质量检查——**这是你的系统特有的**，参考Pipe 4的B1-B7，但根据你的产出调整
- §2.3 C类AI review抽样——**这是你的系统特有的**，参考Pipe 4的C1-C5，但根据你的产出调整
- §3检查标准——每项的阈值和通过/不通过判定
- §6查询脚本输出规范——根据你的系统调整检查项数量

**关键**：检查规范是系统资产，必须提前落盘。Monitor Pipe代码和检查脚本都参照本规范实现。

#### 步骤9：复制monitor并修改检查函数

```bash
cp src/monitor_continuation.py src/monitor_{name}.py
```

**必须修改**：
- import改为`{name}_config`/`{name}_db_schema`
- `MONITOR_ALERTS_COLLECTION = "{name}_monitor_alerts"`——独立的alert集合
- A类检查函数——通常不需要改逻辑，只改集合名和Redis前缀
- **B类检查函数**——根据你的检查规范§2.2实现，Pipe 4的B1-B7是续传特有的，你的系统有不同的B类检查
- **C类抽样函数**——`flag_for_ai_review()`中AI需要检查的项目，根据你的检查规范§2.3调整

**参考`monitor_continuation.py`的`run_monitor_loop()`函数**——主循环结构（A类→B类→C类抽样→创建alerts→状态报告→退出检查）通常不需要改。

#### 步骤10：复制检查脚本并修改

```bash
cp scripts/monitor_check_continuation.sh scripts/monitor_check_{name}.sh
chmod +x scripts/monitor_check_{name}.sh
```

**必须修改**：
- `MONITOR_SESSION`默认值改为`monitor-{name}`
- `pgrep -f`的进程匹配模式改为`run_{name}_pipeline`和`src.monitor_{name}`
- `tmux list-sessions | grep`的前缀改为`{name}-`
- DB查询的集合名改为`{name}_runs`
- 第5项质量汇总——根据你的产出调整统计内容
- 第6项通过率判定——改为你的通过标准
- 行动清单——根据你的系统的处理操作调整

**关键**：行动清单的最后必须提醒Master AI去检查Monitor Pipe的alerts——这是本范式的核心设计。

#### 步骤11：复制run_pipeline并修改

```bash
cp run_continuation_pipeline.py run_{name}_pipeline.py
```

**必须修改**：
- import改为新的模块名
- `--step`的choices通常不变（all/collect/feed/launch/collect-results/status/stop）
- `--method`参数——如果你的任务没有v1/v2方案，删除

### 6.4 验证步骤

完成11个文件后，验证：

```bash
# 1. 验证import
cd analysis-devin-failure-system
.venv/bin/python3 -c "
import sys; sys.path.insert(0, '.')
from src.{name}_config import *
from src.{name}_redis_queue import get_redis, enqueue_pending
from src.{name}_db_schema import connect_db, ensure_schema
from src.{name}_collector import collect_and_prepare
from src.{name}_launcher import launch_batch, status_batch, stop_batch
from src.{name}_result_collector import collect_batch_results
from src.monitor_{name} import run_monitor_loop, check_alerts
print('ALL IMPORTS OK')
"

# 2. 验证CLI
.venv/bin/python3 run_{name}_pipeline.py --help
.venv/bin/python3 -m src.monitor_{name} --help

# 3. 小批量测试（10题）
.venv/bin/python3 run_{name}_pipeline.py --batch-id {name}-test --limit 10

# 4. 启动Monitor Pipe测试
tmux new-session -d -s monitor-{name} ".venv/bin/python3 -m src.monitor_{name} --batch-id {name}-test --interval 60"

# 5. 运行检查脚本
bash scripts/monitor_check_{name}.sh {name}-test
```

### 6.5 关键参考文件——读懂这些就能实现新Pipe

如果时间有限，只读以下5个文件就能理解整个模式：

| 优先级 | 文件 | 行数 | 读什么 |
|---|---|---|---|
| 1 | `src/continuation_launcher.py` | 580行 | **核心**——launch_batch()的主循环、stall/rate_limit/zombie检测、多轮续传逻辑 |
| 2 | `src/monitor_continuation.py` | 748行 | Monitor Pipe的16项检查实现、alert管理、AI review抽样 |
| 3 | `specs/p27_monitor_spec.md` | 242行 | 检查规范的写法——A类/B类/C类分类、检查标准、alert结构 |
| 4 | `scripts/monitor_check_continuation.sh` | 241行 | 检查脚本的6项输出+行动清单写法 |
| 5 | `run_continuation_pipeline.py` | 100行 | 端到端入口的4步串联（collect→feed→launch→collect-results） |

### 6.6 常见陷阱

1. **Redis前缀冲突**——新Pipe必须用自己的前缀（如`{name}:`），不能复用`p27:`或`analysis:`，否则会与其他Pipe的队列冲突。
2. **ArangoDB集合名冲突**——新Pipe必须用自己的集合名（如`{name}_runs`），不能复用`p27_continuation_runs`或`analysis_runs`。
3. **tmux session命名冲突**——新Pipe必须用自己的前缀（如`{name}-`），不能复用`p27-`或`au-`，否则`tmux list-sessions | grep`会匹配到其他Pipe的session。
4. **alert集合冲突**——Monitor Pipe必须用独立的alert集合（如`{name}_monitor_alerts`），不能复用`monitor_alerts`或`p27_monitor_alerts`。
5. **忘记写检查规范**——不要把检查逻辑直接写在代码里不落盘。检查规范是系统资产，必须提前落盘到`specs/{name}_monitor_spec.md`。
6. **忘记在检查脚本最后加行动清单**——行动清单是本范式的核心设计，提醒Master AI去检查Monitor Pipe的alerts。
7. **修改了现有Pipe的代码**——新Pipe应该独立自包含，不修改现有Pipe的任何代码。如果需要共享功能，复制适配而不是修改原文件。

---

## 7. 和其他规则的关系（原§6）

- **`six-dual-check-mechanism.md`**：本范式是双重检查机制在连续工作系统上的具体化。A类+B类是"代码能检查的"，C类是"AI需要检查的"。
- **`six-asset-grading.md`**：检查规范是第2级资产（文件），提前落盘。Monitor Pipe代码和检查脚本都参照规范实现。
- **`six-trace-preservation.md`**：alert写入ArangoDB是痕迹保留——Master AI处理后标记为fixed，全过程可审计。
- **`long-running-work-sop`**：本范式是长程工作SOP化的一部分——连续工作系统的监控SOP。
- **`six-ai-agent-launch.md`**：Monitor Pipe在tmux中运行，遵循tmux优先铁律。

---

## 7. 关键设计原则（来自用户原话）

1. **Monitor Pipe的目的是让应该由Master AI进行智能检查的项目全部放入这个Pipe**——不是让Master AI手动检查，而是把检查项自动化，结果收集起来。
2. **然后留下检查结果（alert）**——alert写入DB，持久化、可查询、可审计。
3. **让Master AI的检查脚本可以查询到这些问题**——检查脚本是Master AI的入口，不是Monitor Pipe本身。
4. **然后让Master AI可以整改**——Master AI看到alert后，对正在运行的系统进行调整、优化、排错。
5. **查询脚本每次检查都要调用**——不是偶尔调用，而是每次检查都调用。
6. **它在输出结果的最后提醒Master AI去检查Monitor Pipe留下的检查结果**——行动清单是核心设计。
7. **能够规则化和代码化检查的内容，全面地进行检查，并放在检查的脚本中**——能代码化的全部代码化，不浪费AI的认知资源。
8. **检查规范要提前落盘作为系统资产**——不是埋在代码里，而是独立可读的规范文件。
