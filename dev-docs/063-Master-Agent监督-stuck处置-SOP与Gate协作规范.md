# 063 — Master Agent 监督、stuck 处置、SOP 与 Gate 协作规范

> **覆盖 Feature**：SUP-01~08、PROD-03~05、OPS-01~02、REL-05
> **用户裁定**：系统不追求难以可靠实现的完全自动化；Master Agent 是 Supervisor of
> System，可通过现有 SOP 定时介入；关键动作使用现有 Gate，不新增复杂控制机制。
> **实施**：`WP-08`。

---

## 一、人机分工

### 程序负责事实和确定性原语

- ACP 进程/会话是否存在；
- 最后 thought/message/tool/permission/error 时间；
- 是否有 pending tool；
- prompt response、usage、provider error、rate limit、connection error；
- 当前 run/round/role/cwd/key 内部 ID；
- proof、notes、formal、日志是否存在；
- DB/Redis/backend/文件/lease 是否一致；
- 提供“发送消息、结束实例、保存资产、重入队”等受控动作原语。

### Master Agent 负责语义判断

- 无通知是深度思考、网络抖动、模型服务抖动、工具等待还是进程卡死；
- 应继续等待、发送“继续”、结束当前 Round、重启、换 key 还是移交用户；
- 形式化覆盖是否足够；
- 边缘状态如何收场；
- 新故障模式是否需要未来补确定性规则。

---

## 二、`suspected_stuck` 的语义

长时间无有效 ACP 信号只代表需要监督者关注，不是终态。程序应输出证据包，而不是直接
执行 kill 或定时发送“继续”。证据至少包括：

- silent duration；
- last event type/time；
- process alive；
- pending tool/permission；
- provider/backend error；
- prompt 是否已响应；
- 当前 token/运行时长；
- proof/notes 是否有新 mtime；
- 同 key 其他实例是否正常；
- 其他 key/同 provider 是否同时异常；
- 可直接查看的 notification 尾部路径。

字段可以嵌入现有 alert/报表，不必为此建立新数据库系统。

---

## 三、Master Agent 可选动作

### 等待

证据显示进程和 provider 正常、可能在深度思考或工具执行。记录判断，下个 SOP 周期复查。

### 发送“继续”

只在检查 session 最后状态后由 Master Agent 决定，不做自动 heartbeat。发送前说明为什么
不会与仍在生成的响应重叠；动作和理由进入行为流水。

### 安全结束当前 Round

确认适合结束后，通过现有 kill/reclaim Gate：先保存实时通知、笔记、partial proof、形式化
文件和错误证据，再停止实例、释放 lease。题目保持可继续，下一观察者消化本轮现场。

### 基础设施重启/换 key

证据明确指向 backend/key/network 时，可把本轮作为基础设施异常处理，保留资产后重启或换
key。是否沿用绝对 Round 编号/重试计数由 WP-01/08 在测试中明确，不允许覆盖历史。

### 移交用户

涉及批量 provider 故障、key 大面积异常、需要改变容量/并发、或无法安全判断时报告用户。

---

## 四、SOP 接入

优先扩现有 SOP_01 的系统健康输出，不新增一个 SOP 步骤。SOP_01 定时列疑似 stuck；
SOP_04/07 继续处理证明与审计语义。SOP 报表保存：证据、Master 判断、选择动作、Gate
reason、后续复查结果。

SOP 是发现和定时介入载体，Gate 是动作前控制点，两者不互相替代：

```text
程序采集事实 → SOP呈现 → Master判断 → 现有Gate放行 → 程序执行 → flow留痕
```

---

## 五、Gate 复用原则

- 不因 observer、solver、key lease、stuck 新建整套平行 Gate。
- observer/solver 启动应复用或最小扩展现有启动语义 Gate。
- 发送“继续”若被认定为关键语义动作，应在 WP-08 中评估复用现有动作 Gate 或增加一个
  最小语义 Gate；不得顺手把所有 ACP RPC 加 Gate。
- kill/reclaim 继续使用现有 kill Gate，论证依据增加资产刷新和 lease 安全。
- 重入队/写最终状态继续使用现有 Gate。
- 底层计数、写 opencode.json、记录通知不设 Gate。

---

## 六、key/provider 横向证据

一 key 多实例后，汇总可帮助 Master Agent：

- 同 key 一个 stuck、另一个正常：更像单实例/session 问题；
- 同 key 多实例同时异常、其他 key 正常：怀疑 key/账户限流；
- 多 key 同时异常：怀疑 provider、网络或 OpenCode；
- 这只是证据，不硬编码成自动根因裁决器。

Master Agent 可根据证据建议用户调整 key capacity，但系统不自动学习并永久改容量。

---

## 七、最小测试与演练

1. 有 thought 活动：不报 suspected stuck。
2. 无 chunk 但有 pending tool：证据正确，不盲杀。
3. 进程活、长静默：SOP 出现候选，默认不自动动作。
4. Master 选择继续：消息只发一次，reason 落 flow，恢复后候选消失。
5. Master 选择结束 Round：资产刷新、Gate、kill、lease 释放、题目可继续。
6. 同 key/多 key 横向概览正确，不泄漏 secret。
7. Master 未介入时系统保持安全状态，不无限重发消息。
8. 所有动作不新增与 Gate 平行的审批状态。

---

## 八、非目标

- 不实现完美 stuck 根因分类器。
- 不用固定静默秒数直接 kill。
- 不自动周期发送“继续”。
- 不为 Supervisor 新建独立服务、UI 或工作流引擎。
- 不让 Master Agent 代替解题者长期推数学；其职责是监督和处置。
