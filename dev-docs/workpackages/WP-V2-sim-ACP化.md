# WP-V2 — sim ACP 化（fake ACP server 剧本演员 + 发布门禁双后端化）

> **优先级**: 实现系列第二（V1 之后、V3 之前——**门禁前置**，铁律 12）
> **依赖**: WP-V1、WP-U3（sim 评估）、WP-U8（任务书）
> **预计规模**: 【待 U8 实数化；框架估 300-500 行】
> **性质**: 实现（sim 系统）——**ACP 化后所有 launcher 改造的发布门禁都在这**
> **⚠️ 框架版**：🔶 槽位由 U8 填实

---

## 0. 给执行 AI 的第一句话

铁律 12 说改调度逻辑必须过 sim 发布门禁——ACP 改造是最大的调度改动，所以 sim 必须
先能"演" ACP：把 fake_devin（tmux 里的剧本演员）升级出 ACP 形态（stdin/stdout
JSON-RPC 按剧本吐通知），让 V3/V4/V5 的每次改造都有假环境可回归。U3 已评估过方向，
你来实现。

## 1. 背景

- sim 现状（`src/sim/`）：fake_devin.py 剧本演员（SIM_MODE 时替换 devin 命令）+
  run_sim.py 跑 7 剧本 + assert_final.py 断言 + setup/teardown 假环境（017 方案，
  首日抓过 5 bug——门禁有效性已证）
- ACP 化后的门禁需求：launcher（V3/V4/V5 改造后）必须在假 ACP 后端上跑通全剧本，
  **不消耗 API 配额、可注入异常**（rate limit 通知/卡死不吐信号/prompt 不响应——
  这些真实环境难复现的场景正是 sim 的价值）

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **049 的 V2 任务书**（含 U3 sim 评估的落地方案） | 🔶 剧本组织方式/工作量实数 |
| 2 | `src/sim/` 全部代码（fake_devin/run_sim/setup/teardown/assert_final） | 现有剧本格式/断言器输入/隔离旋钮（ARANGO_DB/REDIS_PREFIX/SIM_MODE） |
| 3 | `dev-docs/017-全流程模拟系统设计方案.md` | sim 设计意图（断言哲学：过程断言不只结果断言） |
| 4 | `src/acp/`（V1 产物） | 要 mock 的接口（fake ACP server 对 V1 的 base 接口协议兼容） |
| 5 | OpenCode/Devin skill 的通知格式 | fake server 吐的通知必须**格式同构**（否则测不出真问题） |

## 3. 规格（框架）

```
src/sim/fake_acp_server.py   —— ACP server 演员：读剧本 jsonl（通知序列+时间戳），
                                按 stdio JSON-RPC 吐出；支持剧本指令：
                                {delay: N}卡死 N 秒不吐信号（测 spin 检测）
                                {inject_error: "rate limit..."}（测错误三层）
                                {no_prompt_response: true}（测 OpenCode 静默完成）
src/sim/acp_playbooks/       —— 🔶 剧本集（017 七剧本的 ACP 版语义映射 + 2 个 ACP 特有
                                剧本：spin 卡死/静默完成）
sim 的 SIM_MODE 分派扩展：SIM_MODE=1 + backend 字段 → fake_acp_server（V3/V4 接入点）
assert_final：断言产物从 DONE.md/export 扩展为 组装 conversation.json+通知日志 jsonl
```

## 4. 任务分解（框架）

1. fake_acp_server.py 实现（协议兼容 V1 的 poll/terminate——terminate 后进程退出）
2. 剧本迁移：🔶 按U8定的组织方式（017 剧本语义 → ACP 通知序列）+ 2 个新剧本
3. assert_final 扩展 + setup/teardown 的 🔶 调整（U3 评估结论：tmux 假环境是否保留——
   -p 后端过渡期仍需）
4. 端到端验证：用 V1 的库 + fake server 跑 1 个剧本全流程（start→poll→done→组装→断言）
5. py_compile + 测试 + commit

## 5. 禁止事项

- ❌ fake server 的通知格式不许"简化"（必须同构真实格式——格式差异会漏测真 bug）
- ❌ 不动生产 launcher（本包只做 sim 侧）
- ❌ 剧本指令不做真实 API 调用（纯本地）
- ❌ -p 后端的 sim 能力不删（过渡期双后端都要可测）

## 6. 验收 checklist

- [ ] fake_acp_server.py 能被 V1 库 start/poll/terminate 驱动（协议兼容实测）
- [ ] 剧本 ≥🔶 数量（含 spin 卡死/静默完成两个 ACP 特有剧本）
- [ ] 端到端剧本跑通 + assert_final 断言过
- [ ] -p 后端 sim 回归不受影响（跑 1 个旧剧本确认）
- [ ] py_compile；commit

## 7. 完成汇报要求

执行记录：fake server 指令集、剧本清单、端到端输出、-p 回归证据。

## 8. 审计对照

1. fake 通知与真实 jsonl（U2 数据）的格式 diff（同构性）
2. spin 剧本真的能让 V1 检测触发（演示一次）
3. -p sim 无回归
