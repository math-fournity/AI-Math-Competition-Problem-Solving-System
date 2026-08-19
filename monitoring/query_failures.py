#!/usr/bin/env python3
"""query_failures.py — 错题分析系统失败分类统计

查询分析run的失败分类、结果分布、按题库/卡点类型统计。

模仿solver_harness的query_failures.py。

用法:
  python -m monitoring.query_failures --summary
  python -m monitoring.query_failures --by-verdict
  python -m monitoring.query_failures --by-turning-point
  python -m monitoring.query_failures --by-source
  python -m monitoring.query_failures --by-batch
  python -m monitoring.query_failures --export --output failures.json
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
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    ANALYSIS_RUNS_COLLECTION, ANALYSIS_RESULTS_COLLECTION,
)
from monitoring.shared_logger import get_logger

logger = get_logger("query_failures")


def connect_db():
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)


def query_summary(db):
    """汇总统计"""
    print("=== 错题分析系统汇总 ===\n")

    # runs按status
    aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} COLLECT status = r.status WITH COUNT INTO c RETURN {{status, count: c}}"
    cursor = db.aql.execute(aql, ttl=300)
    by_status = {row["status"]: row["count"] for row in cursor}
    print("analysis_runs by status:")
    for s, c in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}")

    # results按verdict
    aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} COLLECT verdict = r.dimension1_verdict WITH COUNT INTO c SORT c DESC RETURN {{verdict, count: c}}"
    cursor = db.aql.execute(aql, ttl=300)
    by_verdict = {row["verdict"]: row["count"] for row in cursor}
    if by_verdict:
        print(f"\nanalysis_results by dimension1_verdict:")
        total = sum(by_verdict.values())
        for v, c in sorted(by_verdict.items(), key=lambda x: -x[1]):
            pct = c * 100 // total if total else 0
            print(f"  {v}: {c} ({pct}%)")

    # results按turning_point
    aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} FILTER r.dimension1_verdict IN ['DIRECTION_ERROR', 'PARTIAL_PROGRESS'] COLLECT tp = r.dimension2_turning_point_type WITH COUNT INTO c SORT c DESC RETURN {{tp, count: c}}"
    cursor = db.aql.execute(aql, ttl=300)
    by_tp = {row["tp"]: row["count"] for row in cursor}
    if by_tp:
        print(f"\nanalysis_results by dimension2_turning_point_type (DIRECTION_ERROR+PARTIAL_PROGRESS only):")
        for tp, c in sorted(by_tp.items(), key=lambda x: -x[1]):
            print(f"  {tp}: {c}")

    # results按confidence
    aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} COLLECT conf = r.confidence WITH COUNT INTO c SORT c DESC RETURN {{conf, count: c}}"
    cursor = db.aql.execute(aql, ttl=300)
    by_conf = {row["conf"]: row["count"] for row in cursor}
    if by_conf:
        print(f"\nanalysis_results by confidence:")
        for conf, c in sorted(by_conf.items(), key=lambda x: -x[1]):
            print(f"  {conf}: {c}")


def query_by_verdict(db, verdict=None, limit=20):
    """按verdict查询详情"""
    if verdict:
        aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} FILTER r.dimension1_verdict == @v LIMIT @l RETURN r"
        cursor = db.aql.execute(aql, bind_vars={"v": verdict, "l": limit}, ttl=300)
        results = list(cursor)
        print(f"=== verdict={verdict} ({len(results)}条, limit={limit}) ===\n")
        for r in results:
            print(f"  {r.get('problem_id')}: {r.get('dimension2_turning_point_type', '?')} (confidence={r.get('confidence', '?')})")
            print(f"    {r.get('dimension1_explanation', '?')[:150]}")
    else:
        # 列出所有verdict
        aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} COLLECT verdict = r.dimension1_verdict WITH COUNT INTO c SORT c DESC RETURN {{verdict, count: c}}"
        cursor = db.aql.execute(aql, ttl=300)
        print("=== by verdict ===\n")
        for row in cursor:
            print(f"  {row['verdict']}: {row['count']}")


def query_by_turning_point(db, tp=None, limit=20):
    """按卡点类型查询"""
    if tp:
        aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} FILTER r.dimension2_turning_point_type == @tp LIMIT @l RETURN r"
        cursor = db.aql.execute(aql, bind_vars={"tp": tp, "l": limit}, ttl=300)
        results = list(cursor)
        print(f"=== turning_point={tp} ({len(results)}条, limit={limit}) ===\n")
        for r in results:
            print(f"  {r.get('problem_id')}: {r.get('dimension1_verdict', '?')} (confidence={r.get('confidence', '?')})")
            print(f"    {r.get('dimension2_explanation', '?')[:150]}")
    else:
        aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} COLLECT tp = r.dimension2_turning_point_type WITH COUNT INTO c SORT c DESC RETURN {{tp, count: c}}"
        cursor = db.aql.execute(aql, ttl=300)
        print("=== by turning_point ===\n")
        for row in cursor:
            print(f"  {row['tp']}: {row['count']}")


def query_by_source(db):
    """按题库分布"""
    import re
    aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} RETURN r.problem_id"
    cursor = db.aql.execute(aql, ttl=300)
    pids = list(cursor)
    by_source = Counter()
    for pid in pids:
        m = re.match(r"^([a-z_]+)", pid)
        prefix = m.group(1) if m else "unknown"
        by_source[prefix] += 1
    print("=== by source ===\n")
    for src, c in by_source.most_common():
        print(f"  {src}: {c}")


def query_by_batch(db):
    """按批次分布"""
    aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} COLLECT batch = r.batch_id, status = r.status WITH COUNT INTO c SORT batch, status RETURN {{batch, status, count: c}}"
    cursor = db.aql.execute(aql, ttl=300)
    print("=== by batch ===\n")
    current_batch = None
    for row in cursor:
        if row["batch"] != current_batch:
            current_batch = row["batch"]
            print(f"\n  {current_batch}:")
        print(f"    {row['status']}: {row['count']}")


def query_export(db, output_path):
    """导出所有结果"""
    aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} RETURN r"
    cursor = db.aql.execute(aql, ttl=300)
    results = list(cursor)
    with open(str(output_path), "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"导出 {len(results)} 条结果到 {output_path}")


def main():
    parser = argparse.ArgumentParser(description="错题分析系统失败分类统计")
    parser.add_argument("--summary", action="store_true", help="汇总统计")
    parser.add_argument("--by-verdict", nargs="?", const="", help="按verdict查询")
    parser.add_argument("--by-turning-point", nargs="?", const="", help="按卡点类型查询")
    parser.add_argument("--by-source", action="store_true", help="按题库分布")
    parser.add_argument("--by-batch", action="store_true", help="按批次分布")
    parser.add_argument("--export", action="store_true", help="导出所有结果")
    parser.add_argument("--output", default="analysis_results_export.json", help="导出路径")
    parser.add_argument("--limit", type=int, default=20, help="限制条数")
    args = parser.parse_args()

    db = connect_db()

    if args.summary:
        query_summary(db)
    if args.by_verdict is not None:
        query_by_verdict(db, verdict=args.by_verdict or None, limit=args.limit)
    if args.by_turning_point is not None:
        query_by_turning_point(db, tp=args.by_turning_point or None, limit=args.limit)
    if args.by_source:
        query_by_source(db)
    if args.by_batch:
        query_by_batch(db)
    if args.export:
        query_export(db, args.output)

    if not any([args.summary, args.by_verdict is not None, args.by_turning_point is not None,
                args.by_source, args.by_batch, args.export]):
        query_summary(db)


if __name__ == "__main__":
    main()
