"""fix_wp_p_running_status.py — WP-P 任务2：修正 5 个"实际已完成但 DB 显示 running"的审计 run

背景：2026-08-21 07:51-07:56 启动的 5 个审计 devin cli 已全部完成（DONE.md 存在 +
export 有实质内容），但 launcher 在它们完成前被 kill，DB status 停留在 running。
result_collector 的候选条件是 status=='completed' AND audit_status==null——必须先修
status 才能被收集。

直接检查原则：每条先亲眼验证 DONE.md 存在且 conversation.json size>1000，
任一不成立则跳过该条（不盲改 DB）。

用法：
  python scripts/fix_wp_p_running_status.py --dry-run   # 只打印计划
  python scripts/fix_wp_p_running_status.py             # 真跑
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.continuation_config import D_TRAJ_DIR
from src.proof_audit_db_schema import connect_db, update_audit_run, get_audit_run

AUDIT_TRAJ_BASE = D_TRAJ_DIR / "p27-proof-audit"
MIN_EXPORT_SIZE = 1000

# WP-P §3 基线表列出的 5 个 audit_run_key
TARGET_KEYS = [
    "paudit-p27-full-deepmath_103k_00000036",
    "paudit-p27-full-deepmath_103k_00000174",
    "paudit-p27-full-deepmath_103k_00000521",
    "paudit-p27-full-deepmath_103k_00000550",
    "paudit-p27-full-deepmath_103k_00000571",
]


def utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def verify_on_disk(audit_run_key):
    """直接检查：DONE.md 存在 且 conversation.json 存在且 size>1000。返回 (ok, 说明)"""
    export_dir = AUDIT_TRAJ_BASE / audit_run_key / "exports"
    done = export_dir / "DONE.md"
    conv = export_dir / "conversation.json"
    if not done.exists():
        return False, f"DONE.md 缺失: {done}"
    if not conv.exists():
        return False, f"conversation.json 缺失: {conv}"
    size = conv.stat().st_size
    if size <= MIN_EXPORT_SIZE:
        return False, f"conversation.json 过小({size}B <= {MIN_EXPORT_SIZE}B)"
    return True, f"DONE.md✅ export={size}B"


def main():
    parser = argparse.ArgumentParser(description="WP-P: 修正 5 个 running 审计 run 的 status")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不改 DB")
    args = parser.parse_args()

    mode = "DRY-RUN" if args.dry_run else "REAL"
    print(f"=== fix_wp_p_running_status [{mode}] ===")

    db = connect_db()
    fixed, skipped = 0, 0

    for key in TARGET_KEYS:
        doc = get_audit_run(db, key)
        if not doc:
            print(f"  [skip] {key}: DB 无记录")
            skipped += 1
            continue
        db_status = doc.get("status")
        ok, reason = verify_on_disk(key)
        if not ok:
            print(f"  [skip] {key}: 直接检查失败（DB status={db_status}）—— {reason}")
            skipped += 1
            continue
        if db_status == "completed":
            print(f"  [noop] {key}: DB 已是 completed，无需修改（磁盘: {reason}）")
            continue
        print(f"  [fix]  {key}: running → completed（磁盘证据: {reason}）")
        if not args.dry_run:
            update_audit_run(db, key, {"status": "completed", "ended_at": utc_now()})
            after = get_audit_run(db, key)
            print(f"         改后复核: status={after.get('status')}, ended_at={after.get('ended_at', '')[:19]}")
        fixed += 1

    print(f"\n=== 完成 [{mode}] === fixed(或计划fix)={fixed}, skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
