# SOP_Z：元检查 + 整体检查

## 认知闭包（执行前必读）

### 为什么要检查 SOP 系统本身

SOP 系统不仅能修目标系统（错题分析系统），还能修自己。这是循环的最后一步——你完成了 6 步工作后，反思整个 SOP 系统是否需要调整。

### SOP 系统结构

```
scripts/sop/
  run.py          — 单一入口（每次运行执行当前步骤）
  checks.py       — 各步骤的自动化检查逻辑
  sop_state.py    — 状态管理（_state.json + 顺序校验）
  _set_next.py    — 强制设定下一步（跳步用）
  _state.json     — 步骤状态记录

docs/sop/
  SOP_01_system_health.md
  SOP_02_data_integrity.md
  SOP_03_alert_triage.md
  SOP_04_ai_judgment.md
  SOP_05_code_repair.md
  SOP_06_report_worklog_selfcheck.md
  SOP_Z_meta_system_review.md（本文件）
```

### 循环结构

```
01 系统存活+进度+Session
02 数据完整性
03 alert分类
04 C类AI判断
05 代码修复
06 报告+WORKLOG+Self-check
Z  元检查+整体检查（本步骤）
→ 回到 01
```

---

## 执行指令

### 第一部分：元检查（每个步骤的合理性）

对 6 个工作步骤逐个反思：

#### 步骤01 系统存活+进度+Session
- 检查项是否全面？有没有新出现的系统问题类型没覆盖？
- `monitor_check_continuation.sh` 的8项输出是否还够用？
- session注册表检查是否有效？

#### 步骤02 数据完整性
- 抽查的10个run够不够？应该全量检查还是抽样？
- 7个路径字段的检查是否完整？有没有新的字段没检查？
- DB-文件一致性检查是否有效？

#### 步骤03 alert分类
- 分类标准是否清晰？有没有无法归类的alert？
- alert类型清单是否需要更新（系统新增了检查项）？
- LIMIT 50 够不够？

#### 步骤04 C类AI判断
- C1-C5是否还够用？需要新增判断项吗？
- 判断标准是否需要更具体？
- 判断结果是否可追溯（DB中是否记录了ai_review_result）？

#### 步骤05 代码修复
- 修复约束是否合理？
- 修复流程是否被执行了？
- 是否需要新的修复能力（自动重启/回滚/验证测试）？

#### 步骤06 报告+WORKLOG+Self-check
- 报告格式是否覆盖了需要记录的信息？
- WORKLOG跨轮记忆是否有效？
- S1-S17 self-check是否有效？有没有需要新增的self-check项？

### 第二部分：整体检查

1. **6步划分是否还合理？**
   - 有没有步骤太重（做太多事）或太轻（几乎没事做）？
   - 是否需要新增步骤（如"环境检查"、"用户通知"）？
   - 是否需要合并步骤？

2. **步骤顺序是否需要调整？**

3. **_state.json 机制是否可靠？**
   - 状态文件有没有不一致？
   - 顺序校验是否过于严格？

4. **SOP系统与目标系统的适配度**
   - SOP循环节奏是否匹配目标系统节奏？
   - batch_id是否需要更新？

5. **AGENTS.md中的SOP说明是否还准确？**

6. **checklist需求覆盖度**
   - 14个门类的需求点是否都有对应的SOP检查？
   - 有没有需求点始终没有被检查到？

### 第三部分：如果需要调整

- 修改对应的 `docs/sop/SOP_XX.md`
- 修改 `scripts/sop/checks.py` 中对应的检查函数
- 如果循环结构变化：修改 `scripts/sop/sop_state.py` 的 `SOP_STEPS`/`SOP_NAMES`/`SOP_DOCS`
- 更新 `AGENTS.md` 的 SOP 说明
- commit 所有调整

### 第四部分：如果没有需要调整的

SOP系统运行良好——直接进入下一轮循环。在todo中记录"Z检查通过，系统无需调整"。

---

## 你需要建立的 todo list

- 元检查6个步骤的合理性（可以合并为一个todo）
- 整体检查（一个todo）
- 如果需调整：修改对应文件 + commit
- **最后一项固定是**：`执行下一个脚本: python -m scripts.sop.run`

**注意**：下一阶段是新一轮循环的开始（步骤01）。这就是7x24持续循环——每完成一个阶段的todo list，最后一项自动触发下一阶段，永不停歇。
