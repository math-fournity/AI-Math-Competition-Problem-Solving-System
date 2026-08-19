"""audit_launcher.py — Pipe 2审计并发启动组件

复用analysis_launcher.py的tmux架构，但：
  - 用audit_batches/audit_runs集合（不是analysis_batches/analysis_runs）
  - 用audit:前缀的Redis队列（不是analysis:前缀）
  - 检测### AUDIT COMPLETE和</audit>标记
  - 并发5（不是10）
  - 更短timeout（审计任务比分析任务简单——只读文本不读原题/thinking）

用法：
  python -m src.audit_launcher --batch-id audit-1 --concurrency 5
  python -m src.audit_launcher --status --batch-id audit-1
  python -m src.audit_launcher --stop --batch-id audit-1
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
from src.audit_collector import AUDIT_BATCHES_COLLECTION, AUDIT_RUNS_COLLECTION
from monitoring.shared_logger import get_logger
from monitoring.audit_redis_queue import (
    get_redis, enqueue_pending, dequeue_pending,
    add_running, remove_running, add_completed, add_failed,
    update_stats, get_stats, pending_count,
)

logger = get_logger("audit_launcher")

# 审计任务并发/超时配置（审计任务比分析任务简单）
AUDIT_CONCURRENCY = 5
AUDIT_MAX_RUNTIME = 180     # 3分钟（审计只读文本，比分析快）
AUDIT_STALL_SECONDS = 90    # 1.5分钟无活动判定为stall
AUDIT_POLL_SECONDS = 10     # 轮询间隔

# 完成标记
AUDIT_COMPLETE_MARKER = "### AUDIT COMPLETE"
AUDIT_XML_END = "</audit>"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def tmux_session_name(audit_exp_id):
    """生成tmux session名（audit前缀，区别于analysis的an前缀）"""
    name = audit_exp_id.replace(".", "-")
    if len(name) > 48:
        name = name[:48]
    return f"au-{name}"


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


def launch_one(audit_exp_id, work_dir):
    """启动一个审计devin cli实例（复用analysis_launcher的tmux架构）"""
    session_name = tmux_session_name(audit_exp_id)
    traj_dir = ANALYSIS_TRAJECTORY_BASE / audit_exp_id
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


def launch_batch(batch_id, concurrency=AUDIT_CONCURRENCY,
                 max_runtime=AUDIT_MAX_RUNTIME,
                 stall_seconds=AUDIT_STALL_SECONDS,
                 poll_seconds=AUDIT_POLL_SECONDS):
    """并发启动审计批次"""
    logger.info(f"启动审计批次 batch={batch_id} concurrency={concurrency}")
    print(f"=== 启动审计批次 batch={batch_id} concurrency={concurrency} ===")

    db = connect_db()
    ensure_schema(db)

    # 连接Redis
    try:
        r = get_redis()
        r.ping()
        print("  Redis: 连接成功")
    except Exception as e:
        print(f"  Redis: 连接失败({e})")
        return

    # 更新batch状态
    batch_doc = {
        "_key": batch_id,
        "status": "launching",
        "updated_at": utc_now(),
        "concurrency": concurrency,
    }
    try:
        db.collection(AUDIT_BATCHES_COLLECTION).update(batch_doc)
    except Exception:
        pass

    pending_in_redis = pending_count(r)
    if pending_in_redis == 0:
        # 检查DB中是否有prepared的audit_run
        aql = (
            f"FOR run IN {AUDIT_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status == 'prepared' "
            f"RETURN run._key"
        )
        cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
        prepared_keys = list(cursor)
        if not prepared_keys:
            print(f"  无待审计任务（Redis pending为空, DB中也无prepared）")
            return
        # 自动入队
        print(f"  自动入队{len(prepared_keys)}个待审计任务...")
        for key in prepared_keys:
            enqueue_pending(r, key, priority=0)
        update_stats(r)
        pending_in_redis = pending_count(r)

    print(f"  Redis pending: {pending_in_redis}个任务待启动")

    running = {}
    completed = []
    failed = []
    rate_limit_paused_until = 0  # rate limit暂停截止时间（timestamp）

    print(f"  开始并发启动（concurrency={concurrency}）...")

    while True:
        if not running and pending_count(r) == 0:
            break

        # rate limit自动暂停检查
        now_ts = time.time()
        if rate_limit_paused_until > now_ts:
            remaining = int(rate_limit_paused_until - now_ts)
            if remaining > 0:
                print(f"  [rate_limit_pause] 等待rate limit恢复，剩余{remaining}s...")
                time.sleep(min(remaining, 60))  # 每60秒检查一次
                continue
            else:
                print(f"  [rate_limit_pause] 恢复运行")
                rate_limit_paused_until = 0

        # 动态并发：从DB读取batch.concurrency
        try:
            bdoc = db.collection(AUDIT_BATCHES_COLLECTION).get(batch_id)
            if bdoc:
                concurrency = int(bdoc.get("concurrency", AUDIT_CONCURRENCY))
        except Exception:
            pass

        # 启动新的——从Redis pending队列dequeue
        while len(running) < concurrency and pending_count(r) > 0:
            items = dequeue_pending(r, count=1)
            if not items:
                break
            run_key, _ = items[0]

            run_doc = db.collection(AUDIT_RUNS_COLLECTION).get(run_key)
            if not run_doc:
                logger.warning(f"DB中找不到run_key={run_key}, 跳过")
                continue
            audit_exp_id = run_doc.get("audit_exp_id", run_key)
            work_dir = run_doc.get("work_dir", "")
            problem_id = run_doc.get("problem_id", "")

            if not work_dir or not Path(work_dir).exists():
                logger.error(f"work_dir不存在: {work_dir}")
                add_failed(r, {"run_key": run_key, "reason": "launch_error"})
                continue

            print(f"  [launch] {problem_id}")
            session_name = launch_one(audit_exp_id, work_dir)

            now_ts = time.time()
            now_iso = utc_now()
            running[audit_exp_id] = {
                "session_name": session_name,
                "work_dir": work_dir,
                "problem_id": problem_id,
                "run_key": run_key,
                "started_at": now_ts,
                "last_activity": now_ts,
                "last_pane_hash": "",
            }

            # 更新DB
            try:
                update_data = {
                    "_key": run_key,
                    "status": "running",
                    "tmux_session": session_name,
                    "started_at": now_iso,
                    "updated_at": now_iso,
                }
                db.collection(AUDIT_RUNS_COLLECTION).update(update_data)
            except Exception:
                pass

            add_running(r, run_key, {
                "audit_exp_id": audit_exp_id,
                "problem_id": problem_id,
                "tmux_session": session_name,
                "started_at": now_ts,
            })
            update_stats(r)

            time.sleep(3)  # 避免rate limit

        # 检查运行中的
        to_remove = []
        for audit_exp_id, info in running.items():
            session_name = info["session_name"]
            run_key = info["run_key"]
            pane_text = tmux_pane_text(session_name)

            # 检测完成
            pane_lines = pane_text.split("\n")
            # 找到最后一个prompt行之后的输出
            last_prompt_idx = -1
            for j, line in enumerate(pane_lines):
                if "请按AGENTS.md" in line or "AUDIT COMPLETE" in line:
                    if "AUDIT COMPLETE" in line:
                        last_prompt_idx = j
                        break
                    last_prompt_idx = j
            agent_output = "\n".join(pane_lines[last_prompt_idx+1:]) if last_prompt_idx >= 0 else pane_text

            is_complete = (
                AUDIT_XML_END in agent_output
                or AUDIT_COMPLETE_MARKER in agent_output
                or "DEVIN_CLI_EXITED code=0" in agent_output
            )

            if is_complete:
                elapsed = int(time.time() - info["started_at"])
                print(f"  [done] {info['problem_id']} — audit complete ({elapsed}s)")
                completed.append({
                    "problem_id": info["problem_id"],
                    "audit_exp_id": audit_exp_id,
                    "run_key": run_key,
                })
                to_remove.append(audit_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name],
                               capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(AUDIT_RUNS_COLLECTION).update({
                        "_key": run_key,
                        "status": "completed",
                        "ended_at": now_iso,
                        "updated_at": now_iso,
                        "runtime_seconds": elapsed,
                    })
                except Exception:
                    pass
                remove_running(r, run_key)
                add_completed(r, {"run_key": run_key, "audit_exp_id": audit_exp_id})
                update_stats(r)
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
                # rate limit自动暂停：检测到rate_limited时，暂停20分钟
                if detected_error == "rate_limited":
                    pause_until = time.time() + 1200  # 20分钟
                    if pause_until > rate_limit_paused_until:
                        rate_limit_paused_until = pause_until
                        print(f"  [rate_limit_pause] 暂停20分钟（到{time.strftime('%H:%M:%S', time.localtime(pause_until))}），等待rate limit恢复...")
                        logger.warning(f"rate limit触发，暂停20分钟")
                failed.append({"problem_id": info["problem_id"], "run_key": run_key, "reason": detected_error})
                to_remove.append(audit_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name],
                               capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(AUDIT_RUNS_COLLECTION).update({
                        "_key": run_key,
                        "status": detected_error,
                        "ended_at": now_iso,
                        "updated_at": now_iso,
                        "runtime_seconds": elapsed_sec,
                    })
                except Exception:
                    pass
                remove_running(r, run_key)
                add_failed(r, {"run_key": run_key, "reason": detected_error})
                update_stats(r)
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
                if (AUDIT_XML_END in agent_output or AUDIT_COMPLETE_MARKER in agent_output
                        or "DEVIN_CLI_EXITED code=0" in agent_output):
                    print(f"  [done] {info['problem_id']} — session ended ({elapsed_sec}s)")
                    completed.append({"problem_id": info["problem_id"], "audit_exp_id": audit_exp_id, "run_key": run_key})
                    to_remove.append(audit_exp_id)
                    now_iso = utc_now()
                    try:
                        db.collection(AUDIT_RUNS_COLLECTION).update({
                            "_key": run_key, "status": "completed",
                            "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed_sec,
                        })
                    except Exception:
                        pass
                    remove_running(r, run_key)
                    add_completed(r, {"run_key": run_key, "audit_exp_id": audit_exp_id})
                    update_stats(r)
                else:
                    print(f"  [dead_session] {info['problem_id']} — ({elapsed_sec}s)")
                    failed.append({"problem_id": info["problem_id"], "run_key": run_key, "reason": "dead_session"})
                    to_remove.append(audit_exp_id)
                    now_iso = utc_now()
                    try:
                        db.collection(AUDIT_RUNS_COLLECTION).update({
                            "_key": run_key, "status": "dead_session",
                            "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed_sec,
                        })
                    except Exception:
                        pass
                    remove_running(r, run_key)
                    add_failed(r, {"run_key": run_key, "reason": "dead_session"})
                    update_stats(r)
                continue

            if elapsed > max_runtime:
                elapsed_sec = int(elapsed)
                print(f"  [timeout] {info['problem_id']} — {elapsed_sec}s")
                failed.append({"problem_id": info["problem_id"], "run_key": run_key, "reason": "timeout"})
                to_remove.append(audit_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(AUDIT_RUNS_COLLECTION).update({
                        "_key": run_key, "status": "failed_timeout",
                        "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed_sec,
                    })
                except Exception:
                    pass
                remove_running(r, run_key)
                add_failed(r, {"run_key": run_key, "reason": "timeout"})
                update_stats(r)
                continue

            if idle > stall_seconds:
                idle_sec = int(idle)
                print(f"  [stall] {info['problem_id']} — idle {idle_sec}s")
                failed.append({"problem_id": info["problem_id"], "run_key": run_key, "reason": "stall"})
                to_remove.append(audit_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(AUDIT_RUNS_COLLECTION).update({
                        "_key": run_key, "status": "failed_stall",
                        "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": int(elapsed),
                    })
                except Exception:
                    pass
                remove_running(r, run_key)
                add_failed(r, {"run_key": run_key, "reason": "stall"})
                update_stats(r)
                continue

        for key in to_remove:
            running.pop(key, None)

        # 状态报告
        rp = pending_count(r)
        if running or rp > 0:
            print(f"  [status] running={len(running)} pending={rp} "
                  f"completed={len(completed)} failed={len(failed)}")
            time.sleep(poll_seconds)

    print(f"\n=== 审计批次完成 ===")
    print(f"  completed: {len(completed)}")
    print(f"  failed: {len(failed)}")
    logger.info(f"审计批次完成 batch={batch_id}: completed={len(completed)}, failed={len(failed)}")

    # 更新batch记录
    from collections import Counter
    status_counts = Counter()
    for c in completed:
        status_counts["completed"] += 1
    for f in failed:
        status_counts[f["reason"]] += 1
    try:
        db.collection(AUDIT_BATCHES_COLLECTION).update({
            "_key": batch_id,
            "status": "launched",
            "updated_at": utc_now(),
            "completed_count": len(completed),
            "failed_count": len(failed),
            "status_counts": dict(status_counts),
        })
    except Exception:
        pass

    # 保存结果
    results_path = OUTPUT_BASE / batch_id / "audit_launch_results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(results_path), "w") as f:
        json.dump({"completed": completed, "failed": failed}, f, ensure_ascii=False, indent=2)
    print(f"  结果保存到: {results_path}")


def status_batch(batch_id):
    """查看审计批次状态"""
    db = connect_db()
    # 从DB读取统计
    aql = f"FOR run IN {AUDIT_RUNS_COLLECTION} FILTER run.batch_id == @bid COLLECT status = run.status WITH COUNT INTO c RETURN {{status, count: c}}"
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
    status_counts = {r["status"]: r["count"] for r in cursor}

    print(f"审计批次: {batch_id}")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    # 检查运行中的tmux sessions
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    au_sessions = [l for l in result.stdout.split("\n") if l.startswith("au-")]
    print(f"  running tmux sessions: {len(au_sessions)}")
    for s in au_sessions:
        print(f"    {s}")


def stop_batch(batch_id):
    """停止审计批次中所有运行中的tmux session"""
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    au_sessions = [l.split(":")[0] for l in result.stdout.split("\n") if l.startswith("au-")]
    for s in au_sessions:
        subprocess.run(["tmux", "kill-session", "-t", s], capture_output=True, timeout=5)
        print(f"  killed: {s}")
    print(f"  已停止 {len(au_sessions)} 个session")


def main():
    parser = argparse.ArgumentParser(description="Pipe 2审计并发启动")
    parser.add_argument("--batch-id", required=True, help="审计批次ID")
    parser.add_argument("--concurrency", type=int, default=AUDIT_CONCURRENCY, help="并发数")
    parser.add_argument("--max-runtime", type=int, default=AUDIT_MAX_RUNTIME, help="最大运行时间（秒）")
    parser.add_argument("--stall-seconds", type=int, default=AUDIT_STALL_SECONDS, help="stall判定时间（秒）")
    parser.add_argument("--poll-seconds", type=int, default=AUDIT_POLL_SECONDS, help="轮询间隔（秒）")
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
