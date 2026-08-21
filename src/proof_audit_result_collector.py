"""proof_audit_result_collector.py — Pipe 5 审计结果收集组件

解析审计 devin cli 的 export（conversation.json），提取 XML 审计报告，
写入 p27_proof_audits 集合，更新 p27_continuation_runs 的审计状态字段。

门闸（@gated）：
  GATE-AUDIT-FINALIZE-PASS — 写 audit_passed=True（resource=db）
  GATE-AUDIT-FINALIZE-FAIL — 写 audit_passed=False + 改 status（resource=db）

用法：
  python -m src.proof_audit_result_collector --batch-id paudit-p27-full
"""
import argparse
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.proof_audit_config import (
    PROOF_AUDIT_RUNS_COLLECTION,
    PROOF_AUDITS_COLLECTION,
    CONTINUATION_RUNS_COLLECTION,
    MONITOR_ALERTS_COLLECTION,
    AUDIT_COMPLETE_MARKER,
    AUDIT_PASS_STATUSES,
    AUDIT_FAIL_STATUSES,
    AUDIT_REDO_STATUSES,
    AUDIT_CHEATING_STATUSES,
    GATE_AUDIT_FINALIZE_PASS,
    GATE_AUDIT_FINALIZE_FAIL,
)
from src.proof_audit_db_schema import (
    connect_db, ensure_schema, get_audit_run, update_audit_run,
    insert_proof_audit, update_continuation_run_audit_status,
)
from src.step_gate import gated
from monitoring.shared_logger import get_logger, log_event

logger = get_logger("proof_audit_result_collector")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


# === XML 解析 ===

def parse_audit_xml(text):
    """从审计 AI 的输出中解析 <proof_audit> XML 块。

    返回 dict 或 None（解析失败时）。
    """
    # 找 <proof_audit>...</proof_audit> 块
    m = re.search(r"<proof_audit>(.*?)</proof_audit>", text, re.DOTALL)
    if not m:
        return None

    block = m.group(1)

    result = {
        "problem_id": _extract_tag(block, "problem_id"),
        "audit_status": _extract_tag(block, "audit_status"),
        "audit_summary": _extract_tag(block, "audit_summary"),
        "cheating_analysis": _extract_tag(block, "cheating_analysis"),
        "check_results": {},
    }

    # 解析 check_results
    cr_match = re.search(r"<check_results>(.*?)</check_results>", block, re.DOTALL)
    if cr_match:
        cr_block = cr_match.group(1)
        for tag in ["A1", "B1", "B2", "C1", "C2", "D1", "D2", "E1", "E2"]:
            result["check_results"][tag] = _extract_tag(cr_block, tag)

    # 校验 audit_status 是有效枚举
    valid_statuses = (
        AUDIT_PASS_STATUSES | AUDIT_FAIL_STATUSES |
        {"PARSE_ERROR"}
    )
    if result["audit_status"] not in valid_statuses:
        result["audit_status"] = "PARSE_ERROR"

    return result


def _extract_tag(block, tag):
    """从 XML 块中提取单个标签的内容"""
    m = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.DOTALL)
    return m.group(1).strip() if m else ""


def extract_audit_from_export(export_path):
    """从 conversation.json 中提取审计 AI 的输出文本。

    审计 AI 的输出在最后一个 assistant message 的 content 中。
    """
    if not Path(export_path).exists():
        return None

    try:
        with open(export_path) as f:
            data = json.load(f)
    except Exception as e:
        log_event(logger, "warning", "parse_export_failed",
                  export_path=str(export_path), error=str(e))
        return None

    # conversation.json 格式：steps 列表，找最后一个 assistant 的 message
    steps = data.get("steps", [])
    assistant_texts = []
    for step in steps:
        if step.get("source") == "assistant":
            msg = step.get("message", "")
            if isinstance(msg, dict):
                # 可能是 {"content": "...", ...}
                content = msg.get("content", "")
            else:
                content = msg
            if content:
                assistant_texts.append(content)

    if not assistant_texts:
        return None

    # 合并所有 assistant 文本（审计报告可能在最后一个）
    full_text = "\n".join(assistant_texts)

    # 也检查是否有 ### PROOF AUDIT COMPLETE 标记
    if AUDIT_COMPLETE_MARKER not in full_text:
        # 标记不在 export 中——可能审计未完成
        # 但仍然尝试解析 XML（可能标记在 tmux pane 中但没进 export）
        pass

    return full_text


# === 门控的终态写入 ===

@gated(resource="db")
def audit_finalize_pass(db, run_key, audit_run_key, audit_status, check_results,
                         cheating_analysis, audit_summary, audited_at):
    """【门闸: GATE-AUDIT-FINALIZE-PASS】写 audit_passed=True（进入选题池）。

    这个函数做什么：
    - 写 p27_proof_audits 审计结果记录；
    - 更新 p27_continuation_runs 的 audit_passed=True。

    为什么追踪这个动作：
    - audit_passed=True 是选题池的准入条件——通过=进入选题池；
    - 误通过会导致错误题目进入选题池。

    放行前 Master Agent 应检查：
    1. 审计 export 的 XML 解析成功 → 查法：check_results 字段齐全
    2. audit_status=PASS 或 PASS_WITH_CAVEAT → 查法：读 audit_status 字段
    3. A1 答案正确性 PASS → 查法：check_results.A1 含 PASS
    4. 无作弊标记 → 查法：E1/E2 均 PASS 或 N/A
    """
    # 获取审计 run 信息
    audit_run = get_audit_run(db, audit_run_key)
    if not audit_run:
        log_event(logger, "error", "finalize_pass_no_audit_run",
                  audit_run_key=audit_run_key)
        return

    # 写 p27_proof_audits
    audit_doc = {
        "_key": f"paudit-result-{run_key}",
        "source_run_key": run_key,
        "problem_id": audit_run.get("problem_id", ""),
        "batch_id": audit_run.get("batch_id", ""),
        "audit_status": audit_status,
        "check_results": check_results,
        "cheating_analysis": cheating_analysis or "无作弊嫌疑",
        "audit_summary": audit_summary,
        "proof_text": audit_run.get("proof_text", ""),
        "problem_text": audit_run.get("problem_text", ""),
        "standard_answer": audit_run.get("standard_answer", ""),
        "solver_trajectory_summary": "（暂未提供）",
        "created_at": audited_at,
    }
    insert_proof_audit(db, audit_doc)

    # 更新 p27_continuation_runs
    update_continuation_run_audit_status(
        db, run_key, audit_status, True, audited_at,
        audit_run_key=audit_run_key)

    # 更新审计 run
    update_audit_run(db, audit_run_key, {
        "status": "completed",
        "audit_status": audit_status,
        "audit_passed": True,
        "audited_at": audited_at,
    })

    log_event(logger, "info", "finalize_pass",
              run_key=run_key, audit_status=audit_status)


@gated(resource="db")
def audit_finalize_fail(db, run_key, audit_run_key, audit_status, check_results,
                         cheating_analysis, audit_summary, audited_at):
    """【门闸: GATE-AUDIT-FINALIZE-FAIL】写 audit_passed=False + 可能改 status。

    这个函数做什么：
    - 写 p27_proof_audits 审计结果记录；
    - 更新 p27_continuation_runs 的 audit_passed=False；
    - FAIL_INCOMPLETE 时改 status=prepared（重做）；
    - FAIL_CHEATING / FAIL_CHEATING_DECLARED 时创建 cheating_detected alert。

    为什么追踪这个动作：
    - audit_passed=False 排除题目出选题池——几乎不可逆（需人工复查翻案）；
    - 改 status=prepared 会让题目重新进入做题队列；
    - 误判会浪费做题资源或错误排除正确题目。

    放行前 Master Agent 应检查：
    1. 审计 export 的 XML 解析成功 → 查法：check_results 字段齐全
    2. audit_status 是 FAIL_* 之一 → 查法：读 audit_status 字段
    3. FAIL_INCOMPLETE 时确认 proof 确实是截断残篇 → 查法：读 proof.md 看是否中途断裂
    4. FAIL_CHEATING 时确认作弊证据充分 → 查法：读 cheating_analysis 字段
    5. 改 status=audit_failed 的影响：该题退出选题池，需人工复查才能翻案
    """
    audit_run = get_audit_run(db, audit_run_key)
    if not audit_run:
        log_event(logger, "error", "finalize_fail_no_audit_run",
                  audit_run_key=audit_run_key)
        return

    # 写 p27_proof_audits
    audit_doc = {
        "_key": f"paudit-result-{run_key}",
        "source_run_key": run_key,
        "problem_id": audit_run.get("problem_id", ""),
        "batch_id": audit_run.get("batch_id", ""),
        "audit_status": audit_status,
        "check_results": check_results,
        "cheating_analysis": cheating_analysis or "无作弊嫌疑",
        "audit_summary": audit_summary,
        "proof_text": audit_run.get("proof_text", ""),
        "problem_text": audit_run.get("problem_text", ""),
        "standard_answer": audit_run.get("standard_answer", ""),
        "solver_trajectory_summary": "（暂未提供）",
        "created_at": audited_at,
    }
    insert_proof_audit(db, audit_doc)

    # 决定 status 变更
    new_status = None
    if audit_status in AUDIT_REDO_STATUSES:
        # FAIL_INCOMPLETE → 改回 prepared 重做
        new_status = "prepared"
    else:
        # 其他 FAIL → audit_failed
        new_status = "audit_failed"

    # 更新 p27_continuation_runs
    from src.continuation_db_schema import update_run
    update_fields = {
        "audit_status": audit_status,
        "audit_passed": False,
        "audited_at": audited_at,
        "audit_run_key": audit_run_key,
    }
    if new_status:
        update_fields["status"] = new_status
    update_run(db, run_key, update_fields)

    # 更新审计 run
    update_audit_run(db, audit_run_key, {
        "status": "completed",
        "audit_status": audit_status,
        "audit_passed": False,
        "audited_at": audited_at,
    })

    # 作弊检测——创建 alert
    if audit_status in AUDIT_CHEATING_STATUSES:
        try:
            alert_doc = {
                "_key": f"p27-alert-cheating_detected-{run_key[-10:]}",
                "alert_type": "cheating_detected",
                "severity": "critical",
                "details": {
                    "summary": f"审计检测到作弊: {audit_status}",
                    "run_key": run_key,
                    "problem_id": audit_run.get("problem_id", ""),
                    "cheating_analysis": cheating_analysis,
                },
                "status": "new",
                "created_at": audited_at,
                "first_seen_at": audited_at,
                "last_seen_at": audited_at,
                "occurrence_count": 1,
            }
            db.collection(MONITOR_ALERTS_COLLECTION).insert(alert_doc)
        except Exception as e:
            # alert 创建失败不影响主流程
            log_event(logger, "warning", "create_cheating_alert_failed",
                      run_key=run_key, error=str(e))

    log_event(logger, "info", "finalize_fail",
              run_key=run_key, audit_status=audit_status, new_status=new_status)


# === 结果收集主逻辑 ===

def collect_results(batch_id, limit=None):
    """收集审计结果——解析 export，写入 DB"""
    print(f"=== 收集审计结果 batch={batch_id} ===")
    log_event(logger, "info", "collect_results_start", batch_id=batch_id)

    db = connect_db()
    ensure_schema(db)

    # 查 completed 但未写入 p27_proof_audits 的审计 run
    aql = (
        f"FOR run IN {PROOF_AUDIT_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'completed' "
        f"FILTER run.audit_status == null "
        f"LIMIT @lim "
        f"RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "lim": limit or 1000}, ttl=120)
    candidates = list(cursor)

    print(f"  待收集审计结果: {len(candidates)}")

    if not candidates:
        print("  （无待收集结果）")
        return 0

    collected = 0
    parse_errors = 0

    for audit_run in candidates:
        audit_run_key = audit_run["_key"]
        run_key = audit_run.get("source_run_key", "")
        export_path = audit_run.get("export_path", "")

        # 从 export 提取审计文本
        audit_text = extract_audit_from_export(export_path)
        if not audit_text:
            print(f"  [skip] {audit_run_key}: 无 export 或无 assistant 文本")
            parse_errors += 1
            continue

        # 解析 XML
        parsed = parse_audit_xml(audit_text)
        if not parsed:
            # XML 解析失败——标记为 PARSE_ERROR
            print(f"  [parse-error] {audit_run_key}: XML 解析失败")
            audited_at = utc_now()
            audit_finalize_fail(
                db, run_key, audit_run_key,
                audit_status="PARSE_ERROR",
                check_results={},
                cheating_analysis="XML解析失败，无法提取审计结果",
                audit_summary="PARSE_ERROR: XML解析失败",
                audited_at=audited_at,
            )
            parse_errors += 1
            collected += 1
            continue

        audit_status = parsed["audit_status"]
        check_results = parsed["check_results"]
        cheating_analysis = parsed.get("cheating_analysis", "无作弊嫌疑")
        audit_summary = parsed.get("audit_summary", "")

        audited_at = utc_now()

        # 根据审计结果走不同门闸
        if audit_status in AUDIT_PASS_STATUSES:
            audit_finalize_pass(
                db, run_key, audit_run_key,
                audit_status, check_results,
                cheating_analysis, audit_summary, audited_at)
            print(f"  [pass] {audit_run_key}: {audit_status}")
        elif audit_status in AUDIT_FAIL_STATUSES:
            audit_finalize_fail(
                db, run_key, audit_run_key,
                audit_status, check_results,
                cheating_analysis, audit_summary, audited_at)
            print(f"  [fail] {audit_run_key}: {audit_status}")
        else:
            # PARSE_ERROR 或其他
            audit_finalize_fail(
                db, run_key, audit_run_key,
                audit_status="PARSE_ERROR",
                check_results=check_results,
                cheating_analysis=cheating_analysis,
                audit_summary=audit_summary or "PARSE_ERROR",
                audited_at=audited_at)
            print(f"  [parse-error] {audit_run_key}: {audit_status}")
            parse_errors += 1

        collected += 1

    print(f"\n=== 收集完成 ===")
    print(f"  collected: {collected}")
    print(f"  parse_errors: {parse_errors}")

    log_event(logger, "info", "collect_results_done",
              batch_id=batch_id, collected=collected, parse_errors=parse_errors)

    return collected


def main():
    parser = argparse.ArgumentParser(description="Pipe 5 审计结果收集")
    parser.add_argument("--batch-id", required=True, help="审计批次ID")
    parser.add_argument("--limit", type=int, default=1000, help="限制收集数")
    args = parser.parse_args()

    count = collect_results(args.batch_id, limit=args.limit)
    print(f"\n完成: {count}条审计结果已收集")


if __name__ == "__main__":
    main()
