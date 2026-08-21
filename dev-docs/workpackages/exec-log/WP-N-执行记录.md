# WP-N 执行记录 — PARSE_ERROR 修复

> **执行时间**: 2026-08-21
> **执行者**: Devin (GLM-5.2 High)
> **状态**: ✅ 完成

---

## 一、做了什么

修复 `proof_audit_result_collector.py` 中 PARSE_ERROR 处理违反 029 §3.3 设计的问题：
- 旧实现：PARSE_ERROR 走 `audit_finalize_fail` 门闸 → `audit_passed=False` + `status="audit_failed"`（题目被踢出选题池）+ 不创建 alert
- 新实现：PARSE_ERROR 走新增的非门控函数 `mark_parse_error` → `audit_passed=None` + **不改 status** + 创建 `audit_parse_error` alert 待人工

## 二、改了哪些文件

| 文件 | 改动 |
|---|---|
| `src/proof_audit_result_collector.py` | 新增 `mark_parse_error()` 函数（~55 行）；改 `collect_results()` 两处 PARSE_ERROR 分支（从调 `audit_finalize_fail` 改为调 `mark_parse_error`） |
| `scripts/test_wp_n_parse_error.py` | 新增单测脚本（~210 行，5 个测试用例，30 个断言） |

### diff 摘要

**新增 `mark_parse_error()` 函数**（行 307-360）：
- 更新审计 run：`audit_status=PARSE_ERROR, audit_passed=None, error_message=detail[:500]`
- 更新 `p27_continuation_runs`：`audit_status, audit_passed=None, audited_at, audit_run_key`——**绝不写 status 字段**
- 创建 alert：`_key=p27-alert-audit_parse_error-{run_key[-10:]}`, `alert_type=audit_parse_error`, `severity=warning`，格式对齐 cheating_detected 段
- `log_event(logger, "warning", "audit_parse_error", ...)`

**改 `collect_results()` 分支1**（行 408-415，parse_audit_xml 返回 None）：
- 旧：调 `audit_finalize_fail(..., audit_status="PARSE_ERROR", ...)`
- 新：调 `mark_parse_error(db, run_key, audit_run_key, "XML解析失败，无法提取审计结果")`

**改 `collect_results()` 分支2**（行 437-442，audit_status 无效枚举）：
- 旧：调 `audit_finalize_fail(..., audit_status="PARSE_ERROR", ...)`
- 新：调 `mark_parse_error(db, run_key, audit_run_key, f"audit_status 无效: {audit_status}")`

## 三、验证结果

### py_compile
```
python -m py_compile src/proof_audit_result_collector.py scripts/test_wp_n_parse_error.py
→ OK（无输出）
```

### 单测输出全文
```
============================================================
WP-N PARSE_ERROR 修复单测
============================================================

=== 测试 1：mark_parse_error 直接调用 ===
  ✅ 审计 run 有 1 次 update
  ✅ 审计 run audit_status=PARSE_ERROR
  ✅ 审计 run audit_passed=None
  ✅ 审计 run 有 error_message
  ✅ 审计 run 未写 status
  ✅ runs 有 1 次 update
  ✅ runs update key 正确
  ✅ runs audit_status=PARSE_ERROR
  ✅ runs audit_passed=None
  ✅ runs 有 audited_at
  ✅ runs 有 audit_run_key
  ✅ ★ runs status 未被修改（与旧实现的本质区别）
  ✅ alert 集合有 1 条 insert
  ✅ alert _key 前缀 p27-alert-audit_parse_error-
  ✅ alert alert_type=audit_parse_error
  ✅ alert severity=warning
  ✅ alert status=new
  ✅ alert details.summary 含 audit_run_key
  ✅ alert details.run_key 正确
  ✅ 未写 p27_proof_audits（PARSE_ERROR 不建审计结果记录）

=== 测试 2：collect_results 分支1（parse_audit_xml 返回 None）===
  ✅ audit_finalize_fail 未被调用
  ✅ mark_parse_error 被调用 1 次
  ✅ collected=1

=== 测试 3：collect_results 分支2（audit_status 无效枚举）===
  ✅ audit_finalize_fail 未被调用
  ✅ mark_parse_error 被调用 1 次
  ✅ collected=1

=== 测试 4：PASS/FAIL 路径未被误伤 ===
  ✅ PASS 走 audit_finalize_pass
  ✅ PASS 不走 audit_finalize_fail
  ✅ PASS 不走 mark_parse_error

=== 测试 5：parse_audit_xml 对无效 audit_status 标 PARSE_ERROR ===
  ✅ 无效 audit_status 被标为 PARSE_ERROR

============================================================
结果: 30 PASS / 0 FAIL
============================================================
```

### 验收 checklist

- [x] `grep -n "mark_parse_error" src/proof_audit_result_collector.py` — 函数定义(307) + 两处调用(411, 439)
- [x] `grep -n "audit_finalize_fail" src/proof_audit_result_collector.py` — 调用点只剩 432（FAIL 分支），PARSE_ERROR 分支不再出现
- [x] `grep -n "audit_parse_error" src/proof_audit_result_collector.py` — alert 创建段存在(338, 339, 358)
- [x] `python -m py_compile src/proof_audit_result_collector.py` — 无输出（通过）
- [x] `python scripts/test_wp_n_parse_error.py` — 30 PASS / 0 FAIL
- [x] 单测断言含"status 未被修改"（测试1的★断言）
- [x] `grep -rn "AUDIT_DEFAULT_CONCURRENCY" src/` — 仍为 5（未动，WP-G 才动）

## 四、遗留问题

- **DB 隔离方案**：单测使用 mock db 对象（`MockDB`/`MockCollection` 类），不依赖真实 DB 写入。这是 WP-N 文档允许的"退而求其次"方案。如果后续需要真实 DB 集成测试，可用 `ARANGO_DB` env 指向测试库（sim 的隔离旋钮）。
- **文档同步**：SYSTEM_CLOSURE.md §6 alert 清单的 `audit_parse_error` 行已存在且描述正确（"审计AI无法解析proof，人工处理"），无需改动。本次改动让实现追上了文档（之前 031 C2 指出清单超前于代码，现在代码对齐了）。

## 五、认知闭包与 checklist 影响分析

```
=== 认知闭包与 checklist 影响分析 ===
认知闭包（SYSTEM_CLOSURE.md）：
  - [无需更新] §6 alert_type 清单：audit_parse_error 行已存在且描述正确，
    本次改动让实现追上了文档，清单本身无需改
  - [无需更新] §1-§5/§7：本次改动是已有模块内部 bug 修复，
    不新增模块/不改架构/不改生命周期/不改数据产出范围
checklist/：
  - [无需更新] 原因：本次改动是修复实现违反 029 设计的 bug，
    不新增检查需求点，不改变现有检查项的判定标准
```
