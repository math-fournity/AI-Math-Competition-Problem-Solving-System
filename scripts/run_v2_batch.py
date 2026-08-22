#!/usr/bin/env python3
"""run_v2_batch.py — v2 批量解题运行器（concurrency=1）

从 p27_continuation_runs 拉取 prepared 的题，逐个调 v2_pipeline.solve_problem，
更新 DB 状态。长命令——放 tmux 跑。

用法：
  python scripts/run_v2_batch.py --batch-id v2-p27-full [--limit 10]
  python scripts/run_v2_batch.py --batch-id v2-p27-full --start-from <pid>
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.continuation_config import CONTINUATION_RUNS_COLLECTION
from src.continuation_db_schema import connect_db
from src.v2_pipeline import solve_problem

V2_WORK_BASE = Path("/Volumes/data/math-agent-glm5.2-tmux-agents-dir/v2-continuation")
V2_TRAJ_BASE = Path("/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/v2-continuation")


def get_problem_text(run_doc):
    """直接读 DB 的 problem_text 字段（collector 写入，可靠）。"""
    pt = run_doc.get("problem_text") or ""
    return pt.strip() if len(pt) > 50 else None

def main():
    ap = argparse.ArgumentParser(description="v2 批量解题运行器")
    ap.add_argument("--batch-id", default="v2-p27-full")
    ap.add_argument("--limit", type=int, default=0, help="最多做几题（0=无限）")
    ap.add_argument("--max-rounds", type=int, default=10, help="每题最大接力轮数")
    ap.add_argument("--start-from", help="从此 problem_id 开始")
    args = ap.parse_args()

    db = connect_db()
    runs = db.collection(CONTINUATION_RUNS_COLLECTION)

    # 拉取候选：status=prepared 或 completed（重做）
    candidates = [r for r in runs.all()
                  if r.get("status") in ("prepared",)]
    print(f"待做题数: {len(candidates)}")

    done_count = 0
    skipped_early = not args.start_from  # 无 start_from 则从头开始

    for run_doc in candidates:
        rk = run_doc["_key"]
        pid = run_doc.get("problem_id", "")

        if not skipped_early:
            if pid == args.start_from or rk.endswith(args.start_from):
                skipped_early = True
            else:
                continue

        if args.limit > 0 and done_count >= args.limit:
            print(f"\n已达 limit={args.limit}，停止。")
            break

        problem_text = get_problem_text(run_doc)
        if not problem_text or len(problem_text) < 50:
            print(f"[skip] {rk}: 题目文本缺失或过短")
            continue

        print(f"\n{'='*60}", flush=True)
        print(f"[{done_count+1}] {rk} ({len(problem_text)} chars)", flush=True)
        print(f"{'='*60}", flush=True)

        # 更新状态为 running
        runs.update({"_key": rk, "status": "running",
                     "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

        # 设定工作目录
        work_dir = V2_WORK_BASE / rk
        traj_dir = V2_TRAJ_BASE / rk

        try:
            t0 = time.time()
            result = solve_problem(problem_text, str(traj_dir),
                                   max_rounds=args.max_rounds)
            elapsed = round(time.time() - t0, 0)

            completed = result.get("completed", False)
            new_status = "completed" if completed else "budget_starved"

            runs.update({"_key": rk,
                         "status": new_status,
                         "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "v2_result": json.dumps(result, ensure_ascii=False)[:5000]})

            # 归档 proof.md 到 work_dir
            proof_src = Path(traj_dir) / "proof.md"
            if proof_src.exists():
                wd = V2_WORK_BASE / rk
                wd.mkdir(parents=True, exist_ok=True)
                shutil.copy(proof_src, wd / "proof.md")

            print(f"[done] {rk}: {new_status} ({elapsed}s, "
                  f"{result['total_rounds']} rounds)", flush=True)

        except Exception as e:
            print(f"[error] {rk}: {e}", flush=True)
            runs.update({"_key": rk, "status": "failed_v2",
                         "error_message": str(e)[:500],
                         "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

        done_count += 1

    print(f"\n=== 批次完成 === 共处理 {done_count} 题")


if __name__ == "__main__":
    main()
