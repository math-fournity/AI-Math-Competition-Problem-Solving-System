#!/usr/bin/env python3
"""run_audit_pipeline.py — Pipe 2审计端到端pipeline

把audit_collector → audit_launcher → audit_result_collector → audit_aggregator串起来。

用法：
  python run_audit_pipeline.py --batch-id audit-1
  python run_audit_pipeline.py --batch-id audit-1 --step collect --limit 10
  python run_audit_pipeline.py --batch-id audit-1 --step launch
  python run_audit_pipeline.py --batch-id audit-1 --step collect-results
  python run_audit_pipeline.py --batch-id audit-1 --step aggregate
  python run_audit_pipeline.py --batch-id audit-1 --step status
  python run_audit_pipeline.py --batch-id audit-1 --step stop
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.audit_collector import collect_and_prepare_audit
from src.audit_launcher import launch_batch, status_batch, stop_batch, AUDIT_CONCURRENCY
from src.audit_result_collector import collect_batch_results
from src.audit_aggregator import aggregate
from src.audit_collector import AUDIT_RUNS_COLLECTION
from monitoring.audit_redis_queue import get_redis, enqueue_pending, update_stats, pending_count, ping


def main():
    parser = argparse.ArgumentParser(description="Pipe 2审计端到端pipeline")
    parser.add_argument("--batch-id", required=True, help="审计批次ID")
    parser.add_argument("--step", 
                        choices=["all", "collect", "feed", "launch", "collect-results", "aggregate", "status", "stop"],
                        default="all", help="执行步骤")
    parser.add_argument("--limit", type=int, help="限制题数（collect阶段，调试用）")
    parser.add_argument("--concurrency", type=int, default=AUDIT_CONCURRENCY, help="并发数")
    args = parser.parse_args()

    if args.step == "status":
        status_batch(args.batch_id)
        return

    if args.step == "stop":
        stop_batch(args.batch_id)
        return

    if args.step in ["all", "collect"]:
        # 步骤1：收集Pipe 1结果，去重，构造审计AGENTS.md
        collect_and_prepare_audit(args.batch_id, limit=args.limit)

    if args.step in ["all", "feed"]:
        # 步骤2：入队到Redis
        if not ping():
            print("Redis连接失败")
            return
        r = get_redis()
        from src.db_schema import connect_db
        db = connect_db()
        # 从audit_runs中取prepared的，入队
        aql = (
            f"FOR run IN {AUDIT_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status == 'prepared' "
            f"RETURN run._key"
        )
        cursor = db.aql.execute(aql, bind_vars={"bid": args.batch_id}, ttl=120)
        keys = list(cursor)
        total = 0
        for key in keys:
            enqueue_pending(r, key, priority=0)
            total += 1
        update_stats(r)
        print(f"  [feed] 入队{total}个审计任务到Redis pending (pending={pending_count(r)})")

    if args.step in ["all", "launch"]:
        # 步骤3：并发启动审计
        launch_batch(args.batch_id, concurrency=args.concurrency)

    if args.step in ["all", "collect-results"]:
        # 步骤4：收集审计结果
        collect_batch_results(args.batch_id)

    if args.step in ["all", "aggregate"]:
        # 步骤5：汇总产出audit_summary.md
        aggregate(args.batch_id)


if __name__ == "__main__":
    main()
