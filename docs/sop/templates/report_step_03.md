# SOP检查报表 — step_03 alert分类

> **填写说明**：本模板由 `scripts/sop/run.py` 自动复制到D盘报表目录。AI加载后逐项检查并填写，填写完用edit写回同一文件。
>
> **打勾规则**：`[x]` 通过 · `[!]` 有问题 · `[ ]` 待检查 · `[-]` 不适用

---

## 系统快照摘要

> 以下数据从 snapshot.json 自动填充。

| 指标 | 值 |
|---|---|
| 总run数 | （从snapshot.json读取） |
| COMPLETED | （从snapshot.json读取） |
| 完成率 | （从snapshot.json读取） |

---

## 检查项清单

### 一、自动化检查项

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| A | 未处理alert列表 | 读check_output.txt中"未处理 alert"节。最多50条alert，逐个看alert_type和severity | [ ] | |

### 二、AI判断检查项

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| T1 | alert分类(A/B/C类) | 逐个读alert，按docs/specs/p27_monitor_spec.md §2分类。A类=自动检查/ B类=续传质量/ C类=AI判断。记录每个alert的分类。 | [ ] | |
| T2 | 需要立即处理的alert | critical severity的alert需要立即处理。如launcher_dead→重启launcher；rate_limit→降并发；export_missing→检查D盘。 | [ ] | |
| T3 | alert标记resolved | 已处理的alert用 `python -m monitoring.continuation_control --resolve-alert <key>` 标记为fixed | [ ] | |
| T4 | 已知问题诊断 | 检查MON-A-issue-01~05中未诊断的alert是否需要优先诊断。特别是MON-A!03(rounds_log_export_missing)和MON-A!04(export_missing)根因未诊断。 | [ ] | |
| T5 | A13/A14应急alert（016事故类） | `real_concurrency_mismatch`(A13)/`launch_churn`(A14)是016事故新增的critical alert，详见docs/specs/p27_monitor_spec.md §A13/A14。launch_churn触发=失控循环正在发生，**立即按016报告§5**处置（kill launcher→清空Redis队列→查根因）；real_concurrency_mismatch=孤儿进程/注册表脱节，查`sessions --consistency-check`清理。 | [ ] | |

---

## alert分类记录

> 逐个记录每个alert的分类和处理方式

| alert_key | alert_type | severity | 分类(A/B/C) | 处理方式 | 已resolved? |
|---|---|---|---|---|---|
| （从check_output.txt读取） | | | | | |

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
