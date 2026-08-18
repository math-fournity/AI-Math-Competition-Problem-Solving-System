"""continuation_collector.py — POC-2.7续传Pipe数据收集组件

从problem_list.json取919道DIRECTION_ERROR题，为每道题构造续传run记录。
复用data_collector.py的模式，但数据源是problem_list.json而非ArangoDB查询。

步骤：
  1. 加载problem_list.json（919题）
  2. 为每道题提取题目文本
  3. 为每道题创建DB run记录（status=prepared）
  4. 返回prepared的run列表（供feeder入Redis队列）

用法：
  python -m src.continuation_collector --batch-id p27-full
  python -m src.continuation_collector --batch-id p27-test --limit 10
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.continuation_config import (
    PROBLEM_LIST_FILE, D_SOLVER_DIR, D_TRAJ_DIR,
    CONTINUATION_SOLVER_BASE, CONTINUATION_TRAJECTORY_BASE,
    CONTINUATION_RUNS_COLLECTION,
)
from src.continuation_db_schema import connect_db, ensure_schema, insert_run, update_run
from monitoring.shared_logger import get_logger

logger = get_logger("continuation_collector")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_problem_list():
    """加载problem_list.json"""
    if not PROBLEM_LIST_FILE.exists():
        print(f"ERROR: problem_list.json不存在: {PROBLEM_LIST_FILE}")
        print("请先运行: python3 batch_continue_948.py export-list")
        return []
    with open(PROBLEM_LIST_FILE) as f:
        return json.load(f)


def extract_problem_text(problem_entry):
    """从problem.txt或AGENTS.md中提取题目文本（复用batch_continue_948.py的逻辑）"""
    # 方法1: problem.txt
    problem_path = problem_entry.get("problem_path", "")
    if problem_path and os.path.exists(problem_path):
        with open(problem_path) as f:
            text = f.read().strip()
        if text:
            return text

    # 方法2: AGENTS.md中的## Problem部分
    agents_md_path = problem_entry.get("agents_md_path", "")
    if agents_md_path and os.path.exists(agents_md_path):
        with open(agents_md_path) as f:
            content = f.read()
        m = re.search(r"## Problem\s*(.*?)(?:### PROOF COMPLETE|$)", content, re.DOTALL)
        if m:
            return m.group(1).strip()

    # 方法3: 从export的system message中找
    export_path = problem_entry.get("seed_export", "")
    if export_path and os.path.exists(export_path):
        with open(export_path) as f:
            d = json.load(f)
        for s in d.get("steps", []):
            if s.get("source") == "system":
                msg = s.get("message", "") or ""
                m = re.search(r"## Problem\s*(.*?)(?:### PROOF COMPLETE|$)", msg, re.DOTALL)
                if m:
                    return m.group(1).strip()
    return None


def collect_and_prepare(batch_id, limit=None, filter_prefix=None):
    """收集数据，为每道题创建DB run记录。

    Args:
        batch_id: 批次ID（如p27-full, p27-test）
        limit: 限制题数（测试用）
        filter_prefix: 题目ID前缀过滤（如omni_math_）
    """
    problems = load_problem_list()
    if not problems:
        return 0

    # 前缀过滤
    if filter_prefix:
        problems = [p for p in problems if p["problem_id"].startswith(filter_prefix)]
        print(f"  前缀过滤 '{filter_prefix}': {len(problems)}题")

    # 数量限制
    if limit:
        problems = problems[:limit]
        print(f"  限制{limit}题")

    print(f"\n=== POC-2.7续传数据收集 ===")
    print(f"  batch_id: {batch_id}")
    print(f"  题目数: {len(problems)}")

    db = connect_db()
    ensure_schema(db)

    prepared = 0
    skipped = 0

    for p in problems:
        pid = p["problem_id"]
        exp_id = p.get("exp_id", "")
        seed_export = p.get("seed_export", "")

        # 验证seed_export存在
        if not seed_export or not os.path.exists(seed_export):
            print(f"  [skip] {pid}: seed_export不存在")
            skipped += 1
            continue

        # 提取题目文本
        problem_text = extract_problem_text(p)
        if not problem_text:
            print(f"  [skip] {pid}: 无法提取题目文本")
            skipped += 1
            continue

        # 生成run_key
        run_key = f"{batch_id}-{pid}".replace("/", "-").replace(" ", "-")

        # 检查是否已存在（断点续传）
        existing = db.collection(CONTINUATION_RUNS_COLLECTION).get(run_key)
        if existing and existing.get("final_status") == "COMPLETED":
            print(f"  [skip] {pid}: 已完成（断点续传）")
            skipped += 1
            continue

        # 创建工作目录
        work_dir = CONTINUATION_SOLVER_BASE / run_key
        work_dir.mkdir(parents=True, exist_ok=True)

        # 创建trajectory目录
        traj_dir = CONTINUATION_TRAJECTORY_BASE / run_key
        traj_dir.mkdir(parents=True, exist_ok=True)
        (traj_dir / "exports").mkdir(exist_ok=True)
        (traj_dir / "tmux").mkdir(exist_ok=True)

        # 保存题目文本到工作目录
        problem_file = work_dir / "problem.txt"
        problem_file.write_text(problem_text)

        # 创建/更新DB run记录
        run_doc = {
            "_key": run_key,
            "batch_id": batch_id,
            "problem_id": pid,
            "original_exp_id": exp_id,
            "seed_export": seed_export,
            "work_dir": str(work_dir),
            "trajectory_dir": str(traj_dir),
            "problem_text": problem_text[:500],  # DB中只存前500字符
            "problem_path": str(problem_file),
            "status": "prepared",
            "final_status": None,
            "rounds_log": [],
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }

        if existing:
            update_run(db, run_key, {
                "status": "prepared",
                "updated_at": utc_now(),
            })
        else:
            insert_run(db, run_doc)

        prepared += 1

    print(f"\n=== 收集完成 ===")
    print(f"  prepared: {prepared}")
    print(f"  skipped: {skipped}")
    print(f"  batch_id: {batch_id}")

    return prepared


def main():
    parser = argparse.ArgumentParser(description="POC-2.7续传数据收集")
    parser.add_argument("--batch-id", required=True, help="批次ID（如p27-full）")
    parser.add_argument("--limit", type=int, help="限制题数（测试用）")
    parser.add_argument("--filter-prefix", help="题目ID前缀过滤")
    args = parser.parse_args()

    count = collect_and_prepare(args.batch_id, limit=args.limit,
                                filter_prefix=args.filter_prefix)
    print(f"\n完成: {count}条续传任务已准备")


if __name__ == "__main__":
    main()
