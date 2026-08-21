# 048 — Devin ACP 备用管线与切换回退机制设计（WP-U7）

> **创建时间**: 2026-08-21
> **执行者**: Claude (ox-alpha, opencode)
> **性质**: 设计文档，零代码。引用 045 架构不重复；本篇 = Devin 侧实现规格 +
> 运维级切换机制细化 + 故障演练设计。
> **定位声明**: 按用户裁定 OpenCode 优先，本包为纯设计（无 devin 实验）；
> B 路对比与截断探针的 Devin 半边随解冻补做（见 §一.6）。

---

## 一、Devin ACP 后端实现规格（任务 1）

### 1.1 完成检测状态机

```
session/prompt 已发送
  ├─ 收到 prompt response {stopReason, usage}   ← 主信号（v1 协议保证返回）
  │    ├─ stopReason=end_turn/max_tokens/...    → done（成败交组装后结构检查——
  │    │                                          end_turn≠解出，同 043 教训）
  │    └─ 其他值                                 → done + finish_reason 留痕
  ├─ 进程退出且无 response                       → failed(proc_dead)
  └─ max_runtime 超时                            → cancel → failed(timeout)
```

比 OpenCode 简单：**response 必然返回是 v1 合同**（U1 复验两次：end_turn 即达），
无静默窗口参数位。done_silence_seconds = None。

### 1.2 权限响应（必须实现的细节）

```jsonc
// agent→client 请求（id 是 string UUID——不是 number！U1 首测 bug 教训）
← {"jsonrpc":"2.0","id":"<uuid>","method":"session/request_permission",
   "params":{"sessionId":"...","toolCallId":"...","options":[
     {"kind":"allow_once","optionId":"..."},{"kind":"allow_session","optionId":"..."},...]}}
// client→agent 响应：outcome 是嵌套结构（不是扁平 "allow"）
→ {"jsonrpc":"2.0","id":"<同uuid>","result":{"outcome":{"outcome":"selected",
                                          "optionId":"<所选>"}}}
```

**自动批准策略裁定：选 `allow_session`**（对应 -p 的 dangerous 语义）——理由：
解题会话工具调用频次高，allow_once 会产生逐次往返延迟；allow_session 一次授权
整会话有效，语义上等价于"本会话全信任"，与生产 -p 模式行为对齐。拒绝类选项
（reject_once）仅 Master Agent 手动模式使用。

### 1.3 session 终止与门闸映射

- 正常收尾：`session/cancel`（notification）→ `proc.terminate()` → 宽限 5s → kill()
- GATE-KILL-SESSION 语义映射：resource 名保持 "process"（或沿用 tmux 兼容名），
  docstring 的检查项改为"cancel 已发/response 已到/组装产物已落盘"
- 无 close 能力（sessionCapabilities 无 close，035 实测）——session 记录靠
  `session/list` 对账（Devin 有 list）

### 1.4 trajectory 组装

引 U2 的 Devin 分支结论（**待 B 路解冻后实证**）：通知流含
agent_thought_chunk/message_chunk/tool_call(+update)，组装器与 OpenCode 共用
（assemble_acp 同款）；comp 从 prompt response 的 usage.outputTokens 取。
风险位：Devin 侧组装无损性未验证——V5 实现前必须补 B 路（标注为 V5 内嵌实验）。

### 1.5 模型与强度

- `--model glm-5-2` 为构造参数，从 DB batch 读（与 backend 字段同记录）
- 推理强度：devin CLI/acp 无开关（2026-08-21 --help 全量核查，工具事实）；
  BackendTask.reasoning_effort 在 devin 后端为 None 并记 debug 日志
- 升级条款：devin 未来版本提供强度参数时，按
  ~/.devin/rules/explicit-model-and-effort.md 改为必须显式设置

## 二、切换/回退机制细化（任务 2）

### 2.1 三态健康模型（量化触发条件）

| 态 | 判定 | 数据源 |
|---|---|---|
| **healthy** | 启动 probe 通过（initialize+session/new ≤5s） | health_probe() |
| **degraded** | probe 通过 但 最近 10 题中失败 ≥6（失败率>50%，滑动窗口） | launcher 判定结果计数 |
| **down** | probe 连续 3 次失败（间隔 30s） | probe 循环 |

数值标注：10/6/3/30s 均为初始值（依据：probe 成本低可密测；任务级失败率窗口取
"够区分偶发与系统性"的量级）——**V7 故障演练时校准**，校准前不视为定案。

### 2.2 事件-动作表

| 事件 | auto-fallback=OFF（默认） | auto-fallback=ON（用户显式开启） |
|---|---|---|
| opencode:down 且 devin:healthy | critical alert `default_backend_down`，新任务**暂停入队**等 Master Agent | 新任务自动切 devin_acp + warning alert `backend_fallback_triggered` |
| opencode:degraded | warning alert `backend_degraded` | 不切（degraded 仍可用），仅告警 |
| devin:down | warning alert `backup_backend_down`（默认管线不受影响） | 同左 |
| 双 down | critical alert `all_backends_down`，暂停入队 | 同左 |
| 切回 opencode | **仅 Master Agent 手动 set-backend**（免费服务恢复确认不自动化） | 同左（自动切回不存在于任何路径） |

### 2.3 记录与可见性

- 状态变化写 `log_event` + 关键事件创建 alert（复用 p27_monitor_alerts，
  **不建独立集合**——奥卡姆，需求出现再加）
- batch 记录的 backend 字段即当前生效后端唯一事实源
- 给 WP-C/U8 的 SOP_07 检查项建议：后端健康概览（当前 backend / 两后端健康态 /
  最近 fallback 事件 / probe 最后时间戳）

## 三、故障演练设计（任务 3，V7 执行）

| # | 场景 | 注入方式 | 预期检测时间 | 预期动作 |
|---|---|---|---|---|
| D1 | OpenCode 进程死亡 | kill opencode acp 子进程 | 下轮 poll（≤15s）发现 proc 退出 → 任务判 failed → probe 连败 3 次（~90s+间隔）→ down | OFF: critical alert+暂停；ON: 切 devin_acp 重试该题 |
| D2 | 认证失效 | 改坏 auth.json 中 openrouter key | start 时 set_config 后首 prompt 报错（≤30s）或 probe 失败 | 同 D1 路径；detail 含认证错误特征 |
| D3 | 网络断开 | 断网（或代理指向黑洞端口） | 首 chunk 迟迟不来 → spin 检测 300s 触发 alert；response 超时 → failed(timeout) | 同 D1；注意 spin alert 先于 down 判定（两层独立） |

每场景验证点：alert 类型正确 / 切换只影响新任务 / running 任务不被误杀 /
切回需手动。

## 四、给 U8/V5/V7 的输入

1. U8：§2.2 事件表进 049 决策点清单（auto-fallback 是否启用属用户拍板）
2. V5：§一实现规格全文（权限细节/终止映射/模型来源）；内嵌实验=B 路组装无损性
3. V7：§三演练脚本化清单（三场景+验证点）；健康阈值校准义务

## 五、验收对照

- [x] Devin 后端实现规格 5 点齐全（状态机/权限含 U1 教训/终止映射/组装引用/
      模型配置来源+强度工具事实）
- [x] 三态健康模型 + 量化触发（10/6/3/30s 标注"待 V7 校准"）
- [x] 事件-动作表（auto-fallback 默认关；自动切回不存在）
- [x] 三个演练场景设计（检测时间/告警/切换行为可验证）
- [x] 048 报告；零代码
