# SOP_01：系统存活 + 进度 + Session 检查

## 认知闭包（执行前必读）

### 你是谁

你是续传解题系统的 Monitor AI。系统正在用并发 devin cli 实例对数学失败题做续传解题（POC-2.7，batch_id=p27-full）。你的角色是持续监控这个系统的运行健康度，发现问题并修复。

> 系统整体认知（架构/数据流/生命周期/判定框架）见上方注入的 **SYSTEM_CLOSURE（L0）**。
> 本节只补充本步骤特有的增量。

### 关键服务进程（本步骤检查对象）

- `p27-launcher` — 续传启动器，并发启动 devin cli 解题实例
- `monitor-p27` — 监控 Pipe，每 120 秒检查一次系统状态写 alert
- `p27-watchdog` — 看门狗，每 30 秒检查 launcher/monitor 是否活着，死了就重启

如果这三个进程任何一个不在了，系统就有问题。

### 本步骤检查什么

上方"自动化检查结果"是 `monitor_check_continuation.sh` 的输出，包含 8 项基础检查。你需要逐项阅读并判断系统是否健康。

> **数字口径说明**：8 项基础检查 + 门闸Y通道 + 行为流水快照（016后新增）= check_01 实际输出 10 项；A13/A14（016新增）+ B1-B4（续传质量）等完整 14 项 A/B 类检查清单见 SYSTEM_CLOSURE §6。

---

## 执行指令

### 1. 阅读检查脚本的 8 项输出

上方已经运行了 `monitor_check_continuation.sh`，输出在"自动化检查结果"部分。逐项阅读：

1. **Monitor Pipe pane 输出** — monitor 是否在正常运行
2. **alerts 集合** — 有没有新 alert（critical/warning/info）
3. **进程状态** — launcher/monitor/watchdog 是否活着
4. **进度** — pending/running/completed/failed 各多少
5. **session 注册表一致性**（A10）— 注册表 vs tmux 实际 session
6. **stuck session 统计**（A11）— stuck 状态的 session 数量
7. **done 未清理 session**（A12）— done 但没清理的 session 数量
8. **运行时健康检查**（10 维度 A-J）— Redis原子性/DB一致性/重复运行/并发限制等

### 2. 判断系统健康度

| 现象 | 判定 | 后续 |
|---|---|---|
| 所有进程活着 + 进度在推进 + 无 critical alert | 健康 | 继续 SOP 循环 |
| 有 critical alert | 需处理 | 步骤03分类 |
| launcher/monitor 不在了 | 系统停了 | 需要重启（见下方） |
| pending=0 且 running=0 | 批次完成 | 步骤06写最终报告后停止 |
| stuck session > 10 | 堆积 | 步骤03分类，可能需清理 |
| 进度长时间不变 | 停滞 | 步骤03查 alert 原因 |

### 3. 如果需要重启服务

```
# 重启 launcher + monitor
python -m monitoring.continuation_control start --batch-id p27-full --concurrency 1
# 注意：--concurrency 1 只是初始值。如果 DB 的 batch 记录里已有 concurrency 字段，
# launcher 会用 DB 的值覆盖命令行参数。运行中改并发用 set-concurrency（见 AGENTS.md）。

# 单独重启 monitor
python -m src.monitor_continuation --batch-id p27-full --interval 120 &
```

> **这两条都是短命令，可以直接在 shell 里裸跑**：`continuation_control start` 执行完就退出，它内部自己用 `tmux new-session -d` 把 launcher/monitor/watchdog 三个长服务各自放进独立 tmux session（`continuation_control.py:158-161`）——你不需要手动套 tmux。`sop.run` 同理，每次只跑一个 SOP 步骤就退出（`scripts/sop/run.py:48-113`），7x24 循环是 Master Agent 用 `todo_write` 自驱动一次次执行 `sop.run`，承载者是 AI 本身。

### 4. Session 注册表深度检查（SESS-01~12 需求点）

除了检查脚本的输出，你还需要用以下命令检查 session 注册表：

```
python -m monitoring.continuation_control sessions --consistency-check
python -m monitoring.continuation_control sessions --status stuck
python -m monitoring.continuation_control sessions --status done
```

检查项：
- 注册表中有但 tmux 无的 session（可能 devin cli 崩溃）
- tmux 有但注册表无的 session（手动启动的未注册 session）
- stuck session 数量和时长
- done 未清理 session 数量（占 tmux 资源）

### 5. 环境检查（ENV-01~07 需求点）

在检查系统进程之前，先确认基础设施正常：

```
echo $ARANGO_DB    # 必须输出 xishujuzhen_math_glm52，如果为空先 source .env
```

检查项：
- **ArangoDB 连接**——`python3 -c "from src.continuation_db_schema import connect_db; db=connect_db(); print(db.properties())"` 能连接
- **Redis 连接**——`python3 -c "from src.continuation_redis_queue import ping; print(ping())"` 输出 True
- **D盘挂载**——`ls /Volumes/data/` 能列出内容（解题数据在D盘）
- **.env 已 source**——`echo $ARANGO_DB` 不为空

如果任何基础设施不正常，记录为 critical 问题——系统无法正常运行。

### 6. 深入了解（如需）

如果需要更深入理解系统架构，加载以下文档：
- `docs/architecture/solve-pipeline.md` — 解题管线核心概念（并发=管线条数=devin cli实例数）
- `docs/architecture/operational-concerns.md` — rate_limit/stall/zombie 的运维处理方式
- `docs/architecture/dynamic-concurrency.md` — 动态并发机制

---

## 你需要建立的 todo list

根据检查结果建立 todo list：
- 发现的问题（每个一个 todo）
- **填写 report.md 报表**（read加载→打勾填发现→edit写回）
- **最后一项固定是**：`执行下一个脚本: python -m scripts.sop.run`

完成所有 todo 后，最后一项自动触发步骤02（数据完整性）。

### 7. 日志观察（检查日志中的异常）

日志是检查点——通过日志可以观察系统运行过程中的所有事件。使用日志检索脚本：

```
# 查看最近的 ERROR 级别日志
python -m scripts.sop.log_search --level ERROR --tail 20

# 查看最近的问题题处理事件
python -m scripts.sop.log_search --event infra_failure --tail 20
python -m scripts.sop.log_search --event timeout --tail 20
python -m scripts.sop.log_search --event stall --tail 20
python -m scripts.sop.log_search --event dead_session --tail 20

# 查看最近的 session 事件
python -m scripts.sop.log_search --event mark_stuck --tail 20
python -m scripts.sop.log_search --event consistency_check --tail 5

# 查看某道题的全部事件
python -m scripts.sop.log_search --problem-id <problem_id>

# 按时间范围检索
python -m scripts.sop.log_search --event launch_solve --since "2026-08-20 01:00" --until "2026-08-20 02:00"

# 统计（不输出详情）
python -m scripts.sop.log_search --event launch_solve --stats
```

日志文件位置：`log/`（项目本地，循环覆盖，最多500个文件/500MB）
日志格式：`[时间戳] [级别] [模块] event=事件名 problem_id=xxx round=x session_key=xxx`

### 8. 系统流动历史观察（行为流水，016事故后新增——必查项）

日志是"事件流"，但**看不到系统的逻辑流动**——谁被取出、为什么被跳过、判定为什么失败、
为什么重入队。016事故（`dev-docs/016`）中失控循环跑了18分钟上千次，所有存量检查
（队列数/session数）都看不见，因为存量没变化，**流动是病态的**。

行为流水（`log/flow/flow-YYYYMMDD.jsonl`）记录 launcher 的每个状态转移：
dequeue → skip/launch → judge → requeue/done。**每轮SOP_01必查**：

```
# 一眼视图：聚合统计（启动速率/每题启动次数Top10/失控嫌疑/判定分布/重入队原因）
python -m src.observability --stats --since 1h

# 看最近的系统行为（最近50条状态转移）
python -m src.observability --tail 50

# 深挖某道题的完整生命周期（含所有判定理由）
python -m src.observability --run-key p27-full-amo_bench_00000006

# 只看某一类事件（如所有防抖拦截）
python -m src.observability --event skip_orphan --since 2h
```

**判断标准**：

| 现象 | 判定 | 后续 |
|---|---|---|
| `churn_suspects` 非空（1小时内某题启动≥5次） | **失控循环正在发生** | 立即按016报告§5处置：kill launcher→清队列→查根因 |
| 启动速率异常高（如>10/分钟，并发≤5时） | 可疑 | 看`--tail`找循环模式 |
| `requeue_reasons` 大量同类原因 | 判定逻辑可疑 | 查对应judge事件的reason |
| `judge_outcomes` 出现大量stale_proof/stale_export | 旧产物残留 | 检查work_dir是否混有历史文件 |
| 事件速率≈0且pending>0 | 系统停滞 | 结合A2队列停滞检查 |

### 8.5 步进门闸——单步跟踪系统（016事故后新增）

行为流水让你**看见**流动，门闸让你**卡住**流动。`@gated`装饰器把系统的
9个语义动作（launcher 8个：启动/杀session/重入队/覆盖文件/写终态 +
feeder 1个：初次入队）变成可单步跟踪的门闸。**hold住一个门闸后，系统
在该动作点冻结等你放行**。

**X/Y注意力模型（你只需在Y出现时操心）**：
- X（mode）是你布防的控制变量；Y（waiting_for）是代码冻结时的需求发起；
- 无Y=不操心（auto模式静默记gate_pass流水，事后可审计）；
- **每轮例行检查里脚本已自动查Y**（上面"门闸Y通道"段）——有Y时会完整
  打印该闸的"放行前检查"清单（认知闭包），你按清单核对后
  `--step` 放行或维持hold。这就是单步跟踪：像工程师断点调试一样，
  冻结点+检查清单+核对+继续。

```
python -m src.step_gate --list      # 门闸目录（按resource分组）
python -m src.step_gate --hold GATE-LAUNCH-SOLVE   # 卡住下一次解题启动
python -m src.step_gate --pending   # 看谁在等（完整输出checklist+论证依据闭包）
python -m src.step_gate --step GATE-LAUNCH-SOLVE --reason '看到1✓+2✓+3✓+4✓，理由：前置条件满足'   # 放行（必须附理由）
python -m src.step_gate --auto GATE-LAUNCH-SOLVE   # 恢复自动
python -m src.step_gate --hold-resource tmux       # 按分类批量hold
```

**落盘论证（铁律）**：放行必须用 `--reason` 附理由——理由落盘到 `gate_release`
行为流水（log/flow/，grep可回溯"某轮某闸放行了什么、为什么"）。`--pending`
输出的checklist闭包现在含【检查项】（含查法）+【论证依据】（可放行+理由/不可放行+理由），
你按论证依据核对后附理由放行。**不放行（维持hold）也要在 report.md 的门闸记录区填写原因。**
没有理由的放行=审计断点，016教训：失控循环就是"无人论证的动作连续发生"。

**使用时机**：怀疑某个动作有问题时（如A14报了launch_churn），hold住对应
门闸逐次放行+检查；日常监控不需要hold。hold会阻塞launcher主循环，
用完记得--auto。设计范式详见 `docs/patterns/StepGate.md`（含"为什么
底层I/O封装不设闸"的教训）。

### 8.6 系统运行过程全景视图（过程叙事，AI分析推理的基础——023方案新增）

行为流水的 `--stats` 给统计聚合（启动频率/判定分布），`--tail` 给原始事件流（逐条JSONL），
但都不回答"**系统作为一个整体在如何运行**"。全景视图把行为流水+门闸流水组织成4层过程叙事：

- **L1 现状**：系统现在在做什么（活跃管线+阶段+进展，不是"running=3"这样的数字）
- **L2 流畅性**：运行过程是否顺畅（速率时间线+卡顿/循环检测，不是统计表）
- **L3 流程合规**：管线流程是否符合设计（事件序列完整性+门闸通过情况）
- **L4 趋势**：运行趋势是什么（完成/失败时间序列+失败模式分布变化）

每轮 SOP_01 自动输出全景视图（上方"系统运行过程全景视图"段）。你需要在认知闭包背景下
阅读这4层，**分析和推理**（不是逐项打勾检查）：

1. **L1 现状**——系统在做什么？这些管线在正确阶段吗？进展合理吗？
2. **L2 流畅性**——节奏正常吗？有卡顿/循环吗？卡顿的原因是什么？
3. **L3 流程合规**——流程按设计走吗？有异常事件序列吗？门闸正常吗？
4. **L4 趋势**——系统在变好还是变差？失败模式在变化吗？

这是"持续思考系统是否正常"的核心——不是逐项打勾检查，而是从过程视角推理系统运行。
与 §8 行为流水快照（统计聚合）互补：快照给你数字，全景给你过程叙事。

手动查看（更长窗口或单层）：
```
python -m scripts.sop.system_panorama --batch-id p27-full --since 2h   # 2小时窗口
python -m scripts.sop.system_panorama --batch-id p27-full --layer L1   # 只看现状
```

### 9. devin cli model 参数检查（CHECKPOINT）

每次启动 devin cli 解题时，日志中会记录 `event=devin_cli_launch model=xxx`。
**model 参数必须是 `devin models list` 中的有效值**。

当前配置：
- `src/continuation_config.py`: `DEVIN_MODEL = "glm-5-2"`（GLM-5.2 High, 200K context, Free）✅

检查日志中的 model 参数：
```
# 查看所有 devin cli 启动事件和其 model 参数
python -m scripts.sop.log_search --event devin_cli_launch --tail 30

# 统计使用了哪些 model
python -m scripts.sop.log_search --event devin_cli_launch --stats
```

如果发现 model 参数为空或值无效（不在 `devin models list` 中），这是 critical 问题——devin cli 会启动失败或使用错误模型。
