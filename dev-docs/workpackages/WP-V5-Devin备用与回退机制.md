# WP-V5 — Devin ACP 备用后端接入 + 自动回退机制（默认关）

> **优先级**: 实现系列第五（V4 之后）
> **依赖**: WP-V1~V4、WP-U7（切换规格）、WP-U8
> **预计规模**: 【待 U8 实数化；框架估 150-300 行】
> **性质**: 实现（备用管线接入 + 回退机制，auto-fallback 默认关）
> **⚠️ 框架版**：🔶 槽位由 U8 填实

---

## ★ U8 任务书修订（2026-08-21）

| 槽位 | 填实值 |
|---|---|
| 实现规格 | 048§一全文：response 驱动状态机 / 权限 allow_session 自动响应（string UUID+outcome 嵌套）/ cancel+terminate 门闸映射 / 组装引 U2 Devin 分支 |
| 内嵌实验 | B 路（Devin 组装无损性）+ 截断探针 Devin 半边——V5 验收项之一 |
| 回退机制 | 048§二事件表（auto-fallback 默认关；自动切回任何路径不存在）；健康阈值 V7 校准 |
| **工作量实数** | **~250 行** |
| **启动条件** | V4 完成；B 路解冻（用户裁定） |

---

## 0. 给执行 AI 的第一句话

接上最后一个后端（Devin ACP）并把 U7 设计的切换/回退机制代码化：三后端全部可选、
健康探测、降级 alert、（用户启用后的）自动回退。完成后双管线体系代码层齐备——
只欠 V6 的检查体系适配和 V7 的灰度切换。

## 1. 背景

- 037 §2.1 的 Devin 备用定位；U7 的三态健康模型与量化触发
- "免费服务消失的那天"——备用管线的存在性验证是本包的验收核心（演练 V7 实操，
  本包做机制）

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **049 对本包任务书** | 🔶 权威 |
| 2 | `dev-docs/048`（U7） | 三态模型/触发量化/alert 设计/演练场景（本包实现前两者+alert） |
| 3 | `src/acp/devin_backend.py`（V1）+ V4 的工厂/set-backend 模式 | 接入参照 |
| 4 | `src/monitor_continuation.py` 的 alert 创建 | backend_health alert 的实现参照（alert_type 注册进 SYSTEM_CLOSURE 属 V6 文档，代码先建 alert） |

## 3. 规格（框架）

```
健康探测：launcher 每轮 poll 时（或每 N 轮）对当前+备用后端 health_probe（5s 超时，
  🔶 频率按 048）；三态转换按 048 量化条件
alert：backend_degraded / backend_down（critical）——alert_type 新增（V6 登记清单）
自动回退（默认关，DB batch 的 auto_fallback 字段，set-backend --auto-fallback 开）：
  条件触发（048 量化）时：新题改用备用后端 + alert 记录；**切回永远手动**
  （set-backend——适度依赖边界，U4/U7 已定）
幂等与重试：回退动作本身失败（备用也 down）→ critical alert + 暂停取新题
  （🔶 行为按 048：预期是停批待人，不是硬崩）
```

## 4. 任务分解（框架）

1. Devin ACP 后端接入工厂（V1 实现 + V4 模式——含权限自动响应 🔶 048 决策值）
2. 健康探测循环 + 三态 + alert（monitor 侧还是 launcher 侧？🔶 048 建议——倾向
   launcher poll 内嵌（及时性）+ monitor 周期复核（A 类检查），按 049 定夺）
3. auto_fallback 机制（默认关）+ 触发/记录/暂停语义
4. sim：fake down 场景（V2 剧本注入——fake server 拒绝 initialize）驱动探测→
   down→alert→（开启 auto 后）回退全链
5. 真实验证：手动 set-backend devin_acp 跑 1 题（Devin ACP 灰度）+ 切回
6. py_compile/测试/commit

## 5. 禁止事项

- ❌ 自动切回不存在于任何路径（grep 验证无 set-backend 自动调用）
- ❌ auto_fallback 默认值必须为关（DB 字段初始 false/未设）
- ❌ 双 down 不硬崩（暂停取题+alert——按 🔶 048 行为）
- ❌ 不动默认 backend（V7 的事）

## 6. 验收 checklist

- [ ] 三后端全部可通过 set-backend 切换且各 health_probe 输出
- [ ] sim down 场景全链（探测→down→alert→回退）演示输出
- [ ] Devin ACP 真实灰度 1 题全链数据
- [ ] auto_fallback 默认关（DB 实查）+ 开启后回退演示
- [ ] grep 无自动切回；py_compile/commit

## 7. 完成汇报要求

执行记录：机制 diff、sim 演练输出、Devin 灰度数据、三态转换的实测时间线。

## 8. 审计对照

1. down→回退链路我会用 fake 复演一次
2. auto_fallback 默认值与切回缺失的 grep 证据
3. alert_type 与 048 设计一致（V6 会登记进清单——预留对齐）
