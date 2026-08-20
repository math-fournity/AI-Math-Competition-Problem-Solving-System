# SOP检查报表 — step_02 数据完整性

> **填写说明**：本模板由 `scripts/sop/run.py` 自动复制到D盘报表目录。AI加载后逐项检查并填写，填写完用edit写回同一文件。
>
> **打勾规则**：`[x]` 通过 · `[!]` 有问题 · `[ ]` 待检查 · `[-]` 不适用
>
> **报表目录**：`{REPORT_DIR}/`（含本文件 + snapshot.json + snapshot_runs.json + check_output.txt）

---

## 系统快照摘要

> 以下数据从 snapshot.json 自动填充。AI填写报表前先读 snapshot.json 确认数据。

| 指标 | 值 |
|---|---|
| 总run数 | （从snapshot.json的aggregate.total_runs读取） |
| COMPLETED | （从snapshot.json的aggregate.completed读取） |
| 完成率 | （从snapshot.json的aggregate.completion_rate读取） |
| results集合 | （从snapshot.json的aggregate.results_collection_count读取） |
| events总数 | （从snapshot.json的aggregate.events_total读取） |
| sessions总数 | （从snapshot.json的aggregate.sessions_total读取） |

### 按题源完成率

> 从 snapshot.json 的 by_source 读取，填入下表。

| 题源 | 总数 | 完成 | 完成率 | 备注 |
|---|---|---|---|---|
| （src） | （total） | （completed） | （rate） | （填写：0%的写"系统性问题"，正常的留空） |

### per-run明细

> snapshot_runs.json 包含全部919条run的明细数据。每条含：
> `problem_id` / `status` / `final_status` / `rounds_count` / `current_round` / `last_method` / `last_completed` / `last_truncated` / `updated_at` / `work_dir`
>
> 需要查某道题的状态时，用 `python3 -c "import json; runs=json.load(open('snapshot_runs.json')); [print(r) for r in runs if r['problem_id']=='XXX']"` 查询。

---

## 检查项清单

### 一、自动化检查项（读 check_output.txt 的输出填写）

> check_output.txt 是 `check_02_data_integrity()` 的完整stdout输出。逐项读输出，填写结果。

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| F1 | rounds_log 6个路径字段文件存在性 | 读check_output.txt中"数据完整性检查"节的issues列表。每个问题格式：`[pid R{N}] {输入/输出} {字段} 文件不存在: {路径}` | [ ] | （填写：发现N个问题，或"全部正常"） |
| F2 | 文件大小检查 | 读check_output.txt中issues列表中"文件过小"的问题 | [ ] | |
| F3 | export JSON格式 | 读check_output.txt中issues列表中"不是JSON格式"的问题 | [ ] | |
| F4 | proof.md内容质量 | 读check_output.txt中issues列表中"proof.md内容过短"的问题 | [ ] | |
| F5 | HANDOVER.md内容质量 | 读check_output.txt中issues列表中"HANDOVER.md内容过短"的问题 | [ ] | |
| F6 | prompt内容质量 | 读check_output.txt中issues列表中"prompt内容过短"的问题 | [ ] | |
| Q1 | proof.md质量统计(RUN-05) | 读check_output.txt中"proof.md 质量统计"节。关注：存在率<100%？boxed率<100%？ | [ ] | |
| Q2 | results集合检查 | 读check_output.txt中"results 集合检查"节。results数<COMPLETED数→critical | [ ] | |
| Q3 | events完整性检查 | 读check_output.txt中"events 完整性检查"节。有launched无completed/failed的run→warning | [ ] | |
| Q4 | prepared堆积检查 | 读check_output.txt中"prepared 堆积检查"节。prepared>0但pending=0→critical | [ ] | |
| Q5 | 按题源完成率统计 | 读check_output.txt中"按题源完成率统计"节。完成率=0%的题源→critical | [ ] | |
| Q6 | 标准文件检查 | 读check_output.txt中"标准文件检查"节。problem.txt/proof.md/round1 export缺失 | [ ] | |
| Q7 | round编号连续性 | 读check_output.txt中"round 编号连续性检查"节。全从round=2开始→需确认是否by design | [ ] | |

### 二、AI判断检查项（需要AI主动执行检查）

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| 2a | DB记录vs文件一致性 | 抽查几个COMPLETED的run，确认proof_path指向的文件确实存在。用snapshot_runs.json找到COMPLETED的run，读work_dir，检查proof.md。 | [ ] | |
| 2b | Redis队列vs DB status | `python3 -c "from src.continuation_redis_queue import get_redis, pending_count, running_count; r=get_redis(); print(f'pending={pending_count(r)} running={running_count(r)}')"` 对比DB中prepared数 | [ ] | |
| 2c | Session注册表完整性 | `python3 -c "from src.continuation_db_schema import connect_db; from src.session_registry import list_sessions; db=connect_db(); sessions=list_sessions(db, status='running', limit=20); [print(s) for s in sessions]"` 检查running session的export_path父目录是否存在 | [ ] | |
| 2d | 事件流完整性确认 | 读Q3中列出的有launched无end的run。用snapshot_runs.json查这些run的status——如果status=running→正常（还在跑）；如果status=completed/dead_session→异常（事件丢失） | [ ] | |
| 2e | 跨题目模式分析 | 读Q5的按题源完成率。0%的题源：诊断原因（都是prepared没跑到？还是跑了都失败？还是都truncated？）。用snapshot_runs.json按题源分组查status分布。 | [ ] | |

---

## 发现的问题

### Critical

> 填写critical级别的问题（数据丢失/系统无法运行/系统性错误），或写「无」

（在此填写）

### Warning

> 填写warning级别的问题（字段缺失/不一致但不影响运行），或写「无」

（在此填写）

### Info

> 填写info级别的问题（需要确认但不影响运行），或写「无」

（在此填写）

---

## 执行的操作

> 填写本轮做了什么修复/重启/重跑等操作。每个操作记录：做了什么、为什么、改了哪些文件、commit hash。或写「无操作」

（在此填写）

---

## 未修复的问题及原因

> 填写哪些问题没修，为什么没修（需要更多信息/需要用户决策/超出本轮范围）。或写「无」

（在此填写）

---

## 下一轮建议

> 填写下一轮SOP循环需要关注什么。或写「无」

（在此填写）
