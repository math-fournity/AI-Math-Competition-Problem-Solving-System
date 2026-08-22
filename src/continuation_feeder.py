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
from monitoring.shared_logger import get_logger, log_event
from src.step_gate import gated
from src.observability import log_flow

logger = get_logger("continuation_feeder")


@gated(resource="redis")
def feed_enqueue(r, key, batch_id):
    """【门闸: GATE-FEED-ENQUEUE】feeder把prepared题入队（priority=0）。

    这个动作做什么：
    从DB查出prepared的run，以最高优先级(0)放入Redis pending队列。prepared
    可以是初次入题，也可以是操作者已写reason显式开启的新调度窗口。
    这是所有题进入调度系统的唯一正门——窗口内截断/防抖重入队
    （round_num/9999）都排在它后面。

    为什么追踪这个动作：
    - 016事故的另一半在此：feeder无条件zadd priority=0，把截断重入队
      的低优先级重置回队首，同一道题被反复dequeue启动。P0-3已改NX模式
      （已存在不覆盖score），hold此闸时可人工复核NX语义真的生效；
    - feeder是launcher的L2闸覆盖不到的唯一调度入口（独立进程）；
    - 016前此动作不进行为流水黑匣子（只写debug日志），Master Agent
      看不见——现在每次入队写log_flow。

    放行前Master Agent应检查并论证：
    【检查项】（每项含查法+正常值）
    1. 该key确实是prepared → 查法：DB p27_continuation_runs查status==prepared；
       若已有rounds_log，还应有resume_reason（显式新窗口）或active窗口（窗口内恢复）
    2. 返回0时score未被重置 → 查法：ZRANK p27:pending <key>看score(应为round_num或9999，非0)
    3. pending总量正常 → 查法：ZCARD p27:pending对比上一轮feed_batch计数

    【论证依据——放行/不放行判定】
    可放行：1✓(确实是prepared且续传来源可解释)+3✓(pending总量正常)。理由：feeder是所有题
       进入调度的唯一正门，入队状态与新窗口/窗口内恢复语义一致——不产生016"feeder高频重喂→队列永远清不空"
    不可放行：2返回0时score被重置为0→016 P0-3根因重现(NX失效，feeder重置优先级导致失控循环)；
       3✗(pending异常膨胀)→016现象(feeder死循环重喂)
    """
    added = enqueue_pending(r, key, priority=0)
    log_flow("enqueue", run_key=key, batch_id=batch_id, priority=0,
             source="feeder", added=int(added or 0))
    return added


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
        # 016事故P0-3修复：只统计"新入队"的（enqueue_pending已改为NX模式，
        # 已存在的返回0且不覆盖score）。否则已入队的题也被计数，
        # feed_batch永远返回非0，main的while True死循环。
        if feed_enqueue(r, key, batch_id, gate_ctx={"run_key": key}):
            count += 1

    log_event(logger, "info", "feed_batch_done", batch_id=batch_id, count=count)
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
