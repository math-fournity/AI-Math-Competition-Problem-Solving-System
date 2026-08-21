# 038 — 续传不可替代性：output 上限与 context 上限是独立问题

> **创建时间**: 2026-08-21
> **性质**: 设计约束澄清——纠正"1M context 消除续传需求"的潜在误解
> **触发**: 用户在审阅 037 双管线策略后指出——Ox Alpha 的 1M context
> 不能替代续传逻辑，因为单次思考输出仍可能超出 output 上限
> **关联**: 037（双 ACP 管线策略）→ 本文（设计约束补充）→ WP-U4（双管线架构设计）
> **不触碰**: 037 及工作包文档（另有 AI 在执行，本文独立存在）

---

## 一、核心区分：两个上限解决不同问题

| | Ox Alpha | glm-5-2 | 解决什么问题 |
|---|---|---|---|
| **context（输入上限）** | 1,048,576 | 200,000 | AI 单次能"读进"多少——历史轮次、题目、之前的推理 |
| **output（单次输出上限）** | 131,072 | 25,000 | AI 单次能"写出"多少——一轮思考的完整输出 |

**续传系统解决的是 output 上限问题，不是 context 问题。**

具体场景：一个复杂数学证明，AI 的单轮思考输出撞到 output 上限被截断——
`is_truncated()` 检测到后，把已完成的部分作为上下文，启动新一轮接力继续写。

1M context 让续传**更顺畅**（历史轮次全装得下，不需要压缩 HANDOVER），
但**不消除**对续传的需求。只要存在"单次思考输出 > output 上限"的可能，
续传就不可替代。

---

## 二、为什么 1M context 不能替代续传

### 2.1 续传的本质是"接力"，不是"装下更多历史"

续传系统的核心机制（`continuation_launcher.py`）：

1. AI 单轮思考输出撞到 output 上限 → `is_truncated()` 检测到（comp ≥ 阈值 + msg=0）
2. 把已完成的部分作为新一轮的上下文（HANDOVER.md）
3. 启动新一轮 devin cli 接力继续写

这个机制解决的是"**单次写不完**"——无论 context 多大，单次 output 上限
是模型推理引擎的硬约束，不是"读不下"的问题。

### 2.2 Ox Alpha 的 131K output 降低了续传触发频率，但不消除它

- glm-5-2：output 上限 25,000，复杂数学证明单轮思考经常撞顶（036 实测
  39 处 comp 恒等于 25000）
- Ox Alpha：output 上限 131,072，是 glm-5-2 的 5 倍——大部分证明单轮能写完

但**复杂数学证明的单轮思考仍可能超 131K**：
- 长证明的完整推理链（含探索性尝试、失败路径、最终正确路径）
- AI 在 thinking 阶段的完整 reasoning_content（glm-5-2 已观测到 rc=70632
  字符的案例，见 036 §三.3——这只是 25K output 下的，131K output 下
  thinking 会更长）
- 多步证明 + 多次工具调用 + 中间结果记录

**结论**：Ox Alpha 让续传从"频繁触发"变成"偶尔触发"，但触发场景仍然存在，
续传逻辑必须保留。

### 2.3 反例：什么时候续传真的可以不要

只有当 **output 上限 ≥ 任何单轮思考的最大可能输出** 时，续传才可消除。
当前没有任何模型保证这一点——数学证明的推理深度没有理论上界。
即使未来出现"无限 output"的模型，也要验证"无限"是真的无限还是只是
"很大但有上限"。

---

## 三、对 `is_truncated()` 阈值的影响

### 3.1 当前实现（针对 glm-5-2）

`continuation_config.py:82`：
```python
TRUNC_COMP_TOKENS_MIN = 24000
```

`continuation_launcher.py:229-254` `is_truncated()`：
```python
rc > 1000 and msg == 0 and tc == 0 and comp >= TRUNC_COMP_TOKENS_MIN
```

036 实测确认：glm-5-2 的 output 硬上限 = 25000，阈值 24000 能覆盖
（39 处 comp 恒等于 25000，无一例外）。

### 3.2 换到 Ox Alpha 后的问题

Ox Alpha 的 output 上限是 131,072。如果继续用 24000 阈值：
- comp = 50000（远超 24000）但 < 131072 → 会被判 truncated → 误触发续传
- 实际上 AI 还没撞顶，只是输出比较长

**阈值必须适配后端的 output 上限**。合理设定：阈值 = output 上限 × 0.96
（留 4% 余量，对应 glm-5-2 的 24000/25000 = 0.96）：
- glm-5-2 后端：阈值 = 25000 × 0.96 = 24000（不变）
- Ox Alpha 后端：阈值 = 131072 × 0.96 ≈ 125829

### 3.3 阈值不能是全局常量——必须后端化

不同后端的 output 上限不同：
- glm-5-2：25,000
- Ox Alpha：131,072
- 未来其他后端：未知

`TRUNC_COMP_TOKENS_MIN` 不能继续作为全局常量写死在 `continuation_config.py`。
它应该从**后端配置**读取——每个后端声明自己的 output 上限和截断阈值。

这符合 037 的设计立场"执行后端抽象——launcher 业务逻辑不动"：
- **业务逻辑不动**：`is_truncated()` 的判定逻辑（comp ≥ 阈值 + msg=0 + ...）
  不变，续传接力机制不变
- **参数后端化**：阈值从后端配置读，不同后端传不同值

也符合工作包总控铁律 9 扩展："静默窗口/模型名/backend 同样从 DB/配置读，
不写死"。

---

## 四、对 WP-U/V 系列的具体影响（供执行 AI 参考，不修改其文档）

本文不修改工作包文档（另有 AI 在执行）。以下是对执行 AI 的提示，
执行 AI 读到本文后应自行判断是否纳入其工作范围：

### 4.1 WP-U4（双管线架构设计）

后端抽象层需要包含以下后端参数（不只 model 名）：

| 参数 | glm-5-2 后端 | Ox Alpha 后端 | 用途 |
|---|---|---|---|
| `model` | `glm-5-2` | `openrouter/stealth/ox-alpha` | 启动 AI |
| `output_limit` | 25000 | 131072 | 后端声明自己的 output 上限 |
| `trunc_comp_threshold` | 24000 | ~125829 | `is_truncated()` 的 comp 阈值 |
| `context_limit` | 200000 | 1048576 | HANDOVER 压缩策略的参考 |

`is_truncated()` 改为从当前后端读 `trunc_comp_threshold`，不读全局常量。

### 4.2 WP-U2（内容完整性三路对比）

除了对比 reasoning_content 完整性（036 §三.3 已要求），还应对比：
- **截断时的 comp 值**——确认 Ox Alpha 撞 output 上限时 comp 是否恒等于
  131072（类似 glm-5-2 恒等于 25000）
- **截断时的 msg/rc/tc 状态**——确认 `is_truncated()` 的其他条件
  （msg=0, rc>1000, tc=0）在 Ox Alpha 下是否同样成立

如果 Ox Alpha 的截断行为与 glm-5-2 不一致（比如截断时 msg>0），
`is_truncated()` 的判定逻辑本身也需要后端化，不只是阈值。

### 4.3 WP-V3（后端抽象重构）

`is_truncated()` 的阈值参数化是 V3 的具体改动点之一：
- 当前：`comp >= TRUNC_COMP_TOKENS_MIN`（全局常量）
- 改后：`comp >= backend.trunc_comp_threshold`（从后端配置读）

业务逻辑（截断 → 重入队续传 → HANDOVER 接力）完全不动。

---

## 五、设计立场重申

037 的三条设计立场中，"判定链复用"在这里有具体体现：

> **判定链复用**——ACP 后端必须产出 ATIF 同构 conversation.json 喂原生
> is_truncated/is_completed（U2 实验先行，V1 组装器落地）——不为 ACP 重写判定

续传判定链（`is_truncated` → 重入队 → HANDOVER 接力）是原生判定的核心组成。
换后端不改判定链，只改判定参数（阈值后端化）。这正是"判定链复用"的
本意——不为 ACP/Ox Alpha 重写续传逻辑，只让现有逻辑读对参数。

---

## 六、认知闭包与 checklist 影响分析

```
=== 认知闭包与 checklist 影响分析 ===
认知闭包（SYSTEM_CLOSURE.md）：
  - [暂不更新] 本文是设计约束澄清，不改变现有系统行为——续传逻辑本就存在，
    本文只是明确"换后端后续传仍需保留 + 阈值需后端化"。等 WP-U4/V3 落地后
    再更新 §2 架构（后端抽象层）和 §5 配置参数（阈值后端化）
checklist/：
  - [暂不更新] 原因：本文是设计约束记录，不新增检查需求点。等 V 系列实现
    后端化阈值时，再考虑加"阈值与后端 output 上限一致性"检查项
```

---

## 七、结论

1. **续传不可替代**——output 上限与 context 上限是独立问题，1M context
   解决的是"读不下"，续传解决的是"写不完"。只要单轮思考可能超 output 上限，
   续传就必须保留。

2. **Ox Alpha 降低续传频率但不消除续传**——131K output 是 glm-5-2 的 5 倍，
   大部分证明单轮能写完，但复杂证明的单轮思考仍可能超 131K。

3. **`is_truncated()` 阈值必须后端化**——不同后端的 output 上限不同，
   阈值不能继续作为全局常量写死。这是 037"执行后端抽象"立场的具体落地点。

4. ~~不修改工作包文档~~（初版立场；**2026-08-21 用户授权后已改变**——本文 §八/§九
   的发现经用户确认需要落地，相关工作包文档已同步更新，见 §十清单）

---

## 八、2026-08-21 补充实测：OpenCode 原生 export 机制（用户提问触发的调查）

> 本节及以后由工作包执行 AI（ox-alpha）在执行线 1 期间应用户要求调查补充。
> 初版 §三.三 的"阈值后端化"立场在本节深化为"检测信号分层设计"（§九）。

### 8.1 实测结论（本机 v1.18.20，官方文档交叉确认）

初版调研（035/037 时期）认为"OpenCode ACP 没有直接的 trajectory 导出功能"——
**这个说法是错的**：

1. **官方 export 命令存在**：`opencode export [sessionID]`（带 `--sanitize` 脱敏）、
   `opencode import`、`opencode session list/delete`——都是 opencode.ai/docs/cli/
   的正式命令
2. **存储是全局 SQLite**：`~/.local/share/opencode/opencode.db`（本机 876MB），表含
   `session`/`message`/`part` 等；历史上曾是 JSON 文件存储后迁移。`storage/` 目录只有
   辅助元数据
3. **★ ACP 创建的 session 与 TUI/run 在存储层完全同构**——ACP 只是前端，落盘走同一
   条路。实测：037 调研时的 ACP 测试 session（"Calculating 1+1"，模型
   stealth/ox-alpha）用 `opencode export ses_fdb78f223ffeOl1e57eWRaJpYI` 成功导出完整
   内容
4. **导出格式比 devin conversation.json 更丰富**：每条 assistant 消息含
   `parts`（`reasoning` 思考实文 / `text` / `tool` / `step-finish`）、逐消息 token 计数、
   `step-finish.reason`（实测见 stop/tool-calls/unknown）+ 细粒度 tokens（reasoning
   单列）——结构上天然覆盖 devin export 的 rc/msg/tc/comp 四件套

### 8.2 对比逆转：trajectory 导出维度 OpenCode 反超 Devin

| | Devin | OpenCode |
|---|---|---|
| `-p` 模式导出 | ✅ `--export` | （run 模式无此需求表述） |
| **ACP 模式导出** | ❌ 无——只能通知流自行组装 | ✅ 原生 export，进程死后仍可从 SQLite 捞回 |

含义：OpenCode 管线的 trajectory 兜底不依赖"纯组装"——即使 launcher 崩溃没存下
通知流，事后仍能从它自己的库里捞回完整轨迹（含 thinking）。Devin ACP 无此能力。

### 8.3 已同步的知识资产

以上事实已更新进两份全局 skill（commit skills-devin `17284c5`、config 大仓 `545ef4f`）：
`skills-devin/opencode-acp-protocol.md` §九重写、`skills-devin/devin-acp-protocol.md`
十·补对比表加行、`.config/opencode/skills/opencode-acp-protocol/` 的 SKILL.md +
full-sop.md 同步。

---

## 九、检测信号分层设计（对 §三 的深化——用户方案与工作包设计的调和）

### 9.1 问题的由来

用户指出：`TRUNC_COMP_TOKENS_MIN` 这类数值阈值本质是 `-p` 模式信息黑罩下的
**验尸启发式**（运行期零信号，只能死后解剖 conversation.json 猜死因）。未来 ACP
管线的截断检测应该**通过协议动态感知**，而不是靠数值阈值猜。这个直觉是对的，且
有协议依据：ACP v1 的 `session/prompt` response 带 `stopReason` 字段（035 实测正常
结束返回 `end_turn`）；OpenCode 的 `step-finish.reason` 是同类结构化信号。

### 9.2 分层裁定（主信号 / 兜底 / 下游统一）

| 层 | 机制 | 适用 |
|---|---|---|
| **第一层（主信号）** | 协议原生信号：Devin `stopReason`（预期截断时为 max_tokens 类值）/ OpenCode `step-finish.reason` | ACP 后端首选 |
| **第二层（兜底）** | 组装后 trajectory 的结构检查（现 `is_truncated`，阈值按 §三.三 后端化） | OpenCode 若不给显式信号时的 fallback；防协议信号缺失 |
| **下游（统一）** | 接力机制不变：归档部分产出 → HANDOVER → 重入队 | 全后端共用——"判定链复用"的正确含义是复用接力机制，不锁死上游信号源 |

### 9.3 未验证项（升格为 WP-U2 实验靶）

"协议会显式告知截断"目前是**高度合理但未证实**的假设：
1. Devin ACP 撞 output 上限时 `stopReason` 返回什么值——从未实测（035 只测过 end_turn）
2. OpenCode ACP 撞顶时 `step-finish.reason` 给什么——实测只见过 stop/tool-calls/unknown
3. OpenCode SQLite 落盘时机（运行中增量 vs 结束批量）——决定崩溃后 export 能捞回多少

三项已写入 WP-U2 任务 6（截断信号探测）与任务 3 扩展（export 对照）。

### 9.4 对 §三.三 的定位修正

§三.三 的"阈值后端化"仍然成立且已采纳（V3 落地），但它从"主检测机制的参数适配"
**降级为第二层兜底的参数化**。U4 架构的检测层按本节分层设计，不再把结构启发式当
唯一机制。

---

## 十、本次更新的落地清单（2026-08-21）

| 文档 | 改动 |
|---|---|
| 本文（038） | 新增 §八（export 实测）/ §九（分层检测）/ §十（本清单） |
| WP-U2 | 前置认知加载清单补 skill §9.3–9.6；任务 3 加 C 路原生 export 对照（零调用成本）；新增任务 6 截断信号探测（配额 +2）；验收 checklist 相应扩展 |
| WP-U4 | §3 阈值讨论改为分层检测裁定；任务 1 接口的 BackendStatus 增 finish_reason 字段；任务 2 增第 7 点 trajectory 三层来源策略；前置认知加载清单补本文 |
| WP-U5 | §3 基线补 export/SQLite 事实；任务 4 设计文档增"trajectory 来源三层"小节 |
| WP-V1 | 规格注记：组装器对接三层来源（通知 jsonl 主 / opencode export 兜底）；detection 消费协议原生 finish reason |
| WP-V3 | 规格注记：TRUNC_COMP_TOKENS_MIN → backend.trunc_comp_threshold 属性（-p 后端返回 24000，行为零变化） |
| workpackages/README.md | §一背景补一行 038 补充说明 |
