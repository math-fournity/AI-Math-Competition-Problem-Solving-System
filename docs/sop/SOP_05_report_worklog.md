# SOP_05：报告 + WORKLOG

> **你的角色**：你是错题分析系统的 Monitor AI。这是 SOP 循环的最后一步——写本轮报告，续写 WORKLOG，resolve 已处理的 alert。完成后回到 sop_01 开始新的一轮。

---

## 这一步你要做什么

### 1. 写 MONITOR_EXEC_REPORT.md

在项目根目录或 `output/monitor_exec/` 下写本轮报告（覆盖上一轮的，因为每轮报告是独立的）：

```markdown
# Monitor Exec Report · 第{cycle}轮

**时间**: {timestamp}
**检查批次**: p27-full

## 检查结果摘要
- A类alert: X个
- B类alert: Y个
- C类AI判断: Z项（其中W项FAIL）

## 修复操作
### 修复1: {alert_type}
- 根因: ...
- 修复: ...
- commit: {hash}
- 验证: py_compile通过

## 未修复的问题（及原因）
- {问题}: {为什么不修——模型能力问题/基础设施问题/需要用户决策}

## 下一轮建议
- {如果有的话}
```

### 2. 续写 WORKLOG.md

在项目根目录的 `WORKLOG.md` 末尾追加（不覆盖已有内容）：

```markdown
---

## 第{cycle}轮 · {timestamp}

### 检查发现
- A类alert: X个
- B类alert: Y个
- C类AI判断: Z项

### 修复操作
- {修复简述}: {根因一句话} → {方案一句话}. commit {hash}

### 思考
- {你为什么这么修、发现了什么模式、对系统的观察}
```

WORKLOG.md 是跨轮连续记忆——下一轮循环的你读它就能快速恢复上下文。

### 3. resolve 已处理的 alert

对 DB 中 `p27_monitor_alerts` 集合的已处理 alert，更新 `status` 为 `resolved`：
- 修复了的代码bug → resolve 对应 alert
- C类判定 PASS 的 → resolve 对应 needs_ai_review 标记
- C类判定 FAIL 的 → 写新 alert（ai_review_*），不 resolve 原标记

可以用 inline python（<3行）或写脚本（>3行，放 scripts/ 下）。

### 4. 提交所有变更

git commit 报告 + WORKLOG + 任何未提交的修复 + trace.csv 更新。

---

## 你需要建立的 todo list

用 `todo_write` 建立本轮 todo list：
- 写 MONITOR_EXEC_REPORT.md
- 续写 WORKLOG.md
- resolve 已处理 alert
- git commit
- **最后一项固定是**：执行下一个脚本 `python -m scripts.sop.sop_01_health_check`

**注意**：sop_01 是新的一轮循环的开始。完成最后一项后，你就开始了第 {cycle+2} 轮循环。

这就是 7x24 持续循环的机制——每完成一个阶段的 todo list，最后一项自动触发下一阶段，永不停歇。
