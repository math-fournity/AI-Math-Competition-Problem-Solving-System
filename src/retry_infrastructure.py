"""retry_infrastructure.py — 基础设施失败自动重试（续传+审计双队列共用）

移植平凡解题系统 retry_infrastructure.py 模式（WP-L），适配本 repo 双队列：
  续传：p27:failed（list，条目 {"run_key","reason"}）→ 重入 p27:pending
  审计：paudit:failed（list，条目 {"audit_run_key","reason"}）→ 重入 paudit:pending

规则（确定性，适度依赖边界的代码侧）：
  reason 经 legacy 映射 + classify_failure 分类后：
    infra 类 且 retry_count < MAX_RETRIES(3) → 状态回 prepared + 重入 pending
      （priority=9999 排队尾——重试不插队）+ 从 failed 移除
    model 类 → 不动（留存是 Profile 数据）
    infra 但计数超限 → 留在 failed（skipped_max）

⚠️ 运行模式边界（用户决策点）：本模块默认只跑一次；--dry-run 全程零写入；
   --interval 循环模式已实现但**常驻化需用户批准 dry-run 分布报告后另行决定**。

用法：
  python -m src.retry_infrastructure --pipe both --dry-run   # 只读盘点（推荐首步）
  python -m src.retry_infrastructure --pipe both             # 单次实跑
  python -m src.retry_infrastructure --pipe continuation --interval 300  # 循环（需批准）
"""
import argparse
import json
import time

from monitoring.shared_logger import get_logger, log_event

logger = get_logger("retry_infrastructure")

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.devin_cli_failure_detection import (
    classify_failure, INFRA_FAILURES, MAX_RETRIES,
)

# legacy reason 映射——历史数据（WP-J 改名前）的 reason 词到现行分类词
LEGACY_REASON_MAP = {
    "stall": "failed_stall",
    "stall_timeout": "max_runtime_exceeded",
    "timeout": "failed_timeout",
}


def normalize_reason(reason):
    """legacy reason → 现行分类词。未知词原样返回（classify 兜底为 model）。"""
    return LEGACY_REASON_MAP.get(reason, reason)


def _parse_failed_items(raw_items, key_field):
    """解析 failed 队列原始字符串 → [(原始串, key, normalized_reason)]"""
    out = []
    for raw in raw_items:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("failed 条目非法 JSON，跳过: %s", str(raw)[:100])
            continue
        key = data.get(key_field, "")
        reason = normalize_reason(data.get("reason", ""))
        out.append((raw, key, reason))
    return out


def _process_queue(r, db, *, queue_key, pending_key, collection,
                   key_field, extra_check, max_retries, dry_run):
    """通用处理：扫描 failed → 分类 → infra 计数<上限则重入。返回统计 dict。

    extra_check(key, doc) -> str|None：重试前的附加校验（如审计的 proof.txt 存在性），
    返回非空字符串表示放弃重试的原因。
    """
    raw_items = r.lrange(queue_key, 0, -1)
    parsed = _parse_failed_items(raw_items, key_field)

    stats = {"total": len(parsed), "infra": 0, "model": 0,
             "retried": 0, "skipped_max": 0, "extra_skip": 0}
    model_dist = {}
    plan = []
    retried_raws = []

    for raw, key, reason in parsed:
        category = classify_failure(reason)
        if category != "infra":
            stats["model"] += 1
            model_dist[reason] = model_dist.get(reason, 0) + 1
            continue  # model 类不动（Profile 数据）

        stats["infra"] += 1
        doc = db.collection(collection).get(key)
        if not doc:
            stats["extra_skip"] += 1
            plan.append(f"[skip] {key}: DB 无记录")
            continue
        retry_count = doc.get("retry_count", 0)
        if retry_count >= max_retries:
            stats["skipped_max"] += 1
            plan.append(f"[skip-max] {key}: 已重试 {retry_count} 次 ≥ 上限 {max_retries}")
            continue

        if extra_check:
            block_reason = extra_check(key, doc)
            if block_reason:
                stats["extra_skip"] += 1
                plan.append(f"[skip] {key}: {block_reason}")
                continue

        if dry_run:
            plan.append(f"[dry-run 将重试] {key}: {reason}（第 {retry_count+1} 次）")
        else:
            db.collection(collection).update({
                "_key": key,
                "status": "prepared",
                "retry_count": retry_count + 1,
                "updated_at": datetime_utc(),
            })
            r.zadd(pending_key, {key: 9999})  # 排队尾——重试不插队
            retried_raws.append(raw)
            plan.append(f"[retried] {key}: {reason} → prepared（第 {retry_count+1} 次）")
        stats["retried"] += 1

    # 队列重建：仅移除已重试条目（real 模式）；dry-run 不动队列
    if not dry_run and retried_raws:
        for raw in retried_raws:
            r.lrem(queue_key, 0, raw)

    stats["model_dist"] = model_dist
    stats["plan"] = plan
    return stats


def datetime_utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def retry_continuation(r, db, max_retries=MAX_RETRIES, dry_run=True):
    return _process_queue(
        r, db, queue_key="p27:failed", pending_key="p27:pending",
        collection="p27_continuation_runs", key_field="run_key",
        extra_check=None, max_retries=max_retries, dry_run=dry_run)


def retry_audit(r, db, max_retries=MAX_RETRIES, dry_run=True):
    """审计重试：不做 work_dir 重建（proof.txt/AGENTS.md 已在——031 设计），
    但重试前检查 proof.txt 仍存在（不存在则报告数据问题不重试）。"""

    def extra_check(key, doc):
        wd = doc.get("work_dir")
        if wd and not (Path(wd) / "proof.txt").exists():
            return f"proof.txt 缺失（work_dir={wd}）——数据问题待人工"
        return None

    return _process_queue(
        r, db, queue_key="paudit:failed", pending_key="paudit:pending",
        collection="p27_proof_audit_runs", key_field="audit_run_key",
        extra_check=extra_check, max_retries=max_retries, dry_run=dry_run)


def print_stats(label, s):
    print(f"\n=== {label} ===")
    print(f"  failed 总数: {s['total']}")
    print(f"  infra（可重试类）: {s['infra']}")
    print(f"  model（不重试，留存数据）: {s['model']}")
    if s["model_dist"]:
        print(f"  model 分布: {s['model_dist']}")
    print(f"  本次重试{'计划' if DRY_RUN else ''}: {s['retried']}")
    print(f"  跳过（超上限 {MAX_RETRIES} 次）: {s['skipped_max']}")
    if s["extra_skip"]:
        print(f"  附加校验跳过: {s['extra_skip']}")
    for line in s["plan"]:
        print(f"    {line}")


DRY_RUN = True


def run_once(pipe, dry_run):
    from src.continuation_redis_queue import get_redis as get_r
    from src.proof_audit_redis_queue import get_redis as get_a
    from src.continuation_db_schema import connect_db as connect_c
    from src.proof_audit_db_schema import connect_db as connect_a

    rc = get_r()
    ra = get_a()
    dbc = connect_c()
    dba = connect_a()

    results = {}
    if pipe in ("continuation", "both"):
        results["continuation"] = retry_continuation(rc, dbc, dry_run=dry_run)
        print_stats("续传 p27:failed", results["continuation"])
    if pipe in ("audit", "both"):
        results["audit"] = retry_audit(ra, dba, dry_run=dry_run)
        print_stats("审计 paudit:failed", results["audit"])
    return results


def main():
    global DRY_RUN
    import argparse
    ap = argparse.ArgumentParser(description="基础设施失败自动重试（双队列）")
    ap.add_argument("--pipe", choices=["continuation", "audit", "both"], default="both")
    ap.add_argument("--dry-run", action="store_true",
                    help="只读盘点——零写入（推荐首步）")
    ap.add_argument("--once", action="store_true",
                    help="执行一次后退出（与默认行为相同，显式声明用）")
    ap.add_argument("--interval", type=int, default=0,
                    help="循环模式间隔秒数（⚠️ 常驻化需用户批准 dry-run 报告后启用）")
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    from monitoring.graceful_shutdown import register_shutdown, should_stop
    register_shutdown("retry_infrastructure")

    if args.interval > 0:
        logger.warning("循环模式启动（间隔 %ss）——注意：常驻化需用户批准", args.interval)
        while not should_stop():
            run_once(args.pipe, dry_run=args.dry_run)
            time.sleep(args.interval)
    else:
        run_once(args.pipe, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
