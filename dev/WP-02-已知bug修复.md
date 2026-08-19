# WP-02: 已知bug修复

> **依据**：2026-08-19 session发现的实际问题
> **优先级**：P0
> **前置条件**：无（可与WP-01并行）
> **预估工作量**：中等（4个bug，每个需要诊断+修复+验证）

---

## 目标

修复2026-08-19 session中发现的4个未修复问题。这些问题在系统运行时会导致误报、数据丢失或功能失效。

## 要读的文档

- `src/monitor_continuation.py`（Monitor Pipe代码）
- `src/continuation_launcher.py`（launcher代码）
- `docs/dynamic-concurrency.md`（动态并发设计）
- `specs/p27_monitor_spec.md`（检查标准）

## Bug清单

### Bug-1: Monitor Pipe的expected_concurrency不从DB读

**现象**：Monitor Pipe用`--concurrency 5`启动参数做session_health检查，当DB并发是1或3时，误报"tmux session数少于并发数5"。

**根因**：`monitor_continuation.py`第831行`run_monitor_loop(batch_id, interval, expected_concurrency=5)`——expected_concurrency来自启动参数，不从DB动态读取。

**修复方案**：Monitor Pipe主循环每轮从DB读batch.concurrency作为expected_concurrency（与launcher的动态并发修复相同的方式）。

**修改文件**：`src/monitor_continuation.py`

**验证**：修改后启动Monitor Pipe，确认session_health检查用DB中的concurrency值而非启动参数。

### Bug-2: alert的_key冲突

**现象**：Monitor Pipe日志出现`创建alert失败: [HTTP 409][ERR 1210] unique constraint violated - in index primary of type primary over '_key'`。

**根因**：`monitor_continuation.py`第95-96行：
```python
ts = int(time.time() * 1000)
alert_key = f"p27-alert-{ts}-{alert_type}"
```
同一轮检查中多个相同类型的alert（如多个rounds_log_export_missing）如果timestamp相同（毫秒级），_key就重复。

**修复方案**：_key加入唯一标识——可以用problem_id（如果details中有）或递增序号或UUID后缀。

**修改文件**：`src/monitor_continuation.py`

**验证**：修改后确认不再出现_key冲突的ERROR日志。

### Bug-3: rounds_log_export_missing根因诊断

**现象**：大量alert报告round2的export文件不存在（`round2/exports/conversation.json`）。

**需要诊断的问题**：
1. 这些run的round2目录是否存在？
2. round2目录存在但exports子目录不存在？
3. exports目录存在但conversation.json不存在？
4. 是devin cli没有执行`--export`，还是执行了但export失败？
5. launcher启动round2时是否正确传了`--export`参数？

**诊断方法**：
- 选3-5个有此alert的run，检查它们的work_dir结构
- 查launcher代码中启动round2的命令构造逻辑
- 查devin cli的`--export`参数是否被正确传递

**修复方案**：根据诊断结果确定。

**修改文件**：待诊断后确定。

**验证**：修复后新完成的run不再出现rounds_log_export_missing。

### Bug-4: export_missing根因诊断

**现象**：completed run无export文件（`export_missing` alert）。

**需要诊断的问题**：
1. 这些run标记completed的依据是什么？（proof.md存在？还是有boxed？）
2. export文件应该在哪个路径？
3. 是export从未生成，还是生成后被误删？
4. 与Bug-3是否有关联（都是export问题）？

**诊断方法**：
- 选2-3个有此alert的run，检查它们的完整work_dir结构
- 查is_completed判定逻辑——是否在无export时就标记completed
- 查export路径计算逻辑

**修复方案**：根据诊断结果确定。

**修改文件**：待诊断后确定。

**验证**：修复后新completed的run都有export文件。

## 已完成的修复（参考）

以下3个bug已在2026-08-19 session中修复并commit：

| commit | bug | 修复内容 |
|---|---|---|
| de38a5e | launcher不从DB读concurrency | 主循环每轮从DB读batch.concurrency |
| cafd195 | session_counter seq unique索引冲突 | counter文档改用counter字段 |
| 7767fa8 | launcher重启覆盖DB concurrency | 启动时先读DB，不覆盖已有值 |

## 铁律

- 每个bug修复必须同步更新第一级文档（如果涉及设计变更）
- git显式路径add
- py_compile验证通过
- commit message用人话描述bug现象+根因+修复

## 验证记录

（执行时在此记录每个bug的诊断和修复结果）
