"""proof_audit_redis_queue.py — Pipe 5 审计 Pipe 的 Redis 队列操作封装

复用 continuation_redis_queue 的模式，用 paudit: 前缀避免与续传 Pipe 冲突。

队列结构（单队列，审计不需要双队列流水线）：
  paudit:pending   — 待审计的任务（ZSET，score=优先级）
  paudit:running   — 正在审计的任务（hash）
  paudit:completed — 已完成审计
  paudit:failed    — 审计失败
  paudit:stats     — 实时统计

用法:
  from src.proof_audit_redis_queue import get_redis, enqueue_pending, dequeue_pending
  r = get_redis()
  enqueue_pending(r, audit_run_key, priority=0)
  items = dequeue_pending(r, count=5)
"""
import json
import os
from typing import Any

from monitoring.shared_logger import get_logger, log_event
logger = get_logger("proof_audit_redis_queue")

try:
    import redis
except ImportError:
    redis = None

REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0

# 队列键前缀——env可覆盖，是全流程模拟的隔离旋钮
_QUEUE_PREFIX = os.environ.get("PAUDIT_REDIS_PREFIX", "paudit:")

PENDING_KEY = _QUEUE_PREFIX + "pending"
RUNNING_KEY = _QUEUE_PREFIX + "running"
COMPLETED_KEY = _QUEUE_PREFIX + "completed"
FAILED_KEY = _QUEUE_PREFIX + "failed"
STATS_KEY = _QUEUE_PREFIX + "stats"


def get_redis() -> "redis.Redis":
    """获取Redis连接"""
    if redis is None:
        raise ImportError("redis package not installed. Run: pip install redis")
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)


def ping() -> bool:
    try:
        return get_redis().ping()
    except Exception:
        return False


# === 队列操作 ===
# 本模块不设门闸：底层I/O封装，门闸设在调用方的语义动作上
#（proof_audit_launcher 的 @gated 函数）。

def enqueue_pending(r, audit_run_key: str, priority: int = 0) -> int:
    """入队（NX模式——只新增，不覆盖已有score）。返回1=新入队，0=已存在。"""
    log_event(logger, "debug", "enqueue_pending", audit_run_key=audit_run_key, priority=priority)
    return r.zadd(PENDING_KEY, {audit_run_key: priority}, nx=True)


def dequeue_pending(r, count: int = 1) -> list[tuple[str, int]]:
    """从pending队列原子取出（zpopmin）。"""
    results = r.zpopmin(PENDING_KEY, count)
    log_event(logger, "debug", "dequeue_pending", count=len(results))
    return [(m, int(s)) for m, s in results]


def add_running(r, audit_run_key: str, metadata: dict[str, Any]) -> int:
    """把审计run加入running hash。"""
    log_event(logger, "debug", "add_running", audit_run_key=audit_run_key)
    return r.hset(RUNNING_KEY, audit_run_key, json.dumps(metadata))


def get_running(r, audit_run_key: str) -> dict[str, Any] | None:
    val = r.hget(RUNNING_KEY, audit_run_key)
    return json.loads(val) if val else None


def get_all_running(r) -> dict[str, dict[str, Any]]:
    raw = r.hgetall(RUNNING_KEY)
    return {k: json.loads(v) for k, v in raw.items()}


def remove_running(r, audit_run_key: str) -> int:
    log_event(logger, "debug", "remove_running", audit_run_key=audit_run_key)
    return r.hdel(RUNNING_KEY, audit_run_key)


def add_completed(r, result: dict[str, Any]) -> int:
    log_event(logger, "info", "add_completed", audit_run_key=result.get("audit_run_key", ""))
    return r.lpush(COMPLETED_KEY, json.dumps(result))


def add_failed(r, result: dict[str, Any]) -> int:
    log_event(logger, "warning", "add_failed", audit_run_key=result.get("audit_run_key", ""))
    return r.lpush(FAILED_KEY, json.dumps(result))


def pending_count(r) -> int:
    return r.zcard(PENDING_KEY)


def running_count(r) -> int:
    return r.hlen(RUNNING_KEY)


def completed_count(r) -> int:
    return r.llen(COMPLETED_KEY)


def failed_count(r) -> int:
    return r.llen(FAILED_KEY)


def get_stats(r) -> dict[str, int]:
    """获取队列统计"""
    return {
        "pending": pending_count(r),
        "running": running_count(r),
        "completed": completed_count(r),
        "failed": failed_count(r),
    }
