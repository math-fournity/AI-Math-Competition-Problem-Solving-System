#!/usr/bin/env python3
"""recover_from_crash.py — 断电恢复 + 僵尸清理

系统断电或launcher异常退出后，运行此脚本恢复一致性。

故障场景：
1. 断电：tmux session全部丢失，但DB中还有running记录
   → 将running记录标记为crash_recovered
2. launcher被kill：tmux session可能还在但无人监控
   → 检查session状态，kill僵尸session
3. 代码热替换：停launcher替换代码，重启launcher
   → running记录需要重新处理

恢复流程：
1. 扫描DB中status=running的记录
2. 对每个running记录，检查tmux session是否存在
   - session存在且pane有内容 → 保留（可能还在分析中）
   - session不存在 → 标记为crash_recovered
   - session存在但pane空白 → kill session，标记为dead_session
3. 报告恢复结果

用法:
  python -m monitoring.recover_from_crash --dry-run       # 只检查不修改
  python -m monitoring.recover_from_crash                  # 执行恢复
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from src.config import (
    OUTPUT_BASE, ANALYSIS_TRAJECTORY_BASE,
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    ANALYSIS_RUNS_COLLECTION,
)
from monitoring.shared_logger import get_logger

logger = get_logger("recover_from_crash")


def connect_db():
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)


def tmux_running(name):
    try:
        r = subprocess.run(
            ["tmux", "has-session", "-t", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


def tmux_pane_is_empty(name):
    try:
        r = subprocess.run(
            ["tmux", "capture-pane", "-t", name, "-p", "-S", "-20"],
            capture_output=True, text=True, timeout=10,
        )
        content_lines = [l for l in r.stdout.split("\n")
                       if l.strip() and not l.startswith("─")
                       and "Guide Devin" not in l and "Ask Devin" not in l]
        return len(content_lines) < 3
    except Exception:
        return True


def recover(dry_run=False):
    """执行恢复"""
    print("=== 断电恢复 + 僚尸清理 ===\n")
    db = connect_db()

    # 1. 扫描DB中status=running的记录
    aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.status == 'running' RETURN r"
    cursor = db.aql.execute(aql, ttl=300)
    running = list(cursor)

    if not running:
        print("  无running记录，无需恢复")
        return

    print(f"  running记录: {len(running)}")

    crash_recovered = 0
    dead_sessions = 0
    still_running = 0

    for r in running:
        exp_id = r.get("analysis_exp_id", "")
        session_name = r.get("tmux_session", "")
        problem_id = r.get("problem_id", "")

        if not session_name:
            # 无tmux_session字段——直接标记为crash_recovered
            print(f"  [crash] {problem_id}: 无tmux_session字段")
            crash_recovered += 1
            if not dry_run:
                db.collection(ANALYSIS_RUNS_COLLECTION).update({
                    "_key": r["_key"],
                    "status": "crash_recovered",
                    "end_reason": "no_tmux_session",
                })
            continue

        is_running = tmux_running(session_name)
        if not is_running:
            # session不存在——crash_recovered
            print(f"  [crash] {problem_id}: session {session_name} 不存在")
            crash_recovered += 1
            if not dry_run:
                db.collection(ANALYSIS_RUNS_COLLECTION).update({
                    "_key": r["_key"],
                    "status": "crash_recovered",
                    "end_reason": "tmux_session_gone",
                })
            continue

        # session存在——检查是否僵尸
        if tmux_pane_is_empty(session_name):
            print(f"  [dead] {problem_id}: session {session_name} pane空白")
            dead_sessions += 1
            if not dry_run:
                subprocess.run(["tmux", "kill-session", "-t", session_name],
                               capture_output=True, timeout=5)
                db.collection(ANALYSIS_RUNS_COLLECTION).update({
                    "_key": r["_key"],
                    "status": "dead_session",
                    "end_reason": "pane_empty_after_crash",
                })
        else:
            print(f"  [alive] {problem_id}: session {session_name} 仍在运行")
            still_running += 1

    print(f"\n  恢复结果:")
    print(f"    crash_recovered: {crash_recovered}")
    print(f"    dead_sessions: {dead_sessions}")
    print(f"    still_running: {still_running}")

    if dry_run:
        print(f"\n  (dry-run模式，未实际修改)")
    else:
        logger.info(f"恢复完成: crash={crash_recovered}, dead={dead_sessions}, alive={still_running}")

    # 2. 清理孤儿tmux session（DB中无记录但tmux中存在的an- session）
    print(f"\n  检查孤儿tmux session...")
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    all_an_sessions = [l.split(":")[0] for l in result.stdout.split("\n") if l.startswith("an-")]
    db_sessions = {r.get("tmux_session", "") for r in running if r.get("tmux_session")}
    orphans = [s for s in all_an_sessions if s not in db_sessions]

    if orphans:
        print(f"  发现 {len(orphans)} 个孤儿session:")
        for s in orphans:
            print(f"    {s}")
            if not dry_run:
                subprocess.run(["tmux", "kill-session", "-t", s], capture_output=True, timeout=5)
                print(f"      killed")
    else:
        print(f"  ✅ 无孤儿session")


def main():
    parser = argparse.ArgumentParser(description="断电恢复 + 僵尸清理")
    parser.add_argument("--dry-run", action="store_true", help="只检查不修改")
    args = parser.parse_args()

    recover(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
