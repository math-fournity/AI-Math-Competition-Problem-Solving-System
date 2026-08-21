---
trigger: always_on
---

# 判断系统状态必须查过程证据铁律

**硬约束**：任何判断系统状态时，必须查过程证据（日志 + 行为流水），不能只看 DB 结果。DB 是"结果"，日志是"过程"——只看结果不看过程会漏掉状态同步 bug、得出错误结论。

## 为什么

DB 的 run/session 状态是 launcher 判定后写入的**结果**。日志和行为流水是 launcher 判定过程的**证据链**。两者可能不一致——launcher 正确判定了完成（flow 有 `run_completed`），但 session_registry 没同步更新（DB session 仍 `stuck`）。

**历史教训（2026-08-21）**：接手系统时被问"做题成功吗"，AI 只查 DB（run 状态 + proof 文件），得出"4 道题完成，但 s1827 状态没更新，可能 launcher 没及时检测到 DONE.md"。后查 observability flow 发现 launcher **正确检测到了完成**（`round_done outcome=completed` → `run_completed final_status=COMPLETED`），问题在 session_registry 同步逻辑。只看 DB 得出的结论（launcher 没检测到）是**错的**——日志证明 launcher 检测到了，问题在下游同步。

这正是 016 事故的教训重演：**存量视角看不到流动过程**。016 事故中存量检查（队列数/session数）看不出病态流动；这次是 DB 结果看不出状态同步断链。

## 触发时机

| 时机 | 说明 |
|---|---|
| 接手系统时确认运行状态 | 不能只查 DB run/session 状态，必须查日志确认过程 |
| 用户问"做题是否成功/系统是否正常" | 必须用日志交叉验证 DB 结果 |
| commit 前验证改动是否影响系统 | 改了 launcher/monitor 代码后查日志确认行为符合预期 |
| 发现 DB 状态与文件不一致时 | 如 proof 存在但 session=stuck——必须查 flow 看状态转移链断在哪里 |
| SOP_01 系统健康检查 | SOP_01 §7§8 已要求查日志，本 rule 是其 always-on 版本 |

## 必做动作（三层证据交叉验证）

### 第1层：DB 查结果

```
# run 状态
python -m monitoring.continuation_control status

# session 状态
python -m monitoring.continuation_control sessions --consistency-check
```

### 第2层：log_search 查结构化日志（事件流）

```
# 某题的所有事件
python -m scripts.sop.log_search --problem-id <problem_id>

# 某session的所有事件
python -m scripts.sop.log_search --session-key <session_key>

# ERROR 级别日志
python -m scripts.sop.log_search --level ERROR --since "2026-08-21 01:43"

# 关键事件
python -m scripts.sop.log_search --event mark_stuck --since "2026-08-21 01:43"
python -m scripts.sop.log_search --event dead_session --since "2026-08-21 01:43"
python -m scripts.sop.log_search --event round_done --problem-id <problem_id>
```

### 第3层：observability 查行为流水（状态转移链）

```
# 某题完整生命周期（含所有判定理由）
python -m src.observability --run-key <run_key>

# 聚合统计（启动速率/每题启动次数Top10/失控嫌疑/判定分布）
python -m src.observability --stats --since 1h

# 最近N条状态转移
python -m src.observability --tail 50
```

### 交叉验证规则

| DB 说 | 日志说 | 判定 |
|---|---|---|
| run=completed | flow 有 run_completed | ✅ 一致，真的完成 |
| run=completed | flow 无 run_completed | ❌ DB 写错了，查 finalize 逻辑 |
| session=stuck | flow 有 round_done outcome=completed | ❌ session_registry 同步 bug |
| session=stuck | flow 无 round_done | ✅ 一致，真的 stuck |
| proof 文件存在 | flow 有 judge reason="proof.md有boxed" | ✅ 一致，proof 是本轮产出 |
| proof 文件存在 | flow 无 judge 事件 | ❌ 旧产物残留（017 场景） |

## 与现有文档的关系

| 文档 | 定位 | 本 rule 的补充 |
|---|---|---|
| SOP_01 §7 | 日志观察——SOP_01 步骤内的子项 | 本 rule 是 always-on 版本：非 SOP_01 场景也要查 |
| SOP_01 §8 | 行为流水观察——SOP_01 步骤内的必查项 | 同上 |
| AGENTS.md §145-179 | 016 后介入能力速查——事故应急处置 | 本 rule 是日常判断的硬约束：不限于事故场景 |
| `closure-trust-but-verify` rule | 认知闭包与代码冲突时的时间比对 | 本 rule 补充：DB 与日志冲突时也要交叉验证 |

## 禁止

- 禁止只查 DB 就断言"系统正常/做题成功"——必须用日志交叉验证
- 禁止只看 proof 文件存在就断言"题目完成"——必须查 flow 确认是本轮 judge 判定
- 禁止发现 DB 与文件不一致时直接猜原因——必须查 flow 状态转移链定位断点
- 禁止把本 rule 理解为"只在 SOP_01 查日志"——任何判断系统状态的场景都触发

## 配套代码

| 工具 | 路径 | 用途 |
|---|---|---|
| `log_search.py` | `scripts/sop/log_search.py` | 结构化日志检索（按 event/problem_id/session_key/level/module/时间范围） |
| `observability.py` | `src/observability.py` | 行为流水检索（状态转移链/聚合统计/失控检测） |

两个工具都已存在，不需要新写。本 rule 的作用是强制使用它们。
