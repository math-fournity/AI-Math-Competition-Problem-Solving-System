# 052 — 基础设施失败重试 dry-run 报告（WP-L）

> **创建时间**: 2026-08-21
> **执行者**: Claude (ox-alpha, opencode)
> **编号偏差说明**: 任务书指定 039，但该编号已被并行会话《失败题池盘点》占用——改用 052。
> **数据时点**: 2026-08-21 18:17 EDT。p27:failed=30、paudit:failed=1。

---

## 一、dry-run 分类分布

| 队列 | 总数 | infra（可重试类） | model（不重试） | 本次将重试 |
|---|---|---|---|---|
| 续传 p27:failed | 30 | **7** | **23**（全部 failed_stall） | 7 |
| 审计 paudit:failed | 1 | 0 | **1**（max_runtime_exceeded） | 0 |

### 续传 7 个 infra 重试候选明细

| run_key | 原 reason | 分类路径 |
|---|---|---|
| deepmath_103k_00012416 | rate_limited | 直接命中 INFRA |
| deepmath_103k_00012388 / 8643 / 8548 / 8309 / 3188 / 1653 | dead_session ×6 | 直接命中 INFRA |

### legacy 映射生效证明

续传侧 23 条 model 类的 reason 原词是 `stall`（WP-J 改名前的 kill reason）——经
LEGACY_REASON_MAP 映射为 failed_stall 后正确归入 model 不重试 ✅。审计侧唯一条目
`stall_timeout` 映射为 max_runtime_exceeded → model ✅。

## 二、重点审阅项（分类可信度）

1. **model 类 23 条 failed_stall**：均为旧时代"无活动超时被 kill"的产物——它们
   不是输出上限截断（那类会进 truncated→续传），是当时的总时长兜底。归类 model
   合理（重试大概率同样超时）。**但**：其中可能混有"当时若用续传机制本可推进"的题
   ——这属于历史编排缺陷，不是分类错误。
2. **infra 类 7 条中 6 条 dead_session 是 WP-K 之前写入的历史数据**——不排除部分
   实为 ai_gave_up（当时无检测）。实跑重试的风险：个别放弃题会被再试一次（≤1 次，
   有 MAX_RETRIES 兜底），可接受；且重试后新判定会用上 WP-K 检测。
3. **审计侧唯一条目**（595 号）是 WP-G 并发实验的超时产物——model 正确，不重试。

## 三、结论与建议

1. **分类可信**：legacy 映射覆盖了全部历史措辞；model 分布单一（failed_stall）
   无混杂信号；未发现"看似该重试却被归 model"的反例。
2. **建议**：可批准 `--pipe continuation --once` 实跑回收 7 个 infra 失败
   （其中 rate_limited 1 题值得优先看）；audit 侧无对象。
3. **常驻化**：不建议现在启用——当前批次接近收尾（pending 122），等下一大批次
   （或 OpenCode ACP 管线上线后）再评估循环模式的必要性。

## 四、给用户的决策请求

- [ ] 是否批准 `--once` 实跑（回收 7 个 infra 失败，重入 pending 排队尾）？
- [ ] 常驻模式：现在否 / 下一批次再议？
