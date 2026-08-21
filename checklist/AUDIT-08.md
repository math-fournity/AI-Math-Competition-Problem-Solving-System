# AUDIT-08: proof.md 数学正确性审计（Pipe 5）

> **门类**: AUDIT · 系统审计
> **状态**: [x] 已实现（dev-docs/029，WP-1~9）
> **来源**: dev-docs/029-Pipe5-proof审计系统设计方案
> **所属章节**: §AUDIT · 系统审计

## 需求描述

对续传系统（Pipe 4）产出的 proof.md 进行独立审计——验证数学正确性、推理完整性、可验证性、作弊检测。审计通过=进入选题池；审计失败=排除或重做。

## 审计维度（9项）

| 维度 | 项 | 检查什么 |
|---|---|---|
| A 答案正确性 | A1 | boxed 答案与标准答案一致 |
| B 推理正确性 | B1 | 每步数学正确 |
| B 推理正确性 | B2 | 无幻觉（不引用不存在的定理/编造公式） |
| C 证明完整性 | C1 | 完整非截断 |
| C 证明完整性 | C2 | 覆盖所有要求 |
| D 可验证性 | D1 | 不依赖"显然""易得" |
| D 可验证性 | D2 | 无思维跳跃 |
| E 作弊检测 | E1 | 声明检查（有声明查属实，无声明查痕迹） |
| E 作弊检测 | E2 | 推理链/trajectory 检查 |

## 审计结果类型（9种）

PASS / PASS_WITH_CAVEAT / FAIL_WRONG_ANSWER / FAIL_HALLUCINATION / FAIL_INCOMPLETE / FAIL_LOGIC_ERROR / FAIL_CHEATING / FAIL_CHEATING_DECLARED / PARSE_ERROR

## 防作弊机制

- **解题 AI**：可用工具（Python/Lean/计算器）和网络搜索，但题目必须靠 AI 自己的数学推理能力解决。搜到/查到题目解答相关内容须在 proof.md 开头主动声明"作弊风险声明"。
- **审计 AI**：不受防作弊约束（可自由搜索查资料），严格审计解题 AI 的数学正确性+作弊检测。

## 门闸（4个）

- GATE-AUDIT-LAUNCH（启动审计 devin cli）
- GATE-AUDIT-KILL-SESSION（kill 审计 session）
- GATE-AUDIT-FINALIZE-PASS（写 audit_passed=True）
- GATE-AUDIT-FINALIZE-FAIL（写 audit_passed=False + 改 status）

## SOP 集成

- SOP_01: A15-A18 审计 Pipe 健康检查
- SOP_03: 6 种审计 alert_type 分诊
- SOP_04: C7-C9 审计质量复核（抽查审计 AI 的判断质量）

## 验证方法

- 142 题 completed 跑一轮审计，检查 audit_status 分布
- 选题池查询只返回 audit_passed=True 的题
- p27_proof_audits 集合有审计结果记录
- 4 个审计门闸在 p27_step_gates 中注册

## 关联文件

- `checklist/README.md`（需求点全集）
- `dev-docs/029-Pipe5-proof审计系统设计方案.md`（完整方案）
- `src/proof_audit_*.py`（实现代码）
- `templates/proof_audit_agents_md.md`（审计 AI prompt 模板）
- `/Users/user/database/AI-Math-Competition-Problem-Solving-System.md`（DB schema 文档）
