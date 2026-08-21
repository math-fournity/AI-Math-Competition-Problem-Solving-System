# WP-J — 审计系统终态检测补全（rate_limit/token_limit/connection/ai_gave_up + 超时语义修正）

> **优先级**: 第三批位置（依赖 WP-I；与 WP-K 可并行）
> **依赖**: WP-I（共享模块）、WP-H（主循环已改，在其上叠加）
> **预计规模**: proof_audit_launcher.py running 检查段 ~90 行改动 + 单测/集成验证
> **性质**: 代码改造（launcher 判定逻辑）——**改判定逻辑，需验证**

---

## 0. 给执行 AI 的第一句话

审计 launcher 的 running 检查目前只认三种结局：DONE.md 完成 / session 消失（有 export
算完成、无 export 算 dead）/ 总时长超时。限流、连接错误、token 用完、AI 放弃——全部
无检测，全部混进 dead_session 或超时。你要接上 WP-I 的共享模块补全这些检测，修正
超时的误导命名（stall_timeout 实为 max_runtime 超时），删除死代码 detect_stall，加
rate_limit 全局暂停。

## 1. 背景（为什么）

- 030 需求 8（用户原文）：续传解题和审计管线中的 devin cli 可能遭遇平凡解题系统踩过
  的所有问题（限流等），"我们的系统是没有足够的应对策略的"
- 现状缺陷（031 A 组核实 + 032 B5 确认）：
  - `detect_stall()`（~216-223 行）**定义了从未被调用**——死代码；`stall_since` 字段
    写入 None 后从不更新
  - 超时判定 `time.time() - started_at > max_runtime` 是**总时长**超时，reason 却写
    "stall_timeout"——名不副实（031 B5：030 还把这点说反了）
  - 无 rate_limit 检测 → 限流时审计会继续启动新任务加剧限流（030 §6.6.5）
- 设计取向（036 §四.1 接受 034 收缩）：**不为 stall 写复杂检测**（奥卡姆剃刀——审计
  任务短，max_runtime 兜底 + Master Agent 通过 SOP 发现）；rate_limit 全局暂停复用
  续传的成熟模式（`operational-concerns.md` §1 有"新 Pipe 如何实现"四步清单）

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **确认 WP-I 完成**（共享模块存在+单测过） | 你要 import 的检测函数清单 |
| 2 | `src/proof_audit_launcher.py` **全文** | ① running 检查段结构（check_audit_complete → tmux_running → 超时）② detect_stall 死代码位置 ③ WP-H 加的收尾即收集接线（完成后有 collect_one 调用——你的失败分支之后它不触发） |
| 3 | `src/devin_cli_failure_detection.py`（WP-I 产物） | API：match_patterns/check_ai_gave_up/classify_failure + 模式常量 |
| 4 | `src/continuation_launcher.py` 搜 `rate_limit_paused_until`（3 处） | 续传的全局暂停模式：设置/检查/恢复打印——照抄结构 |
| 5 | `docs/architecture/operational-concerns.md` §1（rate limit 处理） | "新 Pipe 如何实现"四步清单——你的施工参照 |
| 6 | `src/proof_audit_redis_queue.py` 的 `add_failed` 签名 | 失败写入的 verdict 格式（WP-L 要读） |
| 7 | `dev-docs/030` §6.6.2（审计终态映射，选读） | 各终态对审计的含义（token_limit=报告可能不完整等） |

## 3. 现场事实基线（2026-08-21 09:30 + 前序 WP 后）

- running 检查段顺序：check_audit_complete → (session 消失→dead_done/dead_no_export) →
  max_runtime 超时
- **没有 pane_text 获取**（`tmux_pane_text()` 函数存在但主循环未调用——检查确认）
- 死代码：detect_stall + stall_since 字段
- 失败写入格式：`add_failed(r, {"audit_run_key":..., "reason": "dead_session_no_export"})`
  + `update_audit_run(..., {"status": "failed", "error_message": ...})`——你新增的终态
  沿用此格式，**error_message 写 verdict 原词**（rate_limited/failed_connection/
  failed_token_limit/ai_gave_up/max_runtime_exceeded——WP-L 按词分类）

**基线漂移预期**：WP-H 已加 should_stop/收尾即收集——你的检测加在"检查完成"之后、
"session 消失"之前的位置，与收尾接线不冲突。若 WP-G 已改 launch_batch 签名
（concurrency=None），照现状。

## 4. 任务分解

### 任务 1：主循环引入 pane_text + 四类检测

在 running 检查段（check_audit_complete 判否之后、tmux_running 检查之前或之后——按
续传的顺序：**完成检查 → 错误模式检测 → session 消失 → 超时**，错误检测要在 session
还活着时做因为 pane 是活 session 的）：

```python
pane_text = tmux_pane_text(session_name, lines=300)
detect_text = pane_text  # 审计无 pipe.log 追加内容？——注意：审计有 tmux_pipe.log
                        # （audit_launch 里 pipe-pane 配了）——读文件尾部 5KB 合并更稳：
# detect_text = pane_text + tail(tmux_pipe_path, 5KB)

verdict = None
for name, patterns in [("rate_limited", RATE_LIMIT_PATTERNS),
                       ("failed_connection", CONNECTION_PATTERNS),
                       ("failed_token_limit", TOKEN_LIMIT_PATTERNS)]:
    hit = match_patterns(detect_text, patterns)
    if hit: verdict = name; break
if verdict is None:
    gave = check_ai_gave_up(detect_text)
    if gave: verdict = "ai_gave_up"

if verdict:
    # 分类（WP-L 消费）+ 失败写入 + kill（错误态的 session 不留——与续传"标记stuck不kill"
    # 的策略不同：审计任务短且无部分产物风险，devin 已不产出有效结果）
    # ⚠️ 决策点：rate_limited/connection 不 kill（devin 可能自恢复，同续传"标记不kill"），
    # ai_gave_up/token_limit kill（模型不会再产出）。rate_limited 触发全局暂停 20 分钟。
```

实现要点：
1. **kill 策略分两类**（写进代码注释）：`rate_limited`/`failed_connection` → 不 kill、
   session 留着（对齐续传的"可能还在写 export"哲学），标 failed + verdict 入队；
   `failed_token_limit`/`ai_gave_up`/`max_runtime_exceeded` → `audit_kill_session`
   （reason=verdict，过门闸）
2. rate_limited 全局暂停：抄续传——`audit_rate_paused_until`（模块级变量/函数内非局部），
   触发时 `= time.time() + 1200`；主循环顶部检查（在补充并发之前）：暂停中打印剩余
   秒数 + sleep + continue
3. 失败写入统一：`update_audit_run(db, audit_run_key, {"status": "failed",
   "error_message": verdict, "ended_at": utc_now(), "failure_category":
   classify_failure(verdict)})` + `add_failed(r, {"audit_run_key":..., "reason": verdict})`
4. 每类判定打 `log_event`（event="audit_terminal_state", verdict=...）——SOP 可 grep

### 任务 2：超时语义修正 + 死代码删除

- reason/error_message："stall_timeout" → **"max_runtime_exceeded"**（名实一致）；
  `classify_failure("max_runtime_exceeded")` → model（WP-I 的 MODEL_FAILURES 已含）
- 删除 `detect_stall()` 函数与 `add_running` 里的 `"stall_since": None` 字段
  （grep stall_since 确认清零）
- kill 策略：超时 → kill（任务已超预期，留无意义）——与现状一致只改名

### 任务 3：pipe.log 尾部读取辅助

若决定合并 pipe log（推荐——pane 只有 300 行 scrollback，rate limit 错误可能滚走）：
加小函数 `tail_file(path, nbytes=5120) -> str`（读末尾 n 字节，errors="ignore"）。
路径来源：`add_running` 的 metadata 加 `"tmux_pipe_path"`（audit_launch 里已知）。

### 任务 4：验证

1. py_compile
2. 单测 `scripts/test_wp_j_audit_terminal.py`：对 `match_patterns+check_ai_gave_up` 在
   审计场景文本上的判定（构造含 "rate limit" 的假 pane → verdict=rate_limited 等，
   5 类各 1 例）——若主循环逻辑难以单测，测"判定辅助函数 + kill 策略映射表"
   （把策略做成模块级 dict 便于测）
3. 集成冒烟（若审计批次还有 pending）：启动并发 1，观察几个任务正常完成不被误判
   （**误判率检查**：正常完成的审计 pane 里若含 "rate" 字样会误杀——检查正常审计的
   pane/pipe 是否干净；若有误伤，模式收窄并记录）

### 任务 5：文档同步 + commit

- `docs/architecture/operational-concerns.md` §1 加一行"审计 Pipe 同款（WP-J 接入）"
- SYSTEM_CLOSURE §4 表 proof_audit_launcher 行：加"终态检测（WP-J：4 类+超时）"
- commit 显式路径

## 5. 禁止事项

- ❌ 不写真 stall 检测（pane_hash 追踪那套——034/036 裁定不要；max_runtime 兜底）
- ❌ 不动 check_audit_complete 的 DONE.md 语义（E1 已澄清它是"devin 退出"语义——
  改语义是另一回事，本 WP 不做）
- ❌ 不动 WP-H 的收尾即收集接线（失败分支后不调 collect_one——没有结果可收）
- ❌ 检测顺序上 rate_limit 优先于 connection/token_limit（续传同序——先查最环境性的）

## 6. 验收 checklist

- [ ] `grep -n "detect_stall\|stall_since" src/proof_audit_launcher.py` → 0（死代码清零）
- [ ] `grep -n "stall_timeout" src/proof_audit_launcher.py` → 0（改名完成）
- [ ] `grep -n "max_runtime_exceeded" src/proof_audit_launcher.py` ≥1
- [ ] `grep -n "match_patterns\|check_ai_gave_up\|classify_failure" src/proof_audit_launcher.py` — import + 使用
- [ ] rate_limit 全局暂停：代码含 `+ 1200`（20 分钟）与主循环顶部检查
- [ ] kill 策略两类分明（代码注释+单测断言：rate_limited 不 kill / ai_gave_up kill）
- [ ] failure_category 字段写入失败记录（DB 抽查 1 条贴记录）
- [ ] 单测过 + 集成冒烟输出（含"正常审计不被误判"的观察记录）
- [ ] py_compile；commit 显式路径

## 7. 完成汇报要求

执行记录：检测段 diff 摘要、kill 策略决策及理由、误伤观察结果、单测输出、
pipe log 合并方案（用了 pane-only 还是 pane+pipe tail）。

## 8. 审计对照

1. 我会用含/不含错误模式的假文本实测判定路径（构造 5 类样本）
2. grep 死代码清零 + 命名修正
3. kill 策略与文档声明一致（代码里两类注释）
4. 正常审计误伤检查的证据（这是模式检测最易翻车处——030 的历史教训就是无依据设计）
