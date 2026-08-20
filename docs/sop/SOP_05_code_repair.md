# SOP_05：代码修复

## 认知闭包（执行前必读）

### 什么问题需要修代码

只有步骤03分类为"代码bug"的 alert 和步骤04发现代码相关问题才需要修。数据问题（模型能力）和基础设施问题（rate_limit）不修代码。

### 代码架构（最小必要认知）

```
src/
  continuation_launcher.py    — 续传并发引擎（1484行，最大文件）
  continuation_config.py      — 配置常量
  continuation_db_schema.py   — DB集合定义
  continuation_redis_queue.py — Redis队列操作
  continuation_collector.py   — 数据收集
  continuation_feeder.py      — 入Redis队列
  continuation_result_collector.py — 结果汇总
  monitor_continuation.py     — 监控Pipe（1013行）
  session_registry.py         — Session编号化管理
monitoring/
  continuation_control.py     — 控制命令（start/stop/status/sessions）
  runtime_health_check.py     — 10维度运行时健康检查
scripts/
  monitor_check_continuation.sh — 检查脚本（sop_01调用它）
```

### 修复约束（硬性）

1. **不能 push 代码** — 只 commit 到本地
2. **不能修改这些文件**（架构级规范，只记录建议）：
   - `AGENTS.md`
   - `.devin/rules/*.md`
   - `docs/patterns/MonitorPipe.md` 架构定义
   - `docs/system/AnalysisSystemDesign.md` §5设计原则 / §6关键设计决策
3. **可以修改这些文件**（事实性文档，和代码同一commit）：
   - `src/*.py`（代码本身）
   - `monitoring/*.py`
   - `docs/architecture/*.md`（模块文档）
   - `docs/specs/*.md` 的实现细节部分
4. **git 显式路径 add** — 禁止 `git add -A` / `.` / `-u`
5. **修完必须验证** — `python -m py_compile <修改的文件>`
6. **只修本轮发现的问题** — 不重构、不改架构、不"顺便"修其他
7. **改代码同步更新文档** — 改了 `src/xxx.py` 就同步改 `docs/architecture/xxx.md`（如存在）
8. **更新 trace.csv** — 新增/修改的资产要记录追溯关系

### commit message 格式

```
修复<alert_type或问题简述>: <一句话描述根因和修复>

Generated with [Devin](https://devin.ai)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
```

---

## 执行指令

### 1. 汇总需要修复的问题

从步骤03（分类为代码bug的alert）和步骤04（发现代码相关的AI判断问题）中汇总需要修复的问题。

如果没有需要修复的——跳过本步骤，直接进入步骤06。

### 2. 逐个修复

对每个问题：

1. **读相关代码** — 用 grep 搜索 alert_type 相关的函数，用 read 读完整文件
2. **定位根因** — 不是症状。问"为什么会产生这个alert？"
3. **修复** — 用 edit 工具修改代码
4. **验证** — `python -m py_compile <修改的文件>`
5. **同步文档** — 如果改了代码的行为，同步更新 `docs/architecture/` 或 `docs/specs/` 中对应文档
6. **更新 trace.csv** — 如果新增了文件或函数
7. **git commit** — 显式路径 add

### 3. 修复后确认

修复后，确认问题不会立即复发——下一轮 SOP 循环的步骤01/02/03会发现是否还有同样的 alert。

---

## 你需要建立的 todo list

- 每个修复任务拆解为：读代码→定位根因→修复→验证→同步文档→commit
- **最后一项固定是**：`执行下一个脚本: python -m scripts.sop.run`

完成所有 todo 后，自动触发步骤06（报告+WORKLOG+Self-check）。

### 深入了解（如需）

- `docs/system/AnalysisSystemDesign.md` §6 — 关键设计决策记录（修复代码前理解设计理由）
- `docs/architecture/graceful-shutdown.md` — 优雅停止设计（修复涉及停止逻辑时参考）
- `docs/architecture/framework-checklist.md` — 新Pipe必须考虑的所有方面
