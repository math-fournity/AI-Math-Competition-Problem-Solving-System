# WP-H — 审计 Pipe 优雅停止 + 收尾即收集（复用 SIGINT 模式）

> **优先级**: 第一批（WP-P 之后）
> **依赖**: WP-N（收尾收集调用 mark_parse_error）、WP-P（现场已清，新代码好验证）
> **预计规模**: proof_audit_launcher.py ~100 行改动 + proof_audit_result_collector.py
> ~40 行重构 + run_proof_audit_pipeline.py ~30 行 + 集成测试脚本
> **性质**: 代码改造（launcher 主循环）——**改调度逻辑，需 sim 发布门禁或等效验证**

---

## 0. 给执行 AI 的第一句话

审计 launcher 目前只有"全部做完"和"批次超时"两种退出路径，且**退出时不收集结果**——
这正是 030 需求 1 第二层的事故根因（5 个完成的审计结果至今没人收）。你要给
`proof_audit_launcher` 装上与续传 launcher 同构的优雅停止（SIGINT 信号 + should_stop
检查），并实现**收尾即收集**：每个审计判定完成后立即入库，任何退出路径（自然完成/
优雅停止/批次超时）都先收干净再退。

## 1. 背景（为什么）

- 续传系统已有成体系的优雅停止（`monitoring/graceful_shutdown.py` 信号模块 +
  launcher 接线 + `docs/architecture/graceful-shutdown.md` 文档含"新 Pipe 如何实现"
  六步清单）——**本 WP 严格按该清单实现，不发明新机制**（036 D6 裁定：同 repo 两套
  停止机制是分歧源；030 的 Redis `paudit:stop` 键方案已废弃）
- "收尾即收集"是用户需求 1 第二层的核心：优雅停止不只是"等 devin 退出"，而是
  "整个 pipe 走完"——devin 退出 → 判定 → kill → **解析 export → 写 DB → 更新
  audit_passed**，全部完成才算停
- 批次超时路径（`max_runtime * 10`）同样必须走收尾（033 P3-b）：超时退出时 pending
  可能未清空，但不收集就把已完成的部分又晾在中间态

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `docs/architecture/graceful-shutdown.md` **全文** | §3 实现（信号模块/主循环模式/stop_batch 两模式）+ **§6 新 Pipe 如何实现六步清单——这是你的施工图** |
| 2 | `monitoring/graceful_shutdown.py`（61 行） | register_shutdown/should_stop 用法 |
| 3 | `src/continuation_launcher.py` 搜 `should_stop`（4 处） | 续传的接线姿势：主循环检查位置、dequeue 条件、退出打印、graceful_stop 行为流水 |
| 4 | `src/proof_audit_launcher.py` **全文**（~452 行） | `launch_batch()` 主循环结构：退出条件（pending==0 and running==0）、批次超时分支、补充并发 while、running 检查段（完成/stall/dead 三类判定）、DONE.md 语义 |
| 5 | `src/proof_audit_result_collector.py` 的 `collect_results()` | 你要从中提取 `collect_one()`；注意 WP-N 已加的 `mark_parse_error` |
| 6 | `scripts/run_proof_audit_pipeline.py`（104 行） | `--stop` 选项加在哪、现有 stage 结构 |
| 7 | `dev-docs/030` §二 需求 1 段（只读需求 1） | 用户对优雅停止的完整定义（第一层+第二层） |
| 8 | `src/sim/` 目录 ls + `dev-docs/017` §隔离机制（选读） | sim 的 ARANGO_DB/REDIS_PREFIX 隔离旋钮——测试时用 |

## 3. 现场事实基线（2026-08-21 09:30）

- `proof_audit_launcher.py` **无** graceful_shutdown import；`launch_batch()` 主循环
  无 should_stop 检查；两个 break（自然完成/批次超时）都不收集
- `launch_batch` 结束后只打 `audit_batch_done` 日志——result_collector 是独立手动步骤
  （`run_proof_audit_pipeline.py --stage collect-results`）
- 复核：`grep -n "should_stop\|register_shutdown" src/proof_audit_launcher.py` → 空
- WP-N 已改 result_collector（有 mark_parse_error）；WP-P 已清现场（paudit:running=0，
  pending=130 待跑——这正好是你集成测试的现成批次）

**基线漂移预期**：WP-J（审计终态补全）也改这个文件的 running 检查段——**本 WP 先行**，
WP-J 在你的基础上改。若发现 running 检查段已有 rate_limit/pane 检测，说明 WP-J 已被
执行——照样继续（你的改动在主循环层，不冲突），执行记录注明。

## 4. 任务分解

### 任务 1：`collect_one()` 提取（result_collector）

把 `collect_results()` 循环体的单条处理逻辑（读 export → extract → parse →
PASS 走 finalize_pass / FAIL 走 finalize_fail / 解析失败走 WP-N 的 mark_parse_error）
提取为：

```python
def collect_one(db, audit_run) -> str:
    """收集单个已完成审计。返回 'pass' | 'fail' | 'parse_error' | 'skip'（无文本）。"""
```

`collect_results()` 改为循环调 `collect_one`（行为不变，重构不改变输出语义——先跑
一次重构后的 collect_results 对照 WP-P 时的输出模式确认无回归）。

### 任务 2：launcher 主循环接线（按 graceful-shutdown.md §6 六步）

对 `launch_batch()` 做：
1. 函数开头：`register_shutdown("proof_audit_launcher")`
2. 主循环顶部（两个 break 检查之后、补充并发之前）加 should_stop 分支：
   - `if should_stop():` 且 running 空 → 打印+`log_flow("graceful_stop", ...)` +
     **跳到收尾收集**（见任务 3）后 break
   - running 非空 → 打印"等待 N 个 running 自然完成"，跳过补充并发的 while
3. 补充并发 while 的条件加 `not should_stop() and ...`
4. **收尾即收集**：running 检查段里，每个审计被判定 completed（含 dead_done 分支）
   并 update_audit_run 后，立即：
   ```python
   from src.proof_audit_result_collector import collect_one
   result = collect_one(db, get_audit_run(db, audit_run_key))
   print(f"  [collect] {audit_run_key}: {result}")
   ```
   （失败分支 dead_session_no_export 无结果可收，跳过）
5. **三条退出路径统一收尾**：自然完成 break、批次超时 break、优雅停止 break——
   break 前都执行：
   ```python
   # 兜底收集：正常情况下收尾即收集已入库，这里抓漏网（如崩溃恢复后残留的 completed）
   from src.proof_audit_result_collector import collect_results
   collect_results(batch_id)
   ```
6. `log_event(logger, "info", "audit_batch_done", ...)` 保持最后

### 任务 3：`stop_audit_batch()` + `--stop` 入口

- `proof_audit_launcher.py` 加 `stop_audit_batch(batch_id, force=False)`（模仿
  `continuation_launcher.stop_batch`：优雅=pgrep 发 SIGINT；force=kill 所有
  `paudit-` 前缀 session + 清 Redis paudit 队列——用
  `src/proof_audit_redis_queue.py` 的键常量，不要手写字符串）
- `run_proof_audit_pipeline.py` 加 `--stop` / `--force` 参数转发

### 任务 4：文档同步

- `docs/architecture/graceful-shutdown.md`：§3 后新增 "3.4 审计 Pipe 实例"小节
  （简述接线差异：单队列、收尾即收集、批次超时也收尾）
- `docs/sop/SYSTEM_CLOSURE.md` §2 架构图审计段：proof_audit_launcher 职责行加
  "优雅停止（SIGINT）+收尾即收集"

### 任务 5：集成验证（sim 门禁的等效方案）

sim 无审计剧本（sim 是续传系统的），采用**小批次真跑 + SIGINT 实测**：

```
1. 准备：确认 paudit:pending 还有任务（WP-P 后应剩 ~130）；DB batch 记录此时还没有
   （WP-G 才建）——启动时用 --concurrency 2 --max-runtime 300
2. 启动：python -m src.proof_audit_launcher --batch-id paudit-p27-full --concurrency 2
   （放 tmux 里跑：tmux new-session -d -s paudit-launcher-test "..."，长命令铁律）
3. 等 2-3 个审计启动后（tmux list-sessions | grep ^paudit- 出现新 session）
4. 发 SIGINT：python -m scripts.run_proof_audit_pipeline --batch-id paudit-p27-full --stop
5. 断言 A：不再有新 session 启动（观察 60 秒 session 数不增）
6. 断言 B：已有 session 逐个完成后，p27_proof_audits 持续增长（收尾即收集生效）
7. 断言 C：launcher 进程最终自行退出；退出后 paudit:running==0
8. 断言 D：退出前打印的统计与 DB 一致
9. 测试完恢复现场：本次测试产生的 completed 审计是真实数据（批次就是真实批次），
   无需回滚——记录到执行记录即可
```

### 任务 6：py_compile + commit + 记录

## 5. 禁止事项

- ❌ **不引入 Redis 停止键**（`paudit:stop` 方案已被 036 D6 废弃——SIGINT 是唯一机制）
- ❌ 不改 `monitoring/graceful_shutdown.py`（共享模块，续传在用）
- ❌ 不动续传 launcher 的任何代码
- ❌ 收尾收集失败不能让 launcher 崩溃（collect_one/collect_results 包 try/except，
  失败记日志——收集可重试，崩溃不可接受）
- ❌ 不改 WP-J 范围的终态判定逻辑（rate_limit/pane 检测是 WP-J 的事，别顺手做）

## 6. 验收 checklist

- [ ] `grep -n "register_shutdown\|should_stop" src/proof_audit_launcher.py` — ≥3 处
- [ ] `grep -n "collect_one\|collect_results" src/proof_audit_launcher.py` — running 检查段 1 处 + 三条退出路径收尾
- [ ] `grep -n "stop_audit_batch" src/proof_audit_launcher.py scripts/run_proof_audit_pipeline.py` — 定义+入口
- [ ] `python -m py_compile` 三个改动文件全过
- [ ] 集成测试五断言（A 不再启动 / B 边完成边入库 / C 自行退出且 running=0 / D 统计一致 / 无新异常日志）输出贴记录
- [ ] graceful-shutdown.md §3.4 + SYSTEM_CLOSURE 已同步
- [ ] refactor 后 `collect_results` 对旧数据行为不变（无新 PASS/FAIL 产生——旧的是 audit_status==null 才收）

## 7. 完成汇报要求

执行记录：接线 diff 摘要、集成测试全程时间线（几点启动/几点 SIGINT/几点退出/收集了几条）、
三条退出路径各自如何验证（超时路径可用 `--max-runtime` 调小验证，写明用了哪种）、遗留。

## 8. 审计对照

1. 我会实测：再跑一次 SIGINT 流程（或读你记录的时间线），核对"收尾即收集"语义——
   p27_proof_audits 的 created_at 应早于 launcher 退出时间（边完成边入库），而不是
   退出后批量补
2. 批次超时路径：查代码三条 break 前都有 collect_results
3. grep 确认无 `paudit:stop` 字样引入
4. graceful-shutdown.md §3.4 的描述与实际接线一致（文档不撒谎）
