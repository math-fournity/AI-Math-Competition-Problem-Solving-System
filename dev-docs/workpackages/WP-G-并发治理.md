# WP-G — 并发治理：删除三处写死并发 + 审计并发从 DB batch 读取 + 实验定值

> **优先级**: 第一批末（实验项在 WP-P 后、最好 WP-H 后跑——审计批次能正常启动停止）
> **依赖**: WP-P（清场）；实验项依赖 WP-H（批次可优雅启动）
> **预计规模**: 4 个文件 ~80 行改动 + set-concurrency 验证 + 实验记录文档
> **性质**: 代码修复（违反 AGENTS.md 硬约束的三处写死）+ 配置机制 + 实验

---

## 0. 给执行 AI 的第一句话

AGENTS.md 硬约束（2026-08-21 62a4cc0）："**禁止代码中写死并发数**——并发数的默认值
来源只有一个：本 AGENTS.md"。当前 repo 有**三处**违规（AGENTS.md 只列了两处，031 C3
发现第三处）。你要删掉全部写死默认值、让审计 launcher 像续传 launcher 一样从 DB
batch 记录读并发（DB 无记录报错，不用默认值兜底），最后用 concurrency=1 实测审计
批次给用户一个有依据的并发推荐值。

## 1. 背景（为什么）

- 并发数 = 同时在跑的管线条数 = devin cli 实例数上限（用户在 030 需求 2 亲自教的
  并发模型）——它是系统级配置（影响 API 配额/rate limit），不是代码常量
- `AUDIT_DEFAULT_CONCURRENCY = 5` 是照搬续传的 5，没有任何推理依据（030 §5.1 溯源
  结论："拍脑袋"）——这正是用户质疑的起点
- 续传 launcher 已有正确的动态并发模式：启动读 DB（有则不覆盖）+ 每轮 poll 刷新
  （`continuation_launcher.py` 搜 `db_concurrency`）——审计同构复用

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `AGENTS.md` 搜"禁止代码中写死并发数" | 硬约束全文：为什么/正确做法/**当前违规清单（注意它列的是 2 处，实际 3 处——见 §3）**/修复方向 |
| 2 | `src/continuation_config.py` 第 74-79 行附近 + `src/proof_audit_config.py` 第 41-45 行 | 两个写死常量及其注释（注释也删） |
| 3 | `scripts/run_proof_audit_pipeline.py` 第 70-80 行 | 第三处：argparse `--concurrency default=5` |
| 4 | `src/continuation_launcher.py` 搜 `concurrency` 的启动读 DB 段 + 每轮 poll 段（两段，共 ~25 行） | 你要给审计 launcher 抄的同构模式 |
| 5 | `monitoring/continuation_control.py` 的 `set-concurrency` 实现（搜 "set_concurrency" 或 cmd_set_concurrency） | 它是通用 update `p27_continuation_batches.{batch_id}.concurrency`——**审计批次记录放同一个集合后无需改此命令** |
| 6 | `src/continuation_launcher.py` 搜 `DEFAULT_CONCURRENCY` | 全部消费点（launch_batch 默认参数 + main argparse default）——你删常量时要改的消费点清单 |
| 7 | `src/monitor_continuation.py` 搜 `expected_concurrency` | WP-G 顺带检查：它的默认值已是 1（c2be5d4 改过）——确认它从哪取值，若硬编码来源是常量则同步调整 |
| 8 | `docs/architecture/dynamic-concurrency.md` §2 | DB 记录方案的设计语义（更新文档时引用） |

## 3. 现场事实基线（2026-08-21 09:30）

三处写死（复核：逐一 grep）：
1. `src/continuation_config.py:75` — `DEFAULT_CONCURRENCY = 5`
2. `src/proof_audit_config.py:42` — `AUDIT_DEFAULT_CONCURRENCY = 5`
3. `scripts/run_proof_audit_pipeline.py:76` — `parser.add_argument("--concurrency", type=int, default=5, ...)`

其他事实：
- 续传 launcher 的消费点：`launch_batch(concurrency=DEFAULT_CONCURRENCY, ...)` 默认参数
  + `main()` 的 argparse default
- 审计批次在 `p27_continuation_batches` 集合**没有**记录（审计 batch_id=paudit-p27-full
  从未写入该集合）——你的任务 2 会建
- 生产 batch `p27-full` 的 DB concurrency 字段：启动时初始化过（AGENTS.md 启动命令
  `--concurrency 1`）——**不要动它的值**
- `AUDIT_MAX_RUNTIME_SECONDS=600` 等其他常量**不在本 WP 范围**（它们不是并发数）

**基线漂移预期**：无（前三批 WP 不碰这些文件，除了 WP-H 碰过 proof_audit_launcher——
它 import AUDIT_DEFAULT_CONCURRENCY 的行在你改动后要同步，见任务 1）。

## 4. 任务分解

### 任务 1：删三处写死，消费点改 None-语义

**continuation 侧**：
- `continuation_config.py`：删除 `DEFAULT_CONCURRENCY = 5` 行
- `continuation_launcher.py`：
  - `launch_batch(batch_id, concurrency=None, ...)`——函数内启动逻辑改为：
    ```
    existing = db.collection(CONTINUATION_BATCHES_COLLECTION).get(batch_id)
    if existing and "concurrency" in existing: concurrency = existing["concurrency"]
    elif concurrency is not None: pass  # 命令行显式传值→初始化 DB（现有 update_batch 已做）
    else: print 报错（提示 set-concurrency 用法）并 return
    ```
    （现有代码已是前两步，只缺 else 报错分支——最小改动）
  - `main()` argparse：`default=None`
- `monitor_continuation.py`：`expected_concurrency` 若引用常量已删——改为从 DB batch
  读（或 None=不检查并注释说明）。查清消费逻辑后选最小改法。

**audit 侧**：
- `proof_audit_config.py`：删除 `AUDIT_DEFAULT_CONCURRENCY = 5` 行及注释
- `proof_audit_launcher.py`：
  - `launch_batch(concurrency=None, ...)`，启动时**在
    `p27_continuation_batches` 集合 get/初始化 `batch_id`（如 paudit-p27-full）的
    concurrency 字段**——与续传完全同构（含"DB 有则不覆盖"）；
    **每轮 poll 从 DB 刷新**（抄续传的 try/except pass 模式）
  - `main()` argparse：`default=None`
- `run_proof_audit_pipeline.py`：`--concurrency default=None`（None 时透传给
  launch_batch 走 DB 逻辑）

**报错文案**（三处统一人话）：
`"并发数未设置：DB batch 记录无 concurrency 字段且未传 --concurrency。请先 python -m monitoring.continuation_control set-concurrency --batch-id <id> --concurrency N"`

### 任务 2：验证 set-concurrency 对审计批次可用

```
python -m monitoring.continuation_control set-concurrency --batch-id paudit-p27-full --concurrency 1
# 断言：p27_continuation_batches 多出/更新 paudit-p27-full 文档，concurrency=1
# 断言：p27-full 的 concurrency 值未被影响
```

### 任务 3：并发数实验（concurrency=1 跑审计批次，产出依据）

前置：WP-P 已清场（pending ~130）、WP-H 已完成（可优雅停止）。

```
1. set-concurrency --batch-id paudit-p27-full --concurrency 1
2. tmux 启动审计批次（python -m src.proof_audit_launcher --batch-id paudit-p27-full，
   不传 --concurrency——验证 DB 读取路径）
3. 观察记录（每 10 分钟一次，共 40-60 分钟或跑完 8-10 题）：
   - 单题耗时分布（audit_batch 日志/DB 的 started_at→ended_at）
   - rate limit 迹象（tmux pane/日志搜 rate limit 模式）
   - 收尾即收集正常（WP-H 生效）
4. 中途可 SIGINT 优雅停（同样在验证 WP-H），实验分段进行没问题
5. 写 dev-docs/051-审计并发实验记录.md：
   - 实验设计 / 数据（每题耗时表）/ rate limit 观察
   - 推理：按用户并发模型（审计管线并发=审计 devin cli 总数），基于实测单题耗时
     与 rate limit 表现，给出推荐并发数及依据（宁可保守起步）
   - **结论只推荐不设定**——最终值由用户 set-concurrency 或告知你设定
```

### 任务 4：文档同步

- `AGENTS.md`："当前违规"清单改为已修复状态（3 处→全部修复，注明 commit）
- `docs/sop/SYSTEM_CLOSURE.md` §5 配置参数表：删 DEFAULT_CONCURRENCY 行，改为
  "并发数唯一来源：DB batch.concurrency（set-concurrency 设置）"
- `docs/architecture/dynamic-concurrency.md`：加一段"审计批次同构复用同一集合与命令"
- `dev-docs/051`（任务 3 产出）

### 任务 5：py_compile + 回归检查 + commit

```
python -m py_compile src/continuation_config.py src/continuation_launcher.py \
  src/proof_audit_config.py src/proof_audit_launcher.py \
  scripts/run_proof_audit_pipeline.py src/monitor_continuation.py
grep -rn "DEFAULT_CONCURRENCY\|default=5" src/ scripts/ monitoring/ --include="*.py" | grep -v sim
# 期望：无残留（sim 剧本里的字面量若有，逐一检查是否并发语义——是则一并清理并记录）
```

## 5. 禁止事项

- ❌ 不要给"DB 无记录"写任何数值兜底（报错退出是设计要求——硬约束原文）
- ❌ 不要动 p27-full 生产批次的 concurrency 值
- ❌ 不要删 `AUDIT_MAX_RUNTIME_SECONDS`/`AUDIT_STALL_SECONDS` 等**非并发**常量
- ❌ 实验不要跑 concurrency>2（实验目的是定依据，不是赶进度；130 题跑多久都行）
- ❌ 文档示例中的 `--concurrency 1` **显式传参**是允许的（不是写死默认值）——
  watchdog 脚本/文档里的显式传参不要"顺手清理"

## 6. 验收 checklist

- [ ] `grep -rn "= 5" src/continuation_config.py src/proof_audit_config.py` — 无并发常量
- [ ] `grep -n "default=5" scripts/run_proof_audit_pipeline.py` — 无
- [ ] 三处消费文件 py_compile 过；`grep -rn "DEFAULT_CONCURRENCY" src/ scripts/ monitoring/` 仅剩合理引用（应为 0）
- [ ] DB 无记录 + 不传参 → 启动报错退出（贴输出）；DB 有记录 → 正常启动且用 DB 值（贴启动行打印）
- [ ] set-concurrency 对 paudit-p27-full 生效且不影响 p27-full（贴两个文档的值）
- [ ] 每轮 poll 刷新生效：运行中 set-concurrency 改值，launcher 下轮打印调整日志
- [ ] dev-docs/051 实验记录存在，含单题耗时数据表与推荐推理
- [ ] AGENTS.md / SYSTEM_CLOSURE / dynamic-concurrency.md 已同步

## 7. 完成汇报要求

执行记录：三处删除的 diff、报错路径与正常路径的实测输出、set-concurrency 双批次
验证、实验数据摘要与推荐值、051 文档路径。

## 8. 审计对照

1. 我会 grep 全 repo 找任何残留的并发数值默认（包括新引入的）——**零容忍**
2. 实测 DB-无-记录报错路径（我会故意用一个假 batch-id 启动验证报错文案）
3. 051 的推荐值必须有数据支撑（每题耗时表），不接受"建议 5 因为感觉可以"
4. p27-full 的 concurrency 值前后对比未被改变
