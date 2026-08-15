#!/usr/bin/env python3
"""feeder.py — 服务1：选题入队（独立进程）

从ArangoDB的analysis_runs表取status='prepared'的run，写入Redis pending队列。
独立进程，持续运行直到所有题入队或达到limit。

模仿solver_harness的feeder.py，实现水位机制——
当pending队列低于low_water_mark时自动补充新题。

用法:
  python -m src.feeder --batch-id <id> --low-water-mark 50 --poll-interval 5
  python -m src.feeder --batch-id <id> --limit 500
  python -m src.feeder --batch-id <id> --clear
  python -m src.feeder --batch-id <id> --dry-run
"""
import sys
import os
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from src.config import (
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
)
from src.db_schema import (
    connect_db, ensure_schema, update_run, insert_event,
    ANALYSIS_RUNS_COLLECTION, ANALYSIS_BATCHES_COLLECTION,
)
from monitoring.redis_queue import (
    get_redis, enqueue_pending, pending_count, update_stats,
    clear_all, ping,
)
from monitoring.shared_logger import get_logger

logger = get_logger("feeder")


def feed_batch(db, r, batch_id: str, batch_size: int) -> int:
    """从DB取一批status='prepared'的run，写入Redis pending队列"""
    aql = (
        f"FOR run IN {ANALYSIS_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'prepared' "
        f"SORT run._key ASC "
        f"LIMIT {batch_size} "
        f"RETURN {{_key: run._key, problem_id: run.problem_id, "
        f"analysis_exp_id: run.analysis_exp_id, work_dir: run.work_dir}}"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=300)
    count = 0
    for row in cursor:
        run_key = row["_key"]
        # 入Redis pending队列（priority=0，按_key ASC排序）
        enqueue_pending(r, run_key, priority=0)
        # 更新DB状态为queued
        update_run(db, run_key, {
            "status": "queued",
            "updated_at": _utc_now(),
        })
        count += 1
        logger.debug(f"入队: {run_key} (problem={row['problem_id']})")
    if count > 0:
        logger.info(f"本批入队完成: count={count} batch={batch_id}")
    return count


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description="Feeder: 选题入队")
    parser.add_argument("--batch-id", required=True, help="批次ID")
    parser.add_argument("--batch-size", type=int, default=100, help="每批从DB取多少题")
    parser.add_argument("--limit", type=int, default=0, help="总入队上限（0=无限）")
    parser.add_argument("--low-water-mark", type=int, default=50, help="pending低于此值时补充")
    parser.add_argument("--poll-interval", type=int, default=5, help="检查间隔秒数")
    parser.add_argument("--clear", action="store_true", help="清空Redis队列后重新开始")
    parser.add_argument("--dry-run", action="store_true", help="dry-run模式：只查DB数量，不入队")
    parser.add_argument("--once", action="store_true", help="执行一次后退出（不循环）")
    args = parser.parse_args()

    logger.info(f"启动Feeder, batch={args.batch_id} batch_size={args.batch_size} "
                f"limit={args.limit} low_water_mark={args.low_water_mark} "
                f"poll_interval={args.poll_interval} clear={args.clear} dry_run={args.dry_run}")

    # 检查Redis
    if not ping():
        logger.error("Redis连接失败, 退出")
        sys.exit(1)
    logger.info("Redis连接成功")

    r = get_redis()

    if args.clear:
        clear_all(r)
        logger.warning("已清空Redis队列")

    # 连接ArangoDB
    db = connect_db()
    ensure_schema(db)
    logger.info("ArangoDB连接成功")

    # 检查batch是否存在
    batch_doc = db.collection(ANALYSIS_BATCHES_COLLECTION).get(args.batch_id)
    if not batch_doc:
        logger.error(f"批次不存在: {args.batch_id}")
        sys.exit(1)

    total_enqueued = 0

    def run_once():
        nonlocal total_enqueued
        # 检查是否达到limit
        if args.limit > 0 and total_enqueued >= args.limit:
            logger.info(f"达到limit, total_enqueued={total_enqueued} >= limit={args.limit}")
            return False

        # 检查pending水位
        pending = pending_count(r)
        if pending >= args.low_water_mark:
            logger.info(f"pending={pending} >= low_water_mark={args.low_water_mark}, 等待{args.poll_interval}s")
            return True

        # 计算这批取多少
        need = args.low_water_mark - pending
        if args.limit > 0:
            need = min(need, args.limit - total_enqueued)
        batch = min(need, args.batch_size)
        logger.debug(f"计算批量: pending={pending} need={need} batch={batch}")

        if args.dry_run:
            # dry-run：只查DB数量，不入队
            aql = (
                f"FOR run IN {ANALYSIS_RUNS_COLLECTION} "
                f"FILTER run.batch_id == @bid "
                f"FILTER run.status == 'prepared' "
                f"COLLECT WITH COUNT INTO c RETURN c"
            )
            cursor = db.aql.execute(aql, bind_vars={"bid": args.batch_id}, ttl=300)
            remaining = list(cursor)[0]
            logger.info(f"[DRY-RUN] DB中status=prepared的run: {remaining}")
            print(f"[DRY-RUN] DB中status=prepared的run: {remaining}")
            return remaining > 0

        # 取题入队
        count = feed_batch(db, r, args.batch_id, batch)
        total_enqueued += count
        update_stats(r)

        if count == 0:
            # DB中没有更多prepared的题了
            remaining_aql = (
                f"FOR run IN {ANALYSIS_RUNS_COLLECTION} "
                f"FILTER run.batch_id == @bid "
                f"FILTER run.status == 'prepared' "
                f"COLLECT WITH COUNT INTO c RETURN c"
            )
            cursor = db.aql.execute(remaining_aql, bind_vars={"bid": args.batch_id}, ttl=300)
            remaining = list(cursor)[0]
            if remaining == 0:
                logger.info(f"DB中无更多prepared的题, total_enqueued={total_enqueued}")
                return False
        else:
            logger.info(f"入队{count}题, total_enqueued={total_enqueued}, pending={pending_count(r)}")
            print(f"  入队{count}题, total={total_enqueued}, pending={pending_count(r)}")

        return True

    if args.once:
        run_once()
        return

    # 循环模式
    print(f"循环模式: 每{args.poll_interval}秒检查一次, Ctrl+C退出")
    while True:
        try:
            should_continue = run_once()
            if not should_continue:
                break
        except Exception as e:
            logger.error(f"Feeder轮次失败: {e}", exc_info=True)
        time.sleep(args.poll_interval)

    # 最终统计
    stats_aql = (
        f"FOR run IN {ANALYSIS_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"COLLECT status = run.status WITH COUNT INTO c "
        f"SORT c DESC RETURN {{status, count: c}}"
    )
    cursor = db.aql.execute(stats_aql, bind_vars={"bid": args.batch_id}, ttl=300)
    print(f"\n=== Feeder完成 ===")
    print(f"  总入队: {total_enqueued}")
    print(f"  DB状态分布:")
    for row in cursor:
        print(f"    {row['status']}: {row['count']}")
    print(f"  Redis pending: {pending_count(r)}")


if __name__ == "__main__":
    main()
