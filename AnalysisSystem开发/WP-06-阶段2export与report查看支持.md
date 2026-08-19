# WP-06: 阶段2 export与report查看支持

> **依据**：p27_session_management_and_polish_spec.md §C.2.4
> **优先级**：P2
> **前置条件**：WP-05完成（Pipe集成就绪）
> **预估工作量**：小（脚本和命令的辅助功能）

---

## 目标

为Monitor Exec Devin的export和report提供查看支持，方便Master Agent和用户了解每轮修复的内容。

## 要读的文档

- `specs/p27_session_management_and_polish_spec.md` §C.2.4
- `scripts/monitor_check_continuation.sh`（现有检查脚本）
- `monitoring/continuation_control.py`（现有控制命令）

## 任务清单

### 1. monitor_check_continuation.sh显示report路径

- [ ] 第2项alerts输出中，`monitor_exec_completed`类型的alert显示：
  - MONITOR_EXEC_REPORT.md路径
  - commit hash（如有）
  - 本轮修复的alert数量

### 2. continuation_control.py新增view-exec命令

- [ ] 新增 `view-exec <session_key>` 子命令
- [ ] 一键展示：
  - MONITOR_EXEC_REPORT.md内容
  - git log -3（最近3个commit，展示修复历史）
- [ ] 如果session_key不存在或不是monitor_exec类型，提示错误

## 验证标准

- `monitor_check_continuation.sh`输出中monitor_exec_completed alert有report路径
- `continuation_control view-exec <key>`命令可用，正确展示report和git log

## 预期产出

- `scripts/monitor_check_continuation.sh` 修改
- `monitoring/continuation_control.py` 修改
- commit（显式路径add）

## 验证记录

（执行时在此记录验证结果）
