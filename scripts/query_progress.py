#!/usr/bin/env python3
"""query_progress.py — 查询续传解题系统进度

DB 中的 status=completed 不等于硬盘上有产出。本脚本默认做 DB+硬盘交叉验证。

用法:
  python -m scripts.query_progress                  # 基础进度（含硬盘验证）
  python -m scripts.query_progress --by-source      # 按 source 分布
  python -m scripts.query_progress --by-round       # 按 round 分布
  python -m scripts.query_progress --verify-disk    # 硬盘验证明细（列出有/无 proof.md 的题）
  python -m scripts.query_progress --detail         # 全部维度
"""
import argparse
import os
import re
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


def get_completed_runs(db):
    """取所有 completed 题的完整记录"""
    q = ('FOR r IN p27_continuation_runs '
         'FILTER r.status == "completed" '
         'RETURN {pid: r.problem_id, work_dir: r.work_dir, '
         '        ended_at: r.ended_at, final_status: r.final_status}')
    return list(db.aql.execute(q, ttl=60))


def verify_disk(runs):
    """硬盘验证：检查每道 completed 题的 work_dir/proof.md 是否存在

    返回 (has_proof, no_proof_wd_exists, no_proof_wd_missing)
    """
    has_proof = []
    no_proof_wd_exists = []
    no_proof_wd_missing = []

    for r in runs:
        wd = r.get('work_dir', '') or ''
        if not wd:
            no_proof_wd_missing.append(r)
            continue
        proof_path = os.path.join(wd, 'proof.md')
        if os.path.exists(proof_path):
            r['proof_size'] = os.path.getsize(proof_path)
            with open(proof_path) as f:
                content = f.read()
            r['has_boxed'] = bool(re.search(r'\\boxed\{', content))
            r['has_proof_complete'] = 'PROOF COMPLETE' in content
            has_proof.append(r)
        elif os.path.exists(wd):
            no_proof_wd_exists.append(r)
        else:
            no_proof_wd_missing.append(r)

    return has_proof, no_proof_wd_exists, no_proof_wd_missing


def print_status_dist(db):
    """按 status 统计"""
    q = ('FOR r IN p27_continuation_runs '
         'COLLECT status = r.status WITH COUNT INTO n '
         'SORT n DESC RETURN {status: status, count: n}')
    print("=== 按 status 分布（DB）===")
    total = 0
    for x in db.aql.execute(q, ttl=60):
        print(f"  {x['status']}: {x['count']}")
        total += x['count']
    print(f"  总计: {total}")


def print_disk_verification(runs):
    """硬盘验证汇总"""
    has_proof, no_proof_wd_exists, no_proof_wd_missing = verify_disk(runs)
    print(f"\n=== completed 题硬盘验证 ===")
    print(f"  DB completed 总数: {len(runs)}")
    print(f"  有 proof.md（真正有产出）: {len(has_proof)}")
    print(f"  无 proof.md 但 work_dir 存在: {len(no_proof_wd_exists)}")
    print(f"  无 proof.md 且 work_dir 已删: {len(no_proof_wd_missing)}")
    return has_proof, no_proof_wd_exists, no_proof_wd_missing


def print_completed_by_source(db):
    """completed 题按 source_dataset 分布"""
    q = ('FOR r IN p27_continuation_runs '
         'FILTER r.status == "completed" '
         'LET p = DOCUMENT(CONCAT("problem_extraction_progress/", r.problem_id)) '
         'COLLECT source = p ? p.source_dataset : null WITH COUNT INTO n '
         'SORT n DESC RETURN {source: source, count: n}')
    print("\n=== completed 题按 source_dataset 分布（DB）===")
    for x in db.aql.execute(q, ttl=60):
        print(f"  {x['source']}: {x['count']}")


def print_completed_by_round(db):
    """completed 题按 round 分布"""
    q = ('FOR r IN p27_continuation_runs '
         'FILTER r.status == "completed" '
         'COLLECT round = r.round WITH COUNT INTO n '
         'SORT round RETURN {round: round, count: n}')
    print("\n=== completed 题按 round 分布（DB）===")
    for x in db.aql.execute(q, ttl=60):
        print(f"  round={x['round']}: {x['count']}")


def print_disk_detail(has_proof, no_proof_wd_exists, no_proof_wd_missing):
    """硬盘验证明细"""
    print(f"\n=== 有 proof.md 的 {len(has_proof)} 题 ===")
    for r in has_proof:
        print(f"  {r['pid']:30s}  proof.md={r['proof_size']}B  "
              f"boxed={'✓' if r['has_boxed'] else '✗'}  "
              f"PROOF_COMPLETE={'✓' if r['has_proof_complete'] else '✗'}")

    if no_proof_wd_exists:
        print(f"\n=== 无 proof.md 但 work_dir 存在的 {len(no_proof_wd_exists)} 题 ===")
        for r in no_proof_wd_exists:
            print(f"  {r['pid']}  work_dir={r['work_dir']}")

    if no_proof_wd_missing:
        # 按日期统计
        dates = Counter()
        for r in no_proof_wd_missing:
            date = (r.get('ended_at', '') or '')[:10]
            dates[date] += 1
        print(f"\n=== 无 proof.md 且 work_dir 已删的 {len(no_proof_wd_missing)} 题 ===")
        print(f"  按结束日期分布:")
        for d, n in sorted(dates.items()):
            print(f"    {d}: {n}")
        print(f"  前10题:")
        for r in no_proof_wd_missing[:10]:
            print(f"    {r['pid']}  ended_at={r.get('ended_at','?')}")


def main():
    parser = argparse.ArgumentParser(description="查询续传解题系统进度（含硬盘验证）")
    parser.add_argument("--by-source", action="store_true", help="completed 题按 source 分布")
    parser.add_argument("--by-round", action="store_true", help="completed 题按 round 分布")
    parser.add_argument("--verify-disk", action="store_true", help="硬盘验证明细（列出有/无 proof.md 的题）")
    parser.add_argument("--detail", action="store_true", help="全部维度")
    args = parser.parse_args()

    db = connect_db()
    print_status_dist(db)

    # 默认做硬盘验证汇总
    runs = get_completed_runs(db)
    has_proof, no_proof_wd_exists, no_proof_wd_missing = print_disk_verification(runs)

    if args.by_source or args.detail:
        print_completed_by_source(db)
    if args.by_round or args.detail:
        print_completed_by_round(db)
    if args.verify_disk or args.detail:
        print_disk_detail(has_proof, no_proof_wd_exists, no_proof_wd_missing)


if __name__ == "__main__":
    main()
