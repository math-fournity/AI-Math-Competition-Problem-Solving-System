# Selfrun 工作流 — ZCode 接替 devin cli 载体

> **背景**：2026-08-16 devin cli 载体失效。devin cli 在本系统中只扮演"无工具、单轮、读 AGENTS.md、输出 XML"的分析/审计 AI 载体；采集、入队、DB 记录、收集、汇总全部是程序代码，不受影响。本工作流用 ZCode 主会话（编排）+ subagent（执行分析/审计）顶替载体角色，**现有组件零改动**。

## 架构

```
主会话（编排者）
   │  1. 从DB拉剩余run清单，分片
   ▼
subagent ×N 并发（分析AI）
   │  读 work_dir/AGENTS.md → 产XML → 写 work_dir/selfrun_output.xml
   ▼
主会话 ingest（src/selfrun_intake.py）
   │  validate（复用collector同款解析函数）
   │  write_export（devin格式 exports/conversation.json）
   │  mark_completed（DB: completed + carrier="zcode-selfrun" + 事件）
   ▼
现有流水线原样运行
   collect-delta → insert analysis_results → aggregator
   audit_collector → subagent审计 → ingest-audit → audit_result_collector
```

## 核心组件：src/selfrun_intake.py

| 命令 | 作用 |
|---|---|
| `validate --kind analysis\|audit --xml-file F` | 用 result_collector/audit_result_collector 的同款解析函数做准入校验，过校验=下游必能解析 |
| `ingest-analysis --exp-id E --xml-file F` | 校验→写export→DB推进completed（end_reason=selfrun_complete, carrier=zcode-selfrun） |
| `ingest-audit --exp-id E --xml-file F` | 同上（Pipe 2 / audit_runs） |
| `collect-delta --batch-id B` | 只收集 completed 且未 results_collected 的 run，追加到 collected_results.json，**不会重收旧结果**（insert_result 是纯 insert，全量重跑 collect_batch 会把 analysis_results 翻倍——这是本命令存在的原因） |

## 关键设计决策

1. **conversation.json 仿 devin 格式**（`steps[].source=="agent"`）——result_collector/audit_result_collector 零改动直接读取。
2. **carrier 标记**：run 的 `carrier.type="zcode-selfrun"` + 事件 `analysis_selfrun_completed`——事后可区分 devin 产出与 selfrun 产出（DB-文件双向可追溯，SOP G2）。
3. **落盘位置**：subagent 产出存 `work_dir/selfrun_output.xml`（D卷，持久）；ingest 后 export 在 `trajectory/<exp_id>/exports/conversation.json` + `selfrun_meta.json`。
4. **subagent 提示词质量要求对齐审计 D1/D2**（explanation ≥100 字符、动作动词/数学术语）——这不是放水，而是把审计模板中已成文的质量标准前置到生产端。

## 验证记录（2026-08-16, audit-selfrun1 / Step 1）

3 题（104KB/136KB/163KB，polymath×2 + deepmath×1）全链路通过：

| 环节 | 结果 |
|---|---|
| 分析判定 | TOKEN_LIMIT×2, DIRECTION_ERROR×1（判定分布与已有1385题一致） |
| validate | 3/3 通过 |
| collect-delta | parsed=3，快照 1400→1403 |
| aggregator | 1388/1403 解析，3条新结果进入维度统计 |
| 独立审计 | PASS×2 + PASS_SELECTABLE×1，audit_results 入库 |

**发现的数据问题**：deepmath_103k_00004613 的 AGENTS.md 中题目与 thinking 张冠李戴（题目=反常积分收敛，thinking=素数计数数论题）——原 data_collector 遗留缺陷。模板规则已覆盖此情况（判 DIRECTION_ERROR）；跑全量时同类样本会自然进入 DIRECTION_ERROR 桶，属已知噪声。

## 验证记录二（2026-08-16, Step 2 · 49题分层抽样 + 5题抽样审计）

49题（77-175KB，四层×四题库来源分层抽样，清单：`output/selfrun_step2_sample.json`）+ Step 1的3题，共52题全链路完成：

| 指标 | 结果 |
|---|---|
| 分析产出 | 49/49 有效（2题因并发上限被拒后补做） |
| 判定分布 | DIRECTION_ERROR 48%（25）、TOKEN_LIMIT 36%（19）、PARTIAL_PROGRESS 15%（8）、CONNECTION_ERROR 0% |
| devin基线（1388题） | DIRECTION_ERROR 60%、TOKEN_LIMIT 15%、CONNECTION_ERROR 10%、PARTIAL_PROGRESS 7% |
| 抽样审计（audit-selfrun2，5题覆盖三种判定） | 5/5 通过（PASS×2 + PASS_SELECTABLE×3） |
| 汇总快照 | 1452总/1437解析（+52） |

**运行参数实测**：
- subagent并发上限3（第4个并发被"user concurrency limit exceeded"拒绝）——每波派3个agent×2题。
- 单subagent（2题/会话）耗时3-6分钟，token消耗0.7M-2.3M/会话（均值约1M，即~0.5M/题）。
- 波次节奏：6题/波（3 agent×2题），49题共8波约40分钟。

**⚠️ 重大数据发现：题文/思维错位污染**。24个DIRECTION_ERROR中至少14个（grep下界；subagent汇报口径约18-21个）的判定依据是"AI的thinking在解一道与题目完全无关的题"——即AGENTS.md中Problem/Standard Solution与AI thinking配对错误，是原data_collector采集期的数据缺陷，集中在deepmath_103k和oda_math_460k两个题库来源。模板规则明确覆盖此情况（判DIRECTION_ERROR），且devin已产出的1388题中大概率存在同类污染（其60%的DIRECTION_ERROR基线可能部分由此构成）。**处置属方法论决策**：继续按模板判（与devin可比）/ 加数据标记 / 修复上游重采——需用户拍板，未擅改。

**TOKEN_LIMIT占比偏高的解释假设**（36% vs devin 15%）：剩余池本身偏向长thinking题（AGENTS.md 77KB+），且错位污染占据了DIRECTION_ERROR桶；subagent判定均有具体证据（句中截断、已到正确答案）。Step 3全量后可做终局对比。

## 跑全量（剩余1611题）的操作模式

1. 从 DB 拉 30c 批次剩余 run（status ∈ queued/pending_retry/失败态，problem_id ∉ 已收集集），按 ~4题/分片 切片（中位 134KB/题 ≈ 33K token，单 subagent 一次 session 安全上限）。
2. 并发派 subagent（建议 8 路），每个：读 AGENTS.md（必须读到 EOF）→ 按 AGENTS.md 内嵌模板判定 → 写 selfrun_output.xml。
3. 主会话批量 validate + ingest。
4. 每 ~100 题跑一次 collect-delta + 抽查。
5. 全量完成后：aggregator 汇总 → audit 新批次审计 → 与 devin 产出的 1517 题做判定分布对比。

## 待办边界

- audit-full1 还剩 227 个审计任务（226 prepared + 1 stale running），AGENTS.md 均 ≤8KB，同样用 ingest-audit 路径收尾。
- Redis 队列在本工作流中不再使用（feeder/launcher/retry 服务不需要启动）；audit Redis pending 里的 226 条目可忽略，以 DB audit_runs 状态为准。
