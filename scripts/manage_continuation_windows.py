#!/usr/bin/env python3
"""列出或显式恢复未解题的新调度窗口。

默认严格dry-run，不修改DB/Redis。--apply只把选中run改为prepared并重置窗口；
实际入Redis仍运行现有continuation_feeder，经过GATE-FEED-ENQUEUE。

示例：
  python -m scripts.manage_continuation_windows --batch-id p27-full --all-eligible
  python -m scripts.manage_continuation_windows --run-key <key> --reason '用户要求继续' --apply
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.continuation_config import CONTINUATION_RUNS_COLLECTION
from src.continuation_db_schema import connect_db, insert_event, update_run
from src.observability import log_flow
from src.round_window import next_absolute_round, resume_window_fields


DEFAULT_ELIGIBLE_STATUSES = ("window_exhausted", "ai_gave_up")
LEGACY_ELIGIBLE_FINALS = ("TRUNCATED_AT_MAX", "ABANDONED", "FAILED")
ACTIVE_OR_FINAL_STATUSES = (
    "prepared", "pending", "pending_retry", "handover_pending", "running", "completed",
)


def is_default_eligible(run_doc):
    return (
        run_doc.get("final_status") in LEGACY_ELIGIBLE_FINALS
        or run_doc.get("status") in DEFAULT_ELIGIBLE_STATUSES
        or (
            run_doc.get("continuation_eligible") is True
            and run_doc.get("status") not in ACTIVE_OR_FINAL_STATUSES
            and run_doc.get("final_status") != "COMPLETED"
        )
    )


def load_candidates(db, *, run_keys, batch_id, all_eligible):
    col = db.collection(CONTINUATION_RUNS_COLLECTION)
    if run_keys:
        return [doc for key in run_keys if (doc := col.get(key))]
    if not batch_id or not all_eligible:
        raise ValueError("必须提供--run-key，或同时提供--batch-id和--all-eligible")
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        "FILTER run.batch_id == @bid "
        "FILTER run.final_status != 'COMPLETED' "
        "FILTER run.status IN @statuses OR run.final_status IN @finals "
        "   OR (run.continuation_eligible == true AND run.status NOT IN @active) "
        "SORT run.updated_at ASC RETURN run"
    )
    return list(db.aql.execute(aql, bind_vars={
        "bid": batch_id,
        "statuses": list(DEFAULT_ELIGIBLE_STATUSES),
        "finals": list(LEGACY_ELIGIBLE_FINALS),
        "active": list(ACTIVE_OR_FINAL_STATUSES),
    }, ttl=120))


def main():
    parser = argparse.ArgumentParser(
        description="续传题调度窗口查询/显式恢复（默认dry-run）")
    parser.add_argument("--run-key", action="append", default=[],
                        help="精确run key；可重复")
    parser.add_argument("--batch-id", help="批次ID")
    parser.add_argument("--all-eligible", action="store_true",
                        help="选择批次内window_exhausted/ai_gave_up/历史失败终态")
    parser.add_argument("--apply", action="store_true",
                        help="实际更新DB为prepared；不直接入Redis")
    parser.add_argument("--reason", default="", help="恢复理由；--apply时必填")
    args = parser.parse_args()

    if args.apply and not args.reason.strip():
        parser.error("--apply必须同时提供非空--reason")

    db = connect_db()
    try:
        candidates = load_candidates(
            db, run_keys=args.run_key, batch_id=args.batch_id,
            all_eligible=args.all_eligible)
    except ValueError as exc:
        parser.error(str(exc))

    print(f"=== 调度窗口候选（{'APPLY' if args.apply else 'DRY-RUN'}） ===")
    print(f"候选数: {len(candidates)}")
    changed = 0
    for run in candidates:
        key = run.get("_key", "")
        final_status = run.get("final_status")
        if final_status == "COMPLETED":
            print(f"  SKIP {key}: 已COMPLETED")
            continue
        if not is_default_eligible(run):
            print(f"  SKIP {key}: 当前状态仍在活动/待调度，或未标记继续资格")
            continue
        next_round = next_absolute_round(run)
        print(
            f"  {'RESUME' if args.apply else 'WOULD-RESUME'} {key}: "
            f"status={run.get('status')} final={final_status} next_round=R{next_round}")
        if not args.apply:
            continue
        update = resume_window_fields(run, reason=args.reason)
        update_run(db, key, update)
        insert_event(db, run.get("batch_id", ""), "continuation_window_resumed", {
            "next_round": next_round,
            "reason": args.reason,
            "previous_status": run.get("status"),
            "previous_final_status": final_status,
        }, run_key=key)
        log_flow("round_window_resumed", run_key=key,
                 pid=run.get("problem_id", ""), round=next_round,
                 reason=args.reason, batch_id=run.get("batch_id", ""))
        changed += 1

    if args.apply:
        print(f"已更新DB: {changed}条。下一步显式运行continuation_feeder入队。")
    else:
        print("dry-run完成：DB/Redis未修改。")


if __name__ == "__main__":
    main()
