# SOP_03m：元检查 — AI判断的合理性

> **你的角色**：你是 SOP 系统的自我审查者。刚才你执行了 sop_03（AI判断），现在你要反思这一步本身的设计是否还合理。

---

## 你要反思什么

上方已经打印了被检查的 SOP_03 文档内容。对照它，思考以下问题：

### 1. C1-C5 判断项是否还全面？

- proof_quality / proof_hallucination / answer_leak / handover_quality / continuation_direction 这 5 项是否还够用？
- 系统演进后是否需要新增判断项（如"proof 格式规范性"、"推理链长度合理性"）？
- 现有判断项的通过标准是否需要细化？

### 2. 查询逻辑是否有效？

- 脚本查询 `needs_ai_review == true` 且 `ai_review_done != true` 的 run，LIMIT 10。这是否够用？
- 有没有应该被标记但没被标记的 run？
- `flag_for_ai_review()` 的抽样逻辑（每 3 轮 2 条）是否合理？

### 3. 判断过程是否可追溯？

- 你做 C1-C5 判断后，判断结果记录在哪里？
- 下一轮循环的你能否看到上一轮的判断结果？
- 是否需要在 DB 中记录 `ai_review_result` 字段？

### 4. SOP 文档的判断指引是否充分？

- C1 proof_quality 的"检查证明逻辑链是否完整"是否需要更具体的标准？
- C2 proof_hallucination 的"编造定理"是否需要例子？
- C5 continuation_direction 的判断方法是否可操作？

---

## 如果发现问题

修改 `docs/sop/SOP_03_ai_judgment.md` 和/或 `scripts/sop/sop_03_ai_judgment.py`，然后 commit。

如果需要新增 DB 字段（如 `ai_review_result`），在 `monitor_continuation.py` 中添加。

---

## 你需要建立的 todo list

- 反思 SOP_03 的合理性（必做）
- 如果需修改：修改 SOP_03 文档/脚本 + commit（如有）
- **最后一项固定是**：执行下一个脚本 `python -m scripts.sop.sop_04_code_repair`
