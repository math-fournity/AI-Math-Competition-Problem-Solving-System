# WP-13：Master Agent SOP 流程控制机制

**需求来源**：dev-docs/013-Master-Agent-SOP流程控制机制方案.md
**前置工作包**：WP-11（MasterAgentCheck.md 创建）、WP-12（AGENTS.md 指令）
**性质**：架构升级——从"按需检查"升级为"7x24 持续循环的 SOP 脚本机制"

---

## 工作目标

把 Master Agent 的 Monitor Pipe 工作从"按需检查"（用户问才查）升级为"7x24 持续循环"（用户发一次"开始工作"后持续循环）。通过编号化 SOP 脚本 + 自驱动 todo list 机制实现。

---

## 涉及的 checkpoint

- 无新增 checkpoint——这是工作模式变化，不是系统功能变化
- 相关 checkpoint：MON-A1~A12 / MON-B1~B9 / MON-C1~C5（SOP 脚本承载这些检查的执行）

---

## 执行步骤

| 步骤 | 文件 | 改动 | 状态 |
|---|---|---|---|
| 1 | `scripts/sop/__init__.py` | 新建（空） | ✅ |
| 1 | `scripts/sop/sop_state.py` | 新建——状态管理模块 | ✅ |
| 1 | `scripts/sop/_state.json` | 新建——步骤状态记录 | ✅ |
| 1 | `scripts/sop/sop_01_health_check.py` | 新建 | ✅ |
| 1 | `scripts/sop/sop_02_alert_triage.py` | 新建 | ✅ |
| 1 | `scripts/sop/sop_03_ai_judgment.py` | 新建 | ✅ |
| 1 | `scripts/sop/sop_04_code_repair.py` | 新建 | ✅ |
| 1 | `scripts/sop/sop_05_report_worklog.py` | 新建 | ✅ |
| 1 | `scripts/sop/_set_next.py` | 新建 | ✅ |
| 2 | `docs/sop/SOP_01_health_check.md` | 新建 | ✅ |
| 2 | `docs/sop/SOP_02_alert_triage.md` | 新建 | ✅ |
| 2 | `docs/sop/SOP_03_ai_judgment.md` | 新建 | ✅ |
| 2 | `docs/sop/SOP_04_code_repair.md` | 新建 | ✅ |
| 2 | `docs/sop/SOP_05_report_worklog.md` | 新建 | ✅ |
| 3 | `AGENTS.md` | 修改——按需检查指令→SOP脚本机制说明 | ✅ |
| 4 | `checklist/MasterAgentCheck.md` | 修改——检查内容移入docs/sop/，改为索引 | ✅ |
| 5 | `README.md` | 修改——引导地图加入docs/sop/和scripts/sop/条目 | ✅ |
| 6 | `trace.csv` | 更新——新增资产追溯关系 | 待做 |

---

## 验收标准

1. `python -m scripts.sop.sop_01_health_check` 能执行并打印 SOP 文档+检查结果+todo 指令
2. 错误执行 sop_03（state.next=02）时，脚本拒绝并提示正确的下一步
3. `python -m scripts.sop._set_next 03` 能强制设定下一步
4. AGENTS.md 的 SOP 说明简短（<40 行）
5. SOP 文档自包含——打印出来后 Master Agent 知道该做什么
6. todo list 最后一项是"执行下一个脚本"——自驱动循环成立
