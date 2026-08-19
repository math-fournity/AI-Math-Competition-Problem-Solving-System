"""solver_launcher.py — Mid-Hint实验解题并发启动组件

复用selection_launcher/audit_launcher的tmux架构，但用于数学解题任务：
  - 用solver_batches/solver_runs集合
  - 用solver:前缀的Redis队列
  - 检测### PROOF COMPLETE和</proof>标记
  - 并发最多5（rate limit约束下建议1-3）
  - 更长timeout（1800秒=30分钟，数学题需要深度思考）
  - 更长stall（300秒=5分钟，AI思考时无输出是正常的）

用法：
  python -m src.solver_launcher --batch-id mh-00995 --concurrency 1
  python -m src.solver_launcher --status --batch-id mh-00995
  python -m src.solver_launcher --stop --batch-id mh-00995
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
from monitoring.shared_logger import get_logger

logger = get_logger("solver_launcher")

# 解题任务并发/超时配置（数学题需要深度思考，比分类任务长得多）
# 重要：非交互模式下devin cli进程不退出=AI在持续工作。
# thinking输出通过pipe-pane捕获（capture-pane可能看不到），所以stall判定要足够长。
SOLVER_CONCURRENCY = 1
SOLVER_MAX_RUNTIME = 3600    # 60分钟（复杂数学题需要深度思考）
SOLVER_STALL_SECONDS = 1200  # 20分钟无活动判定为stall（AI长时间思考时pipe-pane可能间歇性输出）
SOLVER_POLL_SECONDS = 30     # 轮询间隔（解题任务不需要太频繁轮询）

# 完成标记
PROOF_COMPLETE_MARKER = "### PROOF COMPLETE"
PROOF_XML_END = "</proof>"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def tmux_session_name(solver_exp_id):
    """生成tmux session名（sv前缀，区别于audit的au/sel的se）"""
    name = solver_exp_id.replace(".", "-")
    if len(name) > 48:
        name = name[:48]
    return f"sv-{name}"


def tmux_running(session_name):
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def tmux_pane_text(session_name, lines=1000):
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout
    except Exception:
        return ""


def launch_one(solver_exp_id, work_dir):
    """启动一个解题devin cli实例（复用audit_launcher的tmux架构）"""
    session_name = tmux_session_name(solver_exp_id)
    traj_dir = ANALYSIS_TRAJECTORY_BASE / solver_exp_id
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


# ===== Redis队列（solver:前缀）=====

REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

SV_PENDING_KEY = "solver:pending"
SV_RUNNING_KEY = "solver:running"
SV_COMPLETED_KEY = "solver:completed"
SV_FAILED_KEY = "solver:failed"
SV_STATS_KEY = "solver:stats"

# DB集合名
SOLVER_BATCHES_COLLECTION = "solver_batches"
SOLVER_RUNS_COLLECTION = "solver_runs"
SOLVER_RESULTS_COLLECTION = "solver_results"


def get_redis():
    import redis
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


def sv_enqueue_pending(r, run_key, priority=0):
    return r.zadd(SV_PENDING_KEY, {run_key: priority})


def sv_dequeue_pending(r, count=1):
    results = r.zpopmin(SV_PENDING_KEY, count)
    return [(m, int(s)) for m, s in results]


def sv_add_running(r, run_key, metadata):
    return r.hset(SV_RUNNING_KEY, run_key, json.dumps(metadata))


def sv_remove_running(r, run_key):
    return r.hdel(SV_RUNNING_KEY, run_key)


def sv_add_completed(r, data):
    return r.rpush(SV_COMPLETED_KEY, json.dumps(data))


def sv_add_failed(r, data):
    return r.rpush(SV_FAILED_KEY, json.dumps(data))


def sv_update_stats(r):
    r.hset(SV_STATS_KEY, mapping={
        "pending": r.zcard(SV_PENDING_KEY),
        "running": r.hlen(SV_RUNNING_KEY),
        "completed": r.llen(SV_COMPLETED_KEY),
        "failed": r.llen(SV_FAILED_KEY),
    })


def sv_pending_count(r):
    return r.zcard(SV_PENDING_KEY)


def sv_clear_all(r):
    r.delete(SV_PENDING_KEY, SV_RUNNING_KEY, SV_COMPLETED_KEY, SV_FAILED_KEY, SV_STATS_KEY)


def prepare_solver_batch(batch_id, problem_file, exp_id=None):
    """准备解题批次：读取题目文件，构造AGENTS.md，写入solver_runs集合

    Args:
        batch_id: 批次ID（如mh-00995）
        problem_file: 题目文件路径（包含题面+脉络+hint的MH输入文件）
        exp_id: 实验ID（如eight-mh-00995-MH），如果不提供则用batch_id
    """
    logger.info(f"准备解题批次 batch={batch_id} problem_file={problem_file}")
    print(f"=== 准备解题批次 batch={batch_id} ===")

    problem_path = Path(problem_file)
    if not problem_path.exists():
        print(f"  ERROR: 题目文件不存在: {problem_file}")
        return 0

    problem_text = problem_path.read_text(encoding="utf-8").strip()

    # 构造解题AGENTS.md
    # 注意：不写"You may use computation"——允许工具调用会导致devin cli进入工具调用模式，
    # 在长推理任务中可能卡住（pane无输出）。数学证明任务用纯推理即可。
    agents_content = f"""# Solver Task

You are a mathematical problem solver. Solve the problem completely.
Do not search for this exact problem, its official answer, or its solution.

**CRITICAL CONSTRAINTS:**
- Do NOT use any tools. Do NOT write files. Do NOT execute commands. Do NOT search. Do NOT read any files.
- All information you need is already in your prompt above. Do NOT read any files.
- Output your complete proof directly in your response (in this TUI).
- Do NOT write any files — do not use write/edit tools.
- End your proof with a line containing exactly: ### PROOF COMPLETE
- Your full reasoning and output are automatically captured by the system.

## Answer Leak Self-Check (MANDATORY before solving)

Before you start solving, check the problem text below for any leaked answers, solutions, solution sketches, or formalization notes that would give away the answer or proof strategy.

If you find ANY of the following in the problem text, do NOT solve the problem. Instead output exactly:
### ANSWER LEAK DETECTED: <brief description of what leaked>

Then stop. Do not attempt to solve a problem whose answer has been leaked.

Watch for:
- Phrases like "The proof follows...", "solution sketch", "Formalization notes"
- Official solutions or answer values embedded in the problem statement
- Lean theorem statements that reveal the answer (e.g. `determine SolutionSet := {{{{n | ...}}}}`)

## Problem

{problem_text}
"""

    db = connect_db()
    ensure_schema(db)
    for col_name in [SOLVER_BATCHES_COLLECTION, SOLVER_RUNS_COLLECTION, SOLVER_RESULTS_COLLECTION]:
        if not db.has_collection(col_name):
            db.create_collection(col_name)

    # 写入batch记录
    now = utc_now()
    try:
        db.collection(SOLVER_BATCHES_COLLECTION).insert({
            "_key": batch_id, "status": "preparing",
            "created_at": now, "updated_at": now,
            "problem_file": str(problem_path),
        })
    except Exception:
        db.collection(SOLVER_BATCHES_COLLECTION).update({
            "_key": batch_id, "status": "preparing", "updated_at": now,
        })

    # 生成exp_id和work_dir
    solver_exp_id = exp_id or batch_id
    work_dir = ANALYSIS_SOLVER_BASE / solver_exp_id
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "AGENTS.md").write_text(agents_content, encoding="utf-8")

    # 写入solver_run记录
    run_doc = {
        "_key": solver_exp_id,
        "batch_id": batch_id,
        "solver_exp_id": solver_exp_id,
        "work_dir": str(work_dir),
        "problem_file": str(problem_path),
        "status": "prepared",
        "created_at": utc_now(),
    }
    try:
        db.collection(SOLVER_RUNS_COLLECTION).insert(run_doc)
    except Exception:
        update_data = {k: v for k, v in run_doc.items() if k != "_key"}
        update_data["_key"] = solver_exp_id
        db.collection(SOLVER_RUNS_COLLECTION).update(update_data)

    # 更新batch状态
    db.collection(SOLVER_BATCHES_COLLECTION).update({
        "_key": batch_id, "status": "prepared", "updated_at": utc_now(),
        "prepared_count": 1,
    })

    print(f"  解题任务已准备: {solver_exp_id}")
    print(f"  work_dir: {work_dir}")
    print(f"  AGENTS.md: {work_dir / 'AGENTS.md'}")
    return 1


def launch_batch(batch_id, concurrency=SOLVER_CONCURRENCY,
                 max_runtime=SOLVER_MAX_RUNTIME,
                 stall_seconds=SOLVER_STALL_SECONDS,
                 poll_seconds=SOLVER_POLL_SECONDS):
    """并发启动解题批次"""
    logger.info(f"启动解题批次 batch={batch_id} concurrency={concurrency}")
    print(f"=== 启动解题批次 batch={batch_id} concurrency={concurrency} ===")

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
        db.collection(SOLVER_BATCHES_COLLECTION).update({
            "_key": batch_id, "status": "launching",
            "updated_at": utc_now(), "concurrency": concurrency,
        })
    except Exception:
        pass

    # 自动入队prepared的任务
    pending_in_redis = sv_pending_count(r)
    if pending_in_redis == 0:
        aql = (
            f"FOR run IN {SOLVER_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status == 'prepared' "
            f"RETURN run._key"
        )
        cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
        prepared_keys = list(cursor)
        if not prepared_keys:
            print(f"  无待解题任务（Redis pending为空, DB中也无prepared）")
            return
        print(f"  自动入队{len(prepared_keys)}个待解题任务...")
        for key in prepared_keys:
            sv_enqueue_pending(r, key, priority=0)
        sv_update_stats(r)
        pending_in_redis = sv_pending_count(r)

    print(f"  Redis pending: {pending_in_redis}个任务待启动")

    running = {}
    completed = []
    failed = []
    rate_limit_paused_until = 0

    print(f"  开始并发启动（concurrency={concurrency}）...")
    print(f"  注意：解题任务可能需要10-30分钟，请耐心等待")

    while True:
        if not running and sv_pending_count(r) == 0:
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

        # 动态并发
        try:
            bdoc = db.collection(SOLVER_BATCHES_COLLECTION).get(batch_id)
            if bdoc:
                concurrency = int(bdoc.get("concurrency", SOLVER_CONCURRENCY))
        except Exception:
            pass

        # 启动新的
        while len(running) < concurrency and sv_pending_count(r) > 0:
            items = sv_dequeue_pending(r, count=1)
            if not items:
                break
            run_key, _ = items[0]

            run_doc = db.collection(SOLVER_RUNS_COLLECTION).get(run_key)
            if not run_doc:
                logger.warning(f"DB中找不到run_key={run_key}, 跳过")
                continue
            solver_exp_id = run_doc.get("solver_exp_id", run_key)
            work_dir = run_doc.get("work_dir", "")

            if not work_dir or not Path(work_dir).exists():
                logger.error(f"work_dir不存在: {work_dir}")
                sv_add_failed(r, {"run_key": run_key, "reason": "launch_error"})
                continue

            print(f"  [launch] {solver_exp_id}")
            session_name = launch_one(solver_exp_id, work_dir)

            now_ts = time.time()
            now_iso = utc_now()
            running[solver_exp_id] = {
                "session_name": session_name,
                "work_dir": work_dir,
                "run_key": run_key,
                "started_at": now_ts,
                "last_activity": now_ts,
                "last_pane_hash": "",
            }

            try:
                db.collection(SOLVER_RUNS_COLLECTION).update({
                    "_key": run_key, "status": "running",
                    "tmux_session": session_name,
                    "started_at": now_iso, "updated_at": now_iso,
                })
            except Exception:
                pass

            sv_add_running(r, run_key, {
                "solver_exp_id": solver_exp_id,
                "tmux_session": session_name,
                "started_at": now_ts,
            })
            sv_update_stats(r)
            time.sleep(3)

        # 检查运行中的
        to_remove = []
        for solver_exp_id, info in running.items():
            session_name = info["session_name"]
            run_key = info["run_key"]
            pane_text = tmux_pane_text(session_name)

            # 检测完成
            is_complete = (
                PROOF_COMPLETE_MARKER in pane_text
                or PROOF_XML_END in pane_text
                or "DEVIN_CLI_EXITED code=0" in pane_text
            )

            if is_complete:
                elapsed = int(time.time() - info["started_at"])
                print(f"  [done] {solver_exp_id} — proof complete ({elapsed}s)")
                completed.append({"solver_exp_id": solver_exp_id, "run_key": run_key})
                to_remove.append(solver_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(SOLVER_RUNS_COLLECTION).update({
                        "_key": run_key, "status": "completed",
                        "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed,
                    })
                except Exception:
                    pass
                sv_remove_running(r, run_key)
                sv_add_completed(r, {"run_key": run_key, "solver_exp_id": solver_exp_id})
                sv_update_stats(r)
                continue

            # 基础设施错误检测
            detect_lower = pane_text.lower()
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
                print(f"  [{detected_error}] {solver_exp_id} — {elapsed_sec}s")
                if detected_error == "rate_limited":
                    pause_until = time.time() + 1200
                    if pause_until > rate_limit_paused_until:
                        rate_limit_paused_until = pause_until
                        print(f"  [rate_limit_pause] 暂停20分钟...")
                        logger.warning(f"rate limit触发，暂停20分钟")
                failed.append({"run_key": run_key, "reason": detected_error})
                to_remove.append(solver_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(SOLVER_RUNS_COLLECTION).update({
                        "_key": run_key, "status": detected_error,
                        "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed_sec,
                    })
                except Exception:
                    pass
                sv_remove_running(r, run_key)
                sv_add_failed(r, {"run_key": run_key, "reason": detected_error})
                sv_update_stats(r)
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
                if (PROOF_COMPLETE_MARKER in pane_text or PROOF_XML_END in pane_text
                        or "DEVIN_CLI_EXITED code=0" in pane_text):
                    print(f"  [done] {solver_exp_id} — session ended ({elapsed_sec}s)")
                    completed.append({"solver_exp_id": solver_exp_id, "run_key": run_key})
                    to_remove.append(solver_exp_id)
                    now_iso = utc_now()
                    try:
                        db.collection(SOLVER_RUNS_COLLECTION).update({
                            "_key": run_key, "status": "completed",
                            "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed_sec,
                        })
                    except Exception:
                        pass
                    sv_remove_running(r, run_key)
                    sv_add_completed(r, {"run_key": run_key, "solver_exp_id": solver_exp_id})
                    sv_update_stats(r)
                else:
                    print(f"  [dead_session] {solver_exp_id} — ({elapsed_sec}s)")
                    failed.append({"run_key": run_key, "reason": "dead_session"})
                    to_remove.append(solver_exp_id)
                    now_iso = utc_now()
                    try:
                        db.collection(SOLVER_RUNS_COLLECTION).update({
                            "_key": run_key, "status": "dead_session",
                            "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed_sec,
                        })
                    except Exception:
                        pass
                    sv_remove_running(r, run_key)
                    sv_add_failed(r, {"run_key": run_key, "reason": "dead_session"})
                    sv_update_stats(r)
                continue

            if elapsed > max_runtime:
                elapsed_sec = int(elapsed)
                print(f"  [timeout] {solver_exp_id} — {elapsed_sec}s")
                failed.append({"run_key": run_key, "reason": "timeout"})
                to_remove.append(solver_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(SOLVER_RUNS_COLLECTION).update({
                        "_key": run_key, "status": "failed_timeout",
                        "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": elapsed_sec,
                    })
                except Exception:
                    pass
                sv_remove_running(r, run_key)
                sv_add_failed(r, {"run_key": run_key, "reason": "timeout"})
                sv_update_stats(r)
                continue

            if idle > stall_seconds:
                idle_sec = int(idle)
                print(f"  [stall] {solver_exp_id} — idle {idle_sec}s")
                failed.append({"run_key": run_key, "reason": "stall"})
                to_remove.append(solver_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    db.collection(SOLVER_RUNS_COLLECTION).update({
                        "_key": run_key, "status": "failed_stall",
                        "ended_at": now_iso, "updated_at": now_iso, "runtime_seconds": int(elapsed),
                    })
                except Exception:
                    pass
                sv_remove_running(r, run_key)
                sv_add_failed(r, {"run_key": run_key, "reason": "stall"})
                sv_update_stats(r)
                continue

        for key in to_remove:
            running.pop(key, None)

        rp = sv_pending_count(r)
        if running or rp > 0:
            elapsed_list = [int(time.time() - info["started_at"]) for info in running.values()]
            elapsed_str = ",".join(str(e) for e in elapsed_list) if elapsed_list else "none"
            print(f"  [status] running={len(running)} pending={rp} "
                  f"completed={len(completed)} failed={len(failed)} elapsed=[{elapsed_str}s]")
            time.sleep(poll_seconds)

    print(f"\n=== 解题批次完成 ===")
    print(f"  completed: {len(completed)}")
    print(f"  failed: {len(failed)}")
    logger.info(f"解题批次完成 batch={batch_id}: completed={len(completed)}, failed={len(failed)}")

    from collections import Counter
    status_counts = Counter()
    for c in completed:
        status_counts["completed"] += 1
    for f in failed:
        status_counts[f["reason"]] += 1
    try:
        db.collection(SOLVER_BATCHES_COLLECTION).update({
            "_key": batch_id, "status": "launched",
            "updated_at": utc_now(),
            "completed_count": len(completed), "failed_count": len(failed),
            "status_counts": dict(status_counts),
        })
    except Exception:
        pass

    results_path = OUTPUT_BASE / batch_id / "solver_launch_results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(results_path), "w") as f:
        json.dump({"completed": completed, "failed": failed}, f, ensure_ascii=False, indent=2)
    print(f"  结果保存到: {results_path}")


def status_batch(batch_id):
    """查看解题批次状态"""
    db = connect_db()
    aql = f"FOR run IN {SOLVER_RUNS_COLLECTION} FILTER run.batch_id == @bid COLLECT status = run.status WITH COUNT INTO c RETURN {{status, count: c}}"
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
    status_counts = {r["status"]: r["count"] for r in cursor}

    print(f"解题批次: {batch_id}")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    sv_sessions = [l for l in result.stdout.split("\n") if l.startswith("sv-")]
    print(f"  running tmux sessions: {len(sv_sessions)}")
    for s in sv_sessions:
        print(f"    {s}")


def stop_batch(batch_id):
    """停止解题批次中所有运行中的tmux session"""
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    sv_sessions = [l.split(":")[0] for l in result.stdout.split("\n") if l.startswith("sv-")]
    for s in sv_sessions:
        subprocess.run(["tmux", "kill-session", "-t", s], capture_output=True, timeout=5)
        print(f"  killed: {s}")
    print(f"  已停止 {len(sv_sessions)} 个session")


def main():
    parser = argparse.ArgumentParser(description="Mid-Hint实验解题并发启动")
    parser.add_argument("--batch-id", required=True, help="解题批次ID")
    parser.add_argument("--problem-file", help="题目文件路径（prepare步骤用）")
    parser.add_argument("--exp-id", help="实验ID（默认用batch-id）")
    parser.add_argument("--concurrency", type=int, default=SOLVER_CONCURRENCY, help="并发数（最多5）")
    parser.add_argument("--max-runtime", type=int, default=SOLVER_MAX_RUNTIME, help="最大运行时间（秒）")
    parser.add_argument("--stall-seconds", type=int, default=SOLVER_STALL_SECONDS, help="stall判定时间（秒）")
    parser.add_argument("--poll-seconds", type=int, default=SOLVER_POLL_SECONDS, help="轮询间隔（秒）")
    parser.add_argument("--step", default="launch",
                        choices=["prepare", "launch", "status", "stop"],
                        help="执行步骤")
    args = parser.parse_args()

    if args.concurrency > 5:
        print(f"  WARN: concurrency={args.concurrency} > 5, 强制设为5")
        args.concurrency = 5

    if args.step == "prepare":
        if not args.problem_file:
            print("ERROR: prepare步骤需要 --problem-file")
            sys.exit(1)
        prepare_solver_batch(args.batch_id, args.problem_file, args.exp_id)

    elif args.step == "launch":
        try:
            r = get_redis()
            sv_clear_all(r)
        except Exception:
            pass
        launch_batch(args.batch_id, concurrency=args.concurrency,
                     max_runtime=args.max_runtime, stall_seconds=args.stall_seconds,
                     poll_seconds=args.poll_seconds)

    elif args.step == "status":
        status_batch(args.batch_id)

    elif args.step == "stop":
        stop_batch(args.batch_id)


if __name__ == "__main__":
    main()
