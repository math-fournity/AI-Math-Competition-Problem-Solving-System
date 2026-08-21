# SOP_04：C 类 AI 判断

## 认知闭包（执行前必读）

### 什么是 C 类检查

监控 Pipe 的检查分三类：
- A类：自动检查（Python脚本能判定的）——session数量、队列进度、文件存在性等
- B类：续传质量检查（Python抽样+阈值判定）——proof完整性、handover完整性、截断模式等
- **C类：AI判断（Python做不了，必须AI判断）**——proof的数学正确性、幻觉、答案泄漏等

**C类判断由你（Master Agent）做**——monitor_continuation.py 只负责每 3 轮抽样 2 条
COMPLETED 结果，标记 `needs_ai_review=True`。你在这个步骤读 proof.md/HANDOVER.md
做 C1-C6 判断，不是由独立 devin cli 做（monitor_exec 从未实现）。

C类检查是**你作为AI的核心价值**——Python只能检查文件存在性，不能检查内容质量。

### C1-C6 检查项

| 编号 | 检查项 | 你要读什么 | 判断什么 | 通过标准 |
|---|---|---|---|---|
| C1 | proof_quality | proof.md | 答案对不对、证明逻辑是否完整 | 答案正确且证明逻辑完整 |
| C2 | proof_hallucination | proof.md | 是否有幻觉——编造定理/编造引用/虚假计算 | 无幻觉 |
| C3 | answer_leak | proof.md | 是否答案泄漏——直接抄题目描述的答案而非推导 | 答案通过推导得到 |
| C4 | handover_quality | HANDOVER.md | 是否准确总结上一轮思考——有无遗漏/编造 | 准确总结、无遗漏、无编造 |
| C5 | continuation_direction | export的thinking | 续传方向是否正确——在上一轮基础上继续还是从头重复 | 在上一轮基础上继续 |
| C6 | export_semantics | export的thinking | thinking 是否真的是在解这道题——不是跑题/循环废话/无实质推理 | thinking 内容与题目相关且有实质推理 |

### 如何读取文件

从待判断条目中获取路径：
- `proof_path` → 用 read 工具读 proof.md
- `handover_path` → 用 read 工具读 HANDOVER.md
- `export` → 用 read 工具读 conversation.json（可能很大，只读前5000行看thinking部分）

如果路径不存在，记录为数据完整性问题（步骤02应该已经发现，但这里再确认）。

---

## 执行指令

### 1. 阅读待判断条目列表

上方 checks.py 已经查询了 `needs_ai_review=True` 且 `ai_review_done != true` 的 run（最多10个）。

### 2. 逐个做 C1-C6 判断

对每个条目：

#### C1 proof_quality
- 读 proof.md
- 检查 `\boxed{}` 中的答案是否正确
- **标准答案来源**：先读 work_dir/problem.txt 看题目是否含答案；如无，查 DB run 记录的
  problem_id 对应的原始数据集（polymath/oda/deepmath 等）是否有标准答案字段。
  如果确实找不到标准答案，只检查证明逻辑链完整性，在报表中标注"未验证答案正确性"。
- 检查证明逻辑链是否完整——每一步是否有前置结论支撑
- 不要求证明优美，要求逻辑正确

#### C2 proof_hallucination
- 编造定理：引用了不存在的数学定理（如"由Frobenius-Zorn引理可知..."）
- 编造引用：引用了不存在的论文/书籍
- 虚假计算：计算结果明显错误（如 2+3=6）

#### C3 answer_leak
- proof.md 中是否直接抄了题目描述中的答案
- 是否没有推导过程只有结论
- 如果题目本身含答案（如选择题），检查是否只是抄答案

#### C4 handover_quality
- 读 HANDOVER.md
- 是否准确总结了上一轮的关键结论
- 是否遗漏了重要发现
- 是否编造了上一轮没有的内容

#### C5 continuation_direction
- 读 export 的 thinking 部分（reasoning_content 字段）
- 判断 AI 是在上一轮的基础上继续工作
- 还是完全从头重复（浪费了 handover 信息）
- 如果是第一轮（round 1），跳过此项

#### C6 export_semantics
- 读 export 的 conversation.json（可能很大，只读前5000行看 thinking 部分）
- **判断 thinking 是否真的是在解这道题**：
  - 跑题了——在解别的题、在讨论无关内容
  - 循环废话——反复重复同样的内容、没有推进
  - 无实质推理——只是重复 prompt 内容、没有真正的数学推导
  - 中途崩溃——thinking 突然中断、内容不完整
- **这是脚本完全无法做的检查**——脚本能查 export 文件存在、是 JSON 格式，但查不了内容是否在解这道题

### 3. 记录判断结果

对每个条目记录：
```
[problem_id] C1: PASS/FAIL（原因）
             C2: PASS/FAIL（原因）
             C3: PASS/FAIL（原因）
             C4: PASS/FAIL（原因）
             C5: PASS/FAIL（原因）
             C6: PASS/FAIL（原因）
```

FAIL 的条目需要决定后续处理：
- 证明逻辑错误 → 数据问题（模型能力），记录不修
- 幻觉/答案泄漏 → 数据问题，记录
- handover 质量差 → 数据问题，记录
- 续传方向错误 → 可能是代码bug（handover prompt有问题）→ 步骤05
- export 语义错误（跑题/循环废话）→ 可能是 prompt 构造问题或 model 问题 → 记录，如批量出现则步骤05

### 4. 标记已判断

判断完的 run，用控制脚本标记 AI 判断完成+结果：

```
# PASS——判断通过
python -m monitoring.continuation_control mark-ai-review <run_key> --result PASS

# FAIL——判断不通过，附备注
python -m monitoring.continuation_control mark-ai-review <run_key> --result FAIL --note "C2幻觉：编造Frobenius-Zorn引理"
```

标记后，下一轮 check_04 不会再查出这个 run（查询条件是 `needs_ai_review == true && ai_review_done != true`）。

---

## 审计质量复核（C7/C8，WP-E 直接检查版）

### 认知增量：三层都要看

审计 AI 的 `audit_summary` 是"它的说法"；export 里的 `<proof_audit>` XML 是
"它的推理"；proof.md 才是"事实"。复核 C7/C8 时三层都要看——只看 summary 就是
间接检查（违反直接检查铁律）。

### 四步复核法

对 check_04 输出的每条候选（已带实物路径与回退解析）：

1. **读 export**——grep `<proof_audit>` 定位审计 AI 的完整推理块；
2. **读 proof 原文**——被审对象本身（指引给出的路径已经过存在性回退解析）；
3. **独立判断**——boxed 答案与解题逻辑是否支撑审计结论；不要只信 summary；
4. **标记**——`python -m monitoring.continuation_control mark-ai-review <audit记录key> --result PASS/FAIL --scope audit`

### C9 已移交

作弊证据复核（FAIL_CHEATING 清单+cheating_analysis 全文）→ **步骤 07 检查项 6**
（同源数据归并，SOP_04 专注 C1-C8）。

---

## 你需要建立的 todo list

- 每个待判断条目一个 todo（读文件+做C1-C6判断+记录结果）
- 需步骤05修复的（如续传方向错误是代码bug）
- **填写 report.md 报表**（read加载→打勾填发现→edit写回）
- **最后一项固定是**：`执行下一个脚本: python -m scripts.sop.run`

完成所有 todo 后，自动触发步骤05（代码修复）。

### 深入了解（如需）

- `docs/specs/p27_monitor_spec.md` §3.3 — C1-C6 AI review 抽样标准的权威定义（C1-C5 由 monitor 抽样标记，C6 export_semantics 为 020 审计新增、由你在本步骤执行）
- `docs/patterns/续传规范文档.md` — HANDOVER.md 的标准格式（C4 handover_quality 判断依据）
