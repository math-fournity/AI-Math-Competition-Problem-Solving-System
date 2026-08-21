# WP-K — 续传系统终态补全（仅 ai_gave_up）

> **优先级**: 第三批位置（依赖 WP-I；与 WP-J 可并行）
> **依赖**: WP-I
> **预计规模**: continuation_launcher.py dead_session 分支 ~30 行 + 单测
> **性质**: 代码改造（判定逻辑）——**最小改动**。**需 sim 门禁**

---

## 0. 给执行 AI 的第一句话

续传 launcher 判定链里，AI 主动放弃（pane 里写"I CANNOT SOLVE"等）的 devin 会被
误判为 dead_session——分类错还是小事，真正的害处（031 B6）：dead_session 属 infra、
`retry_eligible=True`，WP-L 自动重试上线后**放弃的题会被反复无意义重试**。你要在
dead_session 判定前插入 ai_gave_up 检测（WP-I 的 check_ai_gave_up），一行分类、
retry_eligible=False。**只做这一个**——token_limit（is_truncated 已覆盖）、
crash_recovered（不细分）、invalid_tool_use（政策相反）都不做（036 §四.1 裁定）。

## 1. 背景（为什么）

- 判定链现状：devin 退出 → 无 proof → is_completed ✗ → is_truncated ✗（msg>0）→
  dead_session。AI 放弃时 msg>0（有输出"我解不出"）无 proof → 落 dead_session
- 平凡系统有 check_ai_gave_up（7 模式），本 repo 没有（031 B4 grep 零命中）
- 范围裁定的依据：036 §四.1 接受 034 收缩——"适度依赖 Master Agent"原则下，
  crash_recovered 细分只提升分类精度不改变应对（都是 infra 可重试）；token_limit
  已被 is_truncated 结构化覆盖（031 B2）；工具使用合法（031 B3）

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **确认 WP-I 完成** | check_ai_gave_up 可 import |
| 2 | `src/continuation_launcher.py` 的 dead_session 分支（搜 `[dead_session]`） | 现状写入：status/rounds_log/verdict/failure_category/retry_eligible=True 的完整字段组——你插入的分支字段组照此结构 |
| 3 | 同文件 running 检查段开头（搜 `pane_text = tmux_pane_text`） | pane_text 已在循环里获取（dead 分支可用它——确认变量在作用域内） |
| 4 | `src/devin_cli_failure_detection.py`（WP-I） | check_ai_gave_up 签名（返回命中模式串或 None）+ MODEL_FAILURES 含 ai_gave_up |
| 5 | `src/sim/` 的剧本运行方式（`dev-docs/017` 的使用节，选读） | sim 门禁跑法 |

## 3. 现场事实基线（2026-08-21 09:30）

- dead_session 分支的字段写入（复核读代码）：status="dead_session"、rounds_log append
  （reason="dead_session({elapsed}s)"）、verdict、failure_category=
  classify_failure("dead_session")="infra"、**retry_eligible=True**、remove_running/
  add_failed/insert_event
- pane_text 在 running 检查段开头获取（~1474 行），dead 分支在同一 for 循环内可用
- **注意**：dead 分支的触发条件是 `not tmux_running or devin_exited` 且无 proof 且
  非截断——此时 tmux 可能已消失，pane_text 可能取不到（session 没了 capture-pane
  失败返回 ""）。**检测窗口问题**：放弃标记若在 pane scrollback 里且 session 已死，
  capture-pane -t 对死 session 报错 → 返回空 → 检测不到。缓解：DONE.md 存在时 session
  因 sleep 999999 通常还活着（E2）——pane_text 大概率可得。实现按"尽力检测，取不到
  pane 则维持 dead_session 判定"设计，不阻塞。

**基线漂移预期**：WP-S 改过 remove_old_proof（无关）；WP-L 未做（本 WP 是它的前置）。

## 4. 任务分解

### 任务 1：插入 ai_gave_up 分支

在 dead_session 判定**之前**（is_truncated 判否之后）插入：

```python
# AI 主动放弃检测（WP-K / 030 需求 8）——放弃模式优先于 dead_session 分类：
# 放弃是模型能力边界（model 类、不重试），误判为 dead_session（infra、可重试）
# 会导致 WP-L 上线后无意义重试（031 B6）
gave_up = check_ai_gave_up(pane_text or "")
if gave_up:
    # 与 dead_session 分支同构的完整写入，但：
    # status="ai_gave_up"
    # rounds_log reason=f"ai_gave_up(命中模式: {gave_up})"
    # failure_category=classify_failure("ai_gave_up")="model"
    # retry_eligible=False
    # kill_session(reason="ai_gave_up")（过 GATE-KILL-SESSION 门闸，gate_ctx 带 reason）
    # log_flow("run_failed", ..., reason="ai_gave_up")
    # 其余（remove_running/add_failed/insert_event/状态打印）照抄 dead_session 分支
    continue
```

### 任务 2：DB schema/文档确认

- `p27_continuation_runs.status` 是自由字符串（无 schema 枚举约束）——"ai_gave_up"
  直接可用；确认 SOP/monitor 的 status 分布查询（`COLLECT status = run.status`）不受
  新值影响（天然支持任意值）
- `monitor_continuation.py` 的 A 类检查是否对 status 有白名单（grep "dead_session"
  monitor_continuation.py）——若有引用处需加 ai_gave_up（如失败率统计的集合），
  一并改并记录

### 任务 3：sim 门禁 + 单测

- **sim**：跑 solve3 剧本（改判定逻辑必须过——铁律 12）。剧本里有没有"放弃"场景？
  查 `src/sim/` 的剧本定义——若无，跑 solve3 确认主流程无回归即可（ai_gave_up 是
  新增分支，正常剧本不会触发），并在执行记录说明
- 单测 `scripts/test_wp_k_ai_gave_up.py`：构造 pane 文本（含 "I CANNOT SOLVE THIS"）
  → check_ai_gave_up 命中；不含 → None。（分支级测试依赖主循环难单测——逻辑正确性
  由"同构照抄+单测模式函数+sim 无回归"三层保证，执行记录说明该策略）

### 任务 4：py_compile + commit + 文档

- SYSTEM_CLOSURE §6"各阶段正常状态"段：加一行 ai_gave_up 的正常标准（如
  "ai_gave_up：模型能力边界的正常出口，占比随题难度分布，不触发 alert"）
- SYSTEM_CLOSURE §3 生命周期图：dead_session 行前加 ai_gave_up 出口
- commit 显式路径

## 5. 禁止事项

- ❌ 只做 ai_gave_up——不加 crash_recovered 细分 / token_limit / thinking 检测
  （036 §四.1 裁定，做了就是 scope 蔓延）
- ❌ 不改 dead_session 分支本身的任何行为（只是它前面多了个前置出口）
- ❌ 不动 is_truncated/is_completed（031 B2：它们是对的）
- ❌ pane 取不到（session 已死）时不许抛错——回落 dead_session 判定

## 6. 验收 checklist

- [ ] `grep -n "check_ai_gave_up" src/continuation_launcher.py` — import + 调用 ≥2 处
- [ ] 新分支含 `retry_eligible": False` 与 `failure_category.*model`（grep 输出）
- [ ] dead_session 分支 diff 为零改动（`git diff` 确认）
- [ ] 单测输出；sim solve3 无回归输出
- [ ] monitor_continuation 的 status 引用检查结论（改了什么/无需改的依据）
- [ ] SYSTEM_CLOSURE 两处更新
- [ ] py_compile；commit 显式路径

## 7. 完成汇报要求

执行记录：分支 diff、pane 可得性分析（E2 场景说明）、sim 输出、monitor 引用检查结论。

## 8. 审计对照

1. 我会构造一个"假放弃"场景实测（或审查你的单测+sim 证据链）
2. git diff 确认 dead_session 分支零改动 + 无额外终态混入
3. retry_eligible=False 的语义正确性（这是本 WP 的全部意义——防无意义重试）
4. SYSTEM_CLOSURE 的生命周期图与代码出口一致
