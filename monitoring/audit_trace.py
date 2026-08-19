#!/usr/bin/env python3
"""audit_trace.py — 双向追溯验证

验证DB记录和物理文件之间的双向追溯性。
依据: db-file-traceability规则。

模仿solver_harness的audit_trace.py。

用法:
  python -m monitoring.audit_trace --db-to-file [--batch-id <id>] [--limit N]
  python -m monitoring.audit_trace --file-to-db
  python -m monitoring.audit_trace --problem-to-runs --problem-id <pid>
  python -m monitoring.audit_trace --run-to-result --problem-id <pid>
  python -m monitoring.audit_trace --all [--batch-id <id>]
"""
import argparse
import json
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

logger = get_logger("audit_trace")


def connect_db():
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)


def trace_db_to_file(db, batch_id=None, limit=0):
    """DB→文件：从DB记录查文件存在性"""
    print("=== DB→文件追溯 ===\n")

    if batch_id:
        aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.batch_id == @bid RETURN r"
        cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=300)
    else:
        aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} RETURN r"
        cursor = db.aql.execute(aql, ttl=300)

    runs = list(cursor)
    if limit:
        runs = runs[:limit]

    total = len(runs)
    files_checked = 0
    missing_agents = 0
    missing_traj = 0
    missing_pipe = 0

    for r in runs:
        # 检查AGENTS.md
        work_dir = Path(r.get("work_dir", ""))
        if work_dir.exists():
            agents_md = work_dir / "AGENTS.md"
            files_checked += 1
            if not agents_md.exists():
                missing_agents += 1
                if missing_agents <= 3:
                    print(f"  ❌ AGENTS.md缺失: {agents_md}")

        # 检查trajectory目录
        exp_id = r.get("analysis_exp_id", "")
        if exp_id:
            traj_dir = ANALYSIS_TRAJECTORY_BASE / exp_id
            if not traj_dir.exists():
                missing_traj += 1
                if missing_traj <= 3:
                    print(f"  ❌ trajectory目录缺失: {traj_dir}")
            else:
                pipe_path = traj_dir / "tmux" / "tmux_pipe.log"
                if not pipe_path.exists():
                    missing_pipe += 1
                    if missing_pipe <= 3:
                        print(f"  ⚠️ tmux_pipe.log缺失: {pipe_path}")

    print(f"\n  总记录: {total}")
    print(f"  文件检查: {files_checked}")
    print(f"  AGENTS.md缺失: {missing_agents}")
    print(f"  trajectory目录缺失: {missing_traj}")
    print(f"  tmux_pipe.log缺失: {missing_pipe}")

    ok = missing_agents == 0 and missing_traj == 0
    print(f"  {'✅ 追溯完整' if ok else '❌ 存在缺失'}")
    return ok


def trace_file_to_db():
    """文件→DB：从物理文件回查DB记录"""
    print("=== 文件→DB追溯 ===\n")

    # 扫描ANALYSIS_SOLVER_BASE下的analysis-devin-failure目录
    base = ANALYSIS_SOLVER_BASE
    if not base.exists():
        print(f"  目录不存在: {base}")
        return True

    # 找所有有AGENTS.md的子目录
    orphan_dirs = []
    total_dirs = 0
    matched = 0

    for d in base.iterdir():
        if not d.is_dir():
            continue
        if not (d / "AGENTS.md").exists():
            continue
        total_dirs += 1

        # 从目录名提取analysis_exp_id
        exp_id = d.name

        # 查DB
        db = connect_db()
        aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.analysis_exp_id == @eid RETURN r"
        cursor = db.aql.execute(aql, bind_vars={"eid": exp_id}, ttl=60)
        if list(cursor):
            matched += 1
        else:
            orphan_dirs.append(exp_id)

    print(f"  物理目录: {total_dirs}")
    print(f"  DB匹配: {matched}")
    print(f"  孤儿目录: {len(orphan_dirs)}")
    if orphan_dirs:
        for d in orphan_dirs[:5]:
            print(f"    {d}")

    ok = len(orphan_dirs) == 0
    print(f"  {'✅ 无孤儿目录' if ok else '⚠️ 存在孤儿目录'}")
    return ok


def trace_problem_to_runs(db, problem_id):
    """题目→分析run：从problem_id查所有分析run"""
    print(f"=== 题目 {problem_id} → 分析run ===\n")

    aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.problem_id == @pid RETURN r"
    cursor = db.aql.execute(aql, bind_vars={"pid": problem_id}, ttl=60)
    runs = list(cursor)

    if not runs:
        print("  无分析run记录")
        return True

    print(f"  分析run ({len(runs)}条):")
    for r in runs:
        print(f"    batch={r.get('batch_id')}, status={r.get('status')}, "
              f"exp_id={r.get('analysis_exp_id')}")
    return True


def trace_run_to_result(db, problem_id):
    """分析run→结果：从problem_id查分析结果"""
    print(f"=== 题目 {problem_id} → 分析结果 ===\n")

    aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} FILTER r.problem_id == @pid RETURN r"
    cursor = db.aql.execute(aql, bind_vars={"pid": problem_id}, ttl=60)
    results = list(cursor)

    if not results:
        print("  无分析结果")
        return True

    print(f"  分析结果 ({len(results)}条):")
    for r in results:
        print(f"    batch={r.get('batch_id')}")
        print(f"      verdict={r.get('dimension1_verdict')}, "
              f"turning_point={r.get('dimension2_turning_point_type')}, "
              f"confidence={r.get('confidence')}")
    return True


def main():
    parser = argparse.ArgumentParser(description="双向追溯验证")
    parser.add_argument("--db-to-file", action="store_true", help="DB→文件追溯")
    parser.add_argument("--file-to-db", action="store_true", help="文件→DB追溯")
    parser.add_argument("--problem-to-runs", action="store_true", help="题目→分析run")
    parser.add_argument("--run-to-result", action="store_true", help="分析run→结果")
    parser.add_argument("--all", action="store_true", help="全部追溯")
    parser.add_argument("--batch-id", help="指定批次")
    parser.add_argument("--problem-id", help="指定题目ID")
    parser.add_argument("--limit", type=int, default=0, help="限制条数")
    args = parser.parse_args()

    db = connect_db()
    results = []

    if args.all or args.db_to_file:
        results.append(trace_db_to_file(db, args.batch_id, args.limit))
    if args.all or args.file_to_db:
        results.append(trace_file_to_db())
    if args.problem_to_runs:
        if not args.problem_id:
            print("--problem-to-runs 需要 --problem-id")
            sys.exit(1)
        results.append(trace_problem_to_runs(db, args.problem_id))
    if args.run_to_result:
        if not args.problem_id:
            print("--run-to-result 需要 --problem-id")
            sys.exit(1)
        results.append(trace_run_to_result(db, args.problem_id))

    if not results:
        parser.print_help()
        return

    print(f"\n=== 总结: {'全部通过' if all(results) else '存在问题'} ===")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
