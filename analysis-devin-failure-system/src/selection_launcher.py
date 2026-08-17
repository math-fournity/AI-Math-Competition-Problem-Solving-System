"""selection_launcher.py — Pipe 3选题并发启动组件

复用audit_launcher.py的tmux架构，但：
  - 用selection_batches/selection_runs集合（不是audit_batches/audit_runs）
  - 用selection:前缀的Redis队列（不是audit:前缀）
  - 检测### SELECTION COMPLETE和</selection>标记
  - 并发1（rate limit约束下）

用法：
  python -m src.selection_launcher --batch-id selection-1 --concurrency 1
  python -m src.selection_launcher --status --batch-id selection-1
  python -m src.selection_launcher --stop --batch-id selection-1
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import (
    ANALYSIS_SOLVER_BASE, ANALYSIS_TRAJECTORY_BASE, OUTPUT_BASE,
    DEVIN_MODEL, DEVIN_PERMISSION_MODE,
    RATE_LIMIT_PATTERNS, CONNECTION_PATTERNS,
)
from src.db_schema import connect_db, ensure_schema
from src.selection_collector import (
    SELECTION_BATCHES_COLLECTION, SELECTION_RUNS_COLLECTION, SELECTION_RESULTS_COLLECTION,
)
from monitoring.shared_logger import get_logger

logger = get_logger("selection_launcher")

# 选题任务并发/超时配置（选题任务比审计任务稍复杂——需要语义判断d2=other）
SELECTION_CONCURRENCY = 1
SELECTION_MAX_RUNTIME = 180     # 3分钟
SELECTION_STALL_SECONDS = 90    # 1.5分钟无活动判定为stall
SELECTION_POLL_SECONDS = 10     # 轮询间隔

# 完成标记
SELECTION_COMPLETE_MARKER = "### SELECTION COMPLETE"
SELECTION_XML_END = "</selection>"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def tmux_session_name(selection_exp_id):
    """生成tmux session名（sel前缀，区别于audit的au前缀）"""
    name = selection_exp_id.replace(".", "-")
    if len(name) > 48:
        name = name[:48]
    return f"se-{name}"


def tmux_running(session_name):
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def tmux_pane_text(session_name, lines=500):
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout
    except Exception:
        return ""


def launch_one(selection_exp_id, work_dir):
    """启动一个选题devin cli实例（复用audit_launcher的tmux架构）"""
    session_name = tmux_session_name(selection_exp_id)
    traj_dir = ANALYSIS_TRAJECTORY_BASE / selection_exp_id
    traj_dir.mkdir(parents=True, exist_ok=True)
    (traj_dir / "exports").mkdir(exist_ok=True)
    (traj_dir / "tmux").mkdir(exist_ok=True)

    export_path = traj_dir / "exports" / "conversation.json"
    tmux_pipe_path = traj_dir / "tmux" / "tmux_pipe.log"
    tmux_log_path = traj_dir / "tmux" / "tmux.log"

    agents_md_path = Path(work_dir) / "AGENTS.md"
    devin_cmd = (
        f"devin -p "
        f"--prompt-file {agents_md_path} "
        f"--model {DEVIN_MODEL} "
        f"--respect-workspace-trust false "
        f"--permission-mode {DEVIN_PERMISSION_MODE} "
        f"--export {export_path}; "
        f"echo DEVIN_CLI_EXITED code=$?; "
        f"sleep 999999"
    )

    full_cmd = f"cd {work_dir} && {devin_cmd} 2>&1 | tee {tmux_log_path}"

    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, full_cmd],
        capture_output=True, timeout=10,
    )
    subprocess.run(
        ["tmux", "pipe-pane", "-t", session_name, f"cat >> {tmux_pipe_path}"],
        capture_output=True, timeout=5,
    )

    return session_name


# ===== Redis队列（selection:前缀）=====

REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

SEL_PENDING_KEY = "selection:pending"
SEL_RUNNING_KEY = "selection:running"
SEL_COMPLETED_KEY = "selection:completed"
SEL_FAILED_KEY = "selection:failed"
SEL_STATS_KEY = "selection:stats"


def get_redis():
    import redis
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


def sel_enqueue_pending(r, run_key, priority=0):
    return r.zadd(SEL_PENDING_KEY, {run_key: priority})


def sel_dequeue_pending(r, count=1):
    results = r.zpopmin(SEL_PENDING_KEY, count)
    return [(m, int(s)) for m, s in results]


def sel_add_running(r, run_key, metadata):
    return r.hset(SEL_RUNNING_KEY, run_key, json.dumps(metadata))


def sel_remove_running(r, run_key):
    return r.hdel(SEL_RUNNING_KEY, run_key)


def sel_add_completed(r, data):
    return r.rpush(SEL_COMPLETED_KEY, json.dumps(data))


def sel_add_failed(r, data):
    return r.rpush(SEL_FAILED_KEY, json.dumps(data))


def sel_update_stats(r):
    r.hset(SEL_STATS_KEY, mapping={
        "pending": r.zcard(SEL_PENDING_KEY),
        "running": r.hlen(SEL_RUNNING_KEY),
        "completed": r.llen(SEL_COMPLETED_KEY),
        "failed": r.llen(SEL_FAILED_KEY),
    })


def sel_pending_count(r):
    return r.zcard(SEL_PENDING_KEY)


def sel_clear_all(r):
    r.delete(SEL_PENDING_KEY, SEL_RUNNING_KEY, SEL_COMPLETED_KEY, SEL_FAILED_KEY, SEL_STATS_KEY)


def launch_batch(batch_id, concurrency=SELECTION_CONCURRENCY,
                 max_runtime=SELECTION_MAX_RUNTIME,
                 stall_seconds=SELECTION_STALL_SECONDS,
                 poll_seconds=SELECTION_POLL_SECONDS):
    """并发启动选题批次"""
    logger.info(f"启动选题批次 batch={batch_id} concurrency={concurrency}")
    print(f"=== 启动选题批次 batch={batch_id} concurrency={concurrency} ===")

    db = connect_db()
    ensure_schema(db)

    try:
        r = get_redis()
        r.ping()
        print("  Redis: 连接成功")
    except Exception as e:
        print(f"  Redis: 连接失败({e})")
        return

    # 更新batch状态
    try:
        db.collection(SELECTION_BATCHES_COLLECTION).update({
            "_key": batch_id, "status": "launching",
            "updated_at": utc_now(), "concurrency": concurrency,
        })
    except Exception:
        pass

    # 自动入队prepared的任务
    pending_in_redis = sel_pending_count(r)
    if pending_in_redis == 0:
        aql = (
            f"FOR run IN {SELECTION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status == 'prepared' "
            f"RETURN run._key"
        )
        cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
        prepared_keys = list(cursor)
        if not prepared_keys:
            print(f"  无待选题任务（Redis pending为空, DB中也无prepared）")
            return
        print(f"  自动入队{len(prepared_keys)}个待选题任务...")
        for key in prepared_keys:
            sel_enqueue_pending(r, key, priority=0)
        sel_update_stats(r)
        pending_in_redis = sel_pending_count(r)

    print(f"  Redis pending: {pending_in_redis}个任务待启动")

    running = {}
    completed = []
    failed = []
    rate_limit_paused_until = 0

    print(f"  开始并发启动（concurrency={concurrency}）...")

    while True:
        if not running and sel_pending_count(r) == 0:
            break

        # rate limit自动暂停检查
        now_ts = time.time()
        if rate_limit_paused_until > now_ts:
            remaining = int(rate_limit_paused_until - now_ts)
            if remaining > 0:
                print(f"  [rate_limit_pause] 等待rate limit恢复，剩余{remaining}s...")
                time.sleep(min(remaining, 60))
                continue
            else:
                print(f"  [rate_limit_pause] 恢复运行")
                rate_limit_paused_until = 0

        # 动态并发：从DB读取batch.concurrency
        try:
            bdoc = db.collection(SELECTION_BATCHES_COLLECTION).get(batch_id)
            if bdoc:
                concurrency = int(bdoc.get("concurrency", SELECTION_CONCURRENCY))
        except Exception:
            pass

        # 启动新的
        while len(running) < concurrency and sel_pending_count(r) > 0:
            items = sel_dequeue_pending(r, count=1)
            if not items:
                break
            run_key, _ = items[0]

            run_doc = db.collection(SELECTION_RUNS_COLLECTION).get(run_key)
            if not run_doc:
                logger.warning(f"DB中找不到run_key={run_key}, 跳过")
                continue
            selection_exp_id = run_doc.get("selection_exp_id", run_key)
            work_dir = run_doc.get("work_dir", "")
            problem_id = run_doc.get("problem_id", "")

            if not work_dir or not Path(work_dir).exists():
                logger.error(f"work_dir不存在: {work_dir}")
                sel_add_failed(r, {"run_key": run_key, "reason": "launch_error"})
                continue

            print(f"  [launch] {problem_id}")
            session_name = launch_one(selection_exp_id, work_dir)

            now_ts = time.time()
            now_iso = utc_now()
            running[selection_exp_id] = {
                "session_name": session_name,
                "work_dir": work_dir,
                "problem_id": problem_id,
                "run_key": run_key,
                "started_at": now_ts,
                "last_activity": now_ts,
                "last_pane_hash": "",
            }

            try:
                db.collection(SELECTION_RUNS_COLLECTION).update({
                    "_key": run_key, "status": "running",
                    "tmux_session": session_name,
                    "started_at": now_iso, "updated_at": now_iso,
                })
            except Exception:
                pass

            sel_add_running(r, run_key, {
                "selection_exp_id": selection_exp_id,
                "problem_id": problem_id,
                "tmux_session": session_name,
                "started_at": now_ts,
            })
            sel_update_stats(r)
            time.sleep(3)

        # 检查运行中的
        to_remove = []
        for selection_exp_id, info in running.items():
            session_name = info["session_name"]
            run_key = info["run_key"]
            pane_text = tmux_pane_text(session_name)

            pane_lines = pane_text.split("\n")
            last_prompt_idx = -1
            for j, line in enumerate(pane_lines):
                if "SELECTION COMPLETE" in line:
                    last_prompt_idx = j
                    break
                if "prompt-file" in line or "devin -p" in line:
                    last_prompt_idx = j
            agent_output = "\n".join(pane_lines[last_prompt_idx+1:]) if last_prompt_idx >= 0 else pane_text

            is_complete = (
                SELECTION_XML_END in agent_output
                or SELECTION_COMPLETE_MARKER in agent_output
                or "DEVIN_CLI_EXITED code=0" in agent_output
            )

            if is_complete:
                elapsed = int(time.time() - info["started_at"])
                print(f"  [done] {info['problem_id']} — selection complete ({elapsed}s)")
                completed.append({"problem_id": info["problem_id"], "selection_exp_id": selection_exp_id, "run_key": run_key})
                to_remove.append(selection_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(SELECTION_RUNS_COLLECTION).update({
                        "_key": run_key, "status": "completed",
                        "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed,
                    })
                except Exception:
                    pass
                sel_remove_running(r, run_key)
                sel_add_completed(r, {"run_key": run_key, "selection_exp_id": selection_exp_id})
                sel_update_stats(r)
                continue

            # 基础设施错误检测
            detect_lower = agent_output.lower()
            detected_error = None
            for p in RATE_LIMIT_PATTERNS:
                if p.lower() in detect_lower:
                    detected_error = "rate_limited"
                    break
            if not detected_error:
                for p in CONNECTION_PATTERNS:
                    if p.lower() in detect_lower:
                        detected_error = "failed_connection"
                        break

            if detected_error:
                elapsed_sec = int(time.time() - info["started_at"])
                print(f"  [{detected_error}] {info['problem_id']} — {elapsed_sec}s")
                if detected_error == "rate_limited":
                    pause_until = time.time() + 1200
                    if pause_until > rate_limit_paused_until:
                        rate_limit_paused_until = pause_until
                        print(f"  [rate_limit_pause] 暂停20分钟...")
                        logger.warning(f"rate limit触发，暂停20分钟")
                failed.append({"problem_id": info["problem_id"], "run_key": run_key, "reason": detected_error})
                to_remove.append(selection_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(SELECTION_RUNS_COLLECTION).update({
                        "_key": run_key, "status": detected_error,
                        "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed_sec,
                    })
                except Exception:
                    pass
                sel_remove_running(r, run_key)
                sel_add_failed(r, {"run_key": run_key, "reason": detected_error})
                sel_update_stats(r)
                continue

            # stall/timeout检测
            elapsed = time.time() - info["started_at"]
            pane_hash = hash(pane_text[-500:])
            if pane_hash != info["last_pane_hash"]:
                info["last_pane_hash"] = pane_hash
                info["last_activity"] = time.time()
            idle = time.time() - info["last_activity"]

            is_running = tmux_running(session_name)

            if not is_running:
                elapsed_sec = int(elapsed)
                if (SELECTION_XML_END in agent_output or SELECTION_COMPLETE_MARKER in agent_output
                        or "DEVIN_CLI_EXITED code=0" in agent_output):
                    print(f"  [done] {info['problem_id']} — session ended ({elapsed_sec}s)")
                    completed.append({"problem_id": info["problem_id"], "selection_exp_id": selection_exp_id, "run_key": run_key})
                    to_remove.append(selection_exp_id)
                    now_iso = utc_now()
                    try:
                        db.collection(SELECTION_RUNS_COLLECTION).update({
                            "_key": run_key, "status": "completed",
                            "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed_sec,
                        })
                    except Exception:
                        pass
                    sel_remove_running(r, run_key)
                    sel_add_completed(r, {"run_key": run_key, "selection_exp_id": selection_exp_id})
                    sel_update_stats(r)
                else:
                    print(f"  [dead_session] {info['problem_id']} — ({elapsed_sec}s)")
                    failed.append({"problem_id": info["problem_id"], "run_key": run_key, "reason": "dead_session"})
                    to_remove.append(selection_exp_id)
                    now_iso = utc_now()
                    try:
                        db.collection(SELECTION_RUNS_COLLECTION).update({
                            "_key": run_key, "status": "dead_session",
                            "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed_sec,
                        })
                    except Exception:
                        pass
                    sel_remove_running(r, run_key)
                    sel_add_failed(r, {"run_key": run_key, "reason": "dead_session"})
                    sel_update_stats(r)
                continue

            if elapsed > max_runtime:
                elapsed_sec = int(elapsed)
                print(f"  [timeout] {info['problem_id']} — {elapsed_sec}s")
                failed.append({"problem_id": info["problem_id"], "run_key": run_key, "reason": "timeout"})
                to_remove.append(selection_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(SELECTION_RUNS_COLLECTION).update({
                        "_key": run_key, "status": "failed_timeout",
                        "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed_sec,
                    })
                except Exception:
                    pass
                sel_remove_running(r, run_key)
                sel_add_failed(r, {"run_key": run_key, "reason": "timeout"})
                sel_update_stats(r)
                continue

            if idle > stall_seconds:
                idle_sec = int(idle)
                print(f"  [stall] {info['problem_id']} — idle {idle_sec}s")
                failed.append({"problem_id": info["problem_id"], "run_key": run_key, "reason": "stall"})
                to_remove.append(selection_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(SELECTION_RUNS_COLLECTION).update({
                        "_key": run_key, "status": "failed_stall",
                        "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": int(elapsed),
                    })
                except Exception:
                    pass
                sel_remove_running(r, run_key)
                sel_add_failed(r, {"run_key": run_key, "reason": "stall"})
                sel_update_stats(r)
                continue

        for key in to_remove:
            running.pop(key, None)

        rp = sel_pending_count(r)
        if running or rp > 0:
            print(f"  [status] running={len(running)} pending={rp} "
                  f"completed={len(completed)} failed={len(failed)}")
            time.sleep(poll_seconds)

    print(f"\n=== 选题批次完成 ===")
    print(f"  completed: {len(completed)}")
    print(f"  failed: {len(failed)}")
    logger.info(f"选题批次完成 batch={batch_id}: completed={len(completed)}, failed={len(failed)}")

    from collections import Counter
    status_counts = Counter()
    for c in completed:
        status_counts["completed"] += 1
    for f in failed:
        status_counts[f["reason"]] += 1
    try:
        db.collection(SELECTION_BATCHES_COLLECTION).update({
            "_key": batch_id, "status": "launched",
            "updated_at": utc_now(),
            "completed_count": len(completed), "failed_count": len(failed),
            "status_counts": dict(status_counts),
        })
    except Exception:
        pass

    results_path = OUTPUT_BASE / batch_id / "selection_launch_results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(results_path), "w") as f:
        json.dump({"completed": completed, "failed": failed}, f, ensure_ascii=False, indent=2)
    print(f"  结果保存到: {results_path}")


def status_batch(batch_id):
    """查看选题批次状态"""
    db = connect_db()
    aql = f"FOR run IN {SELECTION_RUNS_COLLECTION} FILTER run.batch_id == @bid COLLECT status = run.status WITH COUNT INTO c RETURN {{status, count: c}}"
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
    status_counts = {r["status"]: r["count"] for r in cursor}

    print(f"选题批次: {batch_id}")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    se_sessions = [l for l in result.stdout.split("\n") if l.startswith("se-")]
    print(f"  running tmux sessions: {len(se_sessions)}")
    for s in se_sessions:
        print(f"    {s}")


def stop_batch(batch_id):
    """停止选题批次中所有运行中的tmux session"""
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    se_sessions = [l.split(":")[0] for l in result.stdout.split("\n") if l.startswith("se-")]
    for s in se_sessions:
        subprocess.run(["tmux", "kill-session", "-t", s], capture_output=True, timeout=5)
        print(f"  killed: {s}")
    print(f"  已停止 {len(se_sessions)} 个session")


def main():
    parser = argparse.ArgumentParser(description="Pipe 3选题并发启动")
    parser.add_argument("--batch-id", required=True, help="选题批次ID")
    parser.add_argument("--concurrency", type=int, default=SELECTION_CONCURRENCY, help="并发数")
    parser.add_argument("--max-runtime", type=int, default=SELECTION_MAX_RUNTIME, help="最大运行时间（秒）")
    parser.add_argument("--stall-seconds", type=int, default=SELECTION_STALL_SECONDS, help="stall判定时间（秒）")
    parser.add_argument("--poll-seconds", type=int, default=SELECTION_POLL_SECONDS, help="轮询间隔（秒）")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--stop", action="store_true", help="停止所有")
    args = parser.parse_args()

    if args.status:
        status_batch(args.batch_id)
    elif args.stop:
        stop_batch(args.batch_id)
    else:
        launch_batch(
            args.batch_id,
            concurrency=args.concurrency,
            max_runtime=args.max_runtime,
            stall_seconds=args.stall_seconds,
            poll_seconds=args.poll_seconds,
        )


if __name__ == "__main__":
    main()
