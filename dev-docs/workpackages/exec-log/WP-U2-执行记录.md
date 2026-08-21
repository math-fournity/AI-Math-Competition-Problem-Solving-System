# WP-U2 执行记录 — 内容完整性三路对比

> **执行时间**: 2026-08-21 17:55–22:30（EDT，含并行等待）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（B 路按用户裁定推迟；C 路自洽闭环给出强结论）

---

## 一、做了什么

1. **选题**：deepmath_103k_00000130（泛函分析注入张量积题，glm-5-2 历史 rc=64858
   字符）——从 problem_list.json 的 seed_export 提取纯题目（925 字符，清洗 JSON
   转义与脚手架）
2. **实验脚本**：`scripts/test_wp_u2_content_fidelity.py`（四模式：p_export /
   devin_acp / opencode_acp / analyze；C 路内建铁律 15 前置断言）
3. **执行**（全部 tmux 内跑）：A 路 468s 完成（export 211KB）；C 路 963s 完成
   （12,062 thought_chunks）；B 路**推迟**（用户裁定 OpenCode 优先、Devin 推后）
4. **分析**：组装器对照原生 export——**95,884 = 95,884 字节级一致，零损失**
5. 报告 `dev-docs/043`（含分叉判定、截断信号结论、给 V1/U5 的输入）

## 二、核心发现（详见 043）

1. **OpenCode 组装无损**：通知流拼接 = 原生 export，内容级复验通过 →【完整】分支，
   V1 组装器方案成立
2. **end_turn 掩盖截断**：ox-alpha 烧尽 32,000 output tokens 零正文仍报 end_turn
   ——协议原生截断信号在 OpenCode 侧不可靠，结构检测（rc/msg/tc）是必要判据
3. **有效输出上限修正**：实测单轮 outputTokens=32,000 ≠ 模型卡声称的 131,072
   ——038 §三.三阈值公式的"上限"必须用实测值校准，否则漏判
4. **export 兜底须加固**：首次调用曾产出截断 JSON（exit=0 但未闭合），重跑完整
   ——V1 必须做 JSON 校验+重试
5. **response 会返回**（第二次实证）但 end_turn ≠ 解出——完成检测以 response 为
   结束主信号、组装后 msg==0 结构检查为成败分界

## 三、验收 checklist 对照

- [x] 三路原始数据落盘（a_export.json / c_acp.jsonl；b_acp 推迟）+ 脚本存在
- [x] 对比表完整（043 §一）
- [x] C 路完整性有数字（100%）；分支判定明确（完整分支）
- [x] is_truncated 字段需求对组装产物试跑记录（rc/msg/tc 全命中；comp 从 response 取）
- [x] **C 路原生 export 对照完成**（含首次截断的可靠性发现）
- [x] 截断信号探测：由主实验天然覆盖（真实截断事件），+2 配额未动用
- [x] 043 含"给 V1/V4/U5 的输入"小节
- [x] 生产代码零改动；commit 只含脚本+报告

## 四、偏差与遗留

1. B 路 + 任务 6 Devin 半边：随 Devin 优先级解冻后补做（配额届时另计）
2. ox-alpha 实际生效上限 32000 的成因待查（模型卡 vs OpenRouter 配置）——U6 模型
   能力评估时一并确认
3. 本题两模型均零正文——题目本身超出现有模型能力边界，不影响"传输完整性"结论，
   但解题能力评估属 U6 范围

## 五、认知闭包与 checklist 影响分析

```
=== 认知闭包与 checklist 影响分析 ===
认知闭包（SYSTEM_CLOSURE.md）：
  - [暂不更新] U 系列调查阶段不动生产文档；V1 落地时更新 §5 数据产出
    （ACP trajectory 来源三层 + usage 取数路径）
checklist/：
  - [暂不更新] SOP_07 设计（WP-C）时会引入 ACP 信号停滞检查——引用本报告的
    chunk 流形态数据即可
```
