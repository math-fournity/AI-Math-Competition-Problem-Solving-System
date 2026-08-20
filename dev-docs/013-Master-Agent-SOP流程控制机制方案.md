# 013-Master-Agent-SOP流程控制机制方案

**日期**：2026-08-19
**性质**：方案文档（make-plan 产出）
**需求引用**：用户要求 Master Agent 作为 Monitor Pipe 承载者，用编号化 SOP 脚本控制工作流程

---

## §1 背景与决策变化

### 1.1 上一轮决策（dev-docs/006/011，2026-08-19）

dev-docs/006/011 完成了"Master Agent 接管 Monitor Pipe 检查工作"——但实现的是**按需检查**：用户问"系统怎么样了"时，Master Agent 运行 `monitor_check_continuation.sh` + 加载 `MasterAgentCheck.md` 逐项处理。

### 1.2 本轮决策变化

用户要求升级为**7x24 持续循环**——Master Agent 发一次"开始工作"指令后，持续执行 SOP 循环，不需要用户持续发消息。

### 1.3 7x24 的技术实现

Master Agent 交互式 session 不是 daemon。7x24 通过**自驱动 todo list 机制**实现：

- 每个 SOP 脚本输出末尾要求 Master Agent 用 `todo_write` 建立 todo list
- todo list 最后一项固定是"执行下一个脚本"
- 完成当前阶段所有 todo 后，执行最后一项 → 触发下一阶段脚本
- 下一阶段脚本又建立新的 todo list（最后一项又是调用再下一个脚本）
- sop_05 的最后一项是"执行 sop_01"——循环回到开始

这样 Master Agent 成了状态机：每完成一个阶段的 todo list，最后一项自动触发下一阶段。session 不中断就持续循环；中断了下次从 `_state.json` 的 next 继续。

---

## §2 架构设计

### 2.1 文件结构

```
scripts/sop/
  __init__.py
  sop_state.py              # 状态管理模块（读写_state.json，顺序校验）
  _state.json               # 步骤状态记录
  sop_01_health_check.py    # 健康检查 SOP 脚本
  sop_02_alert_triage.py    # alert 分类处理 SOP 脚本
  sop_03_ai_judgment.py     # C 类 AI 判断 SOP 脚本
  sop_04_code_repair.py     # 代码修复 SOP 脚本
  sop_05_report_worklog.py  # 报告+WORKLOG SOP 脚本
  _set_next.py              # 强制设定下一步脚本

docs/sop/
  SOP_01_health_check.md    # 自包含 SOP 文档（被脚本读取并打印）
  SOP_02_alert_triage.md
  SOP_03_ai_judgment.md
  SOP_04_code_repair.md
  SOP_05_report_worklog.md
```

### 2.2 状态管理（_state.json）

```json
{
  "last": "01",
  "next": "02",
  "cycle": 3,
  "last_ts": "2026-08-19T22:00:00Z",
  "batch_id": "p27-full"
}
```

- `last`：上一个执行的脚本编号
- `next`：下一个应该执行的脚本编号
- `cycle`：当前是第几轮循环（sop_01→05 完成为一轮）
- `last_ts`：上次执行时间
- `batch_id`：当前监控的批次

### 2.3 顺序校验机制

每个 SOP 脚本启动时：
1. 读 `_state.json`
2. 检查 `state["next"]` 是否等于自己的编号
3. 如果不等于 → 打印错误信息（上一个=X，下一个应该是 Y），退出
4. 如果等于 → 打印 SOP 文档内容 → 执行检查逻辑 → 更新 state（last=自己，next=下一个）

### 2.4 脚本输出结构

每个 SOP 脚本的 stdout 结构：
```
=== SOP_XX: <标题> ===
（轮次: 第N轮 | 上次: <时间> | batch: <batch_id>）

--- SOP 文档内容 ---
（完整打印 docs/sop/SOP_XX.md 的内容——自包含的执行指令）

--- 自动化检查结果 ---
（脚本自己执行的检查结果，如运行 monitor_check_continuation.sh 的输出）

--- 下一步指令 ---
请用 todo_write 建立以下 todo list：
1. [todo 1 描述]
2. [todo 2 描述]
...
N. 执行下一个脚本: python -m scripts.sop.sop_<下一编号>_<名称>

完成所有 todo 后，最后一项会自动触发下一阶段。
```

### 2.5 5 步循环内容

| 步骤 | 脚本 | 职责 | 调用的现有工具 |
|---|---|---|---|
| 01 | sop_01_health_check.py | 运行健康检查脚本，获取系统状态+所有未处理 alert | `monitor_check_continuation.sh` |
| 02 | sop_02_alert_triage.py | 逐个读 alert，分类为代码bug/数据问题/基础设施问题/需重跑 | 读 DB `p27_monitor_alerts` 集合 |
| 03 | sop_03_ai_judgment.py | C 类 AI 判断——读 proof.md/HANDOVER.md，判断数学正确性/幻觉/答案泄漏/续传方向 | 读 rounds_log 中的路径 |
| 04 | sop_04_code_repair.py | 修复分类为"代码bug"的问题——读代码→定位根因→修复→py_compile→git commit | edit 工具 + py_compile |
| 05 | sop_05_report_worklog.py | 写本轮报告+续写 WORKLOG.md，resolve 已处理的 alert | 写文件 + 更新 DB |

### 2.6 _set_next.py

强制设定下一步：
```bash
python -m scripts.sop._set_next 03   # 强制设定下一步为 sop_03
python -m scripts.sop._set_next 01   # 回到循环开始
```

---

## §3 与现有系统的关系

### 3.1 替代关系

| 现有 | 新机制 | 关系 |
|---|---|---|
| AGENTS.md "Master Agent 检查工作指令" | AGENTS.md "SOP 脚本机制说明" | 替代——从"按需检查指令"改为"SOP 脚本执行说明" |
| MasterAgentCheck.md 的检查内容 | docs/sop/SOP_01~05.md | 内容迁移——MasterAgentCheck.md 改为索引 |
| monitor_check_continuation.sh | sop_01 调用它 | 包裹——sop_01 调用现有脚本获取状态 |

### 3.2 不变的部分

- `monitor_check_continuation.sh` 不变——sop_01 调用它
- `monitor_continuation.py` 不变——仍在写 alert 到 DB
- `continuation_launcher.py` 不变——仍在并发解题
- `session_registry.py` 不变——仍在管理 session
- `MasterAgentCheck.md` 不删除——改为 SOP 文档索引

### 3.3 与 §B 规范的关系

本方案**不实现 §B 的 Monitor Exec Devin（独立 devin cli）**。Master Agent 自己通过 SOP 脚本机制承载 Monitor Pipe 的 AI 检查+修复工作。§B 规范文档需要后续修订（标注为"由 Master Agent SOP 机制承载，不实现独立 devin cli"）。

---

## §4 执行步骤

1. 建 `scripts/sop/` 目录 + `sop_state.py` + `_state.json`
2. 建 5 个 SOP 脚本 + `_set_next.py`
3. 建 5 个 SOP 文档（`docs/sop/`）
4. 修改 `AGENTS.md`——删除按需检查指令，改为 SOP 脚本机制说明
5. 修改 `MasterAgentCheck.md`——内容移入 docs/sop/，改为索引
6. 更新 `README.md` 引导地图 + `trace.csv`
7. 新建 WP-13 + 更新 INDEX.md
8. 验证：手动执行 sop_01 确认机制工作

---

## §5 验收标准

1. `python -m scripts.sop.sop_01_health_check` 能执行并打印 SOP 文档+检查结果+todo 指令
2. 错误执行 sop_03（state.next=02）时，脚本拒绝并提示正确的下一步
3. `python -m scripts.sop._set_next 03` 能强制设定下一步
4. AGENTS.md 的 SOP 说明简短（<30 行）
5. SOP 文档自包含——打印出来后 Master Agent 知道该做什么，不需要加载其他文档
6. todo list 最后一项是"执行下一个脚本"——自驱动循环成立
