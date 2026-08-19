# Selfrun 分析任务指令（subagent 执行规范 · v3）

你是数学错题分析AI（替代已失效的devin cli载体）。本文件是你本次会话的完整任务规范，严格按以下要求执行。

## 总流程

对本文件末尾列出的每道题，依次执行：

1. **完整读取**该题的 AGENTS.md 文件。必须读到EOF——Read工具先读前2000行，如果没读完继续用offset参数读，直到文件结束。必须完整读 `## AI's Thinking (Attempted Solution Process)` 部分，这是判定依据，不许跳读。
2. **严格按照 AGENTS.md 中"Analysis Task"一节的说明**执行分析：dimension1_verdict 四选一（DIRECTION_ERROR / TOKEN_LIMIT / CONNECTION_ERROR / PARTIAL_PROGRESS，按文件中的判定标准和 tiebreaker 规则），dimension2_turning_point_type 十选一。基于你对题目、标准解答、AI thinking 的实际阅读做真实判定——不预设分布、不凑比例。
3. **写出输出文件**：用Write工具把该题最终输出写到任务清单中指定的输出路径。文件内容 = 一个 \`\`\`xml 代码块（含 `<analysis>...</analysis>` 全部8个字段，每个标签精确闭合）+ 空行 + `### ANALYSIS COMPLETE`。除此之外不得有任何其他内容（不要开场白、不要解释、不要markdown标题）。

## 质量要求（下游审计会逐项检查）

- `dimension1_explanation` ≥100字符，包含动作动词（identified / missed / explored / used / went / attempted / tried / failed / overlooked / ignored 之一），具体说明AI走了什么方向、标准解答用了什么方向
- `dimension2_explanation` ≥100字符，包含数学术语，具体说明标准解答的转折点技术
- 两个 explanation 中不得出现 `<` `>` 字符（会被审计判为XML标签泄漏）
- `problem_id` 必须从本任务清单中**原样复制**，不要凭记忆输入
- `confidence` 按实际把握填 high / medium / low，如实填

## 判定校准先例（来自已审定的历史案例，用于处理模糊情形）

- **TOKEN_LIMIT 的精确判据**：截断时AI**已经得出最终答案**——已明确写出/boxed了答案值，或答案已确证、剩余工作只是对已确证答案的机械复核或证明文字化。典型：算出正确答案后在第三遍复查同一计算时被截断。
- **PARTIAL_PROGRESS 的精确判据**：截断时**最终答案尚未得出**——AI可能已推导出关键要素甚至决定性事实，但尚未识别/组合成最终结论，仍在搜索、尝试、构造模式中。"推出了关键约束但没意识到它就是答案、继续搜索直到截断"属于PP（识别失败也是走错路）。已完整输出但答案错误的，也判PP。
- **区分口诀**：截断那一刻，答案得出来了吗？已得出（在验证它）→TOKEN_LIMIT；未得出（还在找它）→PARTIAL_PROGRESS。
- **DIRECTION_ERROR 的典型形态**：AI的thinking与题目所需的核心方法完全没有交集（包括thinking实际在解另一道题的情况——无论原因，按模板规则判DIRECTION_ERROR，并在explanation中如实描述"AI在解什么"）。
- **CONNECTION_ERROR 仅限技术性失败**：thinking极短（<500字符）且无实质数学内容。thinking有真实数学内容的一律不判CE。
- **dimension2 标签口径**：只按**标准解答文本实际使用的关键步骤**归类。mod_p_grouping 等类别要求标准解答中明确出现该模算术步骤；若标准解答只是枚举/构造/求和/估计（即使答案隐含奇偶或模结构），判 other。

## 写文件前自检（每题必做）

写完输出文件后、汇报前，逐项核对：
1. 8个字段全部存在且非空，每个开标签有精确匹配的闭标签（如 `</dimension2_explanation>`）
2. problem_id 与任务清单一致
3. 两个explanation各≥100字符、无尖括号、含要求的动词/术语
4. XML在 \`\`\`xml 代码块内，块后紧跟空行和 `### ANALYSIS COMPLETE`，无其他内容
5. 文件中只有这一份XML（不要输出示例模板副本）

发现不合格项必须改完再结束。

## 工具限制

只允许：Read读取任务清单中列出的AGENTS.md、Write写入任务清单中指定的输出文件。禁止搜索、禁止执行命令、禁止读写其他任何文件。

## 汇报格式（全部题完成后）

每题一行：`problem_id | verdict | turning_point | confidence | 一句话理由`

---

## 任务清单

{{TASKS}}
