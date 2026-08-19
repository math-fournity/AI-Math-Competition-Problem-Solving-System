#!/usr/bin/env python3
"""run_pipeline.py — 端到端pipeline

把data_collector → analysis_launcher → result_collector → aggregator串起来。

用法：
  python run_pipeline.py --batch-id analysis-1 --limit 10
  python run_pipeline.py --batch-id analysis-1 --concurrency 20
  python run_pipeline.py --batch-id analysis-1 --step collect --limit 100
  python run_pipeline.py --batch-id analysis-1 --step launch
  python run_pipeline.py --batch-id analysis-1 --step collect-results
  python run_pipeline.py --batch-id analysis-1 --step aggregate
"""

import argparse
import sys
from pathlib import Path

# 添加项目根目录到path
sys.path.insert(0, str(Path(__file__).parent))

from src.data_collector import collect_and_prepare
from src.analysis_launcher import launch_batch, status_batch, stop_batch
from src.result_collector import collect_batch
from src.aggregator import aggregate
from src.db_schema import connect_db
from src.config import (
    DEFAULT_CONCURRENCY, DEFAULT_MAX_RUNTIME_SECONDS,
    DEFAULT_STALL_SECONDS, DEFAULT_POLL_SECONDS,
)


def main():
    parser = argparse.ArgumentParser(description="端到端pipeline")
    parser.add_argument("--batch-id", required=True, help="批次ID")
    parser.add_argument("--step", choices=["all", "collect", "launch", "collect-results", "aggregate", "status", "stop"],
                        default="all", help="执行步骤")
    parser.add_argument("--limit", type=int, help="限制题数（collect阶段）")
    parser.add_argument("--problem-ids", help="指定题号（逗号分隔）")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="并发数")
    parser.add_argument("--max-runtime", type=int, default=DEFAULT_MAX_RUNTIME_SECONDS, help="最大运行时间（秒）")
    parser.add_argument("--stall-seconds", type=int, default=DEFAULT_STALL_SECONDS, help="stall判定时间（秒）")
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS, help="轮询间隔（秒）")
    args = parser.parse_args()

    if args.step == "status":
        status_batch(args.batch_id)
        return

    if args.step == "stop":
        stop_batch(args.batch_id)
        return

    if args.step in ["all", "collect"]:
        problem_ids = args.problem_ids.split(",") if args.problem_ids else None
        collect_and_prepare(args.batch_id, limit=args.limit, problem_ids=problem_ids)

    if args.step in ["all", "launch"]:
        # 新架构：先feeder入队，再launcher从队列取题
        # --auto-feed模式：launcher内部自动调用feeder一次性入队
        # 也可以分开运行：python -m src.feeder --batch-id <id> 然后 python -m src.analysis_launcher --batch-id <id>
        from src.feeder import feed_batch
        from monitoring.redis_queue import get_redis, ping, update_stats, pending_count
        if not ping():
            print("Redis连接失败")
            return
        r = get_redis()
        db = connect_db()
        # 一次性入队所有prepared的题
        total = 0
        while True:
            count = feed_batch(db, r, args.batch_id, batch_size=500)
            if count == 0:
                break
            total += count
            update_stats(r)
        print(f"  [feeder] 入队{total}题到Redis pending (pending={pending_count(r)})")

        launch_batch(
            args.batch_id,
            concurrency=args.concurrency,
            max_runtime=args.max_runtime,
            stall_seconds=args.stall_seconds,
            poll_seconds=args.poll_seconds,
        )

    if args.step in ["all", "collect-results"]:
        collect_batch(args.batch_id)

    if args.step in ["all", "aggregate"]:
        aggregate(args.batch_id)


if __name__ == "__main__":
    main()
