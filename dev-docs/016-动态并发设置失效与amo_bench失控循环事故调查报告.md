# 016 — 动态并发设置失效与 amo_bench_00000006 失控循环事故调查报告

> **事故时间**：2026-08-20 01:48 ~ 03:56（本地时间）
> **调查时间**：2026-08-20 03:4x ~ 03:56（强制 cool down 完成后补证）
> **事故等级**：严重（失控循环空转约 20 分钟 + 长期真实并发超限 + API 配额浪费）
> **当前状态**：系统已完全 cool down（进程/队列/session 全部归零），遗留脏数据待清理
> **取证脚本**：`scripts/diag_20260820_incident_report.py`（只读 DB，可重复执行）

---

## 1. 一句话结论

用户把并发从 4 降到 1 后，**设置本身生效了（DB 里 concurrency=1，launcher 也读到了），但系统真实 devin cli 并发是 6 个**——其中 2 个是降并发前的存量 solve，另外 4 个（后来膨胀到上千个）是 `amo_bench_00000006` 这道题陷入"旧产物秒判完成→截断重入队→再启动"的**失控循环**产生的；同时有一个 feeder 进程在高频循环重喂队列，导致队列永远清不空。这不是 set-concurrency 的 bug，是**launcher 判定逻辑 + 旧产物残留 + feeder 重喂**三个问题叠加的系统性事故。

---

## 2. 背景与触发条件

- batch：`p27-full`（POC-2.7 续传 Pipe，v2 方案：Pipe A 生成 HANDOVER.md + Pipe B 解题）
- launcher 以 tmux 服务方式运行，外层包了 `while true; do python -m src.continuation_launcher ...; sleep 5; done` 自动重启
- 03:42 用户执行 `python -m monitoring.continuation_control set-concurrency --batch-id p27-full --concurrency 1`，命令返回"4 → 1，30秒内生效，不影响当前 running"

### set-concurrency 的真实语义（代码确认）

`monitoring/continuation_control.py` 第 498-515 行：只更新 DB 中 `p27_continuation_batches` 文档的 `concurrency` 字段。launcher 主循环每轮 poll 从 DB 刷新该值（`src/continuation_launcher.py` 第 655-666 行），并只用于约束**新任务的启动**：

```python
while not should_stop() and len(running) + len(handover_pending) < concurrency and pending_count(r) > 0:
```

`running` 和 `handover_pending` 都是 launcher **进程内存里的 dict**（第 619-620 行），启动时为空、不恢复。所以：

1. 存量进程不受影响（设计内）；
2. 但不在内存 dict 里的进程（孤儿、注册表 stuck 的）**不占并发槽**，launcher 对它们完全无感知——这就是"设置 1 却有 6 个进程"的主要机制。

---

## 3. 事故时间线（证据支持）

| 时间 | 事件 | 证据来源 |
|---|---|---|
| 01:48:59 | launcher tmux 服务创建（while true 包装） | tmux list-sessions（事故中查询） |
| 01:49:01 | monitor tmux 服务创建 | 同上 |
| 01:59:48 | 当前 launcher 进程（PID 94256）启动；说明 01:48 的首个实例曾退出过一次，被 while true 拉起 | `ps -eo pid,lstart` |
| 02:02 / 02:15 | deepmath_103k_00000006 / 00004725 的 round2 solve 启动（正常工作，session s0031 / s0048） | tmux session 创建时间 |
| 02:2x | amo_bench_00000006 的 round2 solve 在跑（work_dir 出现 reasoning_extract.txt、verify_*.py、_rc.txt） | work_dir 文件 mtime |
| 02:37 前 | **feeder 开始高频循环运行**，反复 feed_batch（count=500），到 03:56 写满 15 个 1MB 轮转日志 | log/continuation_feeder.log* 轮转文件 |
| 03:37:42 | amo_bench round2 结束被判截断 → 重入队 → 首个失控 handover session（s1476） | tmux session 创建时间 |
| 03:42~03:43 | s1565 / s1575 / s1595 连续创建 | 同上 |
| 03:53:48~03:54:26 | 失控加速：每约 3 秒 handover_start 一次（s1789、s1790、s1800、s1817…） | tmux capture-pane（p27-launcher）、log/system.log 窗口 |
| 03:55:20 | 开始强制停止（kill launcher/monitor 服务 session + stop --force） | 操作记录 |
| 03:56:2x | kill feeder 进程（PID 31557/31555）+ kill 残留计算进程 | 操作记录 |
| 03:56:39 | 最终 clear_all，pending=0，系统完全冷却 | Redis 查询 |

---

## 4. 现象与根因分析

### 4.1 现象一：并发设置为 1，真实 devin cli 并发 = 6

03:4x 实测（`ps aux | grep 'devin -p'` + tmux）：

| 进程 | 类型 | 是否被 launcher 跟踪 |
|---|---|---|
| deepmath_103k_00000006 r2（s0031） | solve | ❌ 不在 Redis p27:running（记录脱节） |
| deepmath_103k_00004725 r2（s0048） | solve | ✅ Redis p27:running 唯一一条 |
| amo_bench_00000006 r1 handover ×4（s1476/s1565/s1575/s1595） | handover | ❌ 只在 launcher 内存 handover_pending，部分已是孤儿 |

Redis 视角"并发"=1（running hash 仅 1 条），实际进程 6 个，**队列状态与真实进程严重脱节**。

**根因**：
- `running`/`handover_pending` 是内存 dict，launcher 重启即清空 → 老进程变孤儿，不占并发槽、不被监控；
- Redis `p27:running` 只在部分路径写入/清理，s0031 对应记录缺失；
- `set-concurrency` 只约束新启动，对存量与孤儿无能为力（设计内，但放大了事故）。

### 4.2 现象二：amo_bench_00000006 失控循环（核心事故）

**规模**：DB `p27_sessions` 注册表总 1803 条，其中 amo_bench_00000006 占 **1765 条**（stuck=1733，running=32），session seq 跨度 53~1817。03:37~03:55 约 18 分钟内新增上千个 handover session。

**重要修正**：最初怀疑"launcher 反复重启导致内存丢失后重复启动"，但 `ps` 证实 launcher 进程（PID 94256）从 01:59:48 存活到被 kill，**期间未重启**。失控循环发生在**单个 launcher 进程内部的主循环里**。

**根因链**（每步都有证据）：

1. **旧产物残留**：work_dir 里混着 8 月 18 日的旧产物——`round1_export.json`（08-18 15:09）、`round2/` trajectory 目录（08-18 15:12）、`round1_handover_run/conversation.json`（08-18 15:12，且 `round2/exports/`、`round2/tmux/` 是空目录）。这道题曾在 8 月 18 日被手工跑过一轮，但 DB 里 rounds_log 是空的、status 又被标回 prepared。
2. **判定函数读文件即判**：launcher 的 `is_completed` / `is_truncated` / `check_handover` 基于"文件是否存在/DONE.md 是否出现"，不校验产物属于哪一轮、新旧程度。
3. **截断重入队**：round2 solve 结束被判截断（`src/continuation_launcher.py` 第 1103-1121 行：`update_run(status="prepared")` + `enqueue_pending(r, run_key, priority=round_num)` + kill session + remove_running）。
4. **feeder 把它反复拉回队首**：`enqueue_pending` 用 zadd score=priority，截断重入队时 priority=2，本应排在新题（score=0）后面；但 feeder 每轮 `feed_batch` 对 prepared 状态的题**无条件 zadd score=0**，把 amo_bench 的优先级反复重置回 0 → 它永远排在 zset 顶部（`_key` 字典序也最靠前），每次 poll 都第一个被 `zpopmin` 取出。
5. **秒判循环**：dequeue amo_bench → 判定 current_round=2 → v2 方案需要先生成 round1 的 HANDOVER.md → 启动 handover devin cli → 下一圈检查时读到 8 月 18 日的旧 `conversation.json`/产物 → 立即判定"完成/失败" → 走启动 solve 或失败分支 → 旧产物又致秒判 → 再次截断重入队 → 槽位空出 → 再 dequeue amo_bench……每圈约 3 秒（tmux 启动开销），无限空转。每圈都真实调用 GLM-5.2 API，**纯粹浪费配额**。
6. **无人拦截**：
   - handover 的启动只写 logger 事件（`handover_started`），**不写 DB 事件流**（`insert_event` 的 `continuation_launched` 只在启动 solve 时记录；DB 事件统计 continuation_launched=330，对不上千次 handover）→ monitor 的 A 类检查根本看不到 handover 失控；
   - monitor 有 **33894 个 alert 积压未处理**（SOP 循环未运行）；
   - watchdog 未运行；
   - 铁律"绝不 kill 无 DONE.md 的 session"让 stuck session 只能堆积不能清理（`stop --force` 也只报告 100 stuck + 34 running 而不动它们）。

### 4.3 现象三：feeder 无限空转 + 重置优先级（已完全定论）

- 强制停止后第一次 `clear_all`，pending 几秒内回到 2 → 再查又回到 500；
- 最终发现 `src.continuation_feeder`（PID 31557）一直在运行：**02:37~03:56 之间写满 15 个 1MB 轮转日志**，日志里反复出现 `feed_batch_done count=500`；
- **根因（代码定论，`src/continuation_feeder.py` 第 57-63 行）**：feeder 的 main 是 `while True: count = feed_batch(...); if count == 0: break`。feed_batch 每次从 DB 取 `status=='prepared'` LIMIT 500 入队（zadd score=0）。由于：
  1. DB 里 prepared 有 5957 个，永远取不满也取不完（launcher 被 amo_bench 空转占满并发槽，其他题根本没机会被 dequeue 改状态）；
  2. LIMIT 500 每次取到的是同一批题（AQL 无排序时自然顺序稳定），zadd 幂等，zset 大小不变；
  3. 于是 count 恒为 500，**`count==0` 的退出条件永远不成立 → feeder 是一个自我死循环进程**，不需要任何外部循环调用；
  4. 每圈 `zadd score=0` 还把 launcher 截断重入队设置的 priority=2 **反复重置回 0** → amo_bench 永远钉在 zset 队首，是失控循环的燃料供给线。
- pending 被清空后几秒内回到 500，就是这个死循环进程回填的。

### 4.4 事故中发现的 DB/代码不一致（顺带记录）

- amo_bench run 记录：`status=prepared`、`current_round=2`、`rounds_log=[]`（空）、`tmux_session="p27-p27-full-amo_bench_00000006-r2"`（**双前缀格式错误**）、`verdict.reason="requeued_after_graceful_stop"`；
- DB 进度：prepared=5957 / completed=124 / dead_session=1（与事件流 completed=124 一致）；
- `p27_sessions` 的 `session_type` 字段在注册表里全是 null（按类型统计失败），字段命名/写入存在缺陷。

---

## 5. 处置过程（强制 cool down，03:55~03:57）

按依赖顺序执行，先断"再生产者"再清存量：

1. `tmux kill-session -t p27-launcher` —— 停 launcher + 斩断 while true 自动重启循环；
2. `tmux kill-session -t monitor-p27` —— 停 monitor + 斩断其重启循环；
3. `python -m monitoring.continuation_control stop --force` —— 标记停止 + 首次清空 Redis 队列（它按铁律不 kill stuck/running session，只报告）；
4. 循环 kill 所有 `p27-s*` 工作 tmux session（deepmath r2 两个 solve）；
5. `pkill -f 'devin -p --prompt-file'` —— 清掉脱离 tmux 的残留解题进程；
6. **kill feeder（PID 31557/31555）** —— 停止重喂队列的源头；
7. kill 残留计算进程（PID 76487，amo_bench work_dir 里的 verify python3）；
8. 最终 `clear_all`（此时 feeder 已死，队列才真正清到 0）。

**最终确认（六项全过）**：continuation 进程 0 / p27 tmux session 0 / devin -p 进程 0 / 残留计算进程 0 / Redis 队列全 0 / status 显示三服务均未运行。

**注意**：用户残留的交互式 devin（`devin -r xxx`、裸 `devin` 及其 `devin acp` 子进程）不属于本系统，**未被 kill**。

---

## 6. 遗留脏数据清单（重启前必须处理）

| # | 脏数据 | 规模 | 建议处理 |
|---|---|---|---|
| 1 | `p27_sessions` 注册表孤儿记录 | 1803 条（amo_bench 1765：stuck 1733 / running 32） | 脚本批量清理（tmux 已无对应 session，可安全标记 cleaned/删除） |
| 2 | amo_bench run 记录状态不一致 | status=prepared / current_round=2 / rounds_log=[] / tmux_session 双前缀 | 人工复核后归零重置（该题 8/18 有过手工运行，rounds 语义需裁决） |
| 3 | work_dir 旧产物混杂 | round1_export.json 等 8/18 文件与今晚新产物混放 | 归档旧产物或按轮次分子目录（配合 P0-2 修复） |
| 4 | monitor alert 积压 | 33894 个 | 按 SOP_03 分类批量 resolve |
| 5 | feeder 死循环缺陷 | `while True` + `count==0` 退出条件在 prepared>500 时永不满足 | 修复退出条件（见 P0-3）后才能重启 |
| 6 | trajectory 空目录 | round2/exports、round2/tmux 空目录 | 随 #3 一并清理 |

---

## 7. 修复建议（分级）

### P0（不修不能重启系统）

1. **launcher 同 run_key 防抖**：dequeue 后检查该 run_key 是否已有活跃 session（tmux has-session 或注册表 running 状态），有则不启动、写 alert、跳过。这是拦住失控循环的最后一道闸。
2. **判定函数校验产物归属**：`is_completed`/`is_truncated`/`check_handover` 必须校验产物 mtime 晚于本轮启动时间（或每轮产物写独立子目录），杜绝"8 月 18 日的旧文件秒判今天这一轮"。
3. **feeder 修复（双重缺陷）**：① 退出条件——`count==0` 在 prepared>batch_size 时永不满足，需改为"本批无新入队成员"（对比 zcard 前后变化）或加最大循环数熔断；② 优先级保护——对已存在于 pending zset 的 member 用 `zadd XX NX`（不更新已有 score），绝不把截断重入队的 priority=round 重置回 0。

### P1（尽快）

4. launcher 启动时从 DB/Redis 恢复 `running`/`handover_pending`（消灭"重启即孤儿"）；
5. handover 启动也写 `insert_event`，让 monitor A 类检查可见；
6. launcher 日志落盘（本次 tmux pane 被 kill 后关键 stdout 全丢，log/ 里没有 continuation_launcher.log）；
7. 脏数据清理脚本（§6 表格 1/2/3）。

### P2（观察项）

8. monitor 33894 alert 积压的消化流程；
9. watchdog 为什么没在运行；
10. `p27_sessions.session_type` 全 null 的字段缺陷；
11. tmux_session 字段双前缀 bug（`p27-p27-full-...`）。

---

## 8. 附录：关键证据摘录

### 8.1 真实进程清单（03:4x，cool down 前）

```
devin -p --prompt-file .../p27-full-amo_bench_00000006/round1_handover_prompt.txt  ×4（s029/s035/s045/s064 tty）
zsh -c cd .../p27-full-deepmath_103k_00004725 && devin -p .../round2_prompt.txt     ×1
zsh -c cd .../p27-full-deepmath_103k_00000006 && devin -p .../round2_prompt.txt     ×1
tmux: p27-s0031-solve-...00000006-r2 / p27-s0048-solve-...00004725-r2
      p27-s1476/s1565/s1575/s1595-handover-amo_bench_00000006-r1
```

### 8.2 launcher tmux pane（03:53，失控循环尾部）

```
[2026-08-20 03:53:52] event=devin_cli_launch ... problem_id=amo_bench_00000006 round=1 session_type=handover
[2026-08-20 03:53:52] event=handover_started ... session_name=p27-s1789-handover-amo_bench_00000006-r1
[2026-08-20 03:53:55] event=handover_started ... session_name=p27-s1790-handover-amo_bench_00000006-r1
[2026-08-20 03:54:14] [handover_start] amo_bench_00000006 R2 (生成round1的HANDOVER.md)
[2026-08-20 03:54:17] [handover_start] amo_bench_00000006 R2 (生成round1的HANDOVER.md)
```

### 8.3 Redis 队列（03:5x，cool down 前最后一次）

```
p27:pending zcard=699（zset，首元素 p27-full-amo_bench_00000006）
p27:running hlen=1（仅 p27-full-deepmath_103k_00004725）
v2 双队列（pending_handover 等）全部不存在 —— 实际跑的是 v1 单队列
```

### 8.4 DB 取证（scripts/diag_20260820_incident_report.py 输出，03:5x）

```
batch concurrency = 1（设置已生效）
p27_sessions 总 1803；amo_bench_00000006 = 1765（stuck 1733 / running 32）；seq 53~1817
事件流：continuation_launched=330 / failed=175 / completed=124（不含 handover 启动）
amo_bench run：status=prepared current_round=2 rounds_log=0 tmux_session=p27-p27-full-...(双前缀)
DB 进度：prepared=5957 / completed=124 / dead_session=1
```

### 8.5 feeder 日志证据

```
log/continuation_feeder.log（+ .1~.14 共 15 个文件，每个约 1MB，覆盖 02:37~03:56）
[2026-08-20 03:56:39] event=feed_batch_done batch_id=p27-full count=500   （反复出现）
```

### 8.6 cool down 后最终状态（03:56~03:57 六项确认全过）

```
continuation 进程 0 / p27 tmux session 0 / devin -p 进程 0
残留计算进程 0 / Redis 队列 pending=running=completed=failed=0 / 三服务均"未运行"
```

---

## 9. 复盘一句话

这次事故里，`set-concurrency` 是无辜的——它按设计生效了；真正的雷是"**旧产物残留 + 文件即判的判定逻辑 + feeder 无幂等重喂**"三件事叠加，而"handover 不进事件流 + alert 积压 + watchdog 缺位"让系统失去了所有报警机会。**P0 三项不修，重启系统后同类循环随时复发。**

---

## 10. P0 修复记录（2026-08-20，事故当日完成）

### 修复内容（commit 见 git log "016事故P0修复"）

| P0项 | 修复 | 文件 |
|---|---|---|
| P0-1 同run_key防抖 | dequeue后双检查：①内存dict（running/handover_pending）②注册表活跃session（`find_active_session`，只认tmux还活着的）。命中则priority=9999重入队跳过 | `src/continuation_launcher.py` |
| P0-2 产物归属校验 | `is_truncated`/`is_completed`增加`since_ts`参数（export和proof.md的mtime必须晚于本轮启动）；`check_handover`校验HANDOVER.md mtime晚于hinfo.started_at；主循环proof预检同样校验；round1分支改为**总是**从seed_export覆盖拷贝round1_export.json | `src/continuation_launcher.py` |
| P0-3 feeder幂等 | `enqueue_pending`改NX模式（`zadd nx=True`，已存在不覆盖score——保住截断重入队的低优先级）；**顺带修复feeder死循环根因**：`feed_batch`只统计新入队数（原来统计处理数，导致`while True`永不退出——这正是事故中feeder高频循环写满15个1MB日志的原因） | `src/continuation_redis_queue.py` + `src/continuation_feeder.py` |

### 验证

- `python -m py_compile` 三个文件全部通过；
- 单元测试 `scripts/test_016_p0_fixes.py`：**14/14 通过**（覆盖since_ts校验、check_handover旧文件拒绝、NX幂等、score保持、feeder计数、队首顺序）；
- 真实Redis验证 NX 语义：首次zadd返回1、二次返回0、score保持不变；
- 文档同步：`docs/architecture/operational-concerns.md` 新增 §6"失控循环防护"。

### 修复后的行为变化

- **失控循环三道闸**：旧产物不再被误判（判定层）→ 即使误判重入队也排队尾不霸占队首（队列层）→ 即使队首也拦住不重复启动（防抖层）；
- feeder 跑完自然退出，不再死循环；
- 重启系统前仍需先清理 §6 的脏数据（1765条孤儿session记录 + amo_bench不一致状态）。

### 未修（P1/P2 留待后续）

launcher重启恢复running dict（P1-4）、handover写DB事件流（P1-5）、launcher日志落盘（P1-6）、脏数据清理（P1-7）、watchdog缺位（P2-9）、`p27_sessions.type`字段统计口径（P2-10，注：注册表字段实际叫`type`不是`session_type`，§4.4的"全null"是取证脚本用错字段名，字段本身有值）、tmux_session双前缀（P2-11）。

---

## 11. 可观测性补强（2026-08-20同日实施）

针对"SOP为什么看不见"的复盘：所有检查都是**存量快照**，看不到**流动过程**。实施四层：

| 层 | 内容 |
|---|---|
| 行为流水 | `src/observability.py`——launcher每个状态转移写JSONL到`log/flow/`（含judge判定理由）。CLI：`--stats/--tail/--run-key/--event/--clean-days` |
| launcher插桩 | dequeue/skip/launch/judge/requeue/done 全打点（`log_flow`调用，写失败静默） |
| monitor新检查 | **A13**真实并发四源审计（tmux vs DB vs Redis vs 设定）；**A14**启动抖动（行为流水中同run 1小时≥5次launch→critical，事故场景下第5次启动即报警）；**A1修复**（并发从DB读+补"实际>设定"分支） |
| SOP集成 | SOP_01新增第8节"系统流动历史观察"（每轮必查`--stats --since 1h`，含判断标准表和处置路径） |

**事后回放能力**：若016事故在有此层的情况下重演，Master Agent 执行
`python -m src.observability --stats --since 1h` 会看到：
`churn_suspects: {p27-full-amo_bench_00000006: 900+}`——失控循环3秒内可见；
`--run-key` 能看到每次 judge 的 stale 判定理由，直接定位"旧产物秒判"根因。

测试：`scripts/test_016_observability.py`（21断言全过，含016事故场景模拟——
同一题6次handover启动触发launch_churn critical告警）。

---

## 12. 勘误与代码级自查（用户质询"你确定考察了所有代码吗"后的补查）

用户质询后补查全部相关代码，发现并修复了 **4 个问题**（含 1 个 P0 修复自身引入的 bug）：

| # | 问题 | 性质 | 修复 |
|---|---|---|---|
| 1 | **skip重入队死循环**：P0-1防抖以priority=9999重入队后，若该题是pending里唯一/最低分的，zpopmin立刻再取回它，同一轮poll内无限跳过 | **P0-1修复自身引入的bug** | launcher加`requeued_keys`集合——本轮已跳过的key再被取出时直接break，等下一轮poll |
| 2 | **A13误报**：DB的`status='running'`只在solve启动时写（3处`update_run`确认），handover进行中tmux总数>DB running是正常状态，初版A13会报假critical | A13设计缺陷 | 按`_classify_p27_session`拆分：tmux_solve↔DB↔Redis对账；tmux_total(solve+handover)↔batch设定对账（handover占并发槽是设计行为） |
| 3 | **alert `_key`冲突**（MON-A!02）：A13一轮生成两条同类型`real_concurrency_mismatch`，同毫秒必撞unique约束，第二条静默丢失 | 已知bug被新检查放大 | `create_alert`的key加`uuid.uuid4().hex[:6]`随机后缀 |
| 4 | **`requeued_after_graceful_stop`来历不明**：该verdict出现在DB里，但`git log -S`证实**从未存在于任何已提交代码**（只在报告草稿的stash里） | §4.4证据链勘误 | 来源最可能是8/18-19某次**未提交代码或手工DB操作**（临时恢复脚本）。它不是当晚launcher代码写出的——当晚工作区无src/改动。修正认知：amo_bench回到pending的路径主要是截断重入队+feeder重喂（§4.2根因链3、4步），graceful-stop重入队是未经证实的次要假设 |

**其他补查确认无问题的部分**：`enqueue_pending`改NX后所有调用方兼容（launcher 3处重入队语义不变、feeder/run_continuation_pipeline幂等性反而增强、其他Pipe用独立模块无影响）；`is_completed/is_truncated`仅launcher和测试调用（可选参数向后兼容）；watchdog/collector/result_collector与改动无交互；`monitor_check_continuation.sh`已补第9节"系统流动历史"（`--stats --since 1h`）。

**教训**：修复本身也需要代码级全量自查——P0-1的9999重入队方案在"队列只有一道题"的边界条件下引入了新死循环；A13的初版设计没有核对"DB running状态到底何时写入"这一数据流事实。**每写一个检查/修复，必须回答"这个值是谁在什么时候写的"**。

测试更新：`scripts/test_016_observability.py` 27断言（+6：alert key唯一性、session分类）。




