# WP-L — 基础设施失败自动重试（续传 + 审计共用，dry-run 先行）

> **优先级**: 第三批末（依赖 WP-I + WP-J + WP-K 全部完成——重试的正确性依赖终态分类正确）
> **依赖**: WP-I/J/K
> **预计规模**: 新文件 src/retry_infrastructure.py ~180 行 + 两个 DB schema 各加一个
> 字段 + dry-run 报告
> **性质**: 新守护进程逻辑（**不常驻启动**——先 dry-run + 手动 --once，常驻化在用户
> 批准 dry-run 结果之后）

---

## 0. 给执行 AI 的第一句话

续传和审计系统都会把基础设施失败（rate_limited/dead_session 等）写进 failed 队列并
标记 retry_eligible=True——**但全 repo 没有任何代码读这个标记**（031 A 组核实：4 处
写入 0 处读取），MAX_RETRIES=3 定义了从未使用。你要实现平凡系统 retry_infrastructure
模式的移植：扫描 failed → infra 类查重试计数 → 重入 pending（≤3 次）→ model 类
不动。**第一阶段只做 dry-run 和 --once 手动模式，不进常驻**——上常驻要用户看过
dry-run 分布报告确认分类无误后批准。

## 1. 背景（为什么）

- 030 需求 8 的一部分；平凡系统有独立守护进程（`retry_infrastructure.py` 循环扫描
  failed 队列，infra 类重入 pending，上限 3 次，model 类不重试是 Profile 数据）
- 前置依赖的道理：重试的正确性 = 分类的正确性。WP-K 修了"放弃题误入可重试类"；
  WP-J 给审计失败写了 verdict 原词——没有这两个，重试会把 model 失败也重试（浪费配额）
- "适度依赖"边界：重试决策是确定性规则（分类∈INFRA ∧ 计数<3 → 重试）——进代码；
  **是否常驻、上限值调整**是系统级决策——给用户

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `/Users/user/AI-Math-Normal-Solver/xishujuzhen/solver_harness/pipe/retry_infrastructure.py` **全文**（192 行） | 移植母本：retry_failed 的扫描/分类/计数/重入/队列重建逻辑、get_retry_count 的 AQL |
| 2 | **确认 WP-I/J/K 完成**（总控表） | classify_failure 含 crash_recovered；审计失败带 verdict 原词；ai_gave_up 不在 INFRA |
| 3 | `src/continuation_redis_queue.py`（261 行，重点函数签名） | 续传队列 API：enqueue_pending/pending/failed 的结构（add_failed 的 reason 字段就是你分类的依据）；**failed 是 list（lpush JSON）** |
| 4 | `src/proof_audit_redis_queue.py` | 审计同构 API |
| 5 | `src/continuation_launcher.py` 搜 `add_failed`（3 处） | 续传 failed 条目的字段格式：{"run_key", "reason"} |
| 6 | `src/proof_audit_launcher.py` 搜 `add_failed`（WP-J 后 ≥5 处） | 审计条目：{"audit_run_key", "reason"}——reason=verdict 原词 |
| 7 | `monitoring/graceful_shutdown.py` | 你若实现循环模式的 register_shutdown 接线（照抄平凡系统 main 的模式） |
| 8 | `dev-docs/031` WP-L 段（选读 20 行） | 设计要点：审计重试不需重备 work_dir（proof.txt/AGENTS.md 已在） |

## 3. 现场事实基线（2026-08-21 09:30 + 前序 WP 后）

- `retry_eligible`：continuation_launcher 4 处写（dead_session=True / infra 检测=
  classify 结果 / timeout=False / stall=False）+ WP-K 新增 ai_gave_up=False
- 重试计数**无处存**——平凡系统查 attempt 集合（每 attempt 一条），本 repo runs 每
  run 一条 → 需加字段 `retry_count`（默认 0）到 p27_continuation_runs 与
  p27_proof_audit_runs 的失败路径写入（或本 WP 在重入时惰性初始化——推荐后者，
  不动 launcher）
- Redis failed：续传 `p27:failed`（现存条数查 LLEN）、审计 `paudit:failed`
- 复核：`redis-cli LLEN p27:failed` / `LLEN paudit:failed`（数字记入执行记录——
  dry-run 的样本量）

**基线漂移预期**：WP-J 已给审计失败加 verdict/failure_category 字段——dry-run 的
分类读这些。若某失败条目是 WP-J 之前写入的（reason="stall_timeout"），分类按
reason 字符串映射（stall_timeout→max_runtime_exceeded→model）——加一个 legacy
映射表并记录。

## 4. 任务分解

### 任务 1：`src/retry_infrastructure.py` 实现

```
结构（移植平凡系统，适配双队列）：
  retry_continuation(r, db, max_retries, dry_run) -> dict 统计
    1. LRANGE p27:failed 0 -1 解析 [{run_key, reason}]
    2. 分类：reason → classify_failure（reason 字符串可能等于 status 词；
       legacy 映射：timeout→failed_timeout、stall→failed_stall、stall_timeout→
       max_runtime_exceeded）
    3. infra 类：
       retry_count = run_doc.get("retry_count", 0)
       if retry_count >= MAX_RETRIES: skipped_max += 1（保留在 failed）
       elif dry_run: 计划列表
       else: update run {status:"prepared", retry_count:+1, ...}（不覆盖 rounds_log）
             enqueue_pending(r, run_key, priority=9999)（排队尾——重试不抢队首）
             从 failed 移除
    4. model 类：不动，计数
    5. 队列重建（平凡系统的 remaining 模式）：只保留未重试的条目
  retry_audit(r, db, ...) 同构（audit_run_key / paudit:pending / status 回 prepared）
  main：--pipe continuation|audit|both / --dry-run / --once / --interval（循环模式
        含 register_shutdown；默认只跑一次不循环——常驻需用户批准）
```

要点：
- **审计重试不做 work_dir 重建**（proof.txt 已在——031 设计）；但检查 proof.txt 仍
  存在（不存在则不重试，报告数据问题）
- 重入 priority=9999（队尾）：与防抖重入队一致——重试不该插队
- update run 的 status 回 "prepared"：feeder/dequeue 链路自动接手（续传 launcher 的
  dequeue 读 Redis，谁入队？——**注意**：retry 自己 enqueue Redis，不走 feeder；审计
  同理）
- 统计输出（人话表）：total/infra/model/retried/skipped_max + model 类的 reason 分布
  （这个分布就是给用户判断分类是否正确的材料）

### 任务 2：dry-run 执行 + 报告

```
python -m src.retry_infrastructure --pipe both --dry-run
```
输出贴执行记录 + 写 `dev-docs/039-重试dry-run报告.md`：
- 续传/审计各自的分类分布表
- **重点审阅项**：model 类里有没有"看起来该重试的"（分类错误的信号）；infra 类里
  有没有 ai_gave_up/token_limit（WP-K/J 之前的历史数据可能混着——legacy 映射能兜多少）
- 结论建议：分类是否可信 / 建议常驻与否 → **等用户决策，不擅自 --once 实跑**

（例外：若 dry-run 显示 failed 队列为空或全是明确 model 类，无重试对象——报告写明
并结束本 WP，实跑留待有数据时。）

### 任务 3：--once 实跑（仅当用户批准 dry-run 后）

用户批准方式：对 039 报告回复"可实跑"或指定范围。实跑输出与 DB/Redis 前后对比贴记录。

### 任务 4：文档同步 + commit

- SYSTEM_CLOSURE：§4 表加 retry_infrastructure 行；§6 各阶段正常状态加"failed 队列：
  infra 类会被 retry（≤3）回收，model 类留存是 Profile 数据"
- `docs/architecture/`（新文档或并入 operational-concerns.md）："重试机制"一节
  （平凡系统模式 / 双队列 / 计数字段 / 常驻需批准）
- commit 显式路径

## 5. 禁止事项

- ❌ **不启动常驻循环**（--interval 模式实现了但不默认跑；常驻是用户决策）
- ❌ 不改 launcher 的失败写入逻辑（你只消费 failed 队列）
- ❌ model 类绝不重入（哪怕只有一条"看起来像误分类"——报告里列出来等人工）
- ❌ 不删 failed 队列里的 model 条目（它们是 Profile 数据——资产保留铁律同理）
- ❌ dry-run 之外的写操作全部禁止（dry-run 连 DB 都不该写——update/计数也要跳过）

## 6. 验收 checklist

- [ ] `python -m src.retry_infrastructure --pipe both --dry-run` 正常输出统计表（贴记录）
- [ ] dry-run 前后 `redis-cli LLEN p27:failed / paudit:failed` 与 DB run 状态**零变化**
      （dry-run 纯只读的证据）
- [ ] legacy reason 映射表存在（代码内）且 dry-run 输出体现映射后分布
- [ ] 单测或代码审查证据：计数上限逻辑（构造 retry_count=3 的假 run 走 dry-run →
      skipped_max）
- [ ] 039 报告存在，含分布表与"分类可信度"结论
- [ ] SYSTEM_CLOSURE / architecture 文档已同步
- [ ] py_compile；commit 显式路径
- [ ] 常驻未启动（ps 无 retry_infrastructure 进程）

## 7. 完成汇报要求

执行记录：dry-run 全输出、039 路径、(若批准)--once 的前后对比、遗留。

## 8. 审计对照

1. dry-run 纯只读验证（我会查 DB/Redis 快照对比——你执行记录里要有前后数字）
2. 分类逻辑我会构造 5 类样本（rate_limited/dead_session/crash_recovered/ai_gave_up/
   timeout）走 dry-run 验证归队正确
3. 重入 priority=9999（不抢队首——016 教训的延伸：任何入队不重置既有语义）
4. 常驻未启动
