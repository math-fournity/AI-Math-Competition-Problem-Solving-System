"""redis_queue.py — 错题分析系统Redis队列操作封装

模仿solver_harness的redis_queue.py，封装对Redis队列的所有操作。

队列结构：
  analysis:pending    — Sorted Set, score=priority, member=analysis_run_key
  analysis:running    — Hash, field=analysis_run_key, value=JSON metadata
  analysis:completed  — List, JSON result
  analysis:failed     — List, JSON result
  analysis:stats      — Hash, 实时统计

与solver_harness的区别：
  - 队列前缀用analysis:而不是math:
  - pending的member是analysis_run_key而不是problem_key
  - running的metadata包含analysis_exp_id和tmux_session

用法:
  from monitoring.redis_queue import get_redis, enqueue_pending, dequeue_pending
  r = get_redis()
  enqueue_pending(r, run_key, priority=0)
  items = dequeue_pending(r, count=10)
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

PENDING_KEY = "analysis:pending"
RUNNING_KEY = "analysis:running"
COMPLETED_KEY = "analysis:completed"
FAILED_KEY = "analysis:failed"
STATS_KEY = "analysis:stats"


def get_redis() -> "redis.Redis":
    """获取Redis连接（带重连）"""
    if redis is None:
        raise ImportError("redis package not installed. Run: pip install redis")
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


def enqueue_pending(r, run_key: str, priority: int = 0) -> int:
    """将分析任务加入pending队列（Sorted Set by priority）"""
    return r.zadd(PENDING_KEY, {run_key: priority})


def dequeue_pending(r, count: int = 1) -> list[tuple[str, int]]:
    """从pending队列取出最高优先级的任务（ZPOPMIN，原子操作）"""
    results = r.zpopmin(PENDING_KEY, count)
    return [(m, int(s)) for m, s in results]


def add_running(r, run_key: str, metadata: dict[str, Any]) -> int:
    """将分析任务加入running队列"""
    return r.hset(RUNNING_KEY, run_key, json.dumps(metadata))


def get_running(r, run_key: str) -> dict[str, Any] | None:
    """获取单个running任务的metadata"""
    val = r.hget(RUNNING_KEY, run_key)
    return json.loads(val) if val else None


def get_all_running(r) -> dict[str, dict[str, Any]]:
    """获取所有running任务"""
    raw = r.hgetall(RUNNING_KEY)
    return {k: json.loads(v) for k, v in raw.items()}


def remove_running(r, run_key: str) -> int:
    """从running队列移除"""
    return r.hdel(RUNNING_KEY, run_key)


def add_completed(r, result: dict[str, Any]) -> int:
    """加入completed队列"""
    return r.lpush(COMPLETED_KEY, json.dumps(result))


def add_failed(r, result: dict[str, Any]) -> int:
    """加入failed队列"""
    return r.lpush(FAILED_KEY, json.dumps(result))


def pending_count(r) -> int:
    return r.zcard(PENDING_KEY)


def running_count(r) -> int:
    return r.hlen(RUNNING_KEY)


def completed_count(r) -> int:
    return r.llen(COMPLETED_KEY)


def failed_count(r) -> int:
    return r.llen(FAILED_KEY)


def update_stats(r):
    """更新实时统计"""
    r.hset(STATS_KEY, mapping={
        "pending": pending_count(r),
        "running": running_count(r),
        "completed": completed_count(r),
        "failed": failed_count(r),
        "updated_at": int(time.time()),
    })


def get_stats(r) -> dict[str, Any]:
    """获取统计"""
    return r.hgetall(STATS_KEY)


def clear_all(r):
    """清空所有队列（测试用）"""
    r.delete(PENDING_KEY, RUNNING_KEY, COMPLETED_KEY, FAILED_KEY, STATS_KEY)


def ping() -> bool:
    """测试Redis连接"""
    try:
        r = get_redis()
        return r.ping()
    except Exception:
        return False
