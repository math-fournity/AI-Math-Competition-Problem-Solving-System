#!/usr/bin/env python3
"""analysis_control.py — 错题分析系统控制工具

启动/停止/状态查询/健康检查。

对齐solver_harness的pipe_control.py：
  - start: 一键启动feeder+launcher+retry服务（tmux session + auto-restart）
  - stop: 一键优雅停止所有服务（SIGINT等退出，超时才kill）
  - stop --force: 强制停止
  - stop --kill-sessions: 同时kill正在运行的an-分析session
  - status/health/logs/set-concurrency/retry

用法:
  python -m monitoring.analysis_control start --batch-id <id> --concurrency 30
  python -m monitoring.analysis_control stop [--force] [--kill-sessions]
  python -m monitoring.analysis_control status [--batch-id <id>]
  python -m monitoring.analysis_control health [--batch-id <id>]
  python -m monitoring.analysis_control logs [--lines 50]
  python -m monitoring.analysis_control set-concurrency --batch-id <id> --concurrency 20
  python -m monitoring.analysis_control retry --once
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from collections import Counter

# 添加项目根目录到path
# 注意：本项目根目录是analysis-devin-failure-system，不是worktree根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent  # worktree根目录（用于sys.path）
ANALYSIS_ROOT = Path(__file__).parent.parent          # analysis-devin-failure-system目录
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(ANALYSIS_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from src.config import (
    OUTPUT_BASE, ANALYSIS_SOLVER_BASE, ANALYSIS_TRAJECTORY_BASE,
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    ANALYSIS_RUNS_COLLECTION, ANALYSIS_RESULTS_COLLECTION,
)
from monitoring.shared_logger import get_logger

logger = get_logger("control")


def tmux_running(name: str) -> bool:
    try:
        r = subprocess.run(
            ["tmux", "has-session", "-t", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


def list_analysis_sessions():
    """列出所有an-开头的tmux session"""
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    sessions = []
    for line in result.stdout.strip().split("\n"):
        if line.startswith("an-"):
            name = line.split(":")[0]
            sessions.append(name)
    return sessions


# ============================================================
# 服务启停（对齐solver_harness的pipe_control.py）
# ============================================================

VENV_PYTHON = str(Path(__file__).parent.parent.parent / ".venv" / "bin" / "python3")
# 如果项目根目录没有.venv，用sys.executable
if not Path(VENV_PYTHON).exists():
    VENV_PYTHON = sys.executable


def start_service(name: str, script_cmd: str, auto_restart: bool = False):
    """启动一个服务到tmux session（对齐solver_harness的start_service）

    auto_restart=True: 用bash while循环包裹，服务退出后自动重启（等5秒）。
    """
    session_name = f"analysis-{name}"
    if tmux_running(session_name):
        print(f"  [{name}] 已在运行, 跳过")
        return

    if auto_restart:
        full_cmd = (
            f'while true; do {script_cmd} 2>&1; '
            f'echo "[auto-restart] {name}退出, 5秒后重启..."; '
            f'sleep 5; done'
        )
    else:
        full_cmd = script_cmd + " 2>&1"

    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, full_cmd],
        check=False, timeout=10
    )
    print(f"  [{name}] 启动 → tmux:{session_name}" + (" (auto-restart)" if auto_restart else ""))


def stop_service(name: str, graceful: bool = True, timeout: int = 10):
    """停止一个服务（对齐solver_harness的stop_service）

    graceful=True: 发送SIGINT让服务优雅退出
    graceful=False: 直接kill-session（强制停止）
    """
    session_name = f"analysis-{name}"
    if not tmux_running(session_name):
        print(f"  [{name}] 未运行")
        return

    if graceful:
        subprocess.run(["tmux", "send-keys", "-t", session_name, "C-c", ""],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        print(f"  [{name}] 发送SIGINT, 等待优雅退出...")

        for i in range(timeout):
            time.sleep(1)
            if not tmux_running(session_name):
                print(f"  [{name}] 已优雅退出 (等待{i+1}s)")
                return

        print(f"  [{name}] 优雅退出超时({timeout}s), 强制停止")
        subprocess.run(["tmux", "kill-session", "-t", session_name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        print(f"  [{name}] 已强制停止")
    else:
        subprocess.run(["tmux", "kill-session", "-t", session_name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        print(f"  [{name}] 已强制停止")


def get_pane_tail(session_name, lines=10):
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout
    except Exception:
        return ""


# ============================================================
# status
# ============================================================

def cmd_status(batch_id=None):
    """查看状态"""
    print("=== 错题分析系统状态 ===\n")

    # tmux sessions
    sessions = list_analysis_sessions()
    print(f"运行中的tmux sessions: {len(sessions)}")
    for s in sessions:
        pane = get_pane_tail(s, lines=3)
        # 提取最后一行有内容的
        last_line = ""
        for line in pane.split("\n"):
            if line.strip() and not line.startswith("─") and "Guide Devin" not in line:
                last_line = line.strip()[:80]
        print(f"  {s}: {last_line}")
    print()

    # 各批次状态
    if batch_id:
        batches = [batch_id]
    else:
        # 列出所有有output的批次
        if OUTPUT_BASE.exists():
            batches = [d.name for d in OUTPUT_BASE.iterdir() if d.is_dir()]
        else:
            batches = []

    if not batches:
        print("无批次记录")
        return

    for bid in sorted(batches):
        print(f"--- 批次: {bid} ---")
        # prepared.json
        prepared_path = OUTPUT_BASE / bid / "prepared.json"
        prepared_count = 0
        skipped_count = 0
        if prepared_path.exists():
            with open(str(prepared_path)) as f:
                data = json.load(f)
            prepared_count = len(data.get("prepared", []))
            skipped_count = len(data.get("skipped", []))

        # launch_results.json
        launch_path = OUTPUT_BASE / bid / "launch_results.json"
        completed_count = 0
        failed_count = 0
        if launch_path.exists():
            with open(str(launch_path)) as f:
                data = json.load(f)
            completed_count = len(data.get("completed", []))
            failed_count = len(data.get("failed", []))

        # collected_results.json
        collected_path = OUTPUT_BASE / bid / "collected_results.json"
        parsed_count = 0
        no_xml_count = 0
        if collected_path.exists():
            with open(str(collected_path)) as f:
                data = json.load(f)
            parsed_count = data.get("parsed", 0)
            no_xml_count = data.get("no_xml", 0)

        # aggregated_report.json
        report_path = OUTPUT_BASE / bid / "aggregated_report.json"
        has_report = report_path.exists()

        print(f"  prepared: {prepared_count} (skipped: {skipped_count})")
        print(f"  launched: completed={completed_count}, failed={failed_count}")
        print(f"  collected: parsed={parsed_count}, no_xml={no_xml_count}")
        print(f"  aggregated: {'yes' if has_report else 'no'}")

        # DB状态
        try:
            from arango import ArangoClient
            client = ArangoClient(hosts=ARANGO_HOST)
            db = client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)
            aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.batch_id == @bid COLLECT status = r.status WITH COUNT INTO c RETURN {{status, count: c}}"
            cursor = db.aql.execute(aql, bind_vars={"bid": bid}, ttl=60)
            db_status = {row["status"]: row["count"] for row in cursor}
            if db_status:
                print(f"  DB: {db_status}")
        except Exception as e:
            print(f"  DB: (查询失败: {e})")

        print()


# ============================================================
# health
# ============================================================

def cmd_health(batch_id=None):
    """健康检查"""
    print("=== 错题分析系统健康检查 ===\n")
    checks = []

    # 检查1: tmux session数量
    sessions = list_analysis_sessions()
    checks.append({
        "name": "tmux_sessions",
        "status": "OK" if len(sessions) < 50 else "WARN",
        "detail": f"{len(sessions)}个运行中",
    })

    # 检查2: D盘挂载
    solver_base_exists = ANALYSIS_SOLVER_BASE.exists()
    checks.append({
        "name": "D盘挂载",
        "status": "OK" if solver_base_exists else "FAIL",
        "detail": f"ANALYSIS_SOLVER_BASE {'存在' if solver_base_exists else '不存在'}",
    })

    # 检查3: ArangoDB连接
    try:
        from arango import ArangoClient
        client = ArangoClient(hosts=ARANGO_HOST)
        db = client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)
        db.collections()
        checks.append({"name": "ArangoDB", "status": "OK", "detail": "连接成功"})
    except Exception as e:
        checks.append({"name": "ArangoDB", "status": "FAIL", "detail": str(e)[:80]})

    # 检查3b: Redis连接
    try:
        from monitoring.redis_queue import ping as redis_ping
        if redis_ping():
            checks.append({"name": "Redis", "status": "OK", "detail": "连接成功"})
        else:
            checks.append({"name": "Redis", "status": "WARN", "detail": "ping返回False（launcher会降级为纯内存模式）"})
    except Exception as e:
        checks.append({"name": "Redis", "status": "WARN", "detail": f"连接失败: {str(e)[:60]}"})

    # 检查4: 日志目录可写
    from monitoring.shared_logger import LOG_BASE
    log_writable = LOG_BASE.exists() and os.access(str(LOG_BASE), os.W_OK)
    checks.append({
        "name": "日志目录",
        "status": "OK" if log_writable else "FAIL",
        "detail": str(LOG_BASE),
    })

    # 检查5: 僵尸session检测（tmux session存在但pane空白）
    zombie_sessions = []
    for s in sessions:
        pane = get_pane_tail(s, lines=20)
        # 去掉空行和UI行
        content_lines = [l for l in pane.split("\n") if l.strip() and not l.startswith("─") and "Guide Devin" not in l and "Ask Devin" not in l]
        if len(content_lines) < 3:
            zombie_sessions.append(s)
    checks.append({
        "name": "僵尸session",
        "status": "OK" if not zombie_sessions else "WARN",
        "detail": f"{len(zombie_sessions)}个可能的僵尸session" + (f": {zombie_sessions[:3]}" if zombie_sessions else ""),
    })

    # 检查6: 批次数据一致性（如果指定了batch_id）
    if batch_id:
        prepared_path = OUTPUT_BASE / batch_id / "prepared.json"
        launch_path = OUTPUT_BASE / batch_id / "launch_results.json"
        if prepared_path.exists() and launch_path.exists():
            with open(str(prepared_path)) as f:
                prepared = len(json.load(f).get("prepared", []))
            with open(str(launch_path)) as f:
                launch = json.load(f)
            launched = len(launch.get("completed", [])) + len(launch.get("failed", []))
            if launched == prepared:
                checks.append({"name": "批次一致性", "status": "OK", "detail": f"launched={launched}/prepared={prepared}"})
            elif launched < prepared:
                checks.append({"name": "批次一致性", "status": "WARN", "detail": f"launched={launched} < prepared={prepared}（未全部启动）"})
            else:
                checks.append({"name": "批次一致性", "status": "FAIL", "detail": f"launched={launched} > prepared={prepared}（异常）"})

    # 输出
    ok_count = sum(1 for c in checks if c["status"] == "OK")
    warn_count = sum(1 for c in checks if c["status"] == "WARN")
    fail_count = sum(1 for c in checks if c["status"] == "FAIL")

    for c in checks:
        icon = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}[c["status"]]
        print(f"  {icon} {c['name']}: {c['detail']}")

    print(f"\n  总计: {ok_count} OK, {warn_count} WARN, {fail_count} FAIL")
    return fail_count == 0


# ============================================================
# stop
# ============================================================

def cmd_start(batch_id, concurrency=30, max_runtime=300, stall_seconds=120,
              poll_seconds=10, clear=False, no_feed=False):
    """一键启动分析系统（对齐solver_harness的cmd_start）

    启动3个服务到tmux session：
    1. feeder: 从DB取prepared的run入Redis pending队列（auto-restart）
    2. launcher: 从Redis pending队列取题启动devin cli（auto-restart）
    3. retry: 自动重试基础设施失败（auto-restart）
    """
    from monitoring.redis_queue import ping, get_redis, clear_all, update_stats, pending_count

    print("启动错题分析系统:")
    if not ping():
        print("  ❌ Redis连接失败，请先启动Redis")
        sys.exit(1)
    print("  ✅ Redis连接正常")

    r = get_redis()
    if clear:
        clear_all(r)
        print("  已清空Redis队列")

    # 1. 启动feeder（一次性入队所有prepared的题）
    if not no_feed:
        from src.feeder import feed_batch
        from src.db_schema import connect_db
        db = connect_db()
        total = 0
        while True:
            count = feed_batch(db, r, batch_id, batch_size=500)
            if count == 0:
                break
            total += count
            update_stats(r)
        print(f"  [feeder] 入队{total}题到Redis pending (pending={pending_count(r)})")

    # 2. 启动launcher（不auto-restart——批处理任务，处理完就退出）
    launcher_cmd = (
        f"cd {ANALYSIS_ROOT} && {VENV_PYTHON} -m src.analysis_launcher "
        f"--batch-id {batch_id} --concurrency {concurrency} "
        f"--max-runtime {max_runtime} --stall-seconds {stall_seconds} "
        f"--poll-seconds {poll_seconds}"
    )
    start_service("launcher", launcher_cmd, auto_restart=False)
    time.sleep(2)

    # 3. 启动retry服务（auto-restart）
    retry_cmd = (
        f"cd {ANALYSIS_ROOT} && {VENV_PYTHON} -m monitoring.retry_infrastructure "
        f"--interval 120"
    )
    start_service("retry", retry_cmd, auto_restart=True)

    print(f"\n所有服务已启动。用 'python -m monitoring.analysis_control status' 查看状态。")
    print(f"  批次: {batch_id}")
    print(f"  并发: {concurrency}")
    print(f"  pending: {pending_count(r)}")


def cmd_stop(batch_id=None, force=False, kill_sessions=False, timeout=10):
    """优雅停止分析系统（对齐solver_harness的cmd_stop）

    force=False: 发送SIGINT让launcher/retry优雅退出，等正在运行的an-分析session自然完成
    force=True: 直接kill所有服务
    kill_sessions=True: 同时kill正在运行的an-分析session（强制停止所有分析）
    """
    print("停止错题分析系统:")

    # 1. 停止服务（launcher + retry）
    for name in ["launcher", "retry"]:
        stop_service(name, graceful=not force, timeout=timeout)

    # 2. 可选：kill正在运行的an-分析session
    if kill_sessions:
        sessions = list_analysis_sessions()
        if batch_id:
            target = [s for s in sessions if batch_id in s]
        else:
            target = sessions

        if target:
            print(f"\n停止 {len(target)} 个an-分析session:")
            for s in target:
                subprocess.run(["tmux", "kill-session", "-t", s], capture_output=True, timeout=5)
                print(f"  killed: {s}")
                logger.info(f"停止session: {s}")
        else:
            print("\n无an-分析session运行中")
    else:
        sessions = list_analysis_sessions()
        if sessions:
            print(f"\n  ⚠️ {len(sessions)}个an-分析session仍在运行（不kill，等自然完成）")
            print(f"  如需强制停止: python -m monitoring.analysis_control stop --kill-sessions")
        else:
            print("\n  无an-分析session运行中")


def cmd_stop_all():
    """停止所有an-开头的session（兼容旧命令）"""
    cmd_stop(force=True, kill_sessions=True)


# ============================================================
# logs
# ============================================================

def cmd_logs(lines=50, module=None):
    """查看日志"""
    from monitoring.shared_logger import LOG_BASE
    if module:
        log_path = LOG_BASE / f"{module}.log"
    else:
        log_path = LOG_BASE / "analysis.log"

    if not log_path.exists():
        print(f"日志文件不存在: {log_path}")
        return

    # 读最后N行
    with open(str(log_path)) as f:
        all_lines = f.readlines()
    for line in all_lines[-lines:]:
        print(line, end="")


def cmd_set_concurrency(batch_id, concurrency):
    """动态修改运行中批次的并发数。

    launcher的轮询循环每轮从DB读取batch.concurrency，
    修改DB中的值后，launcher下一轮poll时自动生效。

    模仿solver_harness的cmd_set_concurrency。
    """
    from src.db_schema import connect_db, insert_event, ANALYSIS_BATCHES_COLLECTION

    db = connect_db()
    batch_doc = db.collection(ANALYSIS_BATCHES_COLLECTION).get(batch_id)
    if not batch_doc:
        print(f"批次不存在: {batch_id}")
        return

    old = int(batch_doc.get("concurrency", 0))
    db.collection(ANALYSIS_BATCHES_COLLECTION).update({
        "_key": batch_id,
        "concurrency": concurrency,
        "updated_at": _utc_now(),
    })
    insert_event(db, batch_id, "concurrency_changed", {
        "old": old, "new": concurrency, "source": "set_concurrency_command",
    })
    print(f"批次 {batch_id}: 并发数 {old} → {concurrency}")
    print(f"  (launcher将在下一轮poll时自动生效)")
    logger.info(f"动态并发调整: batch={batch_id}, {old} → {concurrency}")


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description="错题分析系统控制工具")
    sub = parser.add_subparsers(dest="command")

    # start: 一键启动
    p_start = sub.add_parser("start", help="一键启动分析系统（feeder+launcher+retry）")
    p_start.add_argument("--batch-id", required=True, help="批次ID")
    p_start.add_argument("--concurrency", type=int, default=30, help="并发数（默认30）")
    p_start.add_argument("--max-runtime", type=int, default=300, help="单题最大运行时间秒（默认300）")
    p_start.add_argument("--stall-seconds", type=int, default=120, help="stall检测秒数（默认120）")
    p_start.add_argument("--poll-seconds", type=int, default=10, help="轮询间隔秒（默认10）")
    p_start.add_argument("--clear", action="store_true", help="启动前清空Redis队列")
    p_start.add_argument("--no-feed", action="store_true", help="不自动feeder入队（手动feeder后用）")

    p_status = sub.add_parser("status", help="查看状态")
    p_status.add_argument("--batch-id", help="批次ID")

    p_health = sub.add_parser("health", help="健康检查")
    p_health.add_argument("--batch-id", help="批次ID")

    # stop: 优雅停止
    p_stop = sub.add_parser("stop", help="停止分析系统（默认优雅退出服务，保留an-分析session）")
    p_stop.add_argument("--batch-id", help="批次ID（只停止匹配的an-分析session）")
    p_stop.add_argument("--force", action="store_true", help="强制停止（不等优雅退出）")
    p_stop.add_argument("--kill-sessions", action="store_true", help="同时kill正在运行的an-分析session")
    p_stop.add_argument("--timeout", type=int, default=10, help="优雅退出等待秒数（默认10）")

    sub.add_parser("stop-all", help="停止所有（强制kill服务+an-分析session）")

    logs_parser = sub.add_parser("logs", help="查看日志")
    logs_parser.add_argument("--lines", type=int, default=50, help="显示行数")
    logs_parser.add_argument("--module", help="模块名（launcher/collector/aggregator等）")

    p_setc = sub.add_parser("set-concurrency", help="动态修改运行中批次的并发数")
    p_setc.add_argument("--batch-id", required=True, help="批次ID")
    p_setc.add_argument("--concurrency", type=int, required=True, help="新的并发数")

    p_retry = sub.add_parser("retry", help="重试基础设施失败的题目")
    p_retry.add_argument("--max-retries", type=int, default=3, help="最大重试次数")
    p_retry.add_argument("--dry-run", action="store_true", help="只看不执行")
    p_retry.add_argument("--once", action="store_true", help="执行一次后退出（默认循环）")
    p_retry.add_argument("--interval", type=int, default=120, help="循环模式间隔秒数")

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args.batch_id, concurrency=args.concurrency,
                  max_runtime=args.max_runtime, stall_seconds=args.stall_seconds,
                  poll_seconds=args.poll_seconds, clear=args.clear, no_feed=args.no_feed)
    elif args.command == "status":
        cmd_status(getattr(args, "batch_id", None))
    elif args.command == "health":
        cmd_health(getattr(args, "batch_id", None))
    elif args.command == "stop":
        cmd_stop(batch_id=getattr(args, "batch_id", None), force=args.force,
                 kill_sessions=args.kill_sessions, timeout=args.timeout)
    elif args.command == "stop-all":
        cmd_stop_all()
    elif args.command == "logs":
        cmd_logs(args.lines, args.module)
    elif args.command == "set-concurrency":
        cmd_set_concurrency(args.batch_id, args.concurrency)
    elif args.command == "retry":
        from monitoring.retry_infrastructure import main as retry_main
        # 构造参数并调用
        sys.argv = ["retry_infrastructure"]
        if args.dry_run:
            sys.argv.append("--dry-run")
        if args.once:
            sys.argv.append("--once")
        sys.argv.extend(["--max-retries", str(args.max_retries)])
        sys.argv.extend(["--interval", str(args.interval)])
        retry_main()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
