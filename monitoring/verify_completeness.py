#!/usr/bin/env python3
"""verify_completeness.py — 错题分析系统数据完备性验证

验证数据管理的完备性：ID完整性、DB与文件一致性、tmux session一致性。

模仿solver_harness的verify_completeness.py。

用法:
  python -m monitoring.verify_completeness --check-ids
  python -m monitoring.verify_completeness --check-files [--batch-id <id>]
  python -m monitoring.verify_completeness --check-tmux
  python -m monitoring.verify_completeness --check-db-sync [--batch-id <id>]
  python -m monitoring.verify_completeness --all [--batch-id <id>]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from src.config import (
    OUTPUT_BASE, ANALYSIS_SOLVER_BASE, ANALYSIS_TRAJECTORY_BASE,
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    ANALYSIS_RUNS_COLLECTION, ANALYSIS_RESULTS_COLLECTION,
)
from monitoring.shared_logger import get_logger

logger = get_logger("verify_completeness")


def connect_db():
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)


def check_ids(db):
    """DM-01: problem_id唯一性"""
    print("=== 检查1: problem_id唯一性 ===")
    aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} COLLECT pid = r.problem_id WITH COUNT INTO c FILTER c > 1 SORT c DESC RETURN {{pid, count: c}}"
    cursor = db.aql.execute(aql, ttl=300)
    duplicates = list(cursor)
    if duplicates:
        print(f"  ❌ 发现 {len(duplicates)} 个重复problem_id:")
        for d in duplicates[:10]:
            print(f"    {d['pid']}: {d['count']}次")
        return False
    else:
        print("  ✅ 无重复problem_id")
        return True


def check_files(batch_id=None):
    """DM-02: 文件完整性——每个prepared的题都有AGENTS.md"""
    print("\n=== 检查2: 文件完整性 ===")

    if batch_id:
        batches = [batch_id]
    else:
        if OUTPUT_BASE.exists():
            batches = [d.name for d in OUTPUT_BASE.iterdir() if d.is_dir()]
        else:
            batches = []

    if not batches:
        print("  无批次记录")
        return True

    all_ok = True
    for bid in batches:
        prepared_path = OUTPUT_BASE / bid / "prepared.json"
        if not prepared_path.exists():
            print(f"  ⚠️ {bid}: prepared.json不存在")
            all_ok = False
            continue

        with open(str(prepared_path)) as f:
            data = json.load(f)
        prepared = data.get("prepared", [])

        missing_agents = 0
        for item in prepared:
            work_dir = Path(item["work_dir"])
            agents_md = work_dir / "AGENTS.md"
            if not agents_md.exists():
                missing_agents += 1
                if missing_agents <= 3:
                    print(f"  ❌ {bid}: AGENTS.md不存在: {agents_md}")

        if missing_agents == 0:
            print(f"  ✅ {bid}: {len(prepared)}个AGENTS.md全部存在")
        else:
            print(f"  ❌ {bid}: {missing_agents}/{len(prepared)}个AGENTS.md缺失")
            all_ok = False

    return all_ok


def check_tmux():
    """DM-03: tmux session一致性"""
    print("\n=== 检查3: tmux session一致性 ===")
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    an_sessions = [l.split(":")[0] for l in result.stdout.split("\n") if l.startswith("an-")]
    print(f"  运行中的an- session: {len(an_sessions)}")
    for s in an_sessions:
        # 检查pane是否空白
        try:
            r = subprocess.run(
                ["tmux", "capture-pane", "-t", s, "-p", "-S", "-20"],
                capture_output=True, text=True, timeout=10,
            )
            content_lines = [l for l in r.stdout.split("\n")
                           if l.strip() and not l.startswith("─")
                           and "Guide Devin" not in l and "Ask Devin" not in l]
            if len(content_lines) < 3:
                print(f"  ⚠️ {s}: 可能是僵尸session（pane内容太少）")
            else:
                print(f"  ✅ {s}: 正常运行")
        except Exception as e:
            print(f"  ❌ {s}: 检查失败: {e}")
    return True


def check_db_sync(batch_id=None):
    """DM-04: DB与文件同步——DB中的completed记录都有tmux_pipe.log"""
    print("\n=== 检查4: DB与文件同步 ===")
    db = connect_db()

    if batch_id:
        aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.batch_id == @bid AND r.status == 'completed' RETURN r"
        cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=300)
    else:
        aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.status == 'completed' RETURN r"
        cursor = db.aql.execute(aql, ttl=300)

    runs = list(cursor)
    if not runs:
        print("  无completed记录")
        return True

    missing_traj = 0
    missing_pipe = 0
    for r in runs:
        exp_id = r.get("analysis_exp_id", "")
        traj_dir = ANALYSIS_TRAJECTORY_BASE / exp_id
        if not traj_dir.exists():
            missing_traj += 1
            if missing_traj <= 3:
                print(f"  ❌ trajectory目录不存在: {traj_dir}")
            continue
        pipe_path = traj_dir / "tmux" / "tmux_pipe.log"
        if not pipe_path.exists() or pipe_path.stat().st_size < 100:
            missing_pipe += 1
            if missing_pipe <= 3:
                print(f"  ❌ tmux_pipe.log缺失或过小: {pipe_path}")

    if missing_traj == 0 and missing_pipe == 0:
        print(f"  ✅ {len(runs)}个completed记录全部有trajectory和tmux_pipe.log")
        return True
    else:
        print(f"  ❌ missing_traj={missing_traj}, missing_pipe={missing_pipe}")
        return False


def check_redis_sync(batch_id=None):
    """DM-05: Redis与DB一致性——Redis队列计数 vs DB终态记录数"""
    print("\n=== 检查5: Redis与DB一致性 ===")
    from monitoring.redis_queue import (
        get_redis, ping, pending_count, running_count,
        completed_count, failed_count,
    )

    if not ping():
        print("  ❌ Redis连接失败")
        return False

    r = get_redis()
    redis_completed = completed_count(r)
    redis_failed = failed_count(r)
    redis_running = running_count(r)
    redis_pending = pending_count(r)

    db = connect_db()
    # DB中completed的run数
    aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.status == 'completed' COLLECT WITH COUNT INTO c RETURN c"
    db_completed = list(db.aql.execute(aql, ttl=300))[0]

    # DB中failed的run数（所有失败类型）
    aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.status IN ['failed_timeout','failed_stall','rate_limited','failed_connection','dead_session'] COLLECT WITH COUNT INTO c RETURN c"
    db_failed = list(db.aql.execute(aql, ttl=300))[0]

    # DB中running的run数
    aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.status == 'running' OR r.status == 'launching' COLLECT WITH COUNT INTO c RETURN c"
    db_running = list(db.aql.execute(aql, ttl=300))[0]

    print(f"  Redis:  pending={redis_pending} running={redis_running} completed={redis_completed} failed={redis_failed}")
    print(f"  DB:     running={db_running} completed={db_completed} failed={db_failed}")
    print(f"  completed匹配: {'✅' if redis_completed == db_completed else '❌'} ({redis_completed} vs {db_completed})")
    print(f"  failed匹配:    {'✅' if redis_failed == db_failed else '❌'} ({redis_failed} vs {db_failed})")
    print(f"  running匹配:   {'✅' if redis_running == db_running else '❌'} ({redis_running} vs {db_running})")

    return redis_completed == db_completed and redis_failed == db_failed and redis_running == db_running


def main():
    parser = argparse.ArgumentParser(description="数据完备性验证")
    parser.add_argument("--check-ids", action="store_true", help="检查problem_id唯一性")
    parser.add_argument("--check-files", action="store_true", help="检查文件完整性")
    parser.add_argument("--check-tmux", action="store_true", help="检查tmux session一致性")
    parser.add_argument("--check-db-sync", action="store_true", help="检查DB与文件同步")
    parser.add_argument("--check-redis-sync", action="store_true", help="检查Redis与DB一致性")
    parser.add_argument("--all", action="store_true", help="全部检查")
    parser.add_argument("--batch-id", help="指定批次")
    args = parser.parse_args()

    db = connect_db()
    results = []

    if args.all or args.check_ids:
        results.append(check_ids(db))
    if args.all or args.check_files:
        results.append(check_files(args.batch_id))
    if args.all or args.check_tmux:
        results.append(check_tmux())
    if args.all or args.check_db_sync:
        results.append(check_db_sync(args.batch_id))
    if args.all or args.check_redis_sync:
        results.append(check_redis_sync(args.batch_id))

    if not results:
        parser.print_help()
        return

    print(f"\n=== 总结: {'全部通过' if all(results) else '存在问题'} ===")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
