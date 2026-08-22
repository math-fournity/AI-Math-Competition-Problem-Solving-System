# 解题管线（Solve Pipeline）—— 核心领域概念

> **用途**：定义"解题管线"这个核心概念，作为并发控制的语义基础。任何讨论"系统并发""devin cli 实例数"时，必须先理解本文件。

> **实施状态（2026-08-22）**：WP-01 已把“最大轮次”迁移为本次调度窗口额度；未正确
> 解答且未被用户明确放弃的题可跨窗口无限续传。候选 proof 的形式化充分性审计仍待
> WP-04/05。权威目标见 `dev-docs/057~064`。

---

## 1. 定义

**解题管线** = 一道题目从进入系统开始被第一次解题，到最终结束（解出 / 放弃）的完整生命周期。

一条解题管线的阶段：

```
第一次解题（外部 POC-2.5 解题系统，独立 repo）
  → 失败
  → Pipe 4 续传循环：
      handover 生成（devin cli）→ solve 解题（devin cli）→ handover → solve → ...
  → 本次窗口收场：候选解出 / AI放弃暂停 / window_exhausted
  → 未确认正确时，未来显式开启新窗口并从下一绝对Round继续
```

**关键性质：管线内部是顺序调用 devin cli 的。** 一道题在任意时刻最多只有 1 个 devin cli 在为它工作（要么在 handover，要么在 solve，不会同时）。

代码依据：Pipe 4 v2 方案中，一道题的 `handover_pending` 和 `running` 共享并发槽，handover 完成后才启动 solve（`src/continuation_launcher.py:1172`）：
```python
while ... len(running) + len(handover_pending) < concurrency ...
```

---

## 2. 并发 = 解题管线条数

**因为管线内部顺序调用 devin cli，所以：**

> **系统并发数 = 同时在跑的解题管线条数 = 任意时刻解题 devin cli 实例数的上限**

- 限制解题管线数 = N，就能保证任意时刻最多 N 个解题 devin cli 实例（solve + handover）
- 不同题目的管线可能工作在不同阶段（有的在第一次解题，有的在续传第 3 轮），但每条管线内部串行
- 这就是为什么"并发"在语义上等价于"同时有多少条解题管线在跑"

---

## 3. 管线外的 devin cli 消费者（重要）

系统里存在**不属于解题管线**的 devin cli 消费者。限制解题管线数**不能**直接限制它们：

| devin cli 消费者 | 文件 | 并发配置 | 属于解题管线？ | 说明 |
|---|---|---|---|---|
| solve（续传解题）| `continuation_launcher.py` | `DEFAULT_CONCURRENCY=5`（共享池）| ✅ 是 | 管线核心 |
| handover（HANDOVER 生成）| `continuation_launcher.py` | 与 solve 共享并发池 | ✅ 是 | 管线核心 |
| ~~analysis（Pipe 1 分析）~~ | ~~`analysis_launcher.py`~~ | — | ❌ 否 | **已删除**（2026-08-20，Pipe 1/2/3 全删） |
| ~~audit（Pipe 2 审计）~~ | ~~`audit_launcher.py`~~ | — | ❌ 否 | **已删除**（同上） |
| ~~selection（Pipe 3 选题）~~ | ~~`selection_launcher.py`~~ | — | ❌ 否 | **已删除**（同上） |
| ~~solver（Mid-Hint 实验）~~ | ~~`solver_launcher.py`~~ | — | ❌ 否 | **已删除**（同上） |
| monitor_exec（C 类 AI 判断）| **未实现**（spec 中 `- [ ]`）| `MONITOR_EXEC_CONCURRENCY=1`（配置已定义）| ❌ 否 | spec 已写但代码未实现；C类判断由 Master Agent SOP_04 承载 |

**历史注**：Pipe 1/2/3 曾是"分析管线"（分析失败原因/审计质量/选题——都不解题），2026-08-20 已全部删除。当前系统只有解题管线一条；Pipe 4 的输入是预生成的 `problem_list.json`（2026-08-21 时为 6083 题），不依赖任何 Pipe 实时产出（`continuation_collector.py`）。

---

## 4. 用户命题的成立条件

用户命题：*"对解题管线的并发限制，一定能够限制到 devin cli 在系统中同时的实例的数量"*

**成立条件**：只有解题管线在跑（其他 devin cli 消费者不同时运行）。

- ✅ 如果只启动解题管线 → 限制管线数 = 限制 devin cli 实例数，命题成立
- ❌ 历史反例：Pipe 4 和 Pipe 1 同时跑时，Pipe 4 管线数限制了 solve/handover，但 Pipe 1 的 analysis devin cli 不受约束（Pipe 1/2/3 已删除，此反例不再可能发生）
- ⚠️ 残余风险：未来若新增管线外的 devin cli 消费者（如实现 monitor_exec），需重新评估

**当前实际运行模式**（AGENTS.md 启动指令）：只启动解题管线（`continuation_control start --batch-id p27-full --concurrency 1`）。所以命题在当前运行模式下成立。

**如果要保证命题在任何情况下都成立**：需要新增一个跨所有 devin cli 消费者的全局并发闸（不只是管解题管线），让未来新增的消费者启动 devin cli 前也先抢全局锁。当前架构没有这个能力。

---

## 5. 对并发控制设计的影响

理解了"并发 = 管线条数"后，并发控制的设计语义就清晰了：

- **Pipe 4 的 `concurrency` 字段** = 同时在跑的续传管线条数 = 同时解题 devin cli 实例数（含 handover）
- **设 concurrency=1** = 一次只有 1 道题在走续传管线 = 任意时刻最多 1 个解题 devin cli
- **动态调整**：`set-concurrency --batch-id p27-full --concurrency N` 改 DB 里的 concurrency，launcher 下次 poll 生效，只影响后续新启动的管线，不影响正在跑的

这与现有 `docs/architecture/dynamic-concurrency.md` 的机制完全一致——只是现在有了"管线"这个语义锚点，知道 concurrency 的物理含义是"管线条数"而非抽象数字。

---

## 6. 窗口收场与题目终态

当前实现区分“本次窗口收场”和“题目最终正确”：

| 事件 | 判定 | 含义 |
|---|---|---|
| 候选解出 | `proof.md` 存在且含 `\boxed` | 当前仍写COMPLETED；形式化最终门槛待WP-04/05 |
| AI放弃 | devin cli 输出放弃信号 | 暂停当前实例，`continuation_eligible=True`，可显式继续 |
| 窗口额度用完 | `round_window_rounds_used >= round_window_size` | `window_exhausted`，`final_status=null`，未来继续 |

绝对Round编号由rounds_log连续保存；`scripts/manage_continuation_windows.py` 默认dry-run，
显式resume只把run恢复为prepared，实际入队继续经过现有feeder Gate。历史
`TRUNCATED_AT_MAX`只做兼容读取，未经用户批准不批量迁移。

---

## 7. 边界说明

- **第一次解题**在外部 POC-2.5 解题系统（独立 repo），其并发由 `pipe_control.py concurrency` 控制，是独立旋钮，本项目的管线并发控制不覆盖它。
- **Pipe 1/2/3 与 solver_launcher**（Mid-Hint 实验launcher）均已删除（2026-08-20），不再是管线外消费者。
- **monitor_exec** 在 spec 中规划但代码未实现（`src/monitor_exec_launcher.py` 不存在），当前不产生 devin cli 实例；C 类判断由 Master Agent SOP_04 承载。
