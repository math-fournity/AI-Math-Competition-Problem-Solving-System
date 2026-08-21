# WP-E — SOP_04 升级：C7/C8 从"读 DB 摘要"到"读实物"，C9 移交 SOP_07

> **优先级**: 第三批（WP-C 之后）
> **依赖**: WP-C（C9 的接收方）
> **预计规模**: checks.py ~60 行 + SOP_04 文档 ~40 行 + 模板微调
> **性质**: SOP 检查升级（间接→直接）

---

## 0. 给执行 AI 的第一句话

SOP_04 的审计质量复核（C7/C8/C9，WP-7 加的）现在只把 DB 里的 audit_summary/
cheating_analysis 字段打印出来给 AI 看——**间接检查**（030 需求 6 的典型违例：
看到数据库就放心了）。你要让 C7/C8 的查询带出实物路径（export 文件+proof 文件），
指引 Master Agent **读原文**做独立判断；C9（作弊复核）整体移交 SOP_07（WP-C 已建
项 6）。

## 1. 背景（为什么）

- C7 的本意（029 §7.2）："审计 AI 判 PASS 的题，proof 真的对吗？"——只读
  audit_summary 是在判断"审计 AI 的自我描述"，不是判断 proof 本身。真复核必须：
  读 export 的 XML 块（审计 AI 的完整推理）+ 读 proof.md 原文（被审对象）+ Master
  Agent 独立下结论
- 直接检查铁律（WP-B）附录清单第二项就是本 WP
- C9 移交：作弊证据复核与 SOP_07 的项 6 同源（FAIL_CHEATING 清单+cheating_analysis），
  两处重复——归并到 07（SOP_04 专注 C1-C8 的 proof 质量/审计质量）

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **确认 WP-C 完成**（SOP_07 项 6 就位） | C9 有接收方 |
| 2 | `scripts/sop/checks.py` 的 `_check_audit_quality_review`（全文） | 现状三个查询（pass/fail/cheat）的字段与打印——你的改造对象 |
| 3 | `docs/sop/SOP_04_ai_judgment.md` 全文 | 文档结构 + C1-C6 主体（不动）+ 审计复核段的写法（要改） |
| 4 | `src/proof_audit_result_collector.py` 搜 `p27_proof_audits` 文档构造（audit_doc 字段） | 实物路径怎么拿：audit 记录本身存了 proof_text/problem_text 快照；**export 路径**要从 p27_proof_audit_runs 拿（source_run_key→audit_run_key→export_path）——写清楚 JOIN 链 |
| 5 | `src/proof_audit_collector.py` 的 audit_run_doc 字段 | export_path 字段确认 |
| 6 | `docs/sop/templates/report_step_04.md` | 模板的 C7-C9 段（要改） |

## 3. 现场事实基线

- `_check_audit_quality_review` 三个 AQL 返回 `_key/source_run_key/problem_id/
  audit_status/audit_summary(/cheating_analysis)`——**无任何文件路径**
- C1-C6 主体（needs_ai_review 的续传题判断）不受本 WP 影响
- 模板 report_step_04.md 有 C7-C9 段
- 复核：`grep -n "cheat_aql\|pass_aql\|fail_aql" scripts/sop/checks.py`

**基线漂移预期**：WP-N 改过 result_collector（PARSE_ERROR 不再写 p27_proof_audits
——fail_aql 的 LIKE 'FAIL_%' 不含 PARSE_ERROR，无影响）。

## 4. 任务分解

### 任务 1：查询升级（带出实物路径）

`pass_aql`/`fail_aql` 改为 JOIN 拿路径：

```
FOR a IN p27_proof_audits
  FILTER a.audit_status IN [...] FILTER a.ai_review_done != true
  SORT RAND() LIMIT 5
  LET ar = DOCUMENT('p27_proof_audit_runs', CONCAT('paudit-', a.source_run_key))
  LET cr = DOCUMENT('p27_continuation_runs', a.source_run_key)
  RETURN {
    _key, source_run_key, problem_id, audit_status, audit_summary,
    export_path: ar.export_path,                      // 审计 AI 的完整输出（XML 在里面）
    proof_path: cr.rounds_log[LENGTH(cr.rounds_log)-1].proof_path,
    work_dir: cr.work_dir,                            // fallback: work_dir/proof.md
  }
```

打印升级：每条候选输出"**复核指引**"块——
```
[C7-3] problem_id ... PASS
  ① 读 export（审计AI完整推理）: <export_path>（grep '<proof_audit>' 定位块）
  ② 读 proof 原文（被审对象）: <proof_path 或 work_dir/proof.md>
  ③ 独立判断：proof 的 boxed 答案与解题逻辑是否支撑 PASS——不要只信 ①的summary
  ④ 判完标记: continuation_control mark-ai-review <audit记录key> --result PASS/FAIL
```
（mark-ai-review 的现有命令是否支持 audit 记录 key？查 `continuation_control.py`
的 mark-ai-review 实现——它更新 p27_continuation_runs 的 ai_review_done。审计记录的
复核标记应更新 p27_proof_audits 的 ai_review_done——若命令不支持，加一个
`--scope audit` 参数或新命令，实现写入执行记录。）

### 任务 2：C9 段移交

- `_check_audit_quality_review` 删 cheat_aql 段，函数 docstring 注明 C9 → SOP_07 项 6
- 模板 report_step_04.md 的 C9 表格移除（或标"已移交 07"）

### 任务 3：SOP_04 文档更新

- "审计质量复核"段重写：C7/C8 的执行指令升级为四步复核法（读 export→读 proof→
  独立判断→标记）；强调**直接检查**（引 rule）；C9 移交说明
- 认知闭包加一句：审计 AI 的 audit_summary 是"它的说法"，export XML 才是"它的推理"，
  proof.md 才是"事实"——三层都要看
- todo 段不变

### 任务 4：验证 + commit

真跑 check_04（`_set_next` 控制或直接 python -c 调用）——断言输出含 export/proof
路径与复核指引。commit 显式路径。

## 5. 禁止事项

- ❌ 不动 C1-C6（续传题的 AI 判断主体）
- ❌ 检查函数不做"读文件内容判定"的自动化（读与判断是 Master Agent 的活——函数只
  负责**把路径和指引送到眼前**；自动判定是间接检查的死灰复燃）
- ❌ 不删 ai_review_done 标记机制

## 6. 验收 checklist

- [ ] check_04 真跑输出含 C7/C8 各 ≤5 条的"复核指引"块（export_path+proof_path 实值）
- [ ] 输出的路径实测存在（抽 2 个 ls 验证——路径别是空的/错的）
- [ ] cheat_aql 段已删；SOP_04 文档与模板标注 C9 移交
- [ ] mark-ai-review 对 audit 记录的标记路径可用（命令实测或实现说明）
- [ ] 文档四步复核法 + 三层认知句写入
- [ ] py_compile；commit 显式路径

## 7. 完成汇报要求

执行记录：查询 diff、真跑输出、标记命令的处理方式（复用/扩展）、路径抽样验证。

## 8. 审计对照

1. 真跑 check_04，抽输出的一条路径亲手开文件核对（XML 块在 export 里、proof 在
   指引路径）——路径正确性是本 WP 的命门
2. C1-C6 零改动（diff 验证）
3. 没有引入"自动读文件判 PASS/FAIL"的伪自动化
