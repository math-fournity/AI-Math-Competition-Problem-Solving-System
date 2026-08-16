"""monitor_pipe.py — 监控Pipe（Pipe 2.5）

自动监控Pipe 2审计运行，发现问题→写alert→向AI汇报。

两类检查：
  A. 自动检查（脚本判定对错）：
     - session_health: session数量 vs 并发数
     - queue_progress: pending是否在减少
     - output_existence: completed的run是否有输出文件
     - parse_success_rate: XML解析成功率
     - status_consistency: audit_status vs check_results一致性
     - d_check_misapplication: D检查对错误d1类型执行
     - failure_rate: 失败率过高
     - stall_detection: 长时间无进度

  B. AI review抽样（标记需AI判断的）：
     - 每N分钟抽样2条审计结果，标记为needs_ai_review
     - AI检查：审计AI的语义判断是否正确（C2/C3）

alert结构：
  {
    _key: "alert-{timestamp}-{type}",
    alert_type: "session_health" | "queue_progress" | ...,
    severity: "critical" | "warning" | "info",
    details: {...},
    status: "new" | "reviewing" | "fixed" | "wontfix",
    created_at: timestamp,
    resolved_at: null
  }

用法：
  python -m src.monitor_pipe --batch-id audit-full1 --interval 300
  python -m src.monitor_pipe --batch-id audit-full1 --check-alerts  # 查看alerts
  python -m src.monitor_pipe --batch-id audit-full1 --resolve-alert <alert_key>
"""

import argparse
import json
import os
import subprocess
import sys
import time
import re
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import ANALYSIS_TRAJECTORY_BASE, ANALYSIS_SOLVER_BASE
from src.db_schema import connect_db, ensure_schema
from src.audit_collector import AUDIT_BATCHES_COLLECTION, AUDIT_RUNS_COLLECTION, AUDIT_RESULTS_COLLECTION
from src.audit_result_collector import get_audit_output, extract_audit_xml_block, parse_audit_xml
from monitoring.shared_logger import get_logger

logger = get_logger("monitor_pipe")

MONITOR_ALERTS_COLLECTION = "monitor_alerts"

# 检查阈值
FAILURE_RATE_THRESHOLD = 0.10       # 失败率>10% alert
PARSE_SUCCESS_THRESHOLD = 0.95     # XML解析成功率<95% alert
STALL_THRESHOLD_SECONDS = 600      # 10分钟无进度 alert
SAMPLE_SIZE = 2                     # 每轮抽样2条需AI review


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _ts():
    return int(time.time())


# ============================================================
# Alert管理
# ============================================================

def ensure_monitor_collections(db):
    """确保monitor_alerts集合存在"""
    if not db.has_collection(MONITOR_ALERTS_COLLECTION):
        db.create_collection(MONITOR_ALERTS_COLLECTION)


def create_alert(db, alert_type, severity, details):
    """创建一个alert"""
    now = _utc_now()
    ts = int(time.time() * 1000)
    alert_key = f"alert-{ts}-{alert_type}"
    doc = {
        "_key": alert_key,
        "alert_type": alert_type,
        "severity": severity,
        "details": details,
        "status": "new",
        "created_at": now,
        "resolved_at": None,
    }
    try:
        db.collection(MONITOR_ALERTS_COLLECTION).insert(doc)
        print(f"  [ALERT {severity}] {alert_type}: {details.get('summary', '')}")
        return alert_key
    except Exception as e:
        logger.error(f"创建alert失败: {e}")
        return None


def get_new_alerts(db):
    """获取所有status=new的alerts"""
    aql = f"FOR a IN {MONITOR_ALERTS_COLLECTION} FILTER a.status == 'new' SORT a.created_at DESC RETURN a"
    return list(db.aql.execute(aql, ttl=60))


def resolve_alert(db, alert_key, resolution="fixed"):
    """标记alert为已解决"""
    db.collection(MONITOR_ALERTS_COLLECTION).update({
        "_key": alert_key,
        "status": resolution,
        "resolved_at": _utc_now(),
    })


# ============================================================
# 自动检查A：session健康
# ============================================================

def check_session_health(db, batch_id, expected_concurrency):
    """检查tmux session数量是否等于并发数"""
    result = subprocess.run(
        ["tmux", "list-sessions"], capture_output=True, text=True, timeout=5
    )
    au_sessions = [l for l in result.stdout.split("\n") if l.startswith("au-")]
    actual = len(au_sessions)

    # 从DB读取batch的concurrency设置
    batch = db.collection(AUDIT_BATCHES_COLLECTION).get(batch_id)
    expected = batch.get("concurrency", expected_concurrency) if batch else expected_concurrency

    # 从DB读取running状态的run数
    aql = f"FOR run IN {AUDIT_RUNS_COLLECTION} FILTER run.batch_id == @bid FILTER run.status == 'running' COLLECT WITH COUNT INTO c RETURN c"
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
    db_running = list(cursor)[0] if cursor.batch else 0

    alerts = []
    if actual == 0 and db_running > 0:
        # DB说有running但tmux没有session——launcher可能挂了
        alerts.append(("session_health", "critical", {
            "summary": f"DB有{db_running}个running但tmux无au-session，launcher可能挂了",
            "db_running": db_running,
            "tmux_sessions": actual,
        }))
    elif actual < expected and actual > 0:
        # session数少于并发数——可能有些session异常退出
        alerts.append(("session_health", "warning", {
            "summary": f"tmux session数({actual})少于并发数({expected})",
            "expected": expected,
            "actual": actual,
        }))

    return alerts


# ============================================================
# 自动检查B：队列推进
# ============================================================

def check_queue_progress(db, batch_id, last_state):
    """检查Redis队列是否在推进（pending减少，completed增加）"""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        pending = r.zcard("audit:pending")
        completed = r.llen("audit:completed")
        failed = r.llen("audit:failed")
    except Exception as e:
        return [("redis_connection", "critical", {"summary": f"Redis连接失败: {e}"})], last_state

    current_state = {"pending": pending, "completed": completed, "failed": failed, "ts": _ts()}
    alerts = []

    if last_state:
        # 检查pending是否在减少
        if pending == last_state["pending"] and pending > 0:
            # pending没变——可能stall
            elapsed = _ts() - last_state["ts"]
            if elapsed > STALL_THRESHOLD_SECONDS:
                alerts.append(("queue_stalled", "critical", {
                    "summary": f"队列{elapsed}秒无变化，pending={pending}",
                    "pending": pending,
                    "stall_seconds": elapsed,
                }))
        # 检查completed是否在增加
        if completed == last_state["completed"] and pending > 0:
            elapsed = _ts() - last_state["ts"]
            if elapsed > STALL_THRESHOLD_SECONDS:
                alerts.append(("no_completions", "warning", {
                    "summary": f"队列{elapsed}秒无新完成",
                    "completed": completed,
                    "stall_seconds": elapsed,
                }))

    return alerts, current_state


# ============================================================
# 自动检查C：产出存在性
# ============================================================

def check_output_existence(db, batch_id, sample_size=5):
    """抽查completed的run是否有输出文件"""
    aql = (
        f"FOR run IN {AUDIT_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'completed' "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    alerts = []
    missing = 0
    for run in runs:
        audit_exp_id = run.get("audit_exp_id", run.get("_key", ""))
        output = get_audit_output(audit_exp_id)
        if not output:
            missing += 1
            alerts.append(("output_missing", "critical", {
                "summary": f"completed run无输出: {audit_exp_id}",
                "audit_exp_id": audit_exp_id,
                "problem_id": run.get("problem_id", ""),
            }))

    if missing > 0 and len(runs) > 0:
        rate = missing / len(runs)
        if rate > 0.2:
            alerts.append(("output_missing_rate", "critical", {
                "summary": f"输出缺失率{rate:.0%}（{missing}/{len(runs)}）",
                "missing": missing,
                "sampled": len(runs),
            }))

    return alerts


# ============================================================
# 自动检查D：XML解析成功率
# ============================================================

def check_parse_success_rate(db, batch_id, sample_size=10):
    """抽查completed的run的XML解析成功率"""
    aql = (
        f"FOR run IN {AUDIT_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'completed' "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    if not runs:
        return []

    parsed_ok = 0
    parse_failed = []
    for run in runs:
        audit_exp_id = run.get("audit_exp_id", run.get("_key", ""))
        output = get_audit_output(audit_exp_id)
        if not output:
            parse_failed.append((audit_exp_id, "no_output"))
            continue
        xml_block = extract_audit_xml_block(output)
        if not xml_block:
            parse_failed.append((audit_exp_id, "xml_extraction_failed"))
            continue
        parsed = parse_audit_xml(xml_block)
        if parsed.get("audit_status") and parsed.get("audit_status") != "UNKNOWN":
            parsed_ok += 1
        else:
            parse_failed.append((audit_exp_id, "parse_returned_unknown"))

    rate = parsed_ok / len(runs) if runs else 0
    alerts = []
    if rate < PARSE_SUCCESS_THRESHOLD:
        alerts.append(("parse_success_rate", "warning", {
            "summary": f"XML解析成功率{rate:.0%}（{parsed_ok}/{len(runs)}），阈值{PARSE_SUCCESS_THRESHOLD:.0%}",
            "parsed_ok": parsed_ok,
            "sampled": len(runs),
            "failures": parse_failed[:5],
        }))

    return alerts


# ============================================================
# 自动检查E：audit_status vs check_results一致性
# ============================================================

def check_status_consistency(db, batch_id, sample_size=10):
    """检查audit_status是否与check_results一致"""
    aql = (
        f"FOR run IN {AUDIT_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'completed' "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    alerts = []
    for run in runs:
        audit_exp_id = run.get("audit_exp_id", run.get("_key", ""))
        output = get_audit_output(audit_exp_id)
        if not output:
            continue
        xml_block = extract_audit_xml_block(output)
        if not xml_block:
            continue
        parsed = parse_audit_xml(xml_block)
        status = parsed.get("audit_status", "UNKNOWN")
        checks = parsed.get("check_results", {})

        fail_checks = [cid for cid in ['A1','A2','A3','A4','A5','A6','B1','B2','B3','C1','C2','C3']
                       if checks.get(cid, '').startswith('FAIL')]
        a_fails = [c for c in fail_checks if c.startswith('A')]
        b_fails = [c for c in fail_checks if c.startswith('B')]
        c_fails = [c for c in fail_checks if c.startswith('C')]
        d_fails = [cid for cid in ['D1','D2','D3','D4'] if checks.get(cid, '').startswith('FAIL')]

        expected = None
        if a_fails:
            expected = 'FAIL_PARSE_ERROR' if 'A1' in a_fails else 'FAIL_INCOMPLETE'
        elif b_fails:
            expected = 'FAIL_CONTENT_CORRUPT'
        elif c_fails:
            expected = 'FAIL_INCONSISTENT'
        else:
            if d_fails:
                expected = 'PASS_NOT_SELECTABLE'
            else:
                expected = 'PASS or PASS_SELECTABLE'

        if expected and expected not in status and status not in expected:
            alerts.append(("status_inconsistency", "warning", {
                "summary": f"{run.get('problem_id','')}: status={status} but expected={expected}",
                "audit_exp_id": audit_exp_id,
                "problem_id": run.get("problem_id", ""),
                "actual_status": status,
                "expected_status": expected,
                "fail_checks": fail_checks,
                "d_fails": d_fails,
            }))

    return alerts


# ============================================================
# 自动检查F：D检查对错误d1类型执行
# ============================================================

def check_d_check_misapplication(db, batch_id, sample_size=10):
    """检查D类检查是否对CONNECTION_ERROR/TOKEN_LIMIT执行了（不应该）"""
    aql = (
        f"FOR run IN {AUDIT_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'completed' "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    alerts = []
    for run in runs:
        audit_exp_id = run.get("audit_exp_id", run.get("_key", ""))
        source_result_key = run.get("source_result_key", "")

        # 从源数据获取d1
        src = db.collection("analysis_results").get(source_result_key)
        if not src:
            continue
        d1 = src.get("dimension1_verdict", "")
        if d1 not in ("CONNECTION_ERROR", "TOKEN_LIMIT"):
            continue

        # 检查D类检查是否执行了
        output = get_audit_output(audit_exp_id)
        if not output:
            continue
        xml_block = extract_audit_xml_block(output)
        if not xml_block:
            continue
        parsed = parse_audit_xml(xml_block)
        checks = parsed.get("check_results", {})

        for d_check in ["D1", "D2", "D3", "D4"]:
            val = checks.get(d_check, "")
            if val.startswith("FAIL") and "N/A" not in val:
                alerts.append(("d_check_misapplication", "warning", {
                    "summary": f"{run.get('problem_id','')}: {d_check} FAIL on d1={d1}（应为N/A）",
                    "audit_exp_id": audit_exp_id,
                    "problem_id": run.get("problem_id", ""),
                    "d1": d1,
                    "d_check": d_check,
                    "check_value": val[:100],
                }))

    return alerts


# ============================================================
# 自动检查G：失败率
# ============================================================

def check_failure_rate(db, batch_id):
    """检查失败率"""
    aql = (
        f"FOR run IN {AUDIT_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"COLLECT status = run.status WITH COUNT INTO c "
        f"RETURN {{status, count: c}}"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
    status_counts = {r["status"]: r["count"] for r in cursor}

    total = sum(status_counts.values())
    if total == 0:
        return []

    failed_statuses = ["failed_timeout", "failed_stall", "dead_session", "rate_limited", "failed_connection"]
    failed = sum(status_counts.get(s, 0) for s in failed_statuses)
    completed = status_counts.get("completed", 0)
    finished = failed + completed

    if finished == 0:
        return []

    rate = failed / finished
    alerts = []
    if rate > FAILURE_RATE_THRESHOLD:
        alerts.append(("failure_rate", "warning", {
            "summary": f"失败率{rate:.1%}（{failed}/{finished}），阈值{FAILURE_RATE_THRESHOLD:.0%}",
            "failed": failed,
            "completed": completed,
            "finished": finished,
            "failure_breakdown": {s: status_counts.get(s, 0) for s in failed_statuses if status_counts.get(s, 0) > 0},
        }))

    return alerts


# ============================================================
# AI review抽样
# ============================================================

def flag_for_ai_review(db, batch_id, sample_size=SAMPLE_SIZE):
    """抽样几条审计结果，标记为需AI review

    AI需要检查：
    - C2/C3的语义判断是否正确（d1_exp是否真的匹配d1标签）
    - 审计AI是否有明显的误判
    """
    aql = (
        f"FOR run IN {AUDIT_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'completed' "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    flagged = []
    for run in runs:
        audit_exp_id = run.get("audit_exp_id", run.get("_key", ""))
        output = get_audit_output(audit_exp_id)
        if not output:
            continue
        xml_block = extract_audit_xml_block(output)
        if not xml_block:
            continue
        parsed = parse_audit_xml(xml_block)

        flagged.append({
            "audit_exp_id": audit_exp_id,
            "problem_id": run.get("problem_id", ""),
            "source_result_key": run.get("source_result_key", ""),
            "audit_status": parsed.get("audit_status", "?"),
            "check_results": parsed.get("check_results", {}),
            "issues_found": parsed.get("issues_found", ""),
        })

    if flagged:
        create_alert(db, "ai_review_sample", "info", {
            "summary": f"抽样{len(flagged)}条审计结果需AI review",
            "samples": flagged,
        })

    return flagged


# ============================================================
# 主监控循环
# ============================================================

def run_monitor_loop(batch_id, interval=300, expected_concurrency=5):
    """运行监控循环"""
    logger.info(f"监控Pipe启动 batch={batch_id} interval={interval}s")
    print(f"=== 监控Pipe启动 batch={batch_id} interval={interval}s ===")

    db = connect_db()
    ensure_monitor_collections(db)

    last_queue_state = None
    check_count = 0

    while True:
        check_count += 1
        now = _utc_now()
        print(f"\n--- 监控轮次 #{check_count} @ {now} ---")

        all_alerts = []

        # A. session健康
        alerts = check_session_health(db, batch_id, expected_concurrency)
        all_alerts.extend([("session_health", s, d) for _, s, d in alerts])

        # B. 队列推进
        alerts, last_queue_state = check_queue_progress(db, batch_id, last_queue_state)
        all_alerts.extend(alerts)

        # C. 产出存在性
        alerts = check_output_existence(db, batch_id)
        all_alerts.extend(alerts)

        # D. XML解析成功率
        alerts = check_parse_success_rate(db, batch_id)
        all_alerts.extend(alerts)

        # E. audit_status一致性
        alerts = check_status_consistency(db, batch_id)
        all_alerts.extend(alerts)

        # F. D检查误用
        alerts = check_d_check_misapplication(db, batch_id)
        all_alerts.extend(alerts)

        # G. 失败率
        alerts = check_failure_rate(db, batch_id)
        all_alerts.extend(alerts)

        # 创建alerts
        for alert_type, severity, details in all_alerts:
            create_alert(db, alert_type, severity, details)

        # AI review抽样（每3轮一次）
        if check_count % 3 == 0:
            flagged = flag_for_ai_review(db, batch_id)
            if flagged:
                print(f"  [AI_REVIEW] 抽样{len(flagged)}条需AI review:")
                for f in flagged:
                    print(f"    {f['problem_id']}: status={f['audit_status']}")

        # 状态报告
        aql = (
            f"FOR run IN {AUDIT_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"COLLECT status = run.status WITH COUNT INTO c "
            f"RETURN {{status, count: c}}"
        )
        cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
        status_counts = {r["status"]: r["count"] for r in cursor}

        total_done = sum(v for k, v in status_counts.items() if k not in ("prepared", "running"))
        total = sum(status_counts.values())
        print(f"  [status] {json.dumps(status_counts)}")
        print(f"  [progress] {total_done}/{total} ({100*total_done//total if total else 0}%)")

        # 检查是否所有任务都完成了
        if status_counts.get("prepared", 0) == 0 and status_counts.get("running", 0) == 0:
            print("  所有任务已完成，监控Pipe退出")
            break

        # 检查launcher进程是否还在
        result = subprocess.run(["pgrep", "-f", "run_audit_pipeline.*launch"], capture_output=True, text=True)
        if result.returncode != 0:
            create_alert(db, "launcher_dead", "critical", {
                "summary": "launcher进程不在运行，但还有prepared/running任务",
                "remaining_prepared": status_counts.get("prepared", 0),
                "remaining_running": status_counts.get("running", 0),
            })

        # 检查新alerts
        new_alerts = get_new_alerts(db)
        if new_alerts:
            print(f"  [alerts] {len(new_alerts)}个新alert:")
            for a in new_alerts:
                print(f"    [{a['severity']}] {a['alert_type']}: {a['details'].get('summary', '')}")

        time.sleep(interval)


def check_alerts(batch_id):
    """查看所有新alerts"""
    db = connect_db()
    ensure_monitor_collections(db)
    alerts = get_new_alerts(db)
    print(f"=== 新alerts: {len(alerts)}个 ===")
    for a in alerts:
        print(f"\n  [{a['severity']}] {a['alert_type']} (key={a['_key']})")
        print(f"    {a['details'].get('summary', '')}")
        for k, v in a['details'].items():
            if k != 'summary':
                print(f"    {k}: {v}")
    return alerts


def main():
    parser = argparse.ArgumentParser(description="监控Pipe")
    parser.add_argument("--batch-id", required=True, help="审计批次ID")
    parser.add_argument("--interval", type=int, default=300, help="检查间隔（秒）")
    parser.add_argument("--concurrency", type=int, default=5, help="预期并发数")
    parser.add_argument("--check-alerts", action="store_true", help="查看新alerts")
    parser.add_argument("--resolve-alert", help="标记alert为已解决")
    args = parser.parse_args()

    if args.check_alerts:
        check_alerts(args.batch_id)
    elif args.resolve_alert:
        db = connect_db()
        resolve_alert(db, args.resolve_alert)
        print(f"已解决alert: {args.resolve_alert}")
    else:
        run_monitor_loop(args.batch_id, interval=args.interval, expected_concurrency=args.concurrency)


if __name__ == "__main__":
    main()
