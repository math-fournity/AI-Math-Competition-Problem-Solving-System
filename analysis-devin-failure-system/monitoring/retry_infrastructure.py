#!/usr/bin/env python3
"""retry_infrastructure.py — 基础设施失败自动重试

扫描failed队列中的基础设施失败（rate_limited/failed_connection/dead_session/launch_error），
将它们重新入pending队列，让launcher重新启动。

模型能力失败（timeout/stall/no_xml/incomplete）不重试——
它们是分析产出数据，记录失败原因即可。

模仿solver_harness的retry_infrastructure.py。

用法:
  python -m monitoring.retry_infrastructure --once          # 执行一次后退出
  python -m monitoring.retry_infrastructure --dry-run       # 只看不执行
  python -m monitoring.retry_infrastructure --max-retries 3 # 默认3次
  python -m monitoring.retry_infrastructure --interval 120  # 循环模式间隔秒数
"""
import sys
import os
import time
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import (
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    OUTPUT_BASE, INFRA_FAILURES, MODEL_FAILURES, MAX_RETRIES,
)
from src.db_schema import connect_db, insert_event, update_run, ANALYSIS_RUNS_COLLECTION
from monitoring.redis_queue import get_redis, ping
from monitoring.shared_logger import get_logger

logger = get_logger("retry")


def get_retry_count(db, run_key: str) -> int:
    """查DB中该run已有的基础设施失败重试次数"""
    aql = (
        f"FOR r IN {ANALYSIS_RUNS_COLLECTION} "
        f"FILTER r._key == '{run_key}' "
        f"FILTER r.status IN {list(INFRA_FAILURES)!r} "
        f"COLLECT WITH COUNT INTO c RETURN c"
    )
    cursor = db.aql.execute(aql, ttl=60)
    return cursor.next()


def retry_failed(r, db, max_retries: int, dry_run: bool = False) -> dict:
    """扫描Redis failed队列，重试基础设施失败"""
    failed_items = r.lrange("analysis:failed", 0, -1)
    logger.info(f"扫描failed队列: {len(failed_items)}项, max_retries={max_retries}, dry_run={dry_run}")

    infra_count = 0
    model_count = 0
    retried = 0
    skipped_max_retries = 0
    retry_items = []  # 需要重新入pending的项

    for item in failed_items:
        data = json.loads(item)
        reason = data.get("reason", "")
        run_key = data.get("run_key", "")
        failure_type = data.get("failure_type", "")

        # 判断是否为基础设施失败
        is_infra = reason in INFRA_FAILURES or failure_type == "infra"

        if is_infra:
            infra_count += 1
            # 检查重试次数
            retry_count = get_retry_count(db, run_key)
            if retry_count >= max_retries:
                skipped_max_retries += 1
                logger.warning(f"跳过 {run_key}: 已重试{retry_count}次, 达到上限{max_retries}")
                continue

            if dry_run:
                logger.info(f"[DRY-RUN] 重试 {run_key}: {reason} (第{retry_count+1}次)")
                retried += 1
            else:
                # 收集需要重试的项
                retry_items.append((run_key, data, reason, retry_count))
                retried += 1
        else:
            model_count += 1
            logger.debug(f"模型能力失败, 不重试: {run_key} reason={reason}")

    # 执行重试
    if not dry_run and retry_items:
        # 从failed队列中移除已重试的项
        remaining = []
        retry_run_keys = {rk for rk, _, _, _ in retry_items}
        for item in failed_items:
            data = json.loads(item)
            if data.get("run_key") in retry_run_keys and data.get("reason") in INFRA_FAILURES:
                # 检查是否达到上限
                rk = data.get("run_key")
                rc = get_retry_count(db, rk)
                if rc < max_retries:
                    continue  # 移除已重试项
            remaining.append(item)
        r.delete("analysis:failed")
        if remaining:
            r.rpush("analysis:failed", *remaining)

        # 重新入pending队列 + 更新DB
        for run_key, data, reason, retry_count in retry_items:
            # 重新入pending队列
            r.zadd("analysis:pending", {run_key: 0})
            # 更新DB中run状态为pending
            try:
                from src.db_schema import update_run
                from datetime import datetime, timezone
                now_iso = datetime.now(timezone.utc).isoformat()
                update_run(db, run_key, {
                    "status": "pending_retry",
                    "updated_at": now_iso,
                    "end_reason": f"retry_after_{reason}",
                    "verdict": {"auto_status": "pending_retry", "reason": f"retry_after_{reason}",
                                "confidence": "n/a", "needs_human_review": False},
                })
                insert_event(db, data.get("batch_id", ""), "retry_scheduled", {
                    "run_key": run_key,
                    "original_reason": reason,
                    "retry_count": retry_count + 1,
                })
            except Exception as e:
                logger.error(f"DB更新失败: {run_key} error={e}")
            logger.info(f"重试 {run_key}: {reason} -> pending (第{retry_count+1}次)")

    result = {
        "total_failed": len(failed_items),
        "infra_failures": infra_count,
        "model_failures": model_count,
        "retried": retried,
        "skipped_max_retries": skipped_max_retries,
    }
    logger.info(f"完成: total={result['total_failed']} infra={infra_count} "
                f"model={model_count} retried={retried} skipped={skipped_max_retries}")
    return result


def main():
    parser = argparse.ArgumentParser(description="基础设施失败自动重试")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES, help="最大重试次数")
    parser.add_argument("--dry-run", action="store_true", help="只看不执行")
    parser.add_argument("--once", action="store_true", help="执行一次后退出（默认循环）")
    parser.add_argument("--interval", type=int, default=120, help="循环模式间隔秒数")
    args = parser.parse_args()

    if not ping():
        logger.error("Redis连接失败")
        sys.exit(1)
    logger.info("Redis连接成功")

    db = connect_db()
    logger.info("ArangoDB连接成功")
    r = get_redis()

    def run_once():
        logger.info("=== 扫描failed队列 ===")
        result = retry_failed(r, db, args.max_retries, args.dry_run)
        print(f"=== 重试扫描完成 ===")
        print(f"  总failed:        {result['total_failed']}")
        print(f"  基础设施失败:    {result['infra_failures']}")
        print(f"  模型能力失败:    {result['model_failures']} (不重试)")
        print(f"  已重试:          {result['retried']}")
        print(f"  达到上限跳过:    {result['skipped_max_retries']}")
        return result

    if args.once:
        run_once()
        return

    # 循环模式
    print(f"循环模式: 每{args.interval}秒扫描一次, Ctrl+C退出")
    while True:
        try:
            run_once()
        except Exception as e:
            logger.error(f"Retry轮次失败: {e}", exc_info=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
