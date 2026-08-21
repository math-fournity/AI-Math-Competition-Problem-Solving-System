# WP-N — PARSE_ERROR 修复（实现违反 029 设计的回调）

> **优先级**: 第一批之首（WP-P 依赖它）
> **依赖**: 无
> **预计规模**: proof_audit_result_collector.py 内 ~60 行改动 + 测试脚本 ~80 行
> **性质**: 代码修复 + 测试

---

## 0. 给执行 AI 的第一句话

审计 Pipe 的 `proof_audit_result_collector.py` 在 XML 解析失败（PARSE_ERROR）时错误地
走了 `audit_finalize_fail` 门闸——把题目标成 `audit_failed`（踢出选题池）。029 设计
方案（已获用户批准的权威）规定 PARSE_ERROR 应**保持待定**（audit_passed=None、不改
status）并创建 alert 等人工处理。你要把实现改回设计。

## 1. 背景（为什么）

029 §3.2/§3.3 是权威设计：PARSE_ERROR 表示"审计 AI 的输出无法解析"——**我们不知道
proof 对不对**，所以既不能进选题池也不能踢出，必须等人看。当前实现把"不知道"当成
"失败"处理，违反了"适度依赖 Master Agent 介入"硬约束（AGENTS.md，2026-08-21 新增）
——不可靠的判定应标"待人工"，不强行自动判定。

来源：031 §二 C1 发现，032 §四 C1 独立验证，034 接受。链条：dev-docs/029 §3.3 >
实现（7d09079 之前的 commit d6d3dba WP-4~5）——时间线裁定实现错。

## 2. 前置认知加载清单（按序加载，提取指定认知）

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `dev-docs/029-Pipe5-proof审计系统设计方案.md` §3.2（审计结果类型表）+ §3.3（DB 处理逻辑） | PARSE_ERROR 行的准确语义：`audit_passed=None + 需人工复查`、`创建 audit_parse_error alert`、**不改 status** |
| 2 | `src/proof_audit_result_collector.py` **全文**（~424 行） | ① `collect_results()` 中两个 PARSE_ERROR 分支（搜 `PARSE_ERROR`，一个在 parse_audit_xml 返回 None 时、一个在 audit_status 无效时）② `audit_finalize_fail()` 的完整行为（你要绕开它）③ 现有 alert 创建代码（`audit_finalize_fail` 内 cheating_detected 段——key 格式 `p27-alert-cheating_detected-{run_key[-10:]}`，照此风格）④ import 列表 |
| 3 | `src/proof_audit_config.py`（82 行） | `AUDIT_REDO_STATUSES`、`MONITOR_ALERTS_COLLECTION` 的 import 来源、audit_status 枚举 |
| 4 | `AGENTS.md` 搜"适度依赖" | 该硬约束的 4 条设计准则（你的修复是它的示范实现） |
| 5 | `monitoring/shared_logger.py` 的 `log_event` 签名（grep "def log_event"） | 打日志的正确用法 |

## 3. 现场事实基线（2026-08-21 09:30，执行前复核）

- `src/proof_audit_result_collector.py` 的 `collect_results()` 有两处把 PARSE_ERROR 传给
  `audit_finalize_fail(...)`（一处在 `parse_audit_xml` 返回 None 的分支，一处在
  `audit_status` 不在 PASS/FAIL 集合的 else 分支）
- `audit_finalize_fail()` 内 `new_status` 逻辑：`AUDIT_REDO_STATUSES`（仅 FAIL_INCOMPLETE）
  → "prepared"，否则 → "audit_failed"。PARSE_ERROR 落入后者
- PARSE_ERROR 路径当前**不创建任何 alert**
- 复核命令：`grep -n "PARSE_ERROR" src/proof_audit_result_collector.py` 应看到 ≥4 处

**基线漂移预期**：WP-N 是第一个执行的代码 WP，此文件应无人改过。若已被改，停下报告。

## 4. 任务分解

### 任务 1：新增 `mark_parse_error()` 函数（非门控）

在 `proof_audit_result_collector.py` 中新增：

```python
def mark_parse_error(db, run_key, audit_run_key, detail):
    """PARSE_ERROR 处理（029 §3.3）——audit_passed=None、不改 status、创建 alert 待人工。

    为什么不走 audit_finalize_fail 门闸：PARSE_ERROR 表示"审计输出无法解析"，
    我们不知道 proof 对错——既不能进选题池也不能踢出。final 门闸是"确知结果"
    的写入点，"不知道"没有资格过闸（适度依赖 Master Agent 硬约束）。
    """
```

行为规格：
1. `update_audit_run(db, audit_run_key, {"audit_status": "PARSE_ERROR", "audit_passed": None, "audited_at": utc_now(), "error_message": detail[:500]})`
2. 更新 `p27_continuation_runs`：用 `update_run`（从 `src.continuation_db_schema` import，
   参考 `audit_finalize_fail` 内的用法）写 `{audit_status: "PARSE_ERROR", audit_passed: None, audited_at: ..., audit_run_key: ...}`——
   **绝不写 status 字段**
3. 创建 alert 到 `MONITOR_ALERTS_COLLECTION`，格式对齐现有 cheating_detected 段：
   - `_key`: `f"p27-alert-audit_parse_error-{run_key[-10:]}"`
   - `alert_type`: `"audit_parse_error"`，`severity`: `"warning"`
   - `details.summary`: 含 audit_run_key 和 detail 前 100 字
   - 其余字段（status/created_at/first_seen_at/last_seen_at/occurrence_count）照抄
     cheating_detected 段的写法
   - 异常不中断主流程（照抄现有 try/except + log_event 模式）
4. `log_event(logger, "warning", "audit_parse_error", ...)`

### 任务 2：改 `collect_results()` 的两个 PARSE_ERROR 分支

两处都改为调 `mark_parse_error(db, run_key, audit_run_key, <原因描述>)`，删除对
`audit_finalize_fail` 的调用。`parse_errors` 计数保留。

### 任务 3：单测脚本 `scripts/test_wp_n_parse_error.py`

参考 `scripts/test_016_step_gate.py` 的风格。测试策略（不依赖真实 DB 写入的生产集合）：
1. 用 `ARANGO_DB` env 指向测试库（sim 的隔离旋钮，见 `src/continuation_config.py` 的
   `ARANGO_DB` env 说明；若不熟悉则读 `dev-docs/017` §隔离机制，或退而求其次：单测
   `mark_parse_error` 对 mock db 对象的行为）
2. 最小验收断言（至少）：
   - 构造一个 `audit_run` 文档（含 source_run_key）+ 一段**无 XML 块**的假 export 文本
     → 走 `collect_results` 或直接调 `mark_parse_error`
   - 断言：runs 的 status **未被修改**、audit_status=="PARSE_ERROR"、audit_passed is None
   - 断言：alert 集合多了一条 audit_parse_error
   - 断言：`audit_finalize_fail` **未被调用**（可用 monkeypatch 打标记）

### 任务 4：py_compile + 执行单测 + commit

```
python -m py_compile src/proof_audit_result_collector.py scripts/test_wp_n_parse_error.py
python scripts/test_wp_n_parse_error.py
git add src/proof_audit_result_collector.py scripts/test_wp_n_parse_error.py
git commit  # message: "WP-N: PARSE_ERROR按029 §3.3修复——不走FINALIZE-FAIL，audit_passed=None+alert待人工"
```

### 任务 5：文档同步（铁律 2）

- `docs/sop/SYSTEM_CLOSURE.md`：搜 `audit_parse_error`（§6 alert 清单里已有该行），
  确认其"处理方式"列写的是"审计 AI 无法解析 proof，人工处理"——与实现一致即可，
  无需改动则不动
- `dev-docs/029` **不改**（它是历史方案文档，设计本来就是对 的）

## 5. 禁止事项

- ❌ 不要改 `audit_finalize_fail` 本身的 FAIL_* 逻辑（其他 FAIL 状态仍走它，那是正确的）
- ❌ 不要给 PARSE_ERROR 建 `p27_proof_audits` 记录（029 §3.3 没让建；alert 就是痕迹）
- ❌ 不要顺手"优化"文件里的其他代码（scope 严格限定两个分支+一个新函数）
- ❌ 不要改 `proof_audit_config.py` 的枚举（PARSE_ERROR 已在有效枚举里）

## 6. 验收 checklist（逐项执行并贴输出）

- [ ] `grep -n "mark_parse_error" src/proof_audit_result_collector.py` — 函数定义 + 两处调用
- [ ] `grep -n "audit_finalize_fail" src/proof_audit_result_collector.py` — 调用点只剩
      PASS/FAIL 分支的（PARSE_ERROR 分支不再出现）
- [ ] `grep -n "audit_parse_error" src/proof_audit_result_collector.py` — alert 创建段存在
- [ ] `python -m py_compile src/proof_audit_result_collector.py` — 无输出（通过）
- [ ] `python scripts/test_wp_n_parse_error.py` — 全部断言 PASS，输出贴执行记录
- [ ] 单测断言含"status 未被修改"（这是与旧实现的本质区别）
- [ ] `grep -rn "AUDIT_DEFAULT_CONCURRENCY" src/` — 仍为 5（你没动它，WP-G 才动）

## 7. 完成汇报要求

写 `dev-docs/workpackages/exec-log/WP-N-执行记录.md`：改动 diff 摘要、单测输出全文、
验收 checklist 勾选状态、遗留问题（如单测的 DB 隔离方案用了哪种）。填总控状态表。

## 8. 审计对照（设计者审计时核什么）

1. PARSE_ERROR 后 runs 的 status 字段确实未被触碰（我会查测试库/mock 的调用序列）
2. alert 的 key 格式与 cheating_detected 风格一致（`p27-alert-audit_parse_error-`前缀）
3. 没有动 FAIL_* 路径
4. commit 只含两个文件
