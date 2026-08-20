# SOP检查报表 — step_06 报告+WORKLOG+Self-check

> **填写说明**：本模板由 `scripts/sop/run.py` 自动复制到D盘报表目录。AI加载后逐项检查并填写，填写完用edit写回同一文件。
>
> **打勾规则**：`[x]` 通过 · `[!]` 有问题 · `[ ]` 待检查 · `[-]` 不适用
>
> **本步骤核心**：对自己本轮的工作做17项self-check，确保运行正确、不引入新问题。

---

## 系统快照摘要

| 指标 | 值 |
|---|---|
| 总run数 | （从snapshot.json读取） |
| COMPLETED | （从snapshot.json读取） |
| 完成率 | （从snapshot.json读取） |

---

## 检查项清单

### 一、自动化检查项

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| W1 | WORKLOG.md状态 | 读check_output.txt中"WORKLOG.md 状态"。确认WORKLOG存在且在续写 | [ ] | |

### 二、Self-check S1-S17

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| S1 | export完整性 | 检查自己的conversation.json是否存在且>1KB | [ ] | |
| S2 | DONE.md写入 | 退出前确认echo命令正确 | [ ] | |
| S3 | REPORT完整性 | 检查本轮各step的report.md是否都填写了——包含检查/判断/修复/未修复四部分 | [ ] | |
| S4 | session注册 | 检查自己session在p27_sessions中 | [ ] | |
| S5 | py_compile通过 | 修复代码后运行py_compile无语法错误 | [ ] | |
| S6 | git commit成功 | 修复后git add+commit成功 | [ ] | |
| S7 | 未修改第二级架构级规范 | `git diff --name-only`不包含AGENTS.md/.devin/rules/*.md/MonitorPipe.md/AnalysisSystemDesign.md §5§6 | [ ] | |
| S8 | git add规范 | `git diff --cached --name-only`只add具体路径，没有git add -A/. /-u | [ ] | |
| S9 | 只修本轮发现的问题 | 回顾修复操作——无重构/改架构/顺便修其他问题 | [ ] | |
| S10 | 未spawn subagent | 回顾工具调用——无run_subagent调用（除非明确需要） | [ ] | |
| S11 | 未push代码 | 回顾git操作——无git push | [ ] | |
| S12 | C类判断有依据 | 回顾C类判断——每个判断都有读了proof.md/HANDOVER.md的记录 | [ ] | |
| S13 | 未陷入重复修复 | 读最近3轮的report.md——同一问题没有连续3轮修 | [ ] | |
| S14 | 同一alert未反复出现 | 查DB中同一alert_type的创建历史——同一alert_type没有在最近5轮中反复创建 | [ ] | |
| S15 | 第一级文档同步 | 改了代码就改了对应文档（同一commit中）——git diff包含对应文档修改 | [ ] | |
| S16 | 第二级规范建议记录 | 涉及第二级规范需更新时——在report.md中记录"建议同步更新X" | [ ] | |
| S17 | 同步清单完整性 | 对照第一级文档清单——该改的都改了 | [ ] | |
| S18 | sim发布门禁 | 改了调度逻辑后跑了run_sim solve3+chaos_016且全绿。只改文档/配置标[-] | [ ] | |
| S19 | 行为流水必查 | 每轮SOP_01查了observability --stats，churn_suspects为空 | [ ] | |
| S20 | 落盘论证 | Gate放行附了--reason；不放行在report门闸记录区填了原因 | [ ] | |
| S21 | 成果双写 | completed的run的proof入库了continuation_results（双写） | [ ] | |
| S22 | step_gate Y通道 | checks.py每轮查了Y通道；有Y时按闭包核对后放行/hold | [ ] | |

---

## WORKLOG续写

> 在 WORKLOG.md 中续写本轮工作记录。格式：
> ```
> ## 第{cycle}轮 · {timestamp}
> ### 检查结果摘要
> ### 修复操作
> ### 未修复问题
> ### 下一轮建议
> ```

（确认WORKLOG已续写）

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
