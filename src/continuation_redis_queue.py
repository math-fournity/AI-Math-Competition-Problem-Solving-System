"""continuation_redis_queue.py — POC-2.7续传Pipe的Redis队列操作封装

复用redis_queue.py的模式，用p27:前缀避免与现有Pipe冲突。

v2方案用双队列实现流水线：
  p27:pending_handover  — 待生成HANDOVER.md的任务（Pipe A）
  p27:pending_solve     — 待解题的任务（Pipe B，已有HANDOVER.md）
  p27:running_handover  — 正在生成HANDOVER.md的任务
  p27:running_solve     — 正在解题的任务
  p27:completed_handover— 已完成HANDOVER.md的任务
  p27:completed_solve   — 已完成解题的任务
  p27:failed_handover   — HANDOVER.md生成失败
  p27:failed_solve      — 解题失败
  p27:stats             — 实时统计

v1方案用单队列：
  p27:pending / p27:running / p27:completed / p27:failed

用法:
  from src.continuation_redis_queue import get_redis, enqueue_pending, dequeue_pending
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

# v1单队列
PENDING_KEY = "p27:pending"
RUNNING_KEY = "p27:running"
COMPLETED_KEY = "p27:completed"
FAILED_KEY = "p27:failed"
STATS_KEY = "p27:stats"

# v2双队列
HANDOVER_PENDING_KEY = "p27:pending_handover"
SOLVE_PENDING_KEY = "p27:pending_solve"
HANDOVER_RUNNING_KEY = "p27:running_handover"
SOLVE_RUNNING_KEY = "p27:running_solve"
HANDOVER_COMPLETED_KEY = "p27:completed_handover"
SOLVE_COMPLETED_KEY = "p27:completed_solve"
HANDOVER_FAILED_KEY = "p27:failed_handover"
SOLVE_FAILED_KEY = "p27:failed_solve"


def get_redis() -> "redis.Redis":
    """获取Redis连接（带重连）"""
    if redis is None:
        raise ImportError("redis package not installed. Run: pip install redis")
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


def ping() -> bool:
    """测试Redis连接"""
    try:
        return get_redis().ping()
    except Exception:
        return False


# === v1单队列操作 ===

def enqueue_pending(r, run_key: str, priority: int = 0) -> int:
    return r.zadd(PENDING_KEY, {run_key: priority})


def dequeue_pending(r, count: int = 1) -> list[tuple[str, int]]:
    results = r.zpopmin(PENDING_KEY, count)
    return [(m, int(s)) for m, s in results]


def add_running(r, run_key: str, metadata: dict[str, Any]) -> int:
    return r.hset(RUNNING_KEY, run_key, json.dumps(metadata))


def get_running(r, run_key: str) -> dict[str, Any] | None:
    val = r.hget(RUNNING_KEY, run_key)
    return json.loads(val) if val else None


def get_all_running(r) -> dict[str, dict[str, Any]]:
    raw = r.hgetall(RUNNING_KEY)
    return {k: json.loads(v) for k, v in raw.items()}


def remove_running(r, run_key: str) -> int:
    return r.hdel(RUNNING_KEY, run_key)


def add_completed(r, result: dict[str, Any]) -> int:
    return r.lpush(COMPLETED_KEY, json.dumps(result))


def add_failed(r, result: dict[str, Any]) -> int:
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
    """清空所有队列（测试用）"""
    r.delete(PENDING_KEY, RUNNING_KEY, COMPLETED_KEY, FAILED_KEY, STATS_KEY,
             HANDOVER_PENDING_KEY, SOLVE_PENDING_KEY,
             HANDOVER_RUNNING_KEY, SOLVE_RUNNING_KEY,
             HANDOVER_COMPLETED_KEY, SOLVE_COMPLETED_KEY,
             HANDOVER_FAILED_KEY, SOLVE_FAILED_KEY)


# === v2双队列操作（Pipe A: handover / Pipe B: solve）===

def enqueue_handover(r, run_key: str, priority: int = 0) -> int:
    """加入待生成HANDOVER.md的队列"""
    return r.zadd(HANDOVER_PENDING_KEY, {run_key: priority})


def dequeue_handover(r, count: int = 1) -> list[tuple[str, int]]:
    results = r.zpopmin(HANDOVER_PENDING_KEY, count)
    return [(m, int(s)) for m, s in results]


def add_handover_running(r, run_key: str, metadata: dict) -> int:
    return r.hset(HANDOVER_RUNNING_KEY, run_key, json.dumps(metadata))


def remove_handover_running(r, run_key: str) -> int:
    return r.hdel(HANDOVER_RUNNING_KEY, run_key)


def add_handover_completed(r, result: dict) -> int:
    return r.lpush(HANDOVER_COMPLETED_KEY, json.dumps(result))


def add_handover_failed(r, result: dict) -> int:
    return r.lpush(HANDOVER_FAILED_KEY, json.dumps(result))


def handover_pending_count(r) -> int:
    return r.zcard(HANDOVER_PENDING_KEY)


def handover_running_count(r) -> int:
    return r.hlen(HANDOVER_RUNNING_KEY)


def enqueue_solve(r, run_key: str, priority: int = 0) -> int:
    """加入待解题的队列（已有HANDOVER.md）"""
    return r.zadd(SOLVE_PENDING_KEY, {run_key: priority})


def dequeue_solve(r, count: int = 1) -> list[tuple[str, int]]:
    results = r.zpopmin(SOLVE_PENDING_KEY, count)
    return [(m, int(s)) for m, s in results]


def add_solve_running(r, run_key: str, metadata: dict) -> int:
    return r.hset(SOLVE_RUNNING_KEY, run_key, json.dumps(metadata))


def remove_solve_running(r, run_key: str) -> int:
    return r.hdel(SOLVE_RUNNING_KEY, run_key)


def add_solve_completed(r, result: dict) -> int:
    return r.lpush(SOLVE_COMPLETED_KEY, json.dumps(result))


def add_solve_failed(r, result: dict) -> int:
    return r.lpush(SOLVE_FAILED_KEY, json.dumps(result))


def solve_pending_count(r) -> int:
    return r.zcard(SOLVE_PENDING_KEY)


def solve_running_count(r) -> int:
    return r.hlen(SOLVE_RUNNING_KEY)


def update_stats_v2(r):
    """v2方案的统计（合并handover+solve）"""
    r.hset(STATS_KEY, mapping={
        "handover_pending": handover_pending_count(r),
        "handover_running": handover_running_count(r),
        "solve_pending": solve_pending_count(r),
        "solve_running": solve_running_count(r),
        "updated_at": int(time.time()),
    })
