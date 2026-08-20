# SOP检查报表 — step_01 系统存活+进度+Session

> **填写说明**：本模板由 `scripts/sop/run.py` 自动复制到D盘报表目录。AI加载后逐项检查并填写，填写完用edit写回同一文件。
>
> **打勾规则**：`[x]` 通过 · `[!]` 有问题 · `[ ]` 待检查 · `[-]` 不适用

---

## 系统快照摘要

> 以下数据从 snapshot.json 自动填充。AI填写报表前先读 snapshot.json 确认数据。

| 指标 | 值 |
|---|---|
| 总run数 | （从snapshot.json读取） |
| pending | （从snapshot.json读取） |
| running | （从snapshot.json读取） |
| COMPLETED | （从snapshot.json读取） |
| failed | （从snapshot.json读取） |
| 完成率 | （从snapshot.json读取） |
| sessions总数 | （从snapshot.json读取） |
| results集合数 | （从snapshot.json读取，应≥COMPLETED） |
| events总数 | （从snapshot.json读取） |

---

## 检查项清单

### 一、自动化检查项（读 check_output.txt 的输出填写）

> check_output.txt 是 `monitor_check_continuation.sh` 的8项输出 + `check_01_system_health()` 的输出。

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| 1 | Monitor Pipe pane输出 | 读check_output.txt第1节"Monitor Pipe pane输出"。最近3轮监控输出是否正常——有无error/exception | [ ] | |
| 2 | alerts集合 | 读check_output.txt第2节"alerts集合"。有无未处理critical alert | [ ] | |
| 3 | 进程状态 | 读check_output.txt第3节"进程状态"。launcher/monitor/watchdog 3个进程是否存活 | [ ] | |
| 4 | 进度 | 读check_output.txt第4节"进度"。pending是否在减少/completed是否在增加 | [ ] | |
| 5 | 续传质量汇总 | 读check_output.txt第5节"续传质量汇总"。proof统计/截断统计是否正常 | [ ] | |
| 6 | 通过率判定 | 读check_output.txt第6节"通过率判定"。通过率是否达标 | [ ] | |
| 7 | 系统健康 | 读check_output.txt第7节"系统健康"。DB/Redis/Disk是否正常 | [ ] | |
| 8 | 运行时健康检查10维度 | 读check_output.txt第8节"运行时健康检查"。A-J 10维度有无⚠️ | [ ] | |
| 9 | 门闸Y通道 | 读check_output.txt末尾"步进门闸Y通道"节。无Y=✅跳过；有Y=系统冻结在该闸——按打印的checklist闭包逐项核对后 --step 放行或维持hold并记录原因 | [ ] | |
| 10 | 行为流水观察（016预警核心） | SOP_01 §8要求每轮必查。运行`python -m src.observability --stats --since 1h`。`churn_suspects`非空(1小时内某题启动≥5次)=失控循环正在发生，立即按016报告§5处置(kill launcher→清队列→查根因) | [ ] | |

### 二、AI判断检查项

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| SESS | Session注册表深度检查 | `python -m monitoring.continuation_control sessions --consistency-check`。逐项检查SESS-01~12需求点。 | [ ] | |
| ENV | 环境检查 | 确认ARANGO_DB环境变量设置正确。确认D盘挂载。确认Redis运行。逐项检查ENV-01~07。 | [ ] | |
| H1 | 系统健康度综合判断 | 综合8项自动化检查+SESS+ENV，判断系统是否健康。如果 unhealthy→需要重启什么服务？ | [ ] | |

### 三、门闸放行/hold记录（落盘论证）

> 本轮如果有Y（门闸冻结等待放行），在这里记录每个事件的检查结果+决定+理由。
> 放行用 `--step GATE-ID --reason '...'`（理由已落盘flow流水），这里抄录备查。
> 维持hold也填（说明为什么不放行）。无Y则写「无门闸冻结事件」。

| gate_id | 冻结的run | 检查结果（按论证依据逐项） | 决定 | 理由 |
|---|---|---|---|---|
| （从check_output.txt门闸Y通道段读取） | | | 放行/hold | |

---

## 发现的问题

### Critical
（在此填写，或写「无」）

### Warning
（在此填写，或写「无」）

### Info
（在此填写，或写「无」）

---

## 执行的操作
（在此填写，或写「无操作」）

---

## 未修复的问题及原因
（在此填写，或写「无」）

---

## 下一轮建议
（在此填写，或写「无」）
