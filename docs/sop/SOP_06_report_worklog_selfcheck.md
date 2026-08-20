# SOP_06：报告 + WORKLOG + Self-check

## 认知闭包（执行前必读）

### 为什么要写报告和WORKLOG

- **MONITOR_REPORT.md** — 本轮工作的正式产出（检查了什么/发现了什么/修了什么）
- **WORKLOG.md** — 跨轮连续记忆（每轮的摘要+思考）。下一轮循环的你读它就能快速恢复上下文，不用从零开始

### Self-check（SELF-S1~S22）

每轮循环结束时，你必须对自己做 22 项 self-check。这些来自 `checklist/SELF-*.md`：

| 编号 | 检查项 | 通过标准 |
|---|---|---|
| S1 | export完整性 | 本轮如果有 devin cli 解题运行，export 已落盘（Master Agent 自己不产生 export，标 [-]） |
| S2 | DONE.md写入 | 本轮如果有 devin cli 解题运行，DONE.md 已出现（Master Agent 自己不产生 DONE.md，标 [-]） |
| S3 | REPORT完整性 | MONITOR_REPORT.md包含检查/判断/修复/未修复四部分 |
| S4 | session注册 | 本轮如果启动了session，已注册到p27_sessions |
| S5 | py_compile通过 | 本轮如果修了代码，py_compile通过 |
| S6 | git commit成功 | 本轮如果有变更，已commit |
| S7 | 未修改第二级架构级规范 | 没改AGENTS.md/spec的架构定义 |
| S8 | git add规范 | 没用 `git add -A`/`.`/`-u` |
| S9 | 只修本轮发现的问题 | 没"顺便"修其他问题 |
| S10 | 未spawn subagent | 没spawn subagent |
| S11 | 未push代码 | 没`git push` |
| S12 | C类判断有依据 | C1-C5判断有具体原因记录 |
| S13 | 是否陷入重复修复 | 没有反复修同一个问题 |
| S14 | 同一alert是否反复出现 | 检查是否有alert在多轮循环中反复出现 |
| S15 | 第一级文档同步 | 改了代码就改了对应文档（同一commit） |
| S16 | 第二级规范建议记录 | 如果发现规范问题，在REPORT中记录建议 |
| S17 | 同步清单完整性 | trace.csv已同步 |
| S18 | sim发布门禁 | 改了调度/判定逻辑后跑了`src.sim.run_sim --scenario solve3+chaos_016`且全绿（016 P0-1修复引入新死循环的教训）。只改文档/配置标[-] |
| S19 | 行为流水必查 | 每轮SOP_01查了`observability --stats --since 1h`，churn_suspects为空（016根因：存量没变但流动病态） |
| S20 | 落盘论证 | Gate放行附了`--reason`理由（落盘gate_release流水）；不放行在report门闸记录区填了原因（没有理由的放行=审计断点） |
| S21 | 成果双写 | completed的run的proof入库了continuation_results（≤100KB双写，不依赖盘上单点——018教训） |
| S22 | step_gate Y通道接线 | checks.py每轮查了Y通道（waiting_for非空的闸）；有Y时按论证依据闭包核对后放行/hold（016教训：拦不住失控循环） |

### 报告格式

```markdown
# Monitor Report · 第{cycle}轮

**时间**: {timestamp}
**检查批次**: {batch_id}

## 检查结果摘要
- 步骤01系统健康: [健康/有问题]
- 步骤02数据完整性: [正常/X个问题]
- 步骤03 alert分类: [X个alert，Y个代码bug，Z个数据问题]
- 步骤04 AI判断: [X项，Y项PASS，Z项FAIL]

## 修复操作
### 修复1: {alert_type}
- 根因: ...
- 修复: ...
- commit: {hash}
- 验证: py_compile通过

## 未修复的问题（及原因）
- {问题}: {原因}

## Self-check结果（S1-S22）
- S1: PASS / S2: PASS / ...

## 下一轮建议
- {如果有的话}
```

### WORKLOG 续写格式

在 WORKLOG.md 末尾追加（不覆盖已有内容）：

```markdown
---

## 第{cycle}轮 · {timestamp}

### 检查发现
- 系统健康: ...
- 数据完整性: ...
- alert: X个（关键alert列举）
- AI判断: X项

### 修复操作
- {修复简述}: {根因} → {方案}. commit {hash}

### 思考
- {你为什么这么修、发现了什么模式、对系统的观察——这是WORKLOG最宝贵的部分}
```

---

## 执行指令

### 1. 写 MONITOR_REPORT.md

按上方格式写本轮报告。放在项目根目录或 `output/monitor/` 下。

### 2. 续写 WORKLOG.md

在项目根目录的 WORKLOG.md 末尾追加本轮记录。如果文件不存在，创建它。

### 3. 执行 Self-check（S1-S22）

逐项检查上方 22 项。记录 PASS/FAIL。FAIL 的需要说明原因和改进计划。

### 4. resolve 已处理的 alert

DB 中 `p27_monitor_alerts` 集合的已处理 alert，用控制脚本标记为 resolved：

```
# 单个 resolve
python -m monitoring.continuation_control resolve-alert <alert_key>

# 批量 resolve 所有已处理的 critical alert
python -m monitoring.continuation_control resolve-alert --all-critical
```

resolve 规则：
- 修复了的代码bug → resolve
- C类判定PASS的 → 用 mark-ai-review 标记 PASS（不是 resolve alert）
- C类判定FAIL的 → 不resolve（记录为数据问题）

### 5. git commit

提交报告 + WORKLOG + 任何未提交的修复 + trace.csv更新。

---

## 你需要建立的 todo list

- 写 MONITOR_REPORT.md
- 续写 WORKLOG.md
- 执行 Self-check S1-S22
- resolve 已处理 alert
- git commit
- **填写 report.md 报表**（read加载→打勾填发现→edit写回）
- **最后一项固定是**：`执行下一个脚本: python -m scripts.sop.run`

完成所有 todo 后，自动触发步骤Z（元检查+整体检查）。
