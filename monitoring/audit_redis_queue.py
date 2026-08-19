"""audit_redis_queue.py — Pipe 2审计Redis队列操作封装

复用redis_queue.py的逻辑，但用audit:前缀，与Pipe 1的analysis:队列隔离。

队列结构：
  audit:pending    — Sorted Set, score=priority, member=audit_run_key
  audit:running    — Hash, field=audit_run_key, value=JSON metadata
  audit:completed  — List, JSON result
  audit:failed     — List, JSON result
  audit:stats      — Hash, 实时统计
"""
import json
import time
from typing import Any

try:
    import redis
except ImportError:
    redis = None

REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

PENDING_KEY = "audit:pending"
RUNING_KEY = "audit:running"
COMPLETED_KEY = "audit:completed"
FAILED_KEY = "audit:failed"
STATS_KEY = "audit:stats"


def get_redis() -> "redis.Redis":
    if redis is None:
        raise ImportError("redis package not installed. Run: pip install redis")
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


def enqueue_pending(r, run_key: str, priority: int = 0) -> int:
    return r.zadd(PENDING_KEY, {run_key: priority})


def dequeue_pending(r, count: int = 1) -> list[tuple[str, int]]:
    results = r.zpopmin(PENDING_KEY, count)
    return [(m, int(s)) for m, s in results]


def add_running(r, run_key: str, metadata: dict[str, Any]) -> int:
    return r.hset(RUNING_KEY, run_key, json.dumps(metadata))


def get_running(r, run_key: str) -> dict[str, Any] | None:
    val = r.hget(RUNING_KEY, run_key)
    return json.loads(val) if val else None


def get_all_running(r) -> dict[str, dict[str, Any]]:
    raw = r.hgetall(RUNING_KEY)
    return {k: json.loads(v) for k, v in raw.items()}


def remove_running(r, run_key: str) -> int:
    return r.hdel(RUNING_KEY, run_key)


def add_completed(r, result: dict[str, Any]) -> int:
    return r.lpush(COMPLETED_KEY, json.dumps(result))


def add_failed(r, result: dict[str, Any]) -> int:
    return r.lpush(FAILED_KEY, json.dumps(result))


def pending_count(r) -> int:
    return r.zcard(PENDING_KEY)


def running_count(r) -> int:
    return r.hlen(RUNING_KEY)


def completed_count(r) -> int:
    return r.llen(COMPLETED_KEY)


def failed_count(r) -> int:
    return r.llen(FAILED_KEY)


def update_stats(r):
    r.hset(STATS_KEY, mapping={
        "pending": pending_count(r),
        "running": running_count(r),
        "completed": completed_count(r),
        "failed": failed_count(r),
        "updated_at": int(time.time()),
    })


def get_stats(r) -> dict[str, Any]:
    return r.hgetall(STATS_KEY)


def clear_all(r):
    r.delete(PENDING_KEY, RUNING_KEY, COMPLETED_KEY, FAILED_KEY, STATS_KEY)


def ping() -> bool:
    try:
        r = get_redis()
        return r.ping()
    except Exception:
        return False
