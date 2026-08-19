# WP-09: POC-2.7并发1运行和监控

> **依据**：AnalysisSystem.md §6.2
> **优先级**：P0
> **前置条件**：WP-01完成（阶段1验证），WP-02完成（bug修复）
> **预估工作量**：大（长期运行，可能数小时到数天）

---

## 目标

在所有修复和验证完成后，以并发1启动POC-2.7续传系统，运行直到所有题completed或failed。通过标准：COMPLETED≥50%（见AnalysisSystemDesign.md §7.1）。

## 要读的文档

- `AnalysisSystemDesign.md` §1（快速入口）+ §7.1（通过标准）
- `specs/p27_monitor_spec.md`（检查标准）
- `scripts/monitor_check_continuation.sh`（检查脚本）

## 任务清单

### 1. 启动系统并发1

- [ ] 确认DB concurrency=1
- [ ] 确认Redis队列清空（stop --force已清空）
- [ ] 确认无僵尸running（DB running=0）
- [ ] 启动系统：
```bash
cd analysis-devin-failure-system
../.venv/bin/python3 -m monitoring.continuation_control start --batch-id p27-full --concurrency 1
```

### 2. 循环监控

- [ ] 每次运行检查脚本：
```bash
bash analysis-devin-failure-system/scripts/monitor_check_continuation.sh p27-full
```
- [ ] 根据输出处理行动清单
- [ ] sleep 120后再次运行
- [ ] 循环直到所有题completed或failed

### 3. 监控要点

- [ ] 进度是否在推进（completed数在增长）
- [ ] 失败率是否>15%（需降并发或检查rate limit）
- [ ] 有无新alert（按p27_monitor_spec.md §2分类处理）
- [ ] 有无dead_session新增（需重新入队）
- [ ] proof.md质量（存在数 vs COMPLETED数，有boxed数 vs 存在数）

### 4. 阶段2集成后的监控（如果WP-05已完成）

- [ ] 确认Monitor Exec Devin自动启动
- [ ] 确认alert被自动处理（不再堆积）
- [ ] 确认自愈循环在转（Monitor Exec Devin定期检查+修复）

### 5. 通过率判定

- [ ] 所有题完成后，计算通过率：COMPLETED / total
- [ ] 通过标准：COMPLETED≥50%（AnalysisSystemDesign.md §7.1）
- [ ] 如果通过率<50%，分析原因：
  - 续传机制是否需要改进（v2交接文档自动化）
  - TRUNCATED_AT_MAX的题是否有proof.md但答案错误（真正的思维错误）
  - 是否需要重新选题

## 验证标准

- 系统以并发1稳定运行
- 进度持续推进（无长时间停滞）
- 所有题completed或failed
- 通过率≥50%

## 预期产出

- 运行日志（tmux pane输出）
- 最终进度报告（completed/failed/通过率）
- 如果通过，POC-2.7结论报告

## 注意事项

- 这是长期运行的工作——可以在运行中并行做WP-03~WP-08
- 如果系统在运行中发现问题，切回开发者修复（WP-02），修完重启系统
- 绝不kill无DONE.md的session
- 长时间命令用tmux

## 验证记录

（执行时在此记录运行进度和最终结果）
