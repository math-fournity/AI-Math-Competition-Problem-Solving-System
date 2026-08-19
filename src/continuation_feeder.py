"""continuation_feeder.py — POC-2.7续传Pipe的feeder（入Redis队列）

从DB中取prepared的run，入Redis pending队列。
复用feeder.py的模式。

用法：
  python -m src.continuation_feeder --batch-id p27-full
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.continuation_config import CONTINUATION_RUNS_COLLECTION
from src.continuation_db_schema import connect_db
from src.continuation_redis_queue import get_redis, enqueue_pending, update_stats, pending_count, ping
from monitoring.shared_logger import get_logger

logger = get_logger("continuation_feeder")


def feed_batch(db, r, batch_id, batch_size=500):
    """将prepared的run入Redis pending队列"""
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'prepared' "
        f"LIMIT @bs "
        f"RETURN run._key"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id, "bs": batch_size}, ttl=120)
    keys = list(cursor)

    count = 0
    for key in keys:
        enqueue_pending(r, key, priority=0)
        count += 1

    return count


def main():
    parser = argparse.ArgumentParser(description="POC-2.7续传feeder")
    parser.add_argument("--batch-id", required=True, help="批次ID")
    args = parser.parse_args()

    if not ping():
        print("Redis连接失败")
        return

    db = connect_db()
    r = get_redis()

    total = 0
    while True:
        count = feed_batch(db, r, args.batch_id)
        if count == 0:
            break
        total += count
        update_stats(r)

    print(f"  [feeder] 入队{total}题到Redis pending (pending={pending_count(r)})")


if __name__ == "__main__":
    main()
