#!/usr/bin/env python3
"""query_progress.py — 错题分析系统进度查询

查询当前分析进度、某批次的分析详情、某题目的分析历史。

模仿solver_harness的query_progress.py。

用法:
  python -m monitoring.query_progress
  python -m monitoring.query_progress --batch-id analysis-1
  python -m monitoring.query_progress --problem-id polymath_01687
  python -m monitoring.query_progress --exp-id test-2b-polymath_01687
"""
import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from src.config import (
    OUTPUT_BASE, ANALYSIS_TRAJECTORY_BASE,
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    ANALYSIS_RUNS_COLLECTION, ANALYSIS_RESULTS_COLLECTION,
    ANALYSIS_EVENTS_COLLECTION,
)
from monitoring.shared_logger import get_logger

logger = get_logger("query_progress")


def query_overview():
    """全局概览"""
    print("=== 错题分析系统进度概览 ===\n")

    # 所有批次
    if not OUTPUT_BASE.exists():
        print("无output目录")
        return

    batches = [d for d in OUTPUT_BASE.iterdir() if d.is_dir()]
    if not batches:
        print("无批次记录")
        return

    print(f"{'批次':<30} {'prepared':>10} {'launched':>10} {'parsed':>10} {'aggregated':>12}")
    print("-" * 80)

    for bdir in sorted(batches):
        bid = bdir.name
        prepared_count = 0
        launched_count = 0
        parsed_count = 0
        has_report = False

        prepared_path = bdir / "prepared.json"
        if prepared_path.exists():
            with open(str(prepared_path)) as f:
                prepared_count = len(json.load(f).get("prepared", []))

        launch_path = bdir / "launch_results.json"
        if launch_path.exists():
            with open(str(launch_path)) as f:
                data = json.load(f)
            launched_count = len(data.get("completed", [])) + len(data.get("failed", []))

        collected_path = bdir / "collected_results.json"
        if collected_path.exists():
            with open(str(collected_path)) as f:
                parsed_count = json.load(f).get("parsed", 0)

        report_path = bdir / "aggregated_report.json"
        has_report = report_path.exists()

        print(f"{bid:<30} {prepared_count:>10} {launched_count:>10} {parsed_count:>10} {'yes' if has_report else 'no':>12}")

    # DB统计
    print("\n--- DB统计 ---")
    try:
        from arango import ArangoClient
        client = ArangoClient(hosts=ARANGO_HOST)
        db = client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)

        # analysis_runs按status统计
        aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} COLLECT status = r.status WITH COUNT INTO c RETURN {{status, count: c}}"
        cursor = db.aql.execute(aql, ttl=60)
        for row in cursor:
            print(f"  runs.{row['status']}: {row['count']}")

        # analysis_results按verdict统计
        aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} COLLECT verdict = r.dimension1_verdict WITH COUNT INTO c SORT c DESC RETURN {{verdict, count: c}}"
        cursor = db.aql.execute(aql, ttl=60)
        results = list(cursor)
        if results:
            print(f"\n  results by verdict:")
            for row in results:
                print(f"    {row['verdict']}: {row['count']}")

    except Exception as e:
        print(f"  (DB查询失败: {e})")


def query_batch(batch_id):
    """查询某批次的详情"""
    print(f"=== 批次 {batch_id} 详情 ===\n")

    bdir = OUTPUT_BASE / batch_id
    if not bdir.exists():
        print(f"批次目录不存在: {bdir}")
        return

    # prepared.json
    prepared_path = bdir / "prepared.json"
    if prepared_path.exists():
        with open(str(prepared_path)) as f:
            data = json.load(f)
        prepared = data.get("prepared", [])
        skipped = data.get("skipped", [])
        print(f"prepared: {len(prepared)} (skipped: {len(skipped)})")
        if skipped:
            from collections import Counter
            reasons = Counter(s["reason"] for s in skipped)
            print(f"  跳过原因:")
            for reason, count in reasons.most_common():
                print(f"    {reason}: {count}")

    # launch_results.json
    launch_path = bdir / "launch_results.json"
    if launch_path.exists():
        with open(str(launch_path)) as f:
            data = json.load(f)
        completed = data.get("completed", [])
        failed = data.get("failed", [])
        print(f"\nlaunched: completed={len(completed)}, failed={len(failed)}")
        if failed:
            from collections import Counter
            reasons = Counter(f["reason"] for f in failed)
            print(f"  失败原因:")
            for reason, count in reasons.most_common():
                print(f"    {reason}: {count}")

    # collected_results.json
    collected_path = bdir / "collected_results.json"
    if collected_path.exists():
        with open(str(collected_path)) as f:
            data = json.load(f)
        print(f"\ncollected:")
        print(f"  parsed: {data.get('parsed', 0)}")
        print(f"  no_xml: {data.get('no_xml', 0)}")
        print(f"  no_output: {data.get('no_output', 0)}")
        print(f"  incomplete: {data.get('incomplete', 0)}")

    # aggregated_report.json
    report_path = bdir / "aggregated_report.json"
    if report_path.exists():
        with open(str(report_path)) as f:
            report = json.load(f)
        print(f"\naggregated:")
        print(f"  total: {report.get('total', 0)}")
        print(f"  parsed: {report.get('parsed', 0)}")
        if "dimension1_distribution" in report:
            print(f"  维度1分布:")
            for v, c in sorted(report["dimension1_distribution"].items(), key=lambda x: -x[1]):
                print(f"    {v}: {c}")
        if "dimension2_distribution" in report:
            print(f"  维度2分布:")
            for v, c in sorted(report["dimension2_distribution"].items(), key=lambda x: -x[1]):
                print(f"    {v}: {c}")


def query_problem(problem_id):
    """查询某题目的分析历史"""
    print(f"=== 题目 {problem_id} 分析历史 ===\n")

    try:
        from arango import ArangoClient
        client = ArangoClient(hosts=ARANGO_HOST)
        db = client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)

        # 查analysis_runs
        aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.problem_id == @pid RETURN r"
        cursor = db.aql.execute(aql, bind_vars={"pid": problem_id}, ttl=60)
        runs = list(cursor)
        if runs:
            print(f"analysis_runs ({len(runs)}条):")
            for r in runs:
                print(f"  batch={r.get('batch_id')}, status={r.get('status')}, "
                      f"analysis_exp_id={r.get('analysis_exp_id')}")
                print(f"    solution_source={r.get('solution_source')}, "
                      f"solution_len={r.get('solution_length')}, "
                      f"thinking_len={r.get('thinking_length')}")
        else:
            print("无analysis_runs记录")

        # 查analysis_results
        aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} FILTER r.problem_id == @pid RETURN r"
        cursor = db.aql.execute(aql, bind_vars={"pid": problem_id}, ttl=60)
        results = list(cursor)
        if results:
            print(f"\nanalysis_results ({len(results)}条):")
            for r in results:
                print(f"  batch={r.get('batch_id')}")
                print(f"    dimension1: {r.get('dimension1_verdict', '?')}")
                print(f"    dimension2: {r.get('dimension2_turning_point_type', '?')}")
                print(f"    confidence: {r.get('confidence', '?')}")
                print(f"    explanation: {r.get('dimension1_explanation', '?')[:200]}")
        else:
            print("无analysis_results记录")

    except Exception as e:
        print(f"DB查询失败: {e}")


def query_exp(exp_id):
    """查询某次分析的详情"""
    print(f"=== 分析实验 {exp_id} 详情 ===\n")

    # trajectory目录
    traj_dir = ANALYSIS_TRAJECTORY_BASE / exp_id
    if not traj_dir.exists():
        print(f"trajectory目录不存在: {traj_dir}")
        return

    print(f"trajectory目录: {traj_dir}")
    for item in sorted(traj_dir.rglob("*")):
        if item.is_file():
            size = item.stat().st_size
            mtime = datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            rel = item.relative_to(traj_dir)
            print(f"  {rel}: {size} bytes, {mtime}")


def main():
    parser = argparse.ArgumentParser(description="错题分析系统进度查询")
    parser.add_argument("--batch-id", help="批次ID")
    parser.add_argument("--problem-id", help="题目ID")
    parser.add_argument("--exp-id", help="分析实验ID")
    args = parser.parse_args()

    if args.problem_id:
        query_problem(args.problem_id)
    elif args.exp_id:
        query_exp(args.exp_id)
    elif args.batch_id:
        query_batch(args.batch_id)
    else:
        query_overview()


if __name__ == "__main__":
    main()
