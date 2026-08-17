#!/usr/bin/env python3
"""run_selection_pipeline.py — Pipe 3选题端到端pipeline

把selection_collector → selection_launcher → selection_result_collector串起来。

用法：
  python run_selection_pipeline.py --batch-id selection-1 --source-batch-id audit-full1
  python run_selection_pipeline.py --batch-id selection-1 --source-batch-id audit-full1 --step collect --limit 10
  python run_selection_pipeline.py --batch-id selection-1 --step launch --concurrency 1
  python run_selection_pipeline.py --batch-id selection-1 --step collect-results
  python run_selection_pipeline.py --batch-id selection-1 --step status
  python run_selection_pipeline.py --batch-id selection-1 --step stop
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.selection_collector import collect_and_prepare_selection
from src.selection_launcher import (
    launch_batch, status_batch, stop_batch, SELECTION_CONCURRENCY,
    get_redis, sel_clear_all,
)
from src.selection_result_collector import collect_batch_results


def main():
    parser = argparse.ArgumentParser(description="Pipe 3选题端到端pipeline")
    parser.add_argument("--batch-id", required=True, help="选题批次ID（如selection-1）")
    parser.add_argument("--source-batch-id", help="审计批次ID（如audit-full1，collect步骤需要）")
    parser.add_argument("--step", default="all",
                        choices=["all", "collect", "launch", "collect-results", "status", "stop"],
                        help="执行步骤")
    parser.add_argument("--limit", type=int, help="限制题数（collect步骤用）")
    parser.add_argument("--concurrency", type=int, default=SELECTION_CONCURRENCY, help="并发数")
    args = parser.parse_args()

    if args.step == "collect":
        if not args.source_batch_id:
            print("ERROR: collect步骤需要 --source-batch-id")
            sys.exit(1)
        count = collect_and_prepare_selection(args.batch_id, args.source_batch_id, limit=args.limit)
        print(f"\n完成: {count}条选题任务已准备")

    elif args.step == "launch":
        # 清空Redis队列（避免残留）
        try:
            r = get_redis()
            sel_clear_all(r)
            print("Redis selection队列已清空")
        except Exception as e:
            print(f"Redis连接失败({e})，继续...")
        launch_batch(args.batch_id, concurrency=args.concurrency)

    elif args.step == "collect-results":
        collect_batch_results(args.batch_id)

    elif args.step == "status":
        status_batch(args.batch_id)

    elif args.step == "stop":
        stop_batch(args.batch_id)

    elif args.step == "all":
        if not args.source_batch_id:
            print("ERROR: all步骤需要 --source-batch-id")
            sys.exit(1)

        # Step 1: collect
        print("\n=== Step 1: 选题数据收集 ===")
        count = collect_and_prepare_selection(args.batch_id, args.source_batch_id, limit=args.limit)
        print(f"  {count}条选题任务已准备")

        # Step 2: launch
        print("\n=== Step 2: 启动选题 ===")
        try:
            r = get_redis()
            sel_clear_all(r)
        except Exception:
            pass
        launch_batch(args.batch_id, concurrency=args.concurrency)

        # Step 3: collect-results
        print("\n=== Step 3: 收集选题结果 ===")
        collect_batch_results(args.batch_id)

        print("\n=== 选题pipeline完成 ===")


if __name__ == "__main__":
    main()
