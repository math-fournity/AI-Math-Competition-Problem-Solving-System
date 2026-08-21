# WP-U7 — Devin ACP 备用管线设计 + 双管线切换/回退机制

> **优先级**: 线 2（U2 之后；与 U5/U6 可并行）
> **依赖**: WP-U1、WP-U2
> **预计规模**: 设计文档（048）——Devin 侧多数协议细节已被 035/U1 覆盖，本包增量：
> 备用语义 + 切换机制细化
> **性质**: 设计（文档，零代码）

---

## 0. 给执行 AI 的第一句话

Devin ACP 降为备用管线（037 决策），但备用≠不重要——备用管线的**切换触发/健康检查/
切回策略**决定双管线体系的可用性下限。你要设计 Devin ACP 后端的实现要点（多数协议
知识已有，做整合）+ 切换回退机制的细节（U4 已定架构框架，你做运维级细化），特别
想清楚：OpenRouter 免费≠可靠，"免费服务消失"这一天一定会来，备用管线就是为那天
准备的。

## 1. 背景（为什么）

- 037 §2.2 理由 5：双管线降低单点依赖；§4.2.13 切换回退是调查点
- U4 已定：DB batch 的 backend 字段 + set-backend 命令 + 启动健康检查 + 自动回退
  （默认关）+ 切回留人——你把这套机制细化到可实施（触发条件量化/状态记录/alert
  类型/SOP 检查项）
- Devin ACP 的既有知识资产：035 实测 + U1 复验 + skill 文档（权限响应格式/
  sessionCapabilities 无 close/stopReason 精确完成信号/_cognition.ai 标记）——备用
  管线反而特性更明确（完成检测精确，无 OpenCode 的静默窗口问题）

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **WP-U4 报告 045**（切换机制框架） | 你细化的骨架（不推翻，细化） |
| 2 | **WP-U1 基线**（Devin 侧）+ `/Users/user/skills-devin/devin-acp-protocol.md` | Devin ACP 全部协议细节 |
| 3 | `dev-docs/035` §2.6-2.8（权限/版本/capabilities）+ §二·补实测 | Devin 特有的实现要点 |
| 4 | `monitoring/continuation_control.py` 的 set-concurrency 实现（WP-G 后形态） | set-backend 命令的实现参照（同模式） |
| 5 | `src/monitor_continuation.py` 的 alert 创建模式（create_alert） | 切换事件的 alert 类型设计参照 |
| 6 | `dev-docs/037` §4.2.13 原文 | 用户定义的切换要素（触发/健康检查/回退/配置） |

## 3. 现场事实基线

- Devin ACP：v1 / prompt response 含 stopReason / 权限需手动响应 / 无 close /
  有 _cognition.ai 标记 / glm-5-2（200K/25000 输出上限）
- OpenCode ACP：静默窗口完成检测（U5 参数）/ 权限自动 / close/fork/resume /
  Ox Alpha（1M/131K）
- 现有 -p 后端（PtmuxDevin）作为第三后端在过渡期保留（U3/V3）
- 阈值提醒（同 U4 §3）：两模型输出上限差异 → 阈值参数化决策已由 U4 处理，你引用

## 4. 任务分解

### 任务 1：Devin ACP 后端实现要点（048 上半）

整合既有知识成实现规格：
1. 完成检测：prompt response（stopReason）为主 + 进程退出 + max_runtime 兜底——
   状态机比 OpenCode 简单，写清
2. 权限响应：必须实现（响应格式引 skill——id 是 string UUID、outcome 嵌套结构、
   U1 实测里首次有 bug 后修复的教训）——自动批准策略：对应 --permission-mode
   dangerous 的 allow_once/allow_session 选择（建议 allow_session 减交互，写理由）
3. session 终止：cancel + terminate（无 close）——与 kill_session 门闸语义的映射
4. trajectory 组装：引 U2 的 Devin 分支结论
5. 模型参数：--model glm-5-2（构造参数，非写死并发类常量——它不是并发数，是后端
   配置；仍建议从 DB batch 的配置读，与 backend 字段同记录）

### 任务 2：切换/回退机制细化（048 下半）

```
状态机：每后端三态 healthy / degraded / down
  healthy：启动 probe 通过（initialize+session/new 5s）
  degraded：probe 通过但最近 N 题 M 个失败（失败率>50%——量化）
  down：probe 连续 3 次失败
事件与动作：
  opencode:down 持续 >2 分钟 且 devin:healthy
    → 自动回退动作（若用户启用 auto-fallback）：新题用 devin_acp + alert
    → 默认（未启用）：仅 critical alert"默认后端不可用"，Master Agent 决策
  切回：Master Agent 用 set-backend 手动（运维判断：免费服务恢复的确认不自动化——
    适度依赖边界）
记录：batch 记录的 backend 字段 + backend_health 历史事件（入 p27_monitor_alerts
    或独立集合——建议先 alert，独立集合等需求出现再加，奥卡姆）
SOP 检查项（给 WP-C 的 check_07 联动建议，不在本包改代码）：后端健康概览
  （当前 backend/最近切换事件/两后端健康态）——写成 U8 汇总的输入
```

### 任务 3：故障演练设计（纸面推演，V7 实操）

设计三个演练场景（V7 执行时用）：①kill OpenCode 进程模拟 down ②改错 auth 模拟
认证失败 ③网络断开模拟连接失败——每场景的预期检测时间/告警/切换行为。

### 任务 4：报告 `dev-docs/048-Devin备用管线与切换回退机制设计.md` + commit

## 5. 禁止事项

- ❌ 自动切回不做（U4 已定边界——本包细化时不得突破）
- ❌ 不重复 U4 的架构设计（引用；本包是 Devin 侧规格+运维机制）
- ❌ 健康状态不建独立 DB 集合（先 alert 复用——需求出现再加）
- ❌ 不写代码

## 6. 验收 checklist

- [ ] Devin 后端实现规格 5 点齐全（完成状态机/权限响应细节含 U1 教训/终止映射/
      组装引用/模型配置来源）
- [ ] 三态健康模型 + 量化触发条件（N/M 具体数）
- [ ] 事件-动作表（含 auto-fallback 默认关的说明）
- [ ] 三个演练场景设计（预期行为可验证）
- [ ] 048 报告；零代码

## 7. 完成汇报要求

执行记录：设计摘要、与 U4 框架的差异点（若有细化中的修正）、给 U8/V5/V7 的输入。

## 8. 审计对照

1. 量化触发条件的数有依据（或明确标注"初始值待 V7 演练校准"——不许无标注拍脑袋）
2. 自动切回确实不存在于任何路径
3. Devin 权限细节与 skill + U1 实测一致（outcome 嵌套结构等）
