#!/usr/bin/env python3
"""cleanup_continuation_runs.py — 清洗 p27_continuation_runs 中不符合条件的题

移除不在 problem_list.json 中的 prepared 状态的题（已完成的保留不动）。

用法:
  python -m scripts.cleanup_continuation_runs --dry-run    # 只看不删
  python -m scripts.cleanup_continuation_runs              # 执行删除
"""
import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from arango import ArangoClient

PROBLEM_LIST_FILE = PROJECT_ROOT / "data" / "poc_2.7" / "problem_list.json"


def connect_db():
    host = os.environ.get('ARANGO_HOST', 'http://localhost:8529')
    dbname = os.environ.get('ARANGO_DB', 'xishujuzhen_math_glm52')
    user = os.environ.get('ARANGO_USER', 'root')
    password = os.environ.get('ARANGO_PASS', '')
    c = ArangoClient(hosts=host)
    return c.db(dbname, username=user, password=password)


def main():
    parser = argparse.ArgumentParser(description="清洗p27_continuation_runs中不符合条件的题")
    parser.add_argument("--dry-run", action="store_true", help="只看不删")
    args = parser.parse_args()

    # 1. 加载新的 problem_list.json
    with open(PROBLEM_LIST_FILE) as f:
        pl = json.load(f)
    valid_pids = {e["problem_id"] for e in pl}
    print(f"新 problem_list.json: {len(valid_pids)} 题")

    # 2. 查 p27_continuation_runs 中所有题
    db = connect_db()
    all_runs = list(db.aql.execute(
        'FOR r IN p27_continuation_runs RETURN {key: r._key, pid: r.problem_id, status: r.status}',
        ttl=60))
    print(f"p27_continuation_runs 总数: {len(all_runs)}")

    # 3. 分类
    to_remove = []  # 不在 problem_list.json 中 + prepared 状态
    keep_completed = []  # 不在 problem_list.json 中但已完成
    keep_valid = []  # 在 problem_list.json 中

    for r in all_runs:
        if r['pid'] in valid_pids:
            keep_valid.append(r)
        elif r['status'] == 'prepared':
            to_remove.append(r)
        else:
            keep_completed.append(r)

    print(f"\n=== 分类结果 ===")
    print(f"  保留（在新problem_list中）: {len(keep_valid)}")
    print(f"  保留（已完成，不在新list中）: {len(keep_completed)}")
    print(f"  删除（不在新list中 + prepared）: {len(to_remove)}")

    # 4. 显示要删除的题的前缀分布
    if to_remove:
        from collections import Counter
        prefixes = Counter()
        for r in to_remove:
            pid = r['pid']
            prefix = '_'.join(pid.split('_')[:-1]) if '_' in pid else pid
            prefixes[prefix] += 1
        print(f"\n=== 要删除的题按前缀分布 ===")
        for p, n in prefixes.most_common():
            print(f"  {p}: {n}")

    # 5. 显示要保留的已完成题
    if keep_completed:
        print(f"\n=== 保留的已完成题（不在新list中但已完成）===")
        for r in keep_completed[:10]:
            print(f"  {r['pid']}  status={r['status']}")
        if len(keep_completed) > 10:
            print(f"  ... 共 {len(keep_completed)} 题")

    if args.dry_run:
        print(f"\n[dry-run] 不删除。")
        return

    # 6. 执行删除
    if not to_remove:
        print(f"\n无需删除。")
        return

    print(f"\n删除 {len(to_remove)} 题...")
    collection = db.collection('p27_continuation_runs')
    deleted = 0
    for r in to_remove:
        collection.delete(r['key'])
        deleted += 1
        if deleted % 50 == 0:
            print(f"  已删除 {deleted}/{len(to_remove)}")
    print(f"\n✅ 已删除 {deleted} 题")


if __name__ == "__main__":
    main()
