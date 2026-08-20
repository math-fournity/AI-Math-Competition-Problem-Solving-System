# SYSTEM_CLOSURE — 系统级认知闭包（每次SOP执行前注入）

> 这是每次 SOP 执行前**前置注入**的系统级认知闭包。它告诉你"整个系统正常工作时
> 是怎样的"，让你在任何步骤、任何 Gate 触发时都能推理"系统现在工作得对不对"。
> 各步骤 SOP（L1）只补充该步骤特有的增量知识——系统级知识全在这里，不重复。
> Gate 论证依据（L2）引用本闭包的 §3 生命周期 / §6 判定框架。

---

## 1. 系统使命

用并发 devin cli 实例分析数学失败题——判定每道失败题是"**方向出错**"还是
"**token 不够**"，并分类卡点类型。用于 Mid-Hint 实验的选题阶段。

一句话：**判定截断 vs 思维错误**。截断=token不够（续传能救）；思维错误=方向出错
（续传救不了）。核心使命依赖截断判定引擎正确工作——017实证此前它结构性不可达。

## 2. 四 Pipe 架构 + 数据流

```
continuation_collector → continuation_feeder → continuation_launcher → continuation_result_collector
   收集失败题入DB          入Redis队列         并发启动devin cli解题       汇总最终结果
                                               ↑ 并发解题                    ↑ 结果
                         monitor_continuation（监控Pipe，每120s检查写alert到DB）
                         session_registry（session编号化管理）
                         step_gate（步进门闸，9个语义动作可hold/step）
                         observability（行为流水黑匣子，log/flow/）
```

当前只有 Pipe 4（续传）在运行。数据流：collector 把失败题入 DB(prepared) →
feeder 入 Redis pending → launcher 并发 dequeue 启动 devin cli → result_collector 汇总。

## 3. 一道题的完整生命周期（正常工作模式）

```
prepared（DB，等入队）
  ↓ feeder feed_enqueue（priority=0，NX幂等）
pending（Redis ZSET）
  ↓ launcher dequeue_pending（zpopmin，取最低score）
running（DB+Redis，占并发槽）
  ↓ launch_solve 启动 devin cli（tmux session）
  ↓ devin 跑完，写 export + DONE.md
  ↓ launcher judge：
     ├─ is_completed（proof有boxed+mtime本轮）→ finalize_run_completed → COMPLETED（终态）
     ├─ is_truncated（comp≥24000+rc>1000+msg=0）+ round<max → requeue_truncated → 回pending
     ├─ round==max → TRUNCATED_AT_MAX（终态）
     └─ 既非完成也非截断 → dead_session → FAILED（终态）
```

**正常生命周期**：prepared → pending → running → [截断→重入队→再running]循环
（最多 max_rounds 轮）→ COMPLETED 或 TRUNCATED_AT_MAX 或 FAILED。

**round-1 是 seed 预检轮**：launcher 首次取件时对 seed export 重判截断/完成，补录
rounds_log 条目。R2 起才是真正的续传轮（有 prompt/handover/proof）。正常轮序 [1,2,3..]
连续；出现重复轮号(如[2,2,3])=旧数据或 bug 复发。

## 4. 各模块职责

| 模块 | 职责 | 异常时的表现 |
|---|---|---|
| continuation_launcher | 并发引擎：dequeue→launch→judge→requeue/done | 失控循环（016：同题高频启动） |
| continuation_feeder | 把 prepared 入 Redis pending（NX幂等） | 死循环重喂（016：队列永远清不空） |
| monitor_continuation | 每120s检查写 alert（A类自动/B类质量） | 不写alert=检查失效 |
| session_registry | session 编号化管理（p27-s{seq}） | 注册表脱节（A13：tmux vs DB vs Redis） |
| step_gate | 9个语义动作可hold/step（DB信号单步跟踪） | — |
| observability | 行为流水黑匣子（log/flow/flow-*.jsonl） | 无记录=看不见流动（016根因） |

## 5. 数据产出全景

每道题每轮产生：conversation.json（export，devin的thinking）/ proof.md（解题产出，
含boxed）/ round{N}_HANDOVER.md（交接文档）/ round{N}_conversation_map.md（面包屑地图）
/ round{N}_prompt.txt / DONE.md（退出标记）/ tmux.log

DB 集合：p27_continuation_runs（每题续传记录，含rounds_log/status/final_status）/
p27_continuation_events（事件流）/ p27_continuation_results（最终结果，含proof文本双写）/
p27_sessions（session注册表）/ p27_step_gates（门闸状态）/ p27_monitor_alerts（alert）

rounds_log 每条7字段：export/truncated/completed/reason/method + handover_path/map_path/
prompt_path/prev_export/proof_path。round-1 只有 export（5基础字段）。

## 6. 正常工作判定框架（时刻推理用这个）

**正常工作的四个特征**（任何时候都该满足）：
1. **进度推进**：completed/failed 在增加，pending 在减少（不无限堆积）
2. **无失控循环**：行为流水 `observability --stats` 的 churn_suspects 为空
   （同题1小时启动<5次）
3. **四源一致**：tmux实际进程数 ≈ DB running数 ≈ Redis running数 ≈ batch设定concurrency
   （A13审计）
4. **数据完整**：每轮 export/proof/handover 都落盘，rounds_log 字段齐全

**各阶段正常状态**：
- prepared：不该无限堆积（feeder该入队）；prepared>0但pending=0=feeder没工作（critical）
- running：不超concurrency；每个running有对应tmux session和DB记录
- 截断重入队：判定有据（comp≥24000+rc>1000+msg=0）；score=round_num排队尾
  （NX不被feeder重置）
- completed：proof有boxed+mtime本轮；proof文本已入库（双写）

**Monitor A类检查14项的正常标准**（monitor_continuation每120s自动执行，alert写DB p27_monitor_alerts）：
- A1 session_health: session数≈DB running≈设定并发（不匹配=launcher挂/孤儿）
- A2 queue_stalled: pending在减少（15分钟无变化=critical）
- A3 no_completions: completed在增加（15分钟无增加=warning）
- A4 rate_limit: rate_limited<3个（≥3=critical）
- A5 zombie_sessions: 无空pane僵尸session（≥2=warning）
- A6 export_landing: completed的run都有export（缺失>10%=critical）
- A7 failure_rate: 失败率<15%（>15%=warning）
- A8 launcher_dead: launcher活着（消失但有任务=critical）
- A9 stall_detection: 单轮<30分钟（超时=warning）
- A10 session_registry: 注册表≈tmux实际（不一致=critical/warning）
- A11 stuck_sessions: stuck<5（>5=warning，>10=critical）
- A12 done_uncleaned: done未清理<20（>20=info）
- A13 real_concurrency: 四源一致（见上方特征3，任何不一致=critical，016新增）
- A14 launch_churn: churn_suspects为空（同题1小时≥5次=critical，016新增）
> 时刻推理：拿到检查输出后逐项对照——哪项偏离正常标准=那个维度有问题。

**异常信号**（看到就警觉）：
- 016失控循环：churn_suspects非空 / session数暴涨 / 同题高频launch → 立即kill launcher+清队列
- A13四源不一致：孤儿进程/注册表脱节 → `sessions --consistency-check` 清理
- 截断误判：真实截断被当dead_session（017 P0，截断引擎此前不可达）→ 检查is_truncated是否先于dead
- proof残留：旧proof被误判完成（016 P0-2）→ 检查mtime归属

## 7. 关键铁律索引

1. 绝不 kill 无 DONE.md 的 session（dead_session是唯一例外：DONE.md已出现但无proof）
2. git 显式路径 add（禁止 git add -A/. /-u）
3. 改代码同步更新第一级文档（docs/system/architecture/specs/patterns）
4. 成果文件双写（proof入库，不依赖盘上单点——018教训）
5. 改调度逻辑后跑 sim 发布门禁（solve3+chaos_016——016 P0-1引入新死循环的教训）
6. Gate 放行必须附 --reason 理由（落盘flow流水，没有理由=审计断点）

---

> 下方是该步骤的 SOP 文档（L1 增量知识）+ 自动化检查输出（含 Gate Y 通道的 L2 论证依据）。
> 三层结合：你先有系统整体认知（本闭包），再看该步骤做什么，再看检查结果——
> 任何时候都能推理"系统现在工作得对不对"。