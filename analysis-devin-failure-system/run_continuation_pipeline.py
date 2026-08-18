#!/usr/bin/env python3
"""run_continuation_pipeline.py — POC-2.7续传Pipe端到端pipeline

把continuation_collector → feeder → continuation_launcher → continuation_result_collector串起来。
复用run_pipeline.py的模式。

用法：
  # 全量919题
  python run_continuation_pipeline.py --batch-id p27-full

  # 小批量测试（10题）
  python run_continuation_pipeline.py --batch-id p27-test --limit 10

  # 指定前缀
  python run_continuation_pipeline.py --batch-id p27-omni --filter-prefix omni_math_

  # 分步执行
  python run_continuation_pipeline.py --batch-id p27-full --step collect
  python run_continuation_pipeline.py --batch-id p27-full --step feed
  python run_continuation_pipeline.py --batch-id p27-full --step launch --concurrency 5
  python run_continuation_pipeline.py --batch-id p27-full --step collect-results

  # 状态检查
  python run_continuation_pipeline.py --batch-id p27-full --step status

  # 停止
  python run_continuation_pipeline.py --batch-id p27-full --step stop
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.continuation_config import (
    DEFAULT_CONCURRENCY, DEFAULT_MAX_ROUNDS,
    DEFAULT_MAX_RUNTIME_SECONDS, DEFAULT_STALL_SECONDS, DEFAULT_POLL_SECONDS,
)


def main():
    parser = argparse.ArgumentParser(description="POC-2.7续传端到端pipeline")
    parser.add_argument("--batch-id", required=True, help="批次ID（如p27-full）")
    parser.add_argument("--step",
                        choices=["all", "collect", "feed", "launch", "collect-results", "status", "stop"],
                        default="all", help="执行步骤")
    parser.add_argument("--limit", type=int, help="限制题数（collect阶段，测试用）")
    parser.add_argument("--filter-prefix", help="题目ID前缀过滤")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="并发数")
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS, help="最大续传轮次")
    parser.add_argument("--method", choices=["v1", "v2"], default="v2", help="续传方案")
    parser.add_argument("--max-runtime", type=int, default=DEFAULT_MAX_RUNTIME_SECONDS, help="单轮最大运行时间（秒）")
    parser.add_argument("--stall-seconds", type=int, default=DEFAULT_STALL_SECONDS, help="stall判定时间（秒）")
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS, help="轮询间隔（秒）")
    args = parser.parse_args()

    if args.step == "status":
        from src.continuation_launcher import status_batch
        status_batch(args.batch_id)
        return

    if args.step == "stop":
        from src.continuation_launcher import stop_batch
        stop_batch(args.batch_id)
        return

    if args.step in ["all", "collect"]:
        # 步骤1：数据收集
        from src.continuation_collector import collect_and_prepare
        count = collect_and_prepare(args.batch_id, limit=args.limit,
                                    filter_prefix=args.filter_prefix)
        print(f"\n  {count}条续传任务已准备")

    if args.step in ["all", "feed"]:
        # 步骤2：入Redis队列
        from src.continuation_redis_queue import get_redis, enqueue_pending, update_stats, pending_count, ping
        from src.continuation_db_schema import connect_db
        from src.continuation_config import CONTINUATION_RUNS_COLLECTION

        if not ping():
            print("Redis连接失败")
            return
        r = get_redis()
        db = connect_db()

        # 从DB取prepared的，入队
        aql = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
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
        print(f"  [feed] 入队{total}题到Redis pending (pending={pending_count(r)})")

    if args.step in ["all", "launch"]:
        # 步骤3：并发启动续传
        from src.continuation_launcher import launch_batch
        launch_batch(
            args.batch_id,
            concurrency=args.concurrency,
            max_rounds=args.max_rounds,
            max_runtime=args.max_runtime,
            stall_seconds=args.stall_seconds,
            poll_seconds=args.poll_seconds,
            method=args.method,
        )

    if args.step in ["all", "collect-results"]:
        # 步骤4：收集结果
        from src.continuation_result_collector import collect_batch_results
        collect_batch_results(args.batch_id)


if __name__ == "__main__":
    main()
