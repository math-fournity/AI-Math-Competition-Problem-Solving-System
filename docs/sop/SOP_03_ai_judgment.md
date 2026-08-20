# SOP_03：C 类 AI 判断

> **你的角色**：你是错题分析系统的 Monitor AI。这一步你要做 Python 做不了的 AI 判断——读 proof.md/HANDOVER.md，判断数学正确性、幻觉、答案泄漏、续传方向。这是你作为 AI 的核心价值所在。

---

## 这一步你要做什么

脚本已经为你查询了标记 `needs_ai_review=True` 的 run，输出在上方"待 AI 判断的条目"部分。你需要：

1. **逐个读这些文件并做 C1-C5 判断**：

| 编号 | 检查项 | 你要读什么 | 判断什么 | 通过标准 |
|---|---|---|---|---|
| C1 | proof_quality | proof.md | 答案对不对、证明逻辑是否完整 | 答案正确且证明逻辑完整 |
| C2 | proof_hallucination | proof.md | 是否有幻觉——编造的定理、不存在的引用、虚假的计算结果 | 无幻觉 |
| C3 | answer_leak | proof.md | 是否答案泄漏——直接从题目描述抄答案而非推导 | 答案是通过推导得到的 |
| C4 | handover_quality | HANDOVER.md | 是否准确总结上一轮思考——有无遗漏关键结论、有无编造 | 准确总结、无遗漏、无编造 |
| C5 | continuation_direction | export（conversation.json） | 续传方向是否正确——在上一轮基础上继续还是从头重复 | 在上一轮基础上继续 |

2. **读取路径**：从脚本输出的条目中获取 `proof_path`/`handover_path`/`export` 路径，用 `read` 工具读文件。

3. **记录判断结果**：对每个条目，记录 PASS/FAIL + 原因。FAIL 的需要决定：
   - 证明逻辑错误 → 数据问题（模型能力），记录不修
   - 幻觉/答案泄漏 → 数据问题，记录
   - handover 质量差 → 数据问题，记录
   - 续传方向错误 → 可能是代码bug（handover prompt 有问题）→ 步骤04

---

## 判断的要点

**C1 proof_quality**：
- 检查 `\boxed{}` 中的答案是否正确（对照标准答案，如果有的话）
- 检查证明逻辑链是否完整——每一步是否有前置结论支撑
- 不要求证明优美，要求逻辑正确

**C2 proof_hallucination**：
- 编造定理：引用了不存在的数学定理
- 编造引用：引用了不存在的论文/书籍
- 虚假计算：计算结果明显错误（如 2+3=6）

**C3 answer_leak**：
- proof.md 中是否直接抄了题目描述中的答案
- 是否没有推导过程只有结论

**C4 handover_quality**：
- HANDOVER.md 是否准确总结了上一轮的关键结论
- 是否遗漏了重要发现
- 是否编造了上一轮没有的内容

**C5 continuation_direction**：
- 读 export 的 thinking 部分，判断 AI 是在上一轮的基础上继续
- 还是完全从头重复（浪费了 handover 信息）

---

## 你需要建立的 todo list

根据 AI 判断结果，用 `todo_write` 建立本轮 todo list：
- 每个 FAIL 条目一个 todo（记录判断结果）
- 需要步骤04修复的（如续传方向错误可能是代码bug）一个 todo
- 步骤05报告 todo
- **最后一项固定是**：执行下一个脚本 `python -m scripts.sop.sop_04_code_repair`

完成所有 todo 后，最后一项会自动触发步骤04。
