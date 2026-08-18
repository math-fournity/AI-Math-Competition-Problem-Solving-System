"""monitor_selection.py — Pipe 3选题监控Pipe

复用monitor_pipe.py的alert管理架构，但针对selection_runs/selection_results检查。

两类检查：
  A. 自动检查（脚本判定）：
     - session_health: se- session数 vs 并发数
     - queue_progress: selection队列推进
     - output_existence: completed的run是否有输出
     - parse_success_rate: selection XML解析成功率
     - failure_rate: 失败率过高
     - stall_detection: 长时间无进度

  B. POC字段质量检查（Pipe 3扩展特有）：
     - field_completeness: 6个新字段填写率
     - value_distribution: 6字段值分布异常（全unclear/全hard/全root等）
     - logic_consistency: 字段间逻辑一致性（suitable=YES但batch=N/A等）

  C. AI review抽样：
     - 每轮抽样2条selection结果，标记为needs_ai_review
     - AI检查：selection_reason是否合理、6字段值是否合理

alert结构同monitor_pipe.py，details中包含problem_id，便于AI定位需重新处理的题。

用法：
  python -m src.monitor_selection --batch-id selection-full1 --interval 120
  python -m src.monitor_selection --batch-id selection-full1 --check-alerts
  python -m src.monitor_selection --batch-id selection-full1 --resolve-alert <alert_key>
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import ANALYSIS_TRAJECTORY_BASE
from src.db_schema import connect_db, ensure_schema
from src.selection_collector import (
    SELECTION_BATCHES_COLLECTION, SELECTION_RUNS_COLLECTION, SELECTION_RESULTS_COLLECTION,
)
from src.selection_result_collector import (
    get_selection_output, extract_selection_xml, parse_selection_xml,
)
from monitoring.shared_logger import get_logger

logger = get_logger("monitor_selection")

MONITOR_ALERTS_COLLECTION = "monitor_alerts"

# 检查阈值
FAILURE_RATE_THRESHOLD = 0.10
PARSE_SUCCESS_THRESHOLD = 0.95
STALL_THRESHOLD_SECONDS = 600
SAMPLE_SIZE = 2

# 6个POC字段
POC_FIELDS = [
    "false_friend_candidate", "boundary_case_candidate",
    "process_signal_observability", "leakage_risk",
    "difficulty_estimate", "branch_position_hint",
]

# 合法取值
VALID_VALUES = {
    "false_friend_candidate": {"yes", "no", "unclear"},
    "boundary_case_candidate": {"yes", "no", "unclear"},
    "process_signal_observability": {"high", "medium", "low", "unclear"},
    "leakage_risk": {"low", "medium", "high"},
    "difficulty_estimate": {"easy", "medium", "hard"},
    "branch_position_hint": {"root", "line", "unclear"},
}


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _ts():
    return int(time.time())


# ============================================================
# Alert管理（复用monitor_pipe.py的集合）
# ============================================================

def ensure_monitor_collections(db):
    if not db.has_collection(MONITOR_ALERTS_COLLECTION):
        db.create_collection(MONITOR_ALERTS_COLLECTION)


def create_alert(db, alert_type, severity, details):
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
    aql = f"FOR a IN {MONITOR_ALERTS_COLLECTION} FILTER a.status == 'new' SORT a.created_at DESC RETURN a"
    return list(db.aql.execute(aql, ttl=60))


def resolve_alert(db, alert_key, resolution="fixed"):
    db.collection(MONITOR_ALERTS_COLLECTION).update({
        "_key": alert_key,
        "status": resolution,
        "resolved_at": _utc_now(),
    })


# ============================================================
# 自动检查A：session健康
# ============================================================

def check_session_health(db, batch_id, expected_concurrency):
    result = subprocess.run(
        ["tmux", "list-sessions"], capture_output=True, text=True, timeout=5
    )
    se_sessions = [l for l in result.stdout.split("\n") if l.startswith("se-")]
    actual = len(se_sessions)

    batch = db.collection(SELECTION_BATCHES_COLLECTION).get(batch_id)
    expected = batch.get("concurrency", expected_concurrency) if batch else expected_concurrency

    aql = (
        f"FOR run IN {SELECTION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'running' "
        f"COLLECT WITH COUNT INTO c RETURN c"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
    db_running = list(cursor)[0] if cursor.batch else 0

    alerts = []
    if actual == 0 and db_running > 0:
        alerts.append(("session_health", "critical", {
            "summary": f"DB有{db_running}个running但tmux无se-session，launcher可能挂了",
            "db_running": db_running,
            "tmux_sessions": actual,
        }))
    elif actual < expected and actual > 0:
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
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        pending = r.zcard("selection:pending")
        completed = r.llen("selection:completed")
        failed = r.llen("selection:failed")
    except Exception as e:
        return [("redis_connection", "critical", {"summary": f"Redis连接失败: {e}"})], last_state

    current_state = {"pending": pending, "completed": completed, "failed": failed, "ts": _ts()}
    alerts = []

    if last_state:
        if pending == last_state["pending"] and pending > 0:
            elapsed = _ts() - last_state["ts"]
            if elapsed > STALL_THRESHOLD_SECONDS:
                alerts.append(("queue_stalled", "critical", {
                    "summary": f"队列{elapsed}秒无变化，pending={pending}",
                    "pending": pending,
                    "stall_seconds": elapsed,
                }))
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
    aql = (
        f"FOR run IN {SELECTION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'completed' "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    alerts = []
    missing = 0
    for run in runs:
        selection_exp_id = run.get("selection_exp_id", run.get("_key", ""))
        output = get_selection_output(selection_exp_id)
        if not output:
            missing += 1
            alerts.append(("output_missing", "critical", {
                "summary": f"completed run无输出: {selection_exp_id}",
                "selection_exp_id": selection_exp_id,
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
    aql = (
        f"FOR run IN {SELECTION_RUNS_COLLECTION} "
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
        selection_exp_id = run.get("selection_exp_id", run.get("_key", ""))
        output = get_selection_output(selection_exp_id)
        if not output:
            parse_failed.append((selection_exp_id, run.get("problem_id", ""), "no_output"))
            continue
        xml_block = extract_selection_xml(output)
        if not xml_block:
            parse_failed.append((selection_exp_id, run.get("problem_id", ""), "xml_extraction_failed"))
            continue
        parsed = parse_selection_xml(xml_block)
        if parsed.get("suitable") and parsed.get("suitable") not in ("UNKNOWN", None):
            parsed_ok += 1
        else:
            parse_failed.append((selection_exp_id, run.get("problem_id", ""), "parse_returned_unknown"))

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
# 自动检查E：失败率
# ============================================================

def check_failure_rate(db, batch_id):
    aql = (
        f"FOR run IN {SELECTION_RUNS_COLLECTION} "
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
# POC字段质量检查F：6字段填写率
# ============================================================

def check_field_completeness(db, batch_id, sample_size=20):
    """检查selection_results中6个POC字段的填写率"""
    aql = (
        f"FOR r IN {SELECTION_RESULTS_COLLECTION} "
        f"FILTER r.batch_id == @bid "
        f"SORT RAND() LIMIT @n RETURN r"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    results = list(cursor)

    if not results:
        return []

    alerts = []
    for field in POC_FIELDS:
        missing = sum(1 for r in results if not r.get(field) or r.get(field) == "MISSING")
        if missing > 0:
            rate = missing / len(results)
            if rate > 0.05:  # >5%缺失才alert
                missing_pids = [r.get("problem_id", "?") for r in results if not r.get(field) or r.get(field) == "MISSING"]
                alerts.append(("field_completeness", "warning", {
                    "summary": f"字段{field}缺失率{rate:.0%}（{missing}/{len(results)}）",
                    "field": field,
                    "missing_count": missing,
                    "sampled": len(results),
                    "problem_ids": missing_pids[:10],
                }))

    return alerts


# ============================================================
# POC字段质量检查G：值分布异常
# ============================================================

def check_value_distribution(db, batch_id, sample_size=30):
    """检查6个POC字段的值分布是否异常"""
    aql = (
        f"FOR r IN {SELECTION_RESULTS_COLLECTION} "
        f"FILTER r.batch_id == @bid "
        f"SORT RAND() LIMIT @n RETURN r"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    results = list(cursor)

    if len(results) < 10:  # 样本太少不检查分布
        return []

    alerts = []

    # 检查每个字段的值分布
    for field in POC_FIELDS:
        dist = Counter(r.get(field, "MISSING") for r in results)
        total = len(results)

        # 检查是否有非法值
        valid_set = VALID_VALUES.get(field, set())
        invalid_values = {v: c for v, c in dist.items() if v not in valid_set and v != "MISSING"}
        if invalid_values:
            invalid_pids = [r.get("problem_id", "?") for r in results if r.get(field) in invalid_values]
            alerts.append(("invalid_value", "warning", {
                "summary": f"字段{field}有非法值: {invalid_values}",
                "field": field,
                "invalid_values": invalid_values,
                "problem_ids": invalid_pids[:10],
            }))

        # 检查单一值垄断（>90%同一个值）
        for val, count in dist.items():
            if val == "MISSING":
                continue
            if count / total > 0.90:
                # branch_position_hint全root是已知模式，降为info
                severity = "info" if field == "branch_position_hint" and val == "root" else "warning"
                alerts.append(("value_monopoly", severity, {
                    "summary": f"字段{field}值'{val}'占比{count/total:.0%}（{count}/{total}）",
                    "field": field,
                    "value": val,
                    "count": count,
                    "total": total,
                }))

    return alerts


# ============================================================
# POC字段质量检查H：字段间逻辑一致性
# ============================================================

def check_logic_consistency(db, batch_id, sample_size=30):
    """检查字段间逻辑一致性"""
    aql = (
        f"FOR r IN {SELECTION_RESULTS_COLLECTION} "
        f"FILTER r.batch_id == @bid "
        f"SORT RAND() LIMIT @n RETURN r"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    results = list(cursor)

    if not results:
        return []

    alerts = []
    for r in results:
        pid = r.get("problem_id", "?")
        suitable = r.get("suitable", "")
        batch = r.get("batch", "")
        ff = r.get("false_friend_candidate", "")

        issues = []
        # suitable=YES但batch=N/A
        if suitable == "YES" and (not batch or batch == "N/A"):
            issues.append(f"suitable=YES但batch=N/A")
        # suitable=NO但batch≠N/A
        if suitable == "NO" and batch and batch != "N/A":
            issues.append(f"suitable=NO但batch={batch}")
        # suitable=YES但false_friend=yes（矛盾）
        if suitable == "YES" and ff == "yes":
            issues.append(f"suitable=YES但false_friend_candidate=yes（矛盾）")

        if issues:
            alerts.append(("logic_inconsistency", "warning", {
                "summary": f"{pid}: {'; '.join(issues)}",
                "problem_id": pid,
                "suitable": suitable,
                "batch": batch,
                "false_friend_candidate": ff,
                "issues": issues,
            }))

    return alerts


# ============================================================
# AI review抽样
# ============================================================

def flag_for_ai_review(db, batch_id, sample_size=SAMPLE_SIZE):
    """抽样selection结果，标记为需AI review

    AI需要检查：
    - selection_reason是否合理
    - 6个POC字段的值是否合理
    - suitable判定是否正确
    """
    aql = (
        f"FOR r IN {SELECTION_RESULTS_COLLECTION} "
        f"FILTER r.batch_id == @bid "
        f"SORT RAND() LIMIT @n RETURN r"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    results = list(cursor)

    flagged = []
    for r in results:
        flagged.append({
            "problem_id": r.get("problem_id", "?"),
            "suitable": r.get("suitable", "?"),
            "batch": r.get("batch", "?"),
            "selection_reason": r.get("selection_reason", "")[:200],
            "false_friend_candidate": r.get("false_friend_candidate", "?"),
            "boundary_case_candidate": r.get("boundary_case_candidate", "?"),
            "process_signal_observability": r.get("process_signal_observability", "?"),
            "leakage_risk": r.get("leakage_risk", "?"),
            "difficulty_estimate": r.get("difficulty_estimate", "?"),
            "branch_position_hint": r.get("branch_position_hint", "?"),
        })

    if flagged:
        create_alert(db, "ai_review_sample", "info", {
            "summary": f"抽样{len(flagged)}条selection结果需AI review",
            "samples": flagged,
        })

    return flagged


# ============================================================
# 主监控循环
# ============================================================

def run_monitor_loop(batch_id, interval=120, expected_concurrency=5):
    """运行监控循环"""
    logger.info(f"选题监控Pipe启动 batch={batch_id} interval={interval}s")
    print(f"=== 选题监控Pipe启动 batch={batch_id} interval={interval}s ===")

    db = connect_db()
    ensure_monitor_collections(db)

    last_queue_state = None
    check_count = 0

    while True:
        check_count += 1
        now = _utc_now()
        print(f"\n--- 选题监控轮次 #{check_count} @ {now} ---")

        all_alerts = []

        # A. session健康
        alerts = check_session_health(db, batch_id, expected_concurrency)
        all_alerts.extend(alerts)

        # B. 队列推进
        alerts, last_queue_state = check_queue_progress(db, batch_id, last_queue_state)
        all_alerts.extend(alerts)

        # C. 产出存在性
        alerts = check_output_existence(db, batch_id)
        all_alerts.extend(alerts)

        # D. XML解析成功率
        alerts = check_parse_success_rate(db, batch_id)
        all_alerts.extend(alerts)

        # E. 失败率
        alerts = check_failure_rate(db, batch_id)
        all_alerts.extend(alerts)

        # F. 6字段填写率（从第2轮开始，需要有results）
        if check_count >= 2:
            alerts = check_field_completeness(db, batch_id)
            all_alerts.extend(alerts)

        # G. 值分布异常
        if check_count >= 2:
            alerts = check_value_distribution(db, batch_id)
            all_alerts.extend(alerts)

        # H. 逻辑一致性
        if check_count >= 2:
            alerts = check_logic_consistency(db, batch_id)
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
                    print(f"    {f['problem_id']}: suitable={f['suitable']} "
                          f"ff={f['false_friend_candidate']} "
                          f"obs={f['process_signal_observability']} "
                          f"leak={f['leakage_risk']} "
                          f"diff={f['difficulty_estimate']} "
                          f"branch={f['branch_position_hint']}")

        # 状态报告
        aql = (
            f"FOR run IN {SELECTION_RUNS_COLLECTION} "
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
        result = subprocess.run(
            ["pgrep", "-f", "run_selection_pipeline.*launch"],
            capture_output=True, text=True
        )
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
                if k == 'samples':
                    print(f"    {k}:")
                    for s in v:
                        pid = s.get('problem_id', '?')
                        suitable = s.get('suitable', '?')
                        ff = s.get('false_friend_candidate', '?')
                        obs = s.get('process_signal_observability', '?')
                        leak = s.get('leakage_risk', '?')
                        diff = s.get('difficulty_estimate', '?')
                        branch = s.get('branch_position_hint', '?')
                        print(f"      {pid}: suitable={suitable}, "
                              f"ff={ff}, obs={obs}, "
                              f"leak={leak}, diff={diff}, "
                              f"branch={branch}")
                else:
                    print(f"    {k}: {v}")
    return alerts


def main():
    parser = argparse.ArgumentParser(description="Pipe 3选题监控Pipe")
    parser.add_argument("--batch-id", required=True, help="选题批次ID")
    parser.add_argument("--interval", type=int, default=120, help="检查间隔（秒）")
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
