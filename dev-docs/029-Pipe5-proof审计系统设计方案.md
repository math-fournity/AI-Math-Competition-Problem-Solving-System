# 029 — Pipe 5 proof 审计系统设计方案

> **日期**：2026-08-21
> **性质**：方案文档——设计续传系统的独立审计 Pipe，对 proof.md 进行数学正确性审计
> **触发**：028 报告恢复 138 题 proof.md 后，用户指出"Pipe 中缺乏一个独立的 devin cli 对之前的 Pipe 产生的结果进行审计"

---

## 1. 问题陈述

### 1.1 现状缺陷

续传系统（Pipe 4）目前**没有独立的审计 Pipe**。proof.md 一旦被 launcher 标记 completed，就直接进入选题池——没有独立的 devin cli 验证 proof 的数学正确性。

现有机制：
- **A/B 类检查**（monitor_continuation）：脚本自动检查 proof_completeness（有 boxed）、proof_no_boxed、handover_completeness 等——**只检查格式，不检查内容**
- **C 类抽样**（flag_for_ai_review）：每 3 轮抽样 2 条标记 `needs_ai_review=True`——**只标记，不自动审计，靠 Master Agent 人工看**

对比 Pipe 1 分析系统有完整的 Pipe 2 审计（`audit_launcher` 启动独立 devin cli 审计分析结果，1397 条 `audit_results` 记录），Pipe 4 续传系统缺这一层。

### 1.2 需要做什么

建造一个独立的审计 Pipe（Pipe 5），对 Pipe 4 产出的 proof.md 进行数学正确性审计：
1. 独立的 devin cli 实例审计每道 completed 题的 proof.md
2. 给出审计报告（PASS / FAIL 类型）
3. 审计结果写入 DB
4. 根据审计结果决定该题是否进入选题池

---

## 2. 设计参考——Pipe 2 审计系统

Pipe 2 审计系统（`audit_launcher.py` 542行 + `audit_collector.py` 252行 + `audit_result_collector.py` 360行）提供了成熟的参考架构：

| 组件 | Pipe 2（审计分析结果） | Pipe 5（审计 proof.md） |
|---|---|---|
| collector | 收集待审计的 analysis_results | 收集待审计的 completed proof.md |
| launcher | 并发启动 devin cli 审计 | 并发启动 devin cli 审计 proof |
| result_collector | 收集审计结果入 audit_results | 收集审计结果入 p27_proof_audits |
| AGENTS.md 模板 | 5 维度检查（A-E） | 数学正确性检查（见 §3） |
| 完成标记 | `### AUDIT COMPLETE` | `### PROOF AUDIT COMPLETE` |
| DB 集合 | audit_runs / audit_results | p27_proof_audit_runs / p27_proof_audits |

**关键差异**：Pipe 2 审计的是"分析结果的质量"（字段完整性/内容完整性/内部一致性），Pipe 5 审计的是"数学证明的正确性"（答案对不对/推理有没有幻觉/证明完不完整）——后者更难，需要 AI 有数学判断能力。

---

## 3. 防作弊机制——解题 AI 与审计 AI 的不对称约束

### 3.0.1 核心原则：题目靠 AI 自己的数学能力解决

**解题 AI** 可以使用工具（Python 代码计算/验证、Lean 代码形式化验证、计算器），也可以进行网络搜索。但**题目必须靠 AI 自己的数学推理能力解决**——不能靠"找到答案"解决。

**作弊定义**：AI 在网络搜索、查资料、翻找硬盘目录、查数据库内容时，发现了和题目解答或解题线索直接相关的内容，并据此完成证明。这包括：
- 搜到了题目的标准解答（直接抄）
- 搜到了题目的答案（反推证明）
- 翻硬盘/数据库时发现了同一道题的之前解题记录
- 查资料时找到了关键定理/引理的完整证明（AI 自己推不出来的部分直接抄）

**工具使用的合法边界**：
- ✅ 用 Python 做数值计算/符号计算验证猜想——合法（AI 自己决定算什么）
- ✅ 用 Lean 形式化验证推理步骤——合法（AI 自己写证明代码）
- ✅ 搜索通用数学知识（如"群的定义""Hausdorff 空间性质"）——合法（通用知识不是题目答案）
- ❌ 搜索题目文本本身——作弊风险（可能搜到解答）
- ❌ 翻找硬盘上的 trajectory 目录/数据库中的解题记录——作弊
- ❌ 搜索后直接引用搜到的完整证明——作弊

### 3.0.2 解题 AI 的主动声明义务

如果解题 AI 发现自己在搜索/查资料过程中遇到了和题目解答直接相关的内容，**必须主动在 proof.md 开头声明**：

```markdown
## ⚠️ 作弊风险声明

在解题过程中，我通过 [网络搜索/文件查找/数据库查询] 接触到了与本题解答
相关的以下内容：
- [描述接触到了什么，如"搜到了该题的标准解答"/"在硬盘上找到了同一道题
  的之前解题记录"]

我对这些内容的使用情况：
- [说明是直接引用了/参考了/虽然看到了但独立推导的]

因此本 proof 可能存在作弊风险，请审计 AI 重点检查。
```

**为什么让解题 AI 自己声明**：
1. AI 的诚实声明是第一道防线——大多数 AI 在明确要求下会遵守
2. 声明本身是审计 AI 的检查线索——有声明的题审计 AI 重点查"用了多少"
3. 无声明但实际作弊的题，审计 AI 通过推理链分析发现（思维跳跃 = 作弊信号）

### 3.0.3 审计 AI 的不对称约束

**审计 AI 不受防作弊限制**——可以自由搜索、查资料、翻硬盘、查数据库，以辅助判断解题 AI 是否作弊。但审计 AI 的核心任务是**严格审计解题 AI 的证明质量**：

| 审计维度 | 审计 AI 要查什么 | 判定标准 |
|---|---|---|
| 思维跳跃 | 推理链是否有断裂（前一步推不出后一步） | 每步可追溯 / 有跳跃 |
| 数学真理性 | 每一步是否数学正确 | 全程正确 / 有错误 |
| 可验证性 | 每一步是否可独立验证（不依赖"显然""易得"） | 可验证 / 有不可验证的步骤 |
| 数学幻觉 | 是否引用不存在的定理/编造公式/虚构引理 | 无幻觉 / 有幻觉 |
| 作弊检测 | 是否有未声明的作弊行为（推理链中出现搜来的内容但没声明） | 无作弊 / 有作弊 |

**审计 AI 查作弊的方法**：
1. 检查 proof.md 开头有无作弊风险声明——有声明则重点查"用了多少"
2. 分析推理链——如果某一步突然出现 AI 前面推不出来的高级定理/引理，且没有推导过程，可能是搜来的
3. 审计 AI 可以自己搜索题目文本，看能否搜到标准解答——如果能搜到，解题 AI 也可能搜到
4. 审计 AI 可以查硬盘/数据库，看解题 AI 的 trajectory 中有没有搜索行为接触到了答案

---

## 3.1 审计维度（修订版）

审计 AI 收到：题目文本（problem_text）+ 标准答案（answer）+ proof.md 内容 + 解题 AI 的 trajectory（如可用，含 tool_calls 记录）。检查 7 个维度：

| 维度 | 编号 | 检查项 | 判定标准 |
|---|---|---|---|
| A 答案正确性 | A1 | proof 的 boxed 答案与标准答案一致 | 完全一致 / 等价形式 / 不一致 |
| B 推理正确性 | B1 | 关键推理步骤数学正确（无逻辑错误） | 无逻辑错误 / 有错误 |
| B 推理正确性 | B2 | 无幻觉（不引用不存在的定理/编造公式） | 无幻觉 / 有幻觉 |
| C 证明完整性 | C1 | 证明完整（不是截断的残篇） | 完整 / 截断残篇 |
| C 证明完整性 | C2 | 证明覆盖题目的所有要求 | 完全覆盖 / 部分覆盖 |
| D 可验证性 | D1 | 每一步可独立验证（不依赖"显然""易得"） | 可验证 / 有不可验证步骤 |
| D 可验证性 | D2 | 无思维跳跃（推理链连续，前步可推出后步） | 连续 / 有跳跃 |
| E 作弊检测 | E1 | proof.md 有作弊风险声明时，检查声明是否属实 | 声明属实 / 声明不实 |
| E 作弊检测 | E2 | 无声明时，检查推理链有无搜来内容的痕迹 | 无痕迹 / 有未声明作弊 |

### 3.2 审计结果类型（audit_status 枚举）

| audit_status | 含义 | DB 处理 | 选题池 |
|---|---|---|---|
| `PASS` | 答案正确 + 推理正确 + 证明完整 + 可验证 + 无作弊 | 标记 audit_passed=True | ✅ 进入 |
| `PASS_WITH_CAVEAT` | 答案正确但有小瑕疵（如格式不规范/有声明但独立推导） | 标记 audit_passed=True + caveat | ✅ 进入（附注） |
| `FAIL_WRONG_ANSWER` | boxed 答案与标准答案不一致 | 标记 audit_passed=False + 改 status=audit_failed | ❌ 不进入 |
| `FAIL_HALLUCINATION` | 有幻觉（引用不存在的定理/编造公式） | 标记 audit_passed=False + 改 status=audit_failed | ❌ 不进入 |
| `FAIL_INCOMPLETE` | 证明不完整（截断残篇被误判完成） | 标记 audit_passed=False + 改 status=prepared（重做） | ❌ 不进入 |
| `FAIL_LOGIC_ERROR` | 推理有逻辑错误 / 思维跳跃 / 不可验证 | 标记 audit_passed=False + 改 status=audit_failed | ❌ 不进入 |
| `FAIL_CHEATING` | 有未声明的作弊行为（搜来答案/抄来证明） | 标记 audit_passed=False + 改 status=audit_failed | ❌ 不进入 |
| `FAIL_CHEATING_DECLARED` | 有声明但审计判定确实作弊（声明了但直接抄了） | 标记 audit_passed=False + 改 status=audit_failed | ❌ 不进入 |
| `PARSE_ERROR` | 审计 AI 无法解析 proof（格式太乱） | 标记 audit_passed=None + 需人工复查 | ⏸ 待定 |

### 3.3 DB 处理逻辑

审计完成后，根据 audit_status 更新 DB：

```
PASS / PASS_WITH_CAVEAT:
  → p27_continuation_runs.update(run_key, {audit_status, audit_passed: True, audited_at})
  → 选题池查询条件加 audit_passed=True

FAIL_WRONG_ANSWER / FAIL_HALLUCINATION / FAIL_LOGIC_ERROR / FAIL_CHEATING / FAIL_CHEATING_DECLARED:
  → p27_continuation_runs.update(run_key, {audit_status, audit_passed: False, status: "audit_failed", audited_at})
  → 该题不进入选题池，但保留 proof 供人工复查
  → FAIL_CHEATING / FAIL_CHEATING_DECLARED 额外创建 p27_monitor_alerts（cheating_detected）

FAIL_INCOMPLETE:
  → p27_continuation_runs.update(run_key, {audit_status, audit_passed: False, status: "prepared", audited_at})
  → 该题重新进入做题队列（proof 是残篇，需要重做）

PARSE_ERROR:
  → p27_continuation_runs.update(run_key, {audit_status, audit_passed: None, audited_at})
  → 创建 p27_monitor_alerts（audit_parse_error），等人工处理
```

---

## 4. DB Schema 设计

### 4.1 新增集合

| 集合 | 用途 |
|---|---|
| `p27_proof_audit_runs` | 每道题的审计 run 记录（类似 p27_continuation_runs） |
| `p27_proof_audits` | 审计结果（类似 p27_continuation_results） |

### 4.2 p27_proof_audit_runs 字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `_key` | str | 是 | `paudit-{run_key}`（run_key=被审计的 continuation run 的 key） |
| `source_run_key` | str | 是 | 被审计的 p27_continuation_runs 的 _key |
| `problem_id` | str | 是 | 题目 ID |
| `batch_id` | str | 是 | 审计批次 ID |
| `status` | str | 是 | prepared/running/completed/failed |
| `audit_status` | str | 否 | 审计结果（见 §3.2 枚举） |
| `audit_passed` | bool/None | 否 | True=通过，False=不通过，None=待定 |
| `work_dir` | str | 是 | 审计工作目录 |
| `export_path` | str | 否 | 审计 devin cli 的 export 路径 |
| `started_at` | str | 否 | 开始时间 |
| `ended_at` | str | 否 | 结束时间 |
| `audited_at` | str | 否 | 审计完成时间 |
| `error_message` | str | 否 | 失败原因 |

### 4.3 p27_proof_audits 字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `_key` | str | 是 | `paudit-result-{run_key}` |
| `source_run_key` | str | 是 | 被审计的 continuation run 的 _key |
| `problem_id` | str | 是 | 题目 ID |
| `batch_id` | str | 是 | 审计批次 ID |
| `audit_status` | str | 是 | 审计结果（见 §3.2 枚举） |
| `check_results` | object | 是 | {A1, B1, B2, C1, C2, D1, D2, E1, E2} 各项的 PASS/FAIL + reason |
| `cheating_analysis` | str | 否 | 作弊分析详情（无作弊则"无作弊嫌疑"） |
| `audit_summary` | str | 是 | 审计 AI 的一句话总结 |
| `proof_text` | str | 否 | 被审计的 proof 文本（备份） |
| `problem_text` | str | 否 | 题目文本（审计时的输入快照） |
| `standard_answer` | str | 否 | 标准答案（审计时的输入快照） |
| `solver_trajectory_summary` | str | 否 | 解题 AI 的工具调用摘要（用于作弊检测） |
| `created_at` | str | 是 | 创建时间 |

### 4.4 p27_continuation_runs 新增字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `audit_status` | str/None | 审计结果（None=未审计） |
| `audit_passed` | bool/None | 审计是否通过 |
| `audited_at` | str/None | 审计完成时间 |
| `audit_run_key` | str/None | 对应的 p27_proof_audit_runs 的 _key |

### 4.5 索引

```
p27_proof_audit_runs:
  - source_run_key（单字段）
  - problem_id（单字段）
  - batch_id（单字段）
  - status（单字段）

p27_proof_audits:
  - source_run_key（单字段）
  - problem_id（单字段）
  - batch_id（单字段）
  - audit_status（单字段）
```

### 4.6 Redis 队列

复用续传系统的 Redis 队列模式，但用 `paudit:` 前缀：

| 键 | 类型 | 用途 |
|---|---|---|
| `paudit:pending` | sorted set | 待审计队列 |
| `paudit:running` | hash | 正在审计 |
| `paudit:completed` | list | 已完成 |
| `paudit:failed` | list | 失败 |
| `paudit:stats` | hash | 统计 |

---

## 5. 模块设计

### 5.1 文件结构

```
src/
├── proof_audit_config.py          # 审计配置常量
├── proof_audit_collector.py       # 收集 completed 题入审计队列
├── proof_audit_launcher.py        # 并发启动 devin cli 审计
├── proof_audit_result_collector.py # 收集审计结果
├── proof_audit_db_schema.py       # 审计 DB 集合管理
monitoring/
├── proof_audit_redis_queue.py     # 审计 Redis 队列
templates/
├── proof_audit_agents_md.md       # 审计 AI 的 AGENTS.md 模板
```

### 5.2 各模块职责

| 模块 | 职责 | 输入 | 输出 |
|---|---|---|---|
| proof_audit_collector | 查 p27_continuation_runs 中 completed 但未审计的题，创建 p27_proof_audit_runs 记录 | DB | p27_proof_audit_runs(prepared) |
| proof_audit_launcher | 并发启动 devin cli 审计 proof.md | Redis pending + DB | 审计 export + DONE.md |
| proof_audit_result_collector | 解析审计 export，提取 audit_status，写入 p27_proof_audits，更新 p27_continuation_runs | 审计 export | p27_proof_audits + 更新 runs |
| proof_audit_db_schema | DB 集合管理 + AQL 封装 | — | — |

### 5.3 审计 AI 的 AGENTS.md 模板

审计 AI 收到的输入：
- `problem_text`：题目文本
- `standard_answer`：标准答案
- `proof_text`：proof.md 内容（含可能的作弊风险声明）
- `solver_trajectory`：解题 AI 的 tool_calls 记录（如可用，用于作弊检测）

审计 AI 的指令（核心）：
```
你是一个数学证明审计员。你收到一道数学题、标准答案、一个 AI 产生的 proof.md、
以及解题 AI 的工具调用记录。

你的任务是严格审计这个 proof 的数学正确性和解题诚信——不是重新解题，
而是检查证明的质量和真实性。

## 你的权限

你可以自由使用工具——搜索网络、查资料、读文件、查数据库——来辅助你的审计。
你不受解题 AI 的防作弊约束。你可以搜索题目文本来判断这道题的解答是否容易
在网上找到。你可以查解题 AI 的工具调用记录来判断它是否搜到了答案。

## 审计维度

### A 答案正确性
A1: proof 的 boxed 答案与标准答案是否一致（等价形式算 PASS）

### B 推理正确性
B1: 关键推理步骤是否数学正确（每一步都要检查，不能跳过）
B2: 是否有幻觉（引用不存在的定理/编造公式/虚构引理）

### C 证明完整性
C1: 证明是否完整（不是截断的残篇被误判完成）
C2: 证明是否覆盖题目的所有要求

### D 可验证性
D1: 每一步是否可独立验证（不依赖"显然""易得""不难证明"等跳过词）
D2: 无思维跳跃（推理链连续，前一步能推出后一步；如果某一步突然出现前面
    推不出来的高级定理/引理且没有推导过程，这是思维跳跃的信号）

### E 作弊检测
E1: proof.md 开头有无作弊风险声明？
    - 有声明：检查声明是否属实，AI 虽然接触到了相关内容但是否独立推导
    - 无声明：检查推理链有无搜来内容的痕迹
E2: 检查解题 AI 的工具调用记录（如提供）：
    - 有无搜索题目文本的行为
    - 有无翻找硬盘/数据库找到解题记录的行为
    - 搜索/查到的内容是否直接出现在 proof 中

## 审计标准

- PASS: A1✓ + B1✓ + B2✓ + C1✓ + C2✓ + D1✓ + D2✓ + E1✓(无作弊或声明属实) + E2✓
- PASS_WITH_CAVEAT: 答案正确但有小瑕疵（如格式不规范/有声明但确实独立推导）
- FAIL_WRONG_ANSWER: A1✗
- FAIL_HALLUCINATION: B2✗
- FAIL_INCOMPLETE: C1✗（截断残篇）
- FAIL_LOGIC_ERROR: B1✗ 或 D1✗ 或 D2✗（逻辑错误/思维跳跃/不可验证）
- FAIL_CHEATING: E2✗（有未声明的作弊行为）
- FAIL_CHEATING_DECLARED: E1✗（有声明但审计判定确实直接抄了）
- PARSE_ERROR: proof 格式太乱无法解析

输出 XML 格式的审计报告，以 ### PROOF AUDIT COMPLETE 结尾。
```

### 5.4 解题 AI 的 AGENTS.md 模板更新

续传系统解题 AI 的 AGENTS.md（`templates/continuation_solve_agents_md.md`）需要新增防作弊约束：

```
## 工具使用与防作弊约束

你可以使用工具（Python 代码、Lean 代码、计算器）辅助解题，也可以进行网络搜索。
但本题必须靠你自己的数学推理能力解决——不能靠"找到答案"解决。

### 合法使用
- ✅ 用 Python 做数值计算/符号计算验证你的猜想
- ✅ 用 Lean 形式化验证你的推理步骤
- ✅ 搜索通用数学知识（如"群的定义""Hausdorff 空间性质"）

### 作弊行为（禁止）
- ❌ 搜索题目文本本身（可能搜到标准解答）
- ❌ 翻找硬盘上的 trajectory 目录或数据库中的解题记录
- ❌ 搜索后直接引用搜到的完整证明
- ❌ 查资料时找到关键定理的完整证明后直接抄（你自己推不出来的部分）

### 主动声明义务
如果你在搜索/查资料过程中遇到了和题目解答直接相关的内容，你必须在 proof.md
开头加一个"作弊风险声明"章节，说明：
1. 你通过什么方式接触到了什么相关内容
2. 你对这些内容的使用情况（直接引用/参考/虽然看到但独立推导）

不声明但被审计 AI 发现作弊 = FAIL_CHEATING（该题作废）。
声明了但确实独立推导 = PASS_WITH_CAVEAT（该题有效但附注）。
```

### 5.5 审计 launcher 的完成检测

类似 Pipe 2 的 `### AUDIT COMPLETE` 标记，Pipe 5 用 `### PROOF AUDIT COMPLETE`。

审计 AI 输出格式：
```xml
<proof_audit>
  <problem_id>{problem_id}</problem_id>
  <audit_status>ONE_OF: PASS, PASS_WITH_CAVEAT, FAIL_WRONG_ANSWER, FAIL_HALLUCINATION, FAIL_INCOMPLETE, FAIL_LOGIC_ERROR, FAIL_CHEATING, FAIL_CHEATING_DECLARED, PARSE_ERROR</audit_status>
  <check_results>
    <A1>PASS or FAIL: reason</A1>
    <B1>PASS or FAIL: reason</B1>
    <B2>PASS or FAIL: reason</B2>
    <C1>PASS or FAIL: reason</C1>
    <C2>PASS or FAIL: reason</C2>
    <D1>PASS or FAIL: reason</D1>
    <D2>PASS or FAIL: reason</D2>
    <E1>PASS or FAIL or N/A: reason</E1>
    <E2>PASS or FAIL: reason</E2>
  </check_results>
  <cheating_analysis>如果有作弊嫌疑，详细说明发现的证据；无则写"无作弊嫌疑"</cheating_analysis>
  <audit_summary>一句话总结</audit_summary>
</proof_audit>
### PROOF AUDIT COMPLETE
```

---

## 6. 门闸（Step Gate）集成

### 6.1 设计原则——审计 Pipe 必须融入门控体系

续传系统已有 9 个 `@gated` 门闸（`GATE-FEED-ENQUEUE` 到 `GATE-FINALIZE-RUN-COMPLETED`），覆盖启动进程/杀 session/重入队/删产物/写终态等语义动作。门闸的核心设计是：

- **门闸只设在语义动作上**——有独立正确性标准的业务动作
- **docstring 是唯一事实源**——每个闸的 docstring 含"放行前 Master Agent 应检查"段落
- **X/Y 注意力模型**——X=mode(auto/hold)，Y=waiting_for(触发)；无 Y = 不要求操心
- **SOP 循环检查**——SOP_01 每轮检查 `--pending`，发现 Y 则 Master Agent 介入

审计 Pipe 的关键语义动作也必须设闸，让 Master Agent 能单步跟踪审计过程。

### 6.2 审计 Pipe 的门闸设计（4 个新门闸）

| gate_id | 模块 | 动作 | resource | 不可逆性 |
|---|---|---|---|---|
| `GATE-AUDIT-LAUNCH` | proof_audit_launcher | 启动审计 devin cli | action | 可逆（kill session） |
| `GATE-AUDIT-KILL-SESSION` | proof_audit_launcher | kill 审计 session | tmux | 不可逆 |
| `GATE-AUDIT-FINALIZE-PASS` | proof_audit_result_collector | 写 audit_passed=True（进入选题池） | db | 几乎不可逆 |
| `GATE-AUDIT-FINALIZE-FAIL` | proof_audit_result_collector | 写 audit_passed=False + 改 status | db | 几乎不可逆 |

### 6.3 各门闸的 docstring 检查项

**GATE-AUDIT-LAUNCH**（启动审计 devin cli）：
```
放行前 Master Agent 应检查：
1. 待审计的 proof.md 存在且非空 → 查法：ls work_dir/proof.md + wc -c > 0
2. 审计 work_dir 已准备好（AGENTS.md + input.md + proof.txt） → 查法：ls 审计 work_dir
3. 审计并发未超限 → 查法：paudit:running 的hlen < concurrency
```

**GATE-AUDIT-KILL-SESSION**（kill 审计 session）：
```
放行前 Master Agent 应检查：
1. 审计已完成 → 查法：DONE.md存在 或 ### PROOF AUDIT COMPLETE 在 export 中
2. 审计 export 已落盘 → 查法：ls export文件存在
3. reason=completed/stall/dead 时审计结果已提取 → 查法：p27_proof_audits 有记录
```

**GATE-AUDIT-FINALIZE-PASS**（写 audit_passed=True）：
```
放行前 Master Agent 应检查：
1. 审计 export 的 XML 解析成功 → 查法：check_results 字段齐全
2. audit_status=PASS 或 PASS_WITH_CAVEAT → 查法：读 audit_status 字段
3. A1 答案正确性 PASS → 查法：check_results.A1 含 PASS
4. 无作弊标记 → 查法：E1/E2 均 PASS 或 N/A
```

**GATE-AUDIT-FINALIZE-FAIL**（写 audit_passed=False + 可能改 status）：
```
放行前 Master Agent 应检查：
1. 审计 export 的 XML 解析成功 → 查法：check_results 字段齐全
2. audit_status 是 FAIL_* 之一 → 查法：读 audit_status 字段
3. FAIL_INCOMPLETE 时确认 proof 确实是截断残篇 → 查法：读 proof.md 看是否中途断裂
4. FAIL_CHEATING 时确认作弊证据充分 → 查法：读 cheating_analysis 字段
5. 改 status=audit_failed 的影响：该题退出选题池，需人工复查才能翻案
```

### 6.4 门闸注册

审计 Pipe 的门闸在 `proof_audit_launcher.py` 和 `proof_audit_result_collector.py` 中用 `@gated` 装饰器声明。启动时 `--register` 同步到 DB `p27_step_gates` 集合。

Master Agent 操作：
```bash
python -m src.step_gate --register                    # 注册/刷新门闸目录
python -m src.step_gate --list                        # 查看所有门闸（含审计门闸）
python -m src.step_gate --hold GATE-AUDIT-FINALIZE-PASS  # hold 审计通过闸
python -m src.step_gate --pending                     # 查看等待放行的门闸
```

---

## 7. SOP 集成

### 7.1 设计原则——审计 Pipe 必须融入 SOP 循环

现有 SOP 8 步循环（01~06+Z+OP）是 Master Agent 的 7x24 监控机制。审计 Pipe 上线后，SOP 必须能监控审计 Pipe 的运行状态。

### 7.2 SOP_04 的升级——从"Master Agent 人工判断"到"审计 Pipe 自动判断 + Master Agent 复核"

**现状**：SOP_04（C 类 AI 判断）是 Master Agent 人工读 proof.md 做 C1-C6 判断——monitor 只抽样标记 `needs_ai_review=True`，判断靠人。

**升级后**：SOP_04 变为"审计 Pipe 自动判断 + Master Agent 复核审计质量"——

| SOP_04 现状 | SOP_04 升级后 |
|---|---|
| 查 `needs_ai_review=True` 的 run | 查 `audit_passed != None` 的 run（已审计） |
| Master Agent 读 proof.md 做 C1-C6 | Master Agent 读审计报告做"审计质量复核" |
| 最多 10 条（抽样） | 最多 10 条（抽样复核） |
| 判断 proof 质量 | 判断审计 AI 的判断质量——审计 AI 判 PASS 的题，proof 真的对吗？审计 AI 判 FAIL 的题，proof 真的错吗？ |

**SOP_04 新增检查项**：
```
C7 audit_quality_pass: 审计 AI 判 PASS 的题，抽查 proof 是否确实正确
C8 audit_quality_fail: 审计 AI 判 FAIL 的题，抽查 proof 是否确实错误（防误判）
C9 cheating_detected_review: 审计 AI 判 FAIL_CHEATING 的题，复查作弊证据是否充分
```

### 7.3 SOP_01 的升级——新增审计 Pipe 健康检查

SOP_01（系统健康检查）新增审计 Pipe 的检查项：

```
A15 audit_queue_stalled: paudit:pending 在减少（15分钟无变化=critical）
A16 audit_completion: p27_proof_audits 在增加（有审计在完成）
A17 audit_failure_rate: 审计失败率<20%（>20%=warning，审计 AI 可能能力不足）
A18 audit_gate_waiting: GATE-AUDIT-* 有无 Y 在等（有则需 Master Agent 介入）
```

### 7.4 SOP_03 的升级——新增审计相关 alert_type

| alert_type | severity | 分类 | 处理方式 |
|---|---|---|---|
| `audit_queue_stalled` | critical | 需判断 | 查审计 launcher 是否在 dequeue |
| `audit_completion_slow` | warning | 需判断 | 审计完成慢，可能需加并发 |
| `audit_failure_rate_high` | warning | 需判断 | 审计 AI 误判率高，检查 AGENTS.md 模板 |
| `cheating_detected` | critical | 数据问题 | FAIL_CHEATING 的题需人工复查 |
| `audit_parse_error` | warning | 需判断 | 审计 AI 无法解析 proof，人工处理 |
| `audit_gate_waiting` | info | 需AI判断 | 门闸在等放行，Master Agent 查看 --pending |

### 7.5 SOP 步骤不变

SOP 循环的 8 步结构不变（01~06+Z+OP），只是各步骤的检查内容扩展了审计相关项。SOP 状态机（`scripts/sop/_state.json`）不需要改。

---

## 8. 工作流

### 8.1 审计触发时机

两种模式：

**模式 A：批量后审计（默认）**
- Pipe 4 续传系统跑完一批后，启动 Pipe 5 审计这批 completed 题
- 命令：`python -m src.proof_audit_collector --batch-id paudit-p27-full`
- 然后：`python -m src.proof_audit_launcher --batch-id paudit-p27-full`

**模式 B：实时审计（未来可选）**
- Pipe 4 每完成一题，自动入审计队列
- 需要在 `finalize_run_completed` 中加一行：`enqueue_proof_audit(run_key)`
- 本方案先实现模式 A，模式 B 作为 future work

### 8.2 完整流程（含门闸）

```
1. proof_audit_collector --batch-id paudit-p27-full
   → 查 p27_continuation_runs 中 status=completed 且 audit_passed=None
   → 为每题创建 p27_proof_audit_runs(prepared)
   → 入 Redis paudit:pending

2. proof_audit_launcher --batch-id paudit-p27-full --concurrency 5
   → 并发 dequeue paudit:pending
   → 为每题准备 work_dir（写 problem_text/answer/proof.txt + AGENTS.md）
   → 【门闸 GATE-AUDIT-LAUNCH】启动 devin cli 审计
   → 检测 ### PROOF AUDIT COMPLETE
   → 写 export + DONE.md
   → 【门闸 GATE-AUDIT-KILL-SESSION】kill 审计 session

3. proof_audit_result_collector --batch-id paudit-p27-full
   → 解析审计 export 中的 XML
   → 提取 audit_status + check_results
   → 写入 p27_proof_audits
   → 根据 audit_status：
     PASS/PASS_WITH_CAVEAT → 【门闸 GATE-AUDIT-FINALIZE-PASS】写 audit_passed=True
     FAIL_* → 【门闸 GATE-AUDIT-FINALIZE-FAIL】写 audit_passed=False + 改 status
   → 更新 p27_continuation_runs（audit_status/audit_passed/audited_at）

4. SOP 循环监控
   → SOP_01 检查审计 Pipe 健康（A15-A18）
   → SOP_03 分诊审计相关 alert
   → SOP_04 复核审计质量（C7-C9）
```

---

## 9. 选题池查询变更

审计系统上线后，选题池查询从：
```aql
FOR r IN p27_continuation_runs
  FILTER r.status == "completed"
  RETURN r
```

改为：
```aql
FOR r IN p27_continuation_runs
  FILTER r.status == "completed"
  FILTER r.audit_passed == true
  RETURN r
```

**过渡期**：未审计的题（audit_passed=None）不进入选题池，但也不标记失败——等审计完成后决定。

---

## 10. 实施计划

### 工作包拆解

| WP | 内容 | 依赖 | 产出 |
|---|---|---|---|
| WP-1 | DB schema 实现 + 文档化 | 无 | proof_audit_db_schema.py + /Users/user/database/AI-Math-Competition-Problem-Solving-System.md |
| WP-2 | 审计 AI 的 AGENTS.md 模板 + 解题 AI AGENTS.md 防作弊约束更新 | 无 | templates/proof_audit_agents_md.md + 更新 templates/continuation_solve_agents_md.md |
| WP-3 | proof_audit_collector | WP-1 | proof_audit_collector.py |
| WP-4 | proof_audit_launcher + 门闸 GATE-AUDIT-LAUNCH / GATE-AUDIT-KILL-SESSION | WP-1, WP-2 | proof_audit_launcher.py + proof_audit_redis_queue.py + @gated 装饰器 |
| WP-5 | proof_audit_result_collector + 门闸 GATE-AUDIT-FINALIZE-PASS / GATE-AUDIT-FINALIZE-FAIL | WP-1 | proof_audit_result_collector.py + @gated 装饰器 |
| WP-6 | config + 端到端入口 + 门闸注册 | WP-1~5 | proof_audit_config.py + run_proof_audit_pipeline.py + --register |
| WP-7 | SOP 集成：SOP_01/03/04 升级 + checks.py 扩展 | WP-6 | 更新 checks.py + SOP_01/03/04 文档 |
| WP-8 | 对 138 题 completed 跑一轮审计 | WP-1~7 | 审计结果 + DB 更新 |
| WP-9 | 文档同步 | WP-8 | SYSTEM_CLOSURE.md + checklist/AUDIT-08.md + architecture.md |

### 优先级

WP-1 → WP-2 → WP-3 → WP-4 → WP-5 → WP-6 → WP-7 → WP-8 → WP-9

### 验证标准

- WP-8 完成后，138 题 completed 都有 audit_status
- 选题池查询只返回 audit_passed=True 的题
- p27_proof_audits 集合有 138 条记录
- 4 个审计门闸在 `p27_step_gates` 中注册，`--list` 可见
- SOP_01 检查输出含 A15-A18 审计健康项
- SOP_04 检查输出含 C7-C9 审计质量复核项
- /Users/user/database/AI-Math-Competition-Problem-Solving-System.md 文档化所有 p27_ 集合

---

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| 审计 AI 本身数学能力不足，误判 | 审计结果保留 proof_text + check_results，SOP_04 复核 |
| 审计 AI 答案比对困难（等价形式） | AGENTS.md 模板中明确"等价形式算 PASS" |
| 138 题审计耗时 | 并发 5，每题约 3 分钟，约 83 分钟完成 |
| 审计 AI 产生 PARSE_ERROR | 创建 alert，SOP_03 人工处理 |
| 审计后改 status 影响已有统计 | 审计只改 audit_passed 字段，不改 status（FAIL_INCOMPLETE 除外） |
| 门闸 hold 阻塞审计主循环 | 和续传系统一样——hold 是调试模式，SOP_01 每轮提醒 Y 在等 |
| 审计 AI 误判作弊（假阳性） | FAIL_CHEATING 创建 alert，SOP_04 C9 复查作弊证据 |

---

## 12. 与现有系统的关系

| 现有机制 | 关系 |
|---|---|
| 9 个续传门闸 | 审计 Pipe 新增 4 个门闸，同一套 @gated 机制，同一 `p27_step_gates` 集合 |
| SOP 8 步循环 | 步骤结构不变，SOP_01/03/04 检查内容扩展审计项 |
| monitor C 类抽样 | 审计 Pipe 上线后，C 类抽样改为"审计结果的抽样复核"——审计 AI 已经审过了，SOP_04 只需复核审计质量 |
| finalize_run_completed 的 proof 入库 | 审计 collector 从 p27_continuation_results 读 proof_text，不需要再读硬盘 |
| 选题池（Pipe 3，已删除） | 选题查询加 audit_passed=True 过滤 |
| SYSTEM_CLOSURE 认知闭包 | §2 架构图 + §4 模块表 + §5 数据产出 + §6 判定框架 + §7 铁律 需更新 |

---

## 变更记录

- v1 · 2026-08-21 · 初始方案：Pipe 5 proof 审计系统设计
- v2 · 2026-08-21 · 新增防作弊机制：解题 AI 与审计 AI 的不对称约束（解题 AI 受防作弊约束+主动声明义务，审计 AI 不受约束但严格审计数学正确性+作弊检测）；新增 E 维度（作弊检测）；新增 FAIL_CHEATING / FAIL_CHEATING_DECLARED 审计结果类型；新增解题 AI AGENTS.md 防作弊约束模板
- v3 · 2026-08-21 · 新增门闸集成（4 个审计门闸 + docstring 检查项）+ SOP 集成（SOP_01 新增 A15-A18 + SOP_03 新增 6 种审计 alert_type + SOP_04 从"人工判断"升级为"审计 Pipe 自动判断 + Master Agent 复核"）；工作包从 8 个扩展到 9 个（新增 WP-7 SOP 集成）
