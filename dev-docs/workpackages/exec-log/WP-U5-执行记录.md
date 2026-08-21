# WP-U5 执行记录 — OpenCode ACP 管线详细设计

> **执行时间**: 2026-08-21（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（046 报告；实测配额 2/3，余 1 未动用）

---

## 一、做了什么

1. **任务 1（零配额起步）**：U2 c_acp.jsonl 间隔分布——流内 p50=0.07s/p95=0.15s/
   p99=0.24s/max=13.2s；发题→首信号 4.25–10.6s；**末信号→response=0.00s**
   （response 与流末紧耦合——完成检测可走 response 驱动）
2. **任务 1b（零配额）**：session/list 探测——需带对象参数 `{"cwd":...}`（空 dict
   falsy 导致首次 "Invalid params"），返回 {sessionId,cwd,title,updatedAt}
   **无状态字段** → 不可用于完成检测，重定位为崩溃恢复
3. **任务 2（配额 1）**：AGENTS.md 注入标记法实测——BANANA-CONFIRM-7391 在实质
   回答前逐字出现 ✅，全局规范叠加无干扰
4. **任务 3（配额 1）**：ai_gave_up 形态——放弃声明在 agent_message_chunk 文本
   尾部（"### CANNOT COMPLETE"），thought 中亦有；WP-I PATTERNS 跨后端成立；
   rate_limit 三层方案定稿（通知文本/stderr/时序）
5. **046 设计文档**：完成状态机 + 注入映射表 + 错误三层 + trajectory 三层 +
   给 V1/V4 输入清单

## 二、验收 checklist 对照

- [x] 间隔分布统计表（p50/p95/p99/max，两数据集）
- [x] 完成窗口与 spin 窗口协调条件（response 主路径 / 静默兜底仅在其缺席分支 /
      300s spin 独立）
- [x] session/list 实测结果记录（无状态字段→不可用；崩溃恢复价值）
- [x] AGENTS.md 生效行为证据（标记输出）
- [x] ai_give_up 形态实测记录（message_chunk 文本尾部）
- [x] 046 报告 + 给 V1/V4 输入；生产代码零改动

## 三、偏差

- 探针脚本名从计划中的独立文件改为 `scripts/probe_u5_injection.py`（双探针合一，
  --probe agents|giveup）
- 静默窗口建议值 120s（skill 初稿 30s 的保守化）：依据 max 停顿 13.2s 的 ~9 倍余量
