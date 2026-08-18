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

## 6. 和其他规则的关系

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
