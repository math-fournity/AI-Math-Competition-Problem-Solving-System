# SOP_01：系统存活 + 进度 + Session 检查

## 认知闭包（执行前必读）

### 你是谁

你是错题分析系统的 Monitor AI。系统正在用并发 devin cli 实例对数学失败题做续传分析（POC-2.7，batch_id=p27-full）。你的角色是持续监控这个系统的运行健康度，发现问题并修复。

### 系统架构（最小必要认知）

系统有 4 个 Pipe，当前只有 Pipe 4（续传）在运行：

```
continuation_collector → continuation_feeder → continuation_launcher → continuation_result_collector
                                              ↑ 并发解题                    ↑ 结果汇总
                                              monitor_continuation（监控Pipe，写alert到DB）
                                              session_registry（session编号化管理）
```

**关键服务进程**（tmux session）：
- `p27-launcher` — 续传启动器，并发启动 devin cli 解题实例
- `monitor-p27` — 监控 Pipe，每 120 秒检查一次系统状态写 alert
- `p27-watchdog` — 看门狗，每 30 秒检查 launcher/monitor 是否活着，死了就重启

如果这三个进程任何一个不在了，系统就有问题。

### 数据库

- ArangoDB `xishujuzhen_math_glm52`（localhost:8529）
- 关键集合：`p27_continuation_runs`（每道题的续传记录）、`p27_sessions`（session注册表）、`p27_monitor_alerts`（alert）

### 本步骤检查什么

上方"自动化检查结果"是 `monitor_check_continuation.sh` 的输出，包含 8 项检查。你需要逐项阅读并判断系统是否健康。

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
python -m monitoring.continuation_control start --batch-id p27-full --concurrency 5

# 单独重启 monitor
python -m src.monitor_continuation --batch-id p27-full --interval 120 &
```

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
- `docs/system/AnalysisSystemDesign.md` — 系统设计总索引（含§6关键设计决策）
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

### 9. devin cli model 参数检查（CHECKPOINT）

每次启动 devin cli 解题时，日志中会记录 `event=devin_cli_launch model=xxx`。
**model 参数必须是 `devin models list` 中的有效值**。

当前配置：
- `src/continuation_config.py`: `DEVIN_MODEL = "glm-5-2"`（GLM-5.2 High, 200K context, Free）✅
- `src/config.py`: `DEVIN_MODEL = "glm-5-2"`（Pipe 1/2/3 用，已修正）✅

检查日志中的 model 参数：
```
# 查看所有 devin cli 启动事件和其 model 参数
python -m scripts.sop.log_search --event devin_cli_launch --tail 30

# 统计使用了哪些 model
python -m scripts.sop.log_search --event devin_cli_launch --stats
```

如果发现 model 参数为空或值无效（不在 `devin models list` 中），这是 critical 问题——devin cli 会启动失败或使用错误模型。
