#!/usr/bin/env python3
"""query_progress.py — 查询续传解题系统进度

用法:
  python -m scripts.query_progress                  # 基础进度
  python -m scripts.query_progress --by-source      # 按 source 分布
  python -m scripts.query_progress --by-round       # 按 round 分布
  python -m scripts.query_progress --detail         # 全部维度
"""
import argparse
import os
import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from arango import ArangoClient


def connect_db():
    host = os.environ.get('ARANGO_HOST', 'http://localhost:8529')
    dbname = os.environ.get('ARANGO_DB', 'xishujuzhen_math_glm52')
    user = os.environ.get('ARANGO_USER', 'root')
    password = os.environ.get('ARANGO_PASS', '')
    c = ArangoClient(hosts=host)
    return c.db(dbname, username=user, password=password)


def print_status_dist(db):
    """按 status 统计"""
    q = ('FOR r IN p27_continuation_runs '
         'COLLECT status = r.status WITH COUNT INTO n '
         'SORT n DESC RETURN {status: status, count: n}')
    print("=== 按 status 分布 ===")
    total = 0
    for x in db.aql.execute(q, ttl=60):
        print(f"  {x['status']}: {x['count']}")
        total += x['count']
    print(f"  总计: {total}")


def print_completed_by_source(db):
    """completed 题按 source_dataset 分布"""
    q = ('FOR r IN p27_continuation_runs '
         'FILTER r.status == "completed" '
         'LET p = DOCUMENT(CONCAT("problem_extraction_progress/", r.problem_id)) '
         'COLLECT source = p ? p.source_dataset : null WITH COUNT INTO n '
         'SORT n DESC RETURN {source: source, count: n}')
    print("\n=== completed 题按 source_dataset 分布 ===")
    for x in db.aql.execute(q, ttl=60):
        print(f"  {x['source']}: {x['count']}")


def print_completed_by_round(db):
    """completed 题按 round 分布"""
    q = ('FOR r IN p27_continuation_runs '
         'FILTER r.status == "completed" '
         'COLLECT round = r.round WITH COUNT INTO n '
         'SORT round RETURN {round: round, count: n}')
    print("\n=== completed 题按 round 分布 ===")
    for x in db.aql.execute(q, ttl=60):
        print(f"  round={x['round']}: {x['count']}")


def main():
    parser = argparse.ArgumentParser(description="查询续传解题系统进度")
    parser.add_argument("--by-source", action="store_true", help="completed 题按 source 分布")
    parser.add_argument("--by-round", action="store_true", help="completed 题按 round 分布")
    parser.add_argument("--detail", action="store_true", help="全部维度")
    args = parser.parse_args()

    db = connect_db()
    print_status_dist(db)
    if args.by_source or args.detail:
        print_completed_by_source(db)
    if args.by_round or args.detail:
        print_completed_by_round(db)


if __name__ == "__main__":
    main()
