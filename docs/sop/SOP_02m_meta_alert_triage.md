# SOP_02m：元检查 — alert分类的合理性

> **你的角色**：你是 SOP 系统的自我审查者。刚才你执行了 sop_02（alert分类），现在你要反思这一步本身的设计是否还合理。

---

## 你要反思什么

上方已经打印了被检查的 SOP_02 文档内容。对照它，思考以下问题：

### 1. 分类逻辑是否还合理？

- SOP_02 的分类表（代码bug/数据问题/基础设施/需重跑）是否还能覆盖所有 alert 类型？
- 最近有没有出现无法归入这四类的 alert？
- 分类的判断标准是否清晰？

### 2. alert 查询是否有效？

- 脚本查询 `p27_monitor_alerts` 集合的 `status != 'resolved'` 是否正确？
- LIMIT 50 是否够用？有没有 alert 被遗漏？
- 排序（created_at DESC）是否合理？

### 3. SOP 文档的指令是否清晰？

- 你执行 sop_02 时，分类指引是否让你清楚地知道每个 alert 该怎么分类？
- "代码bug vs 数据问题"的判断标准是否需要补充例子？

### 4. 是否需要新的分类？

- 系统演进后是否出现了新的 alert 类型？
- 现有分类是否需要细分（如"代码bug"分为"launcher bug"/"monitor bug"/"registry bug"）？

---

## 如果发现问题

如果你发现 SOP_02 需要改进：修改 `docs/sop/SOP_02_alert_triage.md` 和/或 `scripts/sop/sop_02_alert_triage.py`，然后 commit。

---

## 你需要建立的 todo list

- 反思 SOP_02 的合理性（必做）
- 如果需修改：修改 SOP_02 文档/脚本 + commit（如有）
- **最后一项固定是**：执行下一个脚本 `python -m scripts.sop.sop_03_ai_judgment`
