"""monitor_continuation.py — POC-2.7续传Pipe监控Pipe

按 specs/p27_monitor_spec.md 检查规范实现。
复用monitor_selection.py的alert管理架构，针对p27_continuation_runs检查。

三类检查（详见specs/p27_monitor_spec.md）：
  A. 自动检查（脚本判定）：session_health/queue_progress/rate_limit/zombie/export/failure/launcher_dead/stall
  B. 续传质量检查：proof_completeness/handover_completeness/truncation_pattern/status_anomaly
  C. AI review抽样：每3轮抽样2条COMPLETED结果，标记needs_ai_review

alert集合：p27_monitor_alerts（独立于现有Pipe的monitor_alerts）

用法：
  python -m src.monitor_continuation --batch-id p27-full --interval 120
  python -m src.monitor_continuation --batch-id p27-full --check-alerts
  python -m src.monitor_continuation --batch-id p27-full --resolve-alert <alert_key>
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.continuation_config import (
    CONTINUATION_RUNS_COLLECTION, CONTINUATION_RESULTS_COLLECTION,
    CONTINUATION_SOLVER_BASE, CONTINUATION_TRAJECTORY_BASE,
    PROOF_FILE_NAME, DEFAULT_MAX_RUNTIME_SECONDS,
)
from src.continuation_db_schema import connect_db
from monitoring.shared_logger import get_logger

logger = get_logger("monitor_continuation")

MONITOR_ALERTS_COLLECTION = "p27_monitor_alerts"

# 检查阈值（来自specs/p27_monitor_spec.md）
FAILURE_RATE_THRESHOLD = 0.15
STALL_THRESHOLD_SECONDS = 900       # 15分钟队列无变化
LONG_RUNNING_THRESHOLD = 1800       # 30分钟单轮超时
ZOMBIE_THRESHOLD = 2
RATE_LIMIT_CRITICAL_THRESHOLD = 3
EXPORT_MISSING_RATE_THRESHOLD = 0.10
PROOF_TOO_SMALL_BYTES = 1024
HANDOVER_TOO_SMALL_BYTES = 500
SAMPLE_SIZE = 2
AI_REVIEW_INTERVAL = 3              # 每3轮抽样一次


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _ts():
    return int(time.time())


# ============================================================
# Alert管理（复用monitor_selection.py的模式）
# ============================================================

def ensure_monitor_collections(db):
    if not db.has_collection(MONITOR_ALERTS_COLLECTION):
        db.create_collection(MONITOR_ALERTS_COLLECTION)
    # 索引
    col = db.collection(MONITOR_ALERTS_COLLECTION)
    for name, fields, unique in [
        ("p27_idx_status", ["status"], False),
        ("p27_idx_severity", ["severity"], False),
        ("p27_idx_type", ["alert_type"], False),
    ]:
        try:
            col.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass


def create_alert(db, alert_type, severity, details):
    ts = int(time.time() * 1000)
    alert_key = f"p27-alert-{ts}-{alert_type}"
    doc = {
        "_key": alert_key,
        "alert_type": alert_type,
        "severity": severity,
        "details": details,
        "status": "new",
        "created_at": _utc_now(),
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
# A类自动检查
# ============================================================

def check_session_health(db, batch_id, expected_concurrency):
    """A1: p27- session数 vs DB running数 vs 设定并发"""
    result = subprocess.run(
        ["tmux", "list-sessions"], capture_output=True, text=True, timeout=5
    )
    p27_sessions = [l for l in result.stdout.split("\n") if l.startswith("p27-")]
    actual = len(p27_sessions)

    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'running' "
        f"COLLECT WITH COUNT INTO c RETURN c"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
    db_running = list(cursor)[0] if cursor.batch else 0

    alerts = []
    if actual == 0 and db_running > 0:
        alerts.append(("session_health", "critical", {
            "summary": f"DB有{db_running}个running但tmux无p27-session，launcher可能挂了",
            "db_running": db_running,
            "tmux_sessions": actual,
        }))
    elif actual < expected_concurrency and actual > 0:
        alerts.append(("session_health", "warning", {
            "summary": f"tmux session数({actual})少于并发数({expected_concurrency})",
            "expected": expected_concurrency,
            "actual": actual,
        }))
    return alerts


def check_queue_progress(db, batch_id, last_state):
    """A2/A3: Redis队列推进检查"""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        pending = r.zcard("p27:pending")
        completed = r.llen("p27:completed")
        failed = r.llen("p27:failed")
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


def check_rate_limit(db, batch_id, interval_seconds=120):
    """A4: 最近interval内rate_limited数量"""
    from datetime import datetime, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=interval_seconds * 3)).isoformat()
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'rate_limited' "
        f"FILTER run.updated_at >= @cutoff "
        f"COLLECT WITH COUNT INTO c RETURN c"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "cutoff": cutoff}, ttl=60)
    count = list(cursor)[0] if cursor.batch else 0

    alerts = []
    if count >= RATE_LIMIT_CRITICAL_THRESHOLD:
        alerts.append(("rate_limit", "critical", {
            "summary": f"最近{interval_seconds*3}秒内{count}个rate_limited",
            "count": count,
        }))
    elif count > 0:
        alerts.append(("rate_limit", "warning", {
            "summary": f"最近{interval_seconds*3}秒内{count}个rate_limited",
            "count": count,
        }))
    return alerts


def check_zombie_sessions(db, batch_id):
    """A5: 空pane僵尸session"""
    result = subprocess.run(
        ["tmux", "list-sessions"], capture_output=True, text=True, timeout=5
    )
    p27_sessions = [l.split(":")[0] for l in result.stdout.split("\n") if l.startswith("p27-")]

    zombies = []
    for s in p27_sessions:
        try:
            r = subprocess.run(
                ["tmux", "capture-pane", "-t", s, "-p", "-S", "-50"],
                capture_output=True, text=True, timeout=10
            )
            lines = [l.strip() for l in r.stdout.split("\n") if l.strip() and not l.startswith("\x1b[")]
            if len(lines) < 3:
                zombies.append(s)
        except Exception:
            pass

    alerts = []
    if len(zombies) >= ZOMBIE_THRESHOLD:
        alerts.append(("zombie_sessions", "warning", {
            "summary": f"{len(zombies)}个空pane僵尸session（阈值{ZOMBIE_THRESHOLD}）",
            "zombies": zombies,
        }))
    return alerts


def check_export_landing(db, batch_id, sample_size=5):
    """A6: completed的run是否有export文件"""
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'completed' "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    alerts = []
    missing = 0
    for run in runs:
        rounds_log = run.get("rounds_log", [])
        if rounds_log:
            last_export = rounds_log[-1].get("export", "")
            if last_export and not os.path.exists(last_export):
                missing += 1
                alerts.append(("export_missing", "critical", {
                    "summary": f"completed run无export: {run.get('problem_id', '?')}",
                    "problem_id": run.get("problem_id", ""),
                    "export_path": last_export,
                }))

    if missing > 0 and len(runs) > 0:
        rate = missing / len(runs)
        if rate > EXPORT_MISSING_RATE_THRESHOLD:
            alerts.append(("export_missing_rate", "critical", {
                "summary": f"export缺失率{rate:.0%}（{missing}/{len(runs)}）",
                "missing": missing,
                "sampled": len(runs),
            }))
    return alerts


def check_failure_rate(db, batch_id):
    """A7: 失败率"""
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"COLLECT status = run.status WITH COUNT INTO c "
        f"RETURN {{status, count: c}}"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
    status_counts = {r["status"]: r["count"] for r in cursor}

    total = sum(status_counts.values())
    if total == 0:
        return []

    failed_statuses = ["failed_timeout", "failed_stall", "dead_session", "rate_limited",
                       "failed_connection", "launch_error"]
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


def check_launcher_dead(db, batch_id):
    """A8: launcher进程是否还在"""
    result = subprocess.run(
        ["pgrep", "-f", "run_continuation_pipeline.*launch"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        aql = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status IN ['prepared', 'running'] "
            f"COLLECT WITH COUNT INTO c RETURN c"
        )
        cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
        remaining = list(cursor)[0] if cursor.batch else 0
        if remaining > 0:
            return [("launcher_dead", "critical", {
                "summary": f"launcher进程不在运行，但还有{remaining}个prepared/running任务",
                "remaining": remaining,
            })]
    return []


def check_long_running(db, batch_id):
    """A9: 单轮运行>30分钟"""
    from datetime import datetime, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=LONG_RUNNING_THRESHOLD)).isoformat()
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'running' "
        f"FILTER run.updated_at < @cutoff "
        f"RETURN {{problem_id: run.problem_id, updated_at: run.updated_at, current_round: run.current_round}}"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "cutoff": cutoff}, ttl=60)
    long_runs = list(cursor)

    alerts = []
    if long_runs:
        alerts.append(("long_running", "warning", {
            "summary": f"{len(long_runs)}个run运行超过{LONG_RUNNING_THRESHOLD}秒",
            "runs": [{"problem_id": r["problem_id"], "round": r.get("current_round", "?")}
                     for r in long_runs[:10]],
        }))
    return alerts


# ============================================================
# B类续传质量检查
# ============================================================

def check_proof_completeness(db, batch_id, sample_size=10):
    """B1/B2/B3: proof.md完整性检查"""
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.final_status == 'COMPLETED' "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    alerts = []
    for run in runs:
        pid = run.get("problem_id", "?")
        work_dir = run.get("work_dir", "")
        proof_path = run.get("proof_path", "")

        if not proof_path:
            proof_path = str(Path(work_dir) / PROOF_FILE_NAME) if work_dir else ""

        if not proof_path or not os.path.exists(proof_path):
            alerts.append(("proof_missing", "critical", {
                "summary": f"COMPLETED但无proof.md: {pid}",
                "problem_id": pid,
            }))
            continue

        size = os.path.getsize(proof_path)
        if size < PROOF_TOO_SMALL_BYTES:
            alerts.append(("proof_too_small", "warning", {
                "summary": f"proof.md太小({size}B): {pid}",
                "problem_id": pid,
                "size": size,
            }))

        with open(proof_path) as f:
            content = f.read()
        if "\\boxed" not in content and "boxed{" not in content:
            alerts.append(("proof_no_boxed", "warning", {
                "summary": f"proof.md无boxed答案: {pid}",
                "problem_id": pid,
            }))
    return alerts


def check_handover_completeness(db, batch_id, sample_size=10):
    """B4/B5: HANDOVER.md完整性检查（v2方案）"""
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.rounds_log != [] "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    alerts = []
    for run in runs:
        pid = run.get("problem_id", "?")
        run_key = run.get("_key", "")
        rounds_log = run.get("rounds_log", [])

        for round_info in rounds_log:
            round_num = round_info.get("round", 0)
            if round_num < 2:
                continue  # Round 1不需要HANDOVER.md

            # 优先从rounds_log中读取handover_path（修复后的launcher会存）
            handover_path_str = round_info.get("handover_path", "")
            if handover_path_str:
                handover_path = Path(handover_path_str)
            else:
                # 回退：用work_dir约定路径推断
                work_dir = run.get("work_dir", "")
                if not work_dir:
                    continue
                # 修复后的路径约定：work_dir/round{N}_HANDOVER.md
                # N是前一轮的编号（round_num的前一轮生成handover供round_num用）
                handover_path = Path(work_dir) / f"round{round_num - 1}_HANDOVER.md"

            if not handover_path.exists():
                alerts.append(("handover_missing", "critical", {
                    "summary": f"v2方案round{round_num}无HANDOVER.md: {pid}",
                    "problem_id": pid,
                    "round": round_num,
                }))
            else:
                size = handover_path.stat().st_size
                if size < HANDOVER_TOO_SMALL_BYTES:
                    alerts.append(("handover_too_small", "warning", {
                        "summary": f"HANDOVER.md太小({size}B): {pid} R{round_num}",
                        "problem_id": pid,
                        "round": round_num,
                        "size": size,
                    }))
    return alerts


def check_truncation_pattern(db, batch_id):
    """B6: 5轮全截断的题——可能是真正的思维错误"""
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.final_status == 'TRUNCATED_AT_MAX' "
        f"RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=120)
    runs = list(cursor)

    alerts = []
    all_truncated = []
    for run in runs:
        rounds_log = run.get("rounds_log", [])
        if len(rounds_log) >= 5 and all(r.get("truncated", False) for r in rounds_log):
            all_truncated.append(run.get("problem_id", "?"))

    if all_truncated:
        alerts.append(("all_rounds_truncated", "warning", {
            "summary": f"{len(all_truncated)}道题5轮全截断——可能是真正的思维错误",
            "problem_ids": all_truncated[:20],
            "count": len(all_truncated),
        }))
    return alerts


def check_status_anomaly(db, batch_id):
    """B7: final_status分布异常"""
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.final_status != null "
        f"COLLECT fs = run.final_status WITH COUNT INTO c "
        f"RETURN {{final_status: fs, count: c}}"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
    dist = {r["final_status"]: r["count"] for r in cursor}
    total = sum(dist.values())

    alerts = []
    if total > 10:
        completed_rate = dist.get("COMPLETED", 0) / total
        truncated_rate = dist.get("TRUNCATED_AT_MAX", 0) / total
        error_rate = dist.get("ERROR", 0) / total

        if error_rate > 0.5:
            alerts.append(("status_anomaly", "info", {
                "summary": f"ERROR占比{error_rate:.0%}——可能是数据/机制问题",
                "distribution": dist,
            }))
        if truncated_rate > 0.8:
            alerts.append(("status_anomaly", "info", {
                "summary": f"TRUNCATED_AT_MAX占比{truncated_rate:.0%}——大部分是思维错误",
                "distribution": dist,
            }))
    return alerts


def check_rounds_log_integrity(db, batch_id, sample_size=10):
    """B8: rounds_log完整性检查——验证每轮的中间产物路径都存在且文件未丢失

    检查项：
    1. 每条rounds_log记录是否有完整的字段（round/export/truncated/completed/reason）
    2. export指向的文件是否实际存在
    3. handover_path指向的文件是否存在（如果记录了handover_success=True）
    4. proof_path指向的文件是否存在（如果completed=True）
    5. 同一run的rounds_log中round编号是否连续无重复
    """
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.rounds_log != [] "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    alerts = []
    for run in runs:
        pid = run.get("problem_id", "?")
        rounds_log = run.get("rounds_log", [])

        # 检查round编号连续性
        round_nums = [r.get("round", 0) for r in rounds_log]
        if round_nums and len(round_nums) != len(set(round_nums)):
            alerts.append(("rounds_log_duplicate_round", "critical", {
                "summary": f"rounds_log有重复round编号: {pid} rounds={round_nums}",
                "problem_id": pid,
                "rounds": round_nums,
            }))

        for entry in rounds_log:
            round_num = entry.get("round", 0)

            # 检查必需字段
            missing_fields = [f for f in ["round", "export", "truncated", "completed", "reason"]
                              if f not in entry]
            if missing_fields:
                alerts.append(("rounds_log_missing_field", "warning", {
                    "summary": f"rounds_log缺字段{missing_fields}: {pid} R{round_num}",
                    "problem_id": pid,
                    "round": round_num,
                    "missing": missing_fields,
                }))

            # 检查export文件存在
            export_path = entry.get("export", "")
            if export_path and not os.path.exists(export_path):
                alerts.append(("rounds_log_export_missing", "critical", {
                    "summary": f"rounds_log的export文件不存在: {pid} R{round_num} path={export_path}",
                    "problem_id": pid,
                    "round": round_num,
                    "path": export_path,
                }))

            # 检查handover_path文件存在（如果记录了）
            handover_path = entry.get("handover_path", "")
            handover_success = entry.get("handover_success", False)
            if handover_success and handover_path and not os.path.exists(handover_path):
                alerts.append(("rounds_log_handover_missing", "critical", {
                    "summary": f"rounds_log的handover_path文件不存在: {pid} R{round_num}",
                    "problem_id": pid,
                    "round": round_num,
                    "path": handover_path,
                }))

            # 检查proof_path文件存在（如果completed=True）
            if entry.get("completed"):
                proof_path = entry.get("proof_path", "")
                if proof_path and not os.path.exists(proof_path):
                    alerts.append(("rounds_log_proof_missing", "critical", {
                        "summary": f"rounds_log的proof_path文件不存在: {pid} R{round_num}",
                        "problem_id": pid,
                        "round": round_num,
                        "path": proof_path,
                    }))
                elif not proof_path:
                    alerts.append(("rounds_log_no_proof_path", "warning", {
                        "summary": f"completed=True但rounds_log无proof_path: {pid} R{round_num}",
                        "problem_id": pid,
                        "round": round_num,
                    }))

    return alerts


def check_intermediate_product_uniqueness(db, batch_id, sample_size=10):
    """B9: 中间产物唯一性检查——验证不同run/round的中间产物路径不冲突

    检查项：
    1. 不同run的work_dir不重复
    2. 同一run不同round的export路径不重复
    3. 同一run不同round的handover_path不重复
    4. 同一run不同round的proof_path不重复
    """
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.rounds_log != [] "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    alerts = []
    for run in runs:
        pid = run.get("problem_id", "?")
        rounds_log = run.get("rounds_log", [])

        # 检查同一run内路径重复
        exports = [r.get("export", "") for r in rounds_log if r.get("export")]
        handovers = [r.get("handover_path", "") for r in rounds_log if r.get("handover_path")]
        proofs = [r.get("proof_path", "") for r in rounds_log if r.get("proof_path")]

        for paths, name in [(exports, "export"), (handovers, "handover_path"), (proofs, "proof_path")]:
            if len(paths) != len(set(paths)):
                dup = [p for p in paths if paths.count(p) > 1]
                alerts.append(("intermediate_product_collision", "critical", {
                    "summary": f"同一run的{name}路径重复: {pid} dups={set(dup)}",
                    "problem_id": pid,
                    "field": name,
                    "duplicates": list(set(dup)),
                }))

    # 检查不同run的work_dir不重复
    all_runs = list(db.aql.execute(
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.work_dir != null "
        f"RETURN {{_key: run._key, pid: run.problem_id, work_dir: run.work_dir}}",
        bind_vars={"bid": batch_id}, ttl=120,
    ))
    work_dirs = {}
    for r in all_runs:
        wd = r.get("work_dir", "")
        if wd:
            if wd in work_dirs:
                alerts.append(("work_dir_collision", "critical", {
                    "summary": f"两个run共用work_dir: {r['pid']}和{work_dirs[wd]} dir={wd}",
                    "problem_id": r["pid"],
                    "conflict": work_dirs[wd],
                    "work_dir": wd,
                }))
            else:
                work_dirs[wd] = r["pid"]

    return alerts


# ============================================================
# C类AI review抽样
# ============================================================

def flag_for_ai_review(db, batch_id, sample_size=SAMPLE_SIZE):
    """抽样COMPLETED结果，标记为需AI review

    AI需要检查（详见specs/p27_monitor_spec.md §3.3）：
    - C1. proof_quality: proof.md的数学正确性
    - C2. proof_hallucination: 是否有幻觉
    - C3. answer_leak: 是否答案泄漏
    - C4. handover_quality: HANDOVER.md是否准确
    - C5. continuation_direction: 续传方向是否正确
    """
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.final_status == 'COMPLETED' "
        f"SORT RAND() LIMIT @n RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "n": sample_size}, ttl=60)
    runs = list(cursor)

    flagged = []
    for run in runs:
        pid = run.get("problem_id", "?")
        proof_path = run.get("proof_path", "")
        work_dir = run.get("work_dir", "")
        rounds_log = run.get("rounds_log", [])

        # 读proof.md前500字符作为预览
        proof_preview = ""
        if proof_path and os.path.exists(proof_path):
            with open(proof_path) as f:
                proof_preview = f.read()[:500]

        # 找最后一个HANDOVER.md
        handover_preview = ""
        for r in reversed(rounds_log):
            export_path = r.get("export", "")
            if export_path:
                round_dir = Path(export_path).parent.parent
                hp = round_dir / "HANDOVER.md"
                if hp.exists():
                    with open(hp) as f:
                        handover_preview = f.read()[:500]
                    break

        flagged.append({
            "problem_id": pid,
            "rounds": len(rounds_log),
            "proof_path": proof_path,
            "proof_preview": proof_preview,
            "handover_preview": handover_preview,
            "check_items": [
                "C1.proof_quality", "C2.proof_hallucination", "C3.answer_leak",
                "C4.handover_quality", "C5.continuation_direction",
            ],
        })

    if flagged:
        create_alert(db, "ai_review_sample", "info", {
            "summary": f"抽样{len(flagged)}条COMPLETED结果需AI review（按specs/p27_monitor_spec.md §3.3检查）",
            "samples": flagged,
        })
    return flagged


# ============================================================
# 主监控循环
# ============================================================

def run_monitor_loop(batch_id, interval=120, expected_concurrency=5):
    """运行监控循环"""
    logger.info(f"续传监控Pipe启动 batch={batch_id} interval={interval}s")
    print(f"=== 续传监控Pipe启动 batch={batch_id} interval={interval}s ===")
    print(f"  检查规范: specs/p27_monitor_spec.md")

    db = connect_db()
    ensure_monitor_collections(db)

    last_queue_state = None
    check_count = 0

    while True:
        check_count += 1
        now = _utc_now()
        print(f"\n--- 续传监控轮次 #{check_count} @ {now} ---")

        all_alerts = []

        # A类自动检查
        alerts = check_session_health(db, batch_id, expected_concurrency)
        all_alerts.extend(alerts)

        alerts, last_queue_state = check_queue_progress(db, batch_id, last_queue_state)
        all_alerts.extend(alerts)

        alerts = check_rate_limit(db, batch_id, interval)
        all_alerts.extend(alerts)

        alerts = check_zombie_sessions(db, batch_id)
        all_alerts.extend(alerts)

        alerts = check_export_landing(db, batch_id)
        all_alerts.extend(alerts)

        alerts = check_failure_rate(db, batch_id)
        all_alerts.extend(alerts)

        alerts = check_launcher_dead(db, batch_id)
        all_alerts.extend(alerts)

        alerts = check_long_running(db, batch_id)
        all_alerts.extend(alerts)

        # B类续传质量检查（从第2轮开始）
        if check_count >= 2:
            alerts = check_proof_completeness(db, batch_id)
            all_alerts.extend(alerts)

            alerts = check_handover_completeness(db, batch_id)
            all_alerts.extend(alerts)

            alerts = check_truncation_pattern(db, batch_id)
            all_alerts.extend(alerts)

            alerts = check_status_anomaly(db, batch_id)
            all_alerts.extend(alerts)

            # B8: rounds_log完整性检查（新增）
            alerts = check_rounds_log_integrity(db, batch_id)
            all_alerts.extend(alerts)

            # B9: 中间产物唯一性检查（新增）
            alerts = check_intermediate_product_uniqueness(db, batch_id)
            all_alerts.extend(alerts)

        # 创建alerts
        for alert_type, severity, details in all_alerts:
            create_alert(db, alert_type, severity, details)

        # C类AI review抽样（每3轮）
        if check_count % AI_REVIEW_INTERVAL == 0:
            flagged = flag_for_ai_review(db, batch_id)
            if flagged:
                print(f"  [AI_REVIEW] 抽样{len(flagged)}条需AI review:")
                for f in flagged:
                    print(f"    {f['problem_id']}: {f['rounds']}轮, proof={f['proof_path'][:60]}...")

        # 状态报告
        aql = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
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

        # final_status分布
        aql2 = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.final_status != null "
            f"COLLECT fs = run.final_status WITH COUNT INTO c "
            f"RETURN {{final_status: fs, count: c}}"
        )
        cursor2 = db.aql.execute(aql2, bind_vars={"bid": batch_id}, ttl=60)
        final_dist = {r["final_status"]: r["count"] for r in cursor2}
        if final_dist:
            print(f"  [final_status] {json.dumps(final_dist)}")
            completed = final_dist.get("COMPLETED", 0)
            final_total = sum(final_dist.values())
            if final_total > 0:
                pass_rate = completed / final_total
                print(f"  [pass_rate] COMPLETED={completed}/{final_total} = {pass_rate:.1%}")

        # 检查退出条件
        if status_counts.get("prepared", 0) == 0 and status_counts.get("running", 0) == 0:
            print("  所有任务已完成，监控Pipe退出")
            break

        # 检查新alerts
        new_alerts = get_new_alerts(db)
        if new_alerts:
            print(f"  [alerts] {len(new_alerts)}个新alert")

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
                        print(f"      {s['problem_id']}: {s['rounds']}轮")
                        print(f"        proof: {s.get('proof_preview', '')[:100]}...")
                        print(f"        check_items: {s.get('check_items', [])}")
                else:
                    print(f"    {k}: {v}")
    return alerts


def main():
    parser = argparse.ArgumentParser(description="POC-2.7续传监控Pipe")
    parser.add_argument("--batch-id", required=True, help="续传批次ID")
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
        run_monitor_loop(args.batch_id, interval=args.interval,
                         expected_concurrency=args.concurrency)


if __name__ == "__main__":
    main()
