# SOP_03：alert 分类处理

## 认知闭包（执行前必读）

### alert 是什么

监控 Pipe（`monitor_continuation.py`）每 120 秒检查一次系统状态，发现问题就写 alert 到 DB 的 `p27_monitor_alerts` 集合。alert 是系统问题的唯一持久化痕迹——不查 alert 就不知道系统出了什么问题。

### alert 结构

```python
{
    "_key": "p27-alert-20260819-session_health-...",
    "alert_type": "session_health",      # 见下方类型清单
    "severity": "critical",              # critical / warning / info
    "details": {"summary": "...", ...},  # 详细信息
    "status": "active",                  # active / resolved
    "created_at": "2026-08-19T...",
    "resolved_at": null,
}
```

### alert 类型清单和分类标准

| alert_type | 含义 | 分类 | 处理方式 |
|---|---|---|---|
| `session_health` | session数≠并发数 | 代码bug或配置问题 | 查launcher并发配置 |
| `queue_stalled` | 队列长时间无变化 | 需判断 | 查launcher是否在dequeue |
| `rate_limit` | API限流 | 基础设施 | 等恢复，不修 |
| `zombie_sessions` | 空pane session | 需清理 | kill空session |
| `export_missing` | export文件不存在 | 代码bug | 查launcher的export路径逻辑 |
| `failure_rate` | 失败率过高 | 需判断 | 查failure_breakdown |
| `launcher_dead` | launcher进程不存在 | 基础设施 | 重启launcher |
| `stall_detection` | 长时间无进度 | 需判断 | 查具体原因 |
| `proof_missing` | proof.md不存在 | 数据问题 | 判断是模型能力还是代码bug |
| `proof_too_small` | proof.md过小 | 数据问题 | 记录 |
| `handover_missing` | HANDOVER.md不存在 | 数据问题 | 判断handover devin是否失败 |
| `handover_too_small` | HANDOVER.md过小 | 数据问题 | 记录 |
| `truncation_pattern` | 截断模式异常 | 需判断 | 分析截断原因 |
| `status_anomaly` | 状态分布异常 | 需判断 | 分析具体异常 |
| `rounds_log_integrity` | rounds_log字段不完整 | 代码bug | 查make_round_log_entry |
| `intermediate_product_uniqueness` | 中间产物路径重复 | 代码bug | 查路径生成逻辑 |
| `session_registry_inconsistency` | 注册表vs tmux不一致 | 代码bug或数据 | 查具体不一致 |
| `stuck_session_accumulated` | stuck session堆积 | 需清理 | 判断是否需清理 |
| `done_session_uncleaned` | done未清理 | 需清理 | 清理done session |

### 分类标准

- **代码bug**：问题根因在代码中（路径错误、字段名不匹配、逻辑bug）→ 步骤05修复
- **数据问题**：问题根因是AI产出质量（proof内容不对、handover质量差）→ 记录，不修代码
- **基础设施问题**：rate_limit/网络问题/进程崩溃 → 等恢复或重启，不修代码
- **需重跑的题**：题本身没做出来但不是代码bug → 改DB status为prepared重新入队
- **需清理的**：zombie/stuck/done session → 清理

---

## 执行指令

### 1. 阅读自动化查询结果

上方 checks.py 已经查询了最多 50 个未处理 alert。逐个阅读。

### 2. 逐个分类

对每个 alert，根据上方类型清单决定分类。如果不确定：
- 读 alert 的 `details` 字段获取更多信息
- 读相关代码理解检查逻辑（如 `export_missing` → 读 `monitor_continuation.py` 的 `check_export_landing` 函数）
- 读相关 run 的 rounds_log 了解上下文

### 3. 记录分类结果

对每个 alert 记录：
- alert_type + key
- 分类（代码bug/数据/基础设施/需重跑/需清理）
- 处理方式（步骤05修复 / 记录 / 等恢复 / 重新入队 / 清理）

### 4. 需要立即处理的

- `launcher_dead` → 立即重启（不等到步骤05）
- `zombie_sessions` → 可以立即清理
- `rate_limit` → 记录，等恢复

---

## 你需要建立的 todo list

- 阅读alert列表
- 逐个分类（可以合并为一个todo）
- 需步骤05修复的alert（每个一个todo）
- 需步骤04做AI判断的（如果有needs_ai_review标记）
- 需立即处理的（launcher_dead等）
- **最后一项固定是**：`执行下一个脚本: python -m scripts.sop.run`

完成所有 todo 后，自动触发步骤04（C类AI判断）。
