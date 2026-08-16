"""analysis_launcher.py — 并发启动组件

并发启动devin cli实例，每个实例分析一道题。
模仿solver_harness的launch_attempt设计，但简化：
  - 无MITM（分析任务不需要token级截获）
  - 无problem.txt（AGENTS.md中已包含所有内容）
  - 用--export导出conversation.json
  - 用tmux capture-pane检测### ANALYSIS COMPLETE

用法：
  python -m src.analysis_launcher --batch-id analysis-1 --concurrency 10
  python -m src.analysis_launcher --status --batch-id analysis-1
  python -m src.analysis_launcher --stop --batch-id analysis-1
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
    DEVIN_MODEL, DEVIN_PERMISSION_MODE, DEVIN_PROMPT,
    DEFAULT_CONCURRENCY, DEFAULT_MAX_RUNTIME_SECONDS, DEFAULT_STALL_SECONDS,
    DEFAULT_POLL_SECONDS, ANALYSIS_COMPLETE_MARKER, XML_BLOCK_END,
    RATE_LIMIT_PATTERNS, CONNECTION_PATTERNS,
    INFRA_FAILURES, MODEL_FAILURES,
)
from src.db_schema import (
    connect_db, ensure_schema, insert_event, update_run, update_batch,
    make_verdict, ANALYSIS_BATCHES_COLLECTION,
)
from monitoring.shared_logger import get_logger
from monitoring.redis_queue import (
    get_redis, enqueue_pending, dequeue_pending,
    add_running, get_running, get_all_running, remove_running,
    add_completed, add_failed, update_stats, get_stats, clear_all,
)

logger = get_logger("launcher")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def tmux_session_name(analysis_exp_id):
    """生成tmux session名（不超过50字符）"""
    # tmux session名不能含点号
    name = analysis_exp_id.replace(".", "-")
    if len(name) > 48:
        name = name[:48]
    return f"an-{name}"


def tmux_running(session_name):
    """检查tmux session是否在运行"""
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def tmux_pane_text(session_name, lines=500):
    """获取tmux pane内容"""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout
    except Exception:
        return ""


def tmux_pane_is_empty(session_name):
    """检查tmux pane是否空白（devin cli已退出）"""
    text = tmux_pane_text(session_name, lines=50)
    # 去掉空行和ANSI转义
    lines = [l.strip() for l in text.split("\n") if l.strip() and not l.startswith("\x1b[")]
    return len(lines) < 3


def launch_one(analysis_exp_id, work_dir):
    """启动一个devin cli实例（对齐solver_harness的tmux启动方式）

    与solver_harness一致的关键设计：
    1. tmux new-session -d 无头运行
    2. tee tmux.log 捕获stdout（含ANSI转义码）
    3. tmux pipe-pane >> tmux_pipe.log 捕获pane完整raw流（兜底）
    4. --export conversation.json 保留完整对话导出
    5. -p单轮模式：devin cli完成后自动退出
    6. echo DEVIN_CLI_EXITED code=$? 打印退出码，方便检测异常退出
    7. sleep 999999 保持tmux session存活（-p模式退出后session会销毁）

    Args:
        analysis_exp_id: 分析实验ID
        work_dir: 工作目录路径

    Returns:
        tmux_session_name
    """
    session_name = tmux_session_name(analysis_exp_id)
    traj_dir = ANALYSIS_TRAJECTORY_BASE / analysis_exp_id
    traj_dir.mkdir(parents=True, exist_ok=True)
    (traj_dir / "exports").mkdir(exist_ok=True)
    (traj_dir / "tmux").mkdir(exist_ok=True)

    export_path = traj_dir / "exports" / "conversation.json"
    tmux_pipe_path = traj_dir / "tmux" / "tmux_pipe.log"
    tmux_log_path = traj_dir / "tmux" / "tmux.log"

    # devin cli命令——用-p单轮模式（完成后自动退出+写export）
    # 对齐solver_harness：-p模式 + echo退出码 + sleep保持session
    devin_cmd = (
        f"devin -p '{DEVIN_PROMPT}' "
        f"--model {DEVIN_MODEL} "
        f"--respect-workspace-trust false "
        f"--permission-mode {DEVIN_PERMISSION_MODE} "
        f"--export {export_path}; "
        f"echo DEVIN_CLI_EXITED code=$?; "
        f"sleep 999999"
    )

    full_cmd = f"cd {work_dir} && {devin_cmd} 2>&1 | tee {tmux_log_path}"

    # 启动tmux session（无头模式）
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, full_cmd],
        capture_output=True, timeout=10,
    )

    # 启动pipe-pane（raw流兜底，捕获tmux pane完整内容）
    # 不sleep——tmux new-session -d是同步的，session创建完才返回
    subprocess.run(
        ["tmux", "pipe-pane", "-t", session_name, f"cat >> {tmux_pipe_path}"],
        capture_output=True, timeout=5,
    )

    return session_name


def launch_batch(batch_id, concurrency=DEFAULT_CONCURRENCY,
                 max_runtime=DEFAULT_MAX_RUNTIME_SECONDS,
                 stall_seconds=DEFAULT_STALL_SECONDS,
                 poll_seconds=DEFAULT_POLL_SECONDS):
    """并发启动一个批次的分析

    改造后：从Redis pending队列dequeue取题（不再从内存list取题）。
    feeder.py负责将prepared的run入Redis pending队列。
    launcher只负责从pending队列取题、启动tmux session、监控状态。

    兼容模式：如果Redis pending队列为空但prepared.json存在，
    降级为从prepared.json加载（向后兼容旧流程）。
    """
    logger.info(f"启动分析批次 batch={batch_id} concurrency={concurrency} max_runtime={max_runtime}")
    print(f"=== 启动分析批次 batch={batch_id} concurrency={concurrency} ===")

    db = connect_db()
    ensure_schema(db)

    # 连接Redis（必须可用——新架构依赖Redis队列调度）
    try:
        r = get_redis()
        r.ping()
        use_redis = True
        print("  Redis: 连接成功")
        logger.info("Redis连接成功")
    except Exception as e:
        use_redis = False
        print(f"  Redis: 连接失败({e})")
        logger.error(f"Redis连接失败: {e}")
        print("  新架构需要Redis——请先启动Redis，或用旧流程（feeder+launcher分离模式）")
        return

    # 更新batch状态
    update_batch(db, batch_id, {
        "status": "launching",
        "updated_at": utc_now(),
        "concurrency": concurrency,
        "timeouts": {"max_runtime_seconds": max_runtime, "stall_seconds": stall_seconds},
    })

    # 检查Redis pending队列是否有题
    pending_in_redis = r.zcard("analysis:pending")
    if pending_in_redis == 0:
        # 兼容模式：检查DB中是否有status=prepared或queued的题
        aql = (
            f"FOR run IN analysis_runs "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status IN ['prepared', 'queued', 'pending_retry'] "
            f"COLLECT WITH COUNT INTO c RETURN c"
        )
        cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
        db_pending = list(cursor)[0] if cursor.batch else 0
        if db_pending > 0:
            print(f"  Redis pending为空, 但DB中有{db_pending}个待分析run")
            print(f"  请先运行feeder: python -m src.feeder --batch-id {batch_id}")
            print(f"  或用run_pipeline.py --step launch --auto-feed")
            return
        else:
            print(f"  无待分析任务（Redis pending为空, DB中也无prepared/queued）")
            return

    print(f"  Redis pending: {pending_in_redis}个任务待启动")

    # 状态跟踪
    running = {}  # {analysis_exp_id: {session_name, work_dir, started_at, last_activity, run_key}}
    completed = []
    failed = []

    # 动态并发：跟踪当前生效的并发数，每轮从DB读取batch.concurrency
    # 支持运行中通过 set-concurrency 命令调整并发数
    last_concurrency = concurrency

    print(f"  开始并发启动（concurrency={concurrency}）...")

    while True:
        # 检查退出条件：无running且pending队列为空
        if not running and r.zcard("analysis:pending") == 0:
            break

        # 动态并发：每轮从DB读取batch.concurrency，支持运行中调整
        try:
            batch_doc = db.collection(ANALYSIS_BATCHES_COLLECTION).get(batch_id)
            if batch_doc:
                concurrency = int(batch_doc.get("concurrency", last_concurrency))
                if concurrency != last_concurrency:
                    insert_event(db, batch_id, "concurrency_changed", {
                        "old": last_concurrency, "new": concurrency,
                        "source": "dynamic_read_from_db",
                    })
                    print(f"  [dynamic] concurrency {last_concurrency} → {concurrency}")
                    logger.info(f"动态并发调整: {last_concurrency} → {concurrency}")
                    last_concurrency = concurrency
        except Exception:
            pass  # DB读取失败时保持当前并发数

        # 启动新的（填满并发槽）——从Redis pending队列dequeue
        while len(running) < concurrency and r.zcard("analysis:pending") > 0:
            # 从Redis pending队列原子取出
            items = dequeue_pending(r, count=1)
            if not items:
                break
            run_key, priority = items[0]

            # 从DB查run记录获取work_dir和analysis_exp_id
            run_doc = db.collection("analysis_runs").get(run_key)
            if not run_doc:
                logger.warning(f"DB中找不到run_key={run_key}, 跳过")
                continue
            analysis_exp_id = run_doc.get("analysis_exp_id", run_key)
            work_dir = run_doc.get("work_dir", "")
            problem_id = run_doc.get("problem_id", "")

            if not work_dir or not Path(work_dir).exists():
                logger.error(f"work_dir不存在: {work_dir}, run_key={run_key}")
                add_failed(r, {
                    "run_key": run_key,
                    "reason": "launch_error",
                    "failure_type": "infra",
                    "batch_id": batch_id,
                })
                update_run(db, run_key, {
                    "status": "launch_error",
                    "updated_at": utc_now(),
                    "end_reason": "work_dir_not_found",
                    "verdict": make_verdict("failed", "work_dir_not_found", "high", True),
                })
                update_stats(r)
                continue

            print(f"  [launch] {problem_id}")
            session_name = launch_one(analysis_exp_id, work_dir)

            now_ts = time.time()
            now_iso = utc_now()
            running[analysis_exp_id] = {
                "session_name": session_name,
                "work_dir": work_dir,
                "problem_id": problem_id,
                "run_key": run_key,
                "started_at": now_ts,
                "started_at_iso": now_iso,
                "last_activity": now_ts,
                "last_pane_hash": "",
            }

            # 更新DB（完整字段）
            try:
                update_run(db, run_key, {
                    "status": "running",
                    "tmux_session": session_name,
                    "started_at": now_iso,
                    "updated_at": now_iso,
                    "launch_started_at": now_iso,
                    "verdict": make_verdict("running", "launched"),
                })
            except Exception:
                pass

            # 更新Redis running队列
            add_running(r, run_key, {
                "analysis_exp_id": analysis_exp_id,
                "problem_id": problem_id,
                "tmux_session": session_name,
                "started_at": now_ts,
            })
            update_stats(r)

            insert_event(db, batch_id, "analysis_launched", {
                "problem_id": problem_id,
                "analysis_exp_id": analysis_exp_id,
                "tmux_session": session_name,
            }, run_key=run_key)

            # 3秒间隔——避免rate limit（对齐solver_harness runner.py）
            # 60并发并行启动导致58/60个session遇到rate limit
            time.sleep(3)

        # 检查运行中的
        to_remove = []
        for analysis_exp_id, info in running.items():
            session_name = info["session_name"]
            run_key = info["run_key"]
            pane_text = tmux_pane_text(session_name)

            # 检测完成标记
            # 注意：prompt中包含"### ANALYSIS COMPLETE"，不能用来检测完成
            # 只依赖</analysis>标记和"分析完成"中文标记
            # 对齐solver_harness：-p模式下devin cli完成后自动退出，pane中有DEVIN_CLI_EXITED
            pane_lines = pane_text.split("\n")
            last_prompt_idx = -1
            for j, line in enumerate(pane_lines):
                if "请按AGENTS.md" in line:
                    last_prompt_idx = j
            agent_output = "\n".join(pane_lines[last_prompt_idx+1:]) if last_prompt_idx >= 0 else pane_text
            is_complete = (
                XML_BLOCK_END in agent_output
                or "分析完成" in agent_output
                or "DEVIN_CLI_EXITED code=0" in agent_output  # -p模式正常退出
            )
            if is_complete:
                elapsed = int(time.time() - info["started_at"])
                print(f"  [done] {info['problem_id']} — analysis complete ({elapsed}s)")
                completed.append({
                    "problem_id": info["problem_id"],
                    "analysis_exp_id": analysis_exp_id,
                    "session_name": session_name,
                    "run_key": run_key,
                })
                to_remove.append(analysis_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name],
                               capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    update_run(db, run_key, {
                        "status": "completed",
                        "ended_at": now_iso,
                        "updated_at": now_iso,
                        "runtime_seconds": elapsed,
                        "end_reason": "analysis_complete",
                        "verdict": make_verdict("completed", "analysis_complete"),
                    })
                except Exception:
                    pass
                if use_redis:
                    remove_running(r, run_key)
                    add_completed(r, {"run_key": run_key, "analysis_exp_id": analysis_exp_id})
                    update_stats(r)
                continue

            # === 基础设施错误检测（对齐solver_harness的classify逻辑）===
            # 检测rate_limit和connection_error——即使session还在运行也要检测
            # 否则rate_limited的session要等到timeout才会被处理，浪费并发槽位
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
                logger.warning(f"基础设施失败: {detected_error} problem={info['problem_id']} elapsed={elapsed_sec}s")
                failed.append({
                    "problem_id": info["problem_id"],
                    "analysis_exp_id": analysis_exp_id,
                    "reason": detected_error,
                    "run_key": run_key,
                    "failure_type": "infra",  # 标记为基础设施失败，可重试
                })
                to_remove.append(analysis_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name],
                               capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    update_run(db, run_key, {
                        "status": detected_error,
                        "ended_at": now_iso,
                        "updated_at": now_iso,
                        "runtime_seconds": elapsed_sec,
                        "end_reason": detected_error,
                        "verdict": make_verdict(detected_error, detected_error),
                    })
                    insert_event(db, batch_id, "infra_failure", {
                        "run_key": run_key,
                        "problem_id": info["problem_id"],
                        "failure_type": detected_error,
                        "elapsed": elapsed_sec,
                    })
                except Exception:
                    pass
                if use_redis:
                    remove_running(r, run_key)
                    add_failed(r, {"run_key": run_key, "reason": detected_error,
                                   "failure_type": "infra"})
                    update_stats(r)
                continue

            # 检测stall/timeout
            elapsed = time.time() - info["started_at"]
            pane_hash = hash(pane_text[-500:])
            if pane_hash != info["last_pane_hash"]:
                info["last_pane_hash"] = pane_hash
                info["last_activity"] = time.time()
            idle = time.time() - info["last_activity"]

            is_running = tmux_running(session_name)

            if not is_running:
                # tmux session已退出——区分dead_session和正常完成
                # dead_session: session退出但没有</analysis>标记（devin cli异常退出）
                # 对齐solver_harness：检查DEVIN_CLI_EXITED的退出码
                elapsed_sec = int(elapsed)
                if (XML_BLOCK_END in agent_output or "分析完成" in agent_output
                        or "DEVIN_CLI_EXITED code=0" in agent_output):
                    # 有完成标记或devin cli正常退出——算完成
                    print(f"  [done] {info['problem_id']} — session ended ({elapsed_sec}s)")
                    completed.append({
                        "problem_id": info["problem_id"],
                        "analysis_exp_id": analysis_exp_id,
                        "session_name": session_name,
                        "run_key": run_key,
                    })
                    to_remove.append(analysis_exp_id)
                    now_iso = utc_now()
                    try:
                        update_run(db, run_key, {
                            "status": "completed",
                            "ended_at": now_iso,
                            "updated_at": now_iso,
                            "runtime_seconds": elapsed_sec,
                            "end_reason": "tmux_session_ended",
                            "verdict": make_verdict("completed", "session_ended"),
                        })
                    except Exception:
                        pass
                    if use_redis:
                        remove_running(r, run_key)
                        add_completed(r, {"run_key": run_key, "analysis_exp_id": analysis_exp_id})
                        update_stats(r)
                else:
                    # dead_session: session退出但没有完成标记——基础设施失败，可重试
                    print(f"  [dead_session] {info['problem_id']} — session died ({elapsed_sec}s)")
                    logger.warning(f"dead_session: problem={info['problem_id']} elapsed={elapsed_sec}s")
                    failed.append({
                        "problem_id": info["problem_id"],
                        "analysis_exp_id": analysis_exp_id,
                        "reason": "dead_session",
                        "run_key": run_key,
                        "failure_type": "infra",  # 标记为基础设施失败，可重试
                    })
                    to_remove.append(analysis_exp_id)
                    now_iso = utc_now()
                    try:
                        update_run(db, run_key, {
                            "status": "dead_session",
                            "ended_at": now_iso,
                            "updated_at": now_iso,
                            "runtime_seconds": elapsed_sec,
                            "end_reason": "dead_session",
                            "verdict": make_verdict("dead_session", "dead_session"),
                        })
                        insert_event(db, batch_id, "infra_failure", {
                            "run_key": run_key,
                            "problem_id": info["problem_id"],
                            "failure_type": "dead_session",
                            "elapsed": elapsed_sec,
                        })
                    except Exception:
                        pass
                    if use_redis:
                        remove_running(r, run_key)
                        add_failed(r, {"run_key": run_key, "reason": "dead_session",
                                       "failure_type": "infra"})
                        update_stats(r)
                continue

            if elapsed > max_runtime:
                elapsed_sec = int(elapsed)
                print(f"  [timeout] {info['problem_id']} — {elapsed_sec}s")
                failed.append({
                    "problem_id": info["problem_id"],
                    "analysis_exp_id": analysis_exp_id,
                    "reason": "timeout",
                    "run_key": run_key,
                    "failure_type": "model",  # 模型能力失败，不重试
                })
                to_remove.append(analysis_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name],
                               capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    update_run(db, run_key, {
                        "status": "failed_timeout",
                        "ended_at": now_iso,
                        "updated_at": now_iso,
                        "runtime_seconds": elapsed_sec,
                        "end_reason": "max_runtime_exceeded",
                        "verdict": make_verdict("failed_timeout", "max_runtime_exceeded"),
                    })
                except Exception:
                    pass
                if use_redis:
                    remove_running(r, run_key)
                    add_failed(r, {"run_key": run_key, "reason": "timeout"})
                    update_stats(r)
                continue

            if idle > stall_seconds:
                idle_sec = int(idle)
                print(f"  [stall] {info['problem_id']} — idle {idle_sec}s")
                failed.append({
                    "problem_id": info["problem_id"],
                    "analysis_exp_id": analysis_exp_id,
                    "reason": "stall",
                    "run_key": run_key,
                    "failure_type": "model",  # 模型能力失败，不重试
                })
                to_remove.append(analysis_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name],
                               capture_output=True, timeout=5)
                now_iso = utc_now()
                try:
                    update_run(db, run_key, {
                        "status": "failed_stall",
                        "ended_at": now_iso,
                        "updated_at": now_iso,
                        "runtime_seconds": int(elapsed),
                        "end_reason": "stall_detected",
                        "verdict": make_verdict("failed_stall", "stall_detected"),
                    })
                except Exception:
                    pass
                if use_redis:
                    remove_running(r, run_key)
                    add_failed(r, {"run_key": run_key, "reason": "stall"})
                    update_stats(r)
                continue

        for key in to_remove:
            running.pop(key, None)

        # 状态报告
        redis_pending = r.zcard("analysis:pending")
        if running or redis_pending > 0:
            print(f"  [status] running={len(running)} pending={redis_pending} "
                  f"completed={len(completed)} failed={len(failed)}")
            stats = get_stats(r)
            print(f"  [redis] pending={stats.get('pending',0)} running={stats.get('running',0)} "
                  f"completed={stats.get('completed',0)} failed={stats.get('failed',0)}")
            time.sleep(poll_seconds)

    print(f"\n=== 批次完成 ===")
    print(f"  completed: {len(completed)}")
    print(f"  failed: {len(failed)}")
    logger.info(f"批次完成 batch={batch_id}: completed={len(completed)}, failed={len(failed)}")

    # 更新batch记录
    from collections import Counter
    status_counts = Counter()
    for c in completed:
        status_counts["completed"] += 1
    for f in failed:
        status_counts[f["reason"]] += 1
    update_batch(db, batch_id, {
        "status": "launched",
        "updated_at": utc_now(),
        "completed_count": len(completed),
        "failed_count": len(failed),
        "status_counts": dict(status_counts),
        "launched_at": utc_now(),
    })

    # 保存结果
    results_path = OUTPUT_BASE / batch_id / "launch_results.json"
    with open(str(results_path), "w") as f:
        json.dump({"completed": completed, "failed": failed}, f, ensure_ascii=False, indent=2)
    print(f"  结果保存到: {results_path}")


def status_batch(batch_id):
    """查看批次状态"""
    prepared_path = OUTPUT_BASE / batch_id / "prepared.json"
    results_path = OUTPUT_BASE / batch_id / "launch_results.json"

    prepared_count = 0
    if prepared_path.exists():
        with open(str(prepared_path)) as f:
            prepared_count = len(json.load(f)["prepared"])

    completed_count = 0
    failed_count = 0
    if results_path.exists():
        with open(str(results_path)) as f:
            results = json.load(f)
            completed_count = len(results["completed"])
            failed_count = len(results["failed"])

    # 检查运行中的tmux sessions
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    an_sessions = [l for l in result.stdout.split("\n") if l.startswith("an-")]

    print(f"批次: {batch_id}")
    print(f"  prepared: {prepared_count}")
    print(f"  completed: {completed_count}")
    print(f"  failed: {failed_count}")
    print(f"  running tmux sessions: {len(an_sessions)}")
    for s in an_sessions:
        print(f"    {s}")


def stop_batch(batch_id):
    """停止批次中所有运行中的tmux session"""
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    an_sessions = [l.split(":")[0] for l in result.stdout.split("\n") if l.startswith("an-")]
    for s in an_sessions:
        subprocess.run(["tmux", "kill-session", "-t", s], capture_output=True, timeout=5)
        print(f"  killed: {s}")
    print(f"  已停止 {len(an_sessions)} 个session")


def _run_key(problem_id, batch_id):
    """生成DB key"""
    return f"{problem_id.replace('_', '-')}-{batch_id}"


def main():
    parser = argparse.ArgumentParser(description="并发启动分析devin cli")
    parser.add_argument("--batch-id", required=True, help="批次ID")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="并发数")
    parser.add_argument("--max-runtime", type=int, default=DEFAULT_MAX_RUNTIME_SECONDS, help="最大运行时间（秒）")
    parser.add_argument("--stall-seconds", type=int, default=DEFAULT_STALL_SECONDS, help="stall判定时间（秒）")
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS, help="轮询间隔（秒）")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--stop", action="store_true", help="停止所有")
    parser.add_argument("--auto-feed", action="store_true",
                        help="启动前自动调用feeder一次性入队所有prepared的题")
    args = parser.parse_args()

    if args.status:
        status_batch(args.batch_id)
    elif args.stop:
        stop_batch(args.batch_id)
    else:
        # --auto-feed: 启动前自动入队
        if args.auto_feed:
            from src.feeder import feed_batch
            from monitoring.redis_queue import get_redis, ping, update_stats
            if not ping():
                print("Redis连接失败")
                return
            r = get_redis()
            db = connect_db()
            # 一次性入队所有prepared的题
            total = 0
            while True:
                count = feed_batch(db, r, args.batch_id, batch_size=500)
                if count == 0:
                    break
                total += count
                update_stats(r)
            print(f"  [auto-feed] 入队{total}题到Redis pending")

        launch_batch(
            args.batch_id,
            concurrency=args.concurrency,
            max_runtime=args.max_runtime,
            stall_seconds=args.stall_seconds,
            poll_seconds=args.poll_seconds,
        )


if __name__ == "__main__":
    main()
