# SOP检查报表 — step_04 C类AI判断

> **填写说明**：本模板由 `scripts/sop/run.py` 自动复制到D盘报表目录。AI加载后逐项检查并填写，填写完用edit写回同一文件。
>
> **打勾规则**：`[x]` 通过 · `[!]` 有问题 · `[ ]` 待检查 · `[-]` 不适用
>
> **核心原则**：C类检查是AI的核心价值——Python只能检查文件存在性，不能检查内容质量。每个判断必须有读了文件的记录。

---

## 系统快照摘要

| 指标 | 值 |
|---|---|
| 总run数 | （从snapshot.json读取） |
| COMPLETED | （从snapshot.json读取） |

---

## 检查项清单

### 一、自动化检查项

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| C0 | 待AI判断条目列表 | 读check_output.txt中"待 AI 判断的条目"节。最多10个needs_ai_review=True的run | [ ] | |

### 二、AI判断检查项（C1-C6）

> 对每个待判断的run，读其proof.md/HANDOVER.md/export，逐项做C1-C6判断。

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| C1 | proof数学正确性 | 读proof.md。检查boxed答案是否正确。检查证明逻辑链是否完整——每一步是否有前置结论支撑。不要求优美，要求逻辑正确。 | [ ] | |
| C2 | proof幻觉检查 | 读proof.md。检查：编造定理（引用不存在的定理）/编造引用（不存在的论文书籍）/虚假计算（错误的计算结果伪装成正确） | [ ] | |
| C3 | 答案泄漏检查 | 读proof.md。检查是否直接从题目描述抄答案而非推导。如选择题直接抄选项、题目含答案时直接抄。 | [ ] | |
| C4 | HANDOVER质量 | 读HANDOVER.md。检查：是否准确总结上一轮思考/有无遗漏关键结论/有无编造上一轮没有的内容 | [ ] | |
| C5 | 续传方向 | 读export的thinking(reasoning_content字段)。判断AI是在上一轮基础上继续还是从头重复。第一轮跳过此项。 | [ ] | |
| C6 | export语义检查 | 读export的conversation.json(前5000行)。判断thinking是否真的在解这道题——不是跑题/循环废话/无实质推理/中途崩溃。 | [ ] | |

---

## C类判断记录

> 逐个记录每个run的C1-C6判断结果

### run 1: {problem_id}

- 读取的文件：proof.md路径 / HANDOVER.md路径 / export路径
- C1 proof_quality: PASS/FAIL（原因）
- C2 proof_hallucination: PASS/FAIL（原因）
- C3 answer_leak: PASS/FAIL（原因）
- C4 handover_quality: PASS/FAIL（原因）
- C5 continuation_direction: PASS/FAIL（原因）
- C6 export_semantics: PASS/FAIL（原因）
- 处理：PASS→resolve needs_ai_review / FAIL→写alert + 是否需步骤05修代码

（如有多个run，复制上面的模板逐个填写）

---

## 发现的问题

### Critical
（在此填写，或写「无」）

### Warning
（在此填写，或写「无」）

### Info
（在此填写，或写「无」）

---

## 执行的操作
（在此填写，或写「无操作」）

---

## 未修复的问题及原因
（在此填写，或写「无」）

---

## 下一轮建议
（在此填写，或写「无」）
