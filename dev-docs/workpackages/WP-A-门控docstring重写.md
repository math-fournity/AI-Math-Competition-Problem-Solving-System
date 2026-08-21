# WP-A — 审计门控 docstring 重写（4 要素统一标准 + E1 语义澄清）

> **优先级**: 第二批（可与其他二批 WP 并行）
> **依赖**: 无（纯 docstring 改写，不改逻辑）
> **预计规模**: proof_audit_launcher.py 2 个 docstring + proof_audit_result_collector.py
> 2 个 docstring（每个 30-50 行）+ StepGate.md 格式标准段更新
> **性质**: 文档型代码改动（docstring 即注册进 DB 的认知闭包，是功能的一部分）

---

## 0. 给执行 AI 的第一句话

4 个审计门闸（GATE-AUDIT-*）的 docstring 只有"检查项"没有"论证依据"——Master Agent
在 `--pending` 单步时刻拿到的是不完整的认知闭包，不知道检查结果如何转化为放行/不放行
决定（这是 030 需求 3 的核心缺陷）。你要按**与续传 9 闸同构的 4 要素格式**重写它们，
并补上 E1 语义澄清（"completed = devin 退出 ≠ 审计成功"）。

## 1. 背景（为什么）

- docstring 是门闸认知闭包的**唯一事实源**（`step_gate.py` 的 `@gated` 经 inspect 反射
  进 DB 注册表；`extract_checklist()` 按"放行前"标题截取到末尾）——docstring 缺论证
  依据 = `--pending` 输出的闭包缺判定标准 = 032 E1 说的"SOP 检查看 completed 以为审计
  成功"这类误判没有防线
- 030 §5.2 已对比：续传门控（如 GATE-LAUNCH-SOLVE）有完整 5 段（做什么/为什么/
  检查项/论证依据/教训引用），审计门控只有前 2.5 段
- 格式裁定（033 D3 + 034 接受）：**4 固定段**，【论证依据】段内含两个小标题
  （"放行/不放行判定" + "系统正常运行表现"）——后者是 030 需求 3 原文要求
  （"让未来的 AI 知道……对系统的运行是否正常，作出怎样的判断"）

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `src/continuation_launcher.py` 的 `launch_solve` docstring（搜"GATE-LAUNCH-SOLVE"） | **格式金标准**——4 要素的写法、检查项的"查法+正常值"结构、论证依据的"可放行：1✓+2✓…理由"句式 |
| 2 | 同文件 `kill_session` docstring（GATE-KILL-SESSION） | 第二个金标准（tmux 类） |
| 3 | `src/proof_audit_launcher.py` 的 `audit_launch` + `audit_kill_session` docstring | 你要重写的对象 1、2（现状：只有做什么/为什么/简单检查项） |
| 4 | `src/proof_audit_result_collector.py` 的 `audit_finalize_pass` + `audit_finalize_fail` docstring | 对象 3、4 |
| 5 | `src/step_gate.py` 的 `extract_checklist()`（10 行） | 截取规则——你的新 docstring 里"放行前"标题之后的所有内容都会被输出，格式要自洽 |
| 6 | 030/031/033 中的检查项内容设计（直接读本文档 §4，已整合，无需回读 dev-docs） | 每个门闸该查什么的完整清单 |
| 7 | 032 E1 + 034 E1（语义）：本 WP §4 的 KILL-SESSION 检查项里已整合 | "completed=devin 已退出"的语义边界 |

## 3. 现场事实基线（2026-08-21 09:30）

- 4 个审计门闸 docstring 现状（复核：grep 每个函数名看 docstring）：
  - `audit_launch`：有做什么/为什么/3 项检查——**无论证依据**；检查项里"proof.txt 存在"
    没提"与 DB proof_text 比对"（028 教训）
  - `audit_kill_session`：**缺"这个函数做什么"段**（032 C 组发现）；检查项无 tmux
    直接验证
  - `audit_finalize_pass/fail`：检查项是"读字段"式（间接），无 export/文件直接读要求
- WP-N 已改 result_collector（mark_parse_error）——finalize docstring 的检查项要提
  PARSE_ERROR 不走此闸（WP-N 的新语义）
- 门闸注册表在 launcher 启动/`--register` 时同步——docstring 改完要刷新

**基线漂移预期**：WP-H 已改 proof_audit_launcher 主循环（should_stop/收尾即收集）——
docstring 重写不受影响，但 `audit_launch` 的函数体若被 WP-H 动过（不应该——WP-H 只动
主循环），以现状为准。

## 4. 任务分解

### 统一格式模板（4 要素 + 论证依据内双小标题）

```
"""【门闸: GATE-X】<一句话动作>。

这个函数做什么：
- <具体动作>

为什么追踪这个动作：
- <理由>
- <历史教训引用（028/030 事故编号）>

放行前Master Agent应检查并论证：
【检查项】（每项含查法+正常值）
1. <项> → 查法：<命令/工具> + 正常值=<什么算正常>
2. ...

【论证依据——放行/不放行判定】
放行/不放行：<条件组合>。理由：<为什么安全/不安全>
不可放行：<条件>→<后果>；<条件>→<后果>

系统正常运行表现：<此门控处系统健康的样子>；异常时：<表现>→<如何处置（alert/SOP）>
"""
```

### GATE-AUDIT-LAUNCH 检查项（重写内容，逐项写入）

1. proof.txt 存在且非空 → 查法：`ls work_dir/proof.txt && wc -c`（>0）——**且与 DB
   audit_run.proof_text 前 200 字符抽样一致**（028 教训：DB 有文本≠文件在；直接检查）
2. AGENTS.md 模板渲染正确 → 查法：`grep -c "{" work_dir/AGENTS.md` 中
   `{problem_text}` 等占位符应为 0（未替换=模板 bug）
3. 并发未超限 → 查法：`redis-cli HLEN paudit:running` < 并发数；**并发数来源=DB
   batch 记录**（WP-G 后无写死默认——查法：读 p27_continuation_batches.{batch_id}.concurrency）
4. 该 audit_run 无活跃 session → 查法：`tmux list-sessions | grep <audit_run_key 后30字符>`

论证依据：
- 可放行：1✓+2✓+3✓+4✓。理由：审计输入真实存在且与 DB 一致、模板正确、并发受控、
  无重复启动——启动不会白耗配额也不会重复审计
- 不可放行：1✗（proof.txt 缺失/不一致）→028 重现（审计无输入或审的是旧文本）；
  2✗（占位符未替换）→审计 AI 收到模板骨架，产出必然 PARSE_ERROR；3✗→并发失控
  （rate limit 风险）

系统正常运行表现：paudit:pending 持续下降 + running ≤ concurrency + 每个审计 3-10
分钟完成；异常：pending 不降（launcher 没 dequeue——查 launcher 活着吗）/ 秒退
（devin 启动失败——查 pane）→ 交 SOP_07 处理

### GATE-AUDIT-KILL-SESSION（补"做什么"段 + E1 澄清）

做什么段：kill 该审计的 tmux session（devin 已退出后 session 因 sleep 999999 设计
仍存活，kill 是正常清理）。

检查项：
1. **completed 的真实语义**：DONE.md 存在 = **devin cli 已退出**，≠ 审计成功——审计
   成败要看 p27_proof_audits.audit_status（E1 澄清，写进检查项 1 本身）
2. DONE.md 存在 或 export 有 `### PROOF AUDIT COMPLETE` → 查法：ls DONE.md；
   grep export
3. session 确属该 audit_run → 查法：session 名 = audit_run_key 后 30 字符（映射规则）
4. kill 前 export 已落盘非空 → 查法：`stat -f%z` > 1000

论证依据：可放行 2✓+3✓+4✓（1 是语义提醒非条件）。不可放行：无 DONE.md 且非
dead_session→违反铁律；export 空→审计产出未落盘就 kill=结果丢失

系统正常运行表现：completed 后 kill 干净、tmux 无 paudit- 残留 session；异常：
paudit session 堆积=孤儿（launcher 死了）→SOP_07 孤儿对账发现

### GATE-AUDIT-FINALIZE-PASS

检查项（全部直接读）：
1. XML 解析成功 → 查法：**直接读 export 的 `<proof_audit>` 块**（grep export 文件），
   不是只看 DB check_results 字段（直接检查）
2. audit_status ∈ {PASS, PASS_WITH_CAVEAT}
3. A1 含 PASS（答案正确性是硬门槛）
4. E1/E2 无 FAIL（作弊标记）
5. proof.txt 与审计对象一致 → 查法：work_dir/proof.txt 前 200 字 vs DB proof_text

论证依据：可放行 1✓+2✓+3✓+4✓+5✓——审计结果有据且对象正确，audit_passed=True
让题进选题池是安全决策。不可放行：3✗（答案错）→绝不能进池；4✗→应走 FINALIZE-FAIL；
XML 解析不出→**不走本闸也不走 FAIL 闸，走 mark_parse_error 待人工**（WP-N 语义）

系统正常运行表现：PASS 后 p27_proof_audits 增长、runs.audit_passed=True 同步；
异常：finalize 后两集合不一致=收集链断裂→SOP_07 交叉验证发现

### GATE-AUDIT-FINALIZE-FAIL

检查项：
1. XML 解析成功（同上直接读 export）
2. audit_status ∈ FAIL_*（六种）
3. FAIL_INCOMPLETE 时直接读 proof.txt 确认截断残篇特征（中途断裂/无结论）
4. FAIL_CHEATING 时 cheating_analysis 证据充分（非空且指明行为）
5. 影响：audit_failed 几乎不可逆（需人工翻案）——放行前明确知道这一点

论证依据：可放行 1✓+2✓+（3✓ 或 4✓ 按类型）。不可放行：XML 解析失败→走
mark_parse_error（把"不知道"当"失败"是 030~036 修的 bug，WP-N）；FAIL_INCOMPLETE
但 proof.txt 完整→审计 AI 误判，人工复核

系统正常运行表现：FAIL 分布中 FAIL_WRONG_ANSWER/FAIL_LOGIC_ERROR 为主、失败率<20%；
异常：FAIL_CHEATING 批量出现→cheating_detected alert→SOP_07 C9 复查

### 任务 2：StepGate.md 格式标准更新

`docs/patterns/StepGate.md` §2.3 的 docstring 约定段：补充"4 固定段 + 论证依据内
双小标题（放行/不放行判定 + 系统正常运行表现）"的格式说明，引用审计 4 闸为第二批
实例。**注明**：续传 9 闸为首批实例（格式等价——其论证依据段天然含正常运行语义），
不要求回改。

### 任务 3：刷新注册表并验证闭包输出

```
python -m src.step_gate --register
python -m src.step_gate --list          # 4 个 GATE-AUDIT-* 的 doc 摘要已更新
python -m src.step_gate --hold GATE-AUDIT-LAUNCH   # 布防验证（下一步会自动触发? 不会——
                                                    # 没有审计在跑；改用直接读DB验证doc字段）
```
更稳的验证：直接查 DB `p27_step_gates` 的 4 个 GATE-AUDIT-* 文档的 `doc` 字段含
"【论证依据"和"系统正常运行表现"字样。**验证后记得 `--auto` 复位**（若 hold 过）。

### 任务 4：py_compile + commit

docstring 改动不影响逻辑，但仍跑 py_compile。commit 显式路径：
`src/proof_audit_launcher.py src/proof_audit_result_collector.py docs/patterns/StepGate.md`。

## 5. 禁止事项

- ❌ **不改任何函数逻辑**（纯 docstring；若发现逻辑 bug，记录到执行记录"发现但未动"，
  不在本 WP 修）
- ❌ 不回改续传 9 闸的 docstring（它们是成熟金标准，033 D3 已裁定不回改）
- ❌ 不在 docstring 里写行号（会漂移；写函数名/grep 关键字）
- ❌ hold 验证后必须 --auto 复位（hold 挂着会冻住未来启动的审计）

## 6. 验收 checklist

- [ ] 4 个 docstring 均含四段标识词：`这个函数做什么` / `为什么追踪` / `【检查项】` / `【论证依据`（grep 验证）
- [ ] 4 个 docstring 均含 `系统正常运行表现`（grep）
- [ ] KILL-SESSION 的 docstring 含"已退出"与"≠ 审计成功"字样（E1 澄清）
- [ ] LAUNCH 检查项含 proof.txt 与 DB 比对（"028"教训引用）
- [ ] FINALIZE-FAIL 检查项含 mark_parse_error 分流说明（与 WP-N 实现一致）
- [ ] `--register` 后 DB doc 字段验证通过（贴 4 条 grep 结果）
- [ ] StepGate.md 格式标准段已更新
- [ ] py_compile 过；无逻辑改动（`git diff --stat` 只应见 docstring 行变化）

## 7. 完成汇报要求

执行记录：4 个 docstring 全文、DB 验证输出、StepGate.md diff 摘要、验证时是否
hold/auto 复位确认。

## 8. 审计对照

1. 我会模拟 Master Agent 单步场景：`--hold GATE-AUDIT-LAUNCH` + 跑一个审计 + 读
   `--pending` 输出——闭包必须能让我不看任何其他文档就做出放行判断（自包含性检验）
2. 四段齐全 + 双小标题格式 + E1/028/WP-N 三处语义点逐项核对
3. `git diff` 确认无逻辑行改动
