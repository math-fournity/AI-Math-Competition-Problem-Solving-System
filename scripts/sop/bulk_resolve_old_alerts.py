#!/usr/bin/env python3
"""bulk_resolve_old_alerts.py — 批量 resolve 旧格式 alert（去重修复部署前创建的）。

按前一个 Master Agent 的计划：
- 只 resolve created_at < 部署时间的未处理 alert（旧随机后缀 key 格式）
- 排除 ai_review_sample（待 SOP_04 AI 判断）
- 保留新格式 alert（去重修复后创建的，代表真实当前未处理问题）
- 加 resolution_note 字段记录批量 resolve 原因

用法：
  python -m scripts.sop.bulk_resolve_old_alerts --dry-run   # 预览不执行
  python -m scripts.sop.bulk_resolve_old_alerts             # 执行
  python -m scripts.sop.bulk_resolve_old_alerts --cutoff "2026-08-21T06:20:00+00:00"
"""
import argparse
import os
import sys
from datetime import datetime, timezone

# 项目根目录加入 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def main():
    parser = argparse.ArgumentParser(description="批量 resolve 旧格式 alert")
    parser.add_argument("--dry-run", action="store_true", help="只统计不执行")
    parser.add_argument(
        "--cutoff",
        default="2026-08-21T06:20:00+00:00",
        help="resolve 此时间之前创建的 alert（ISO 格式，默认去重修复部署时间）",
    )
    args = parser.parse_args()

    from arango import ArangoClient
    from src.continuation_config import MONITOR_ALERTS_COLLECTION

    host = os.environ.get("ARANGO_HOST", "http://localhost:8529")
    db_name = os.environ.get("ARANGO_DB", "xishujuzhen_math_glm52")
    user = os.environ.get("ARANGO_USER", "root")
    password = os.environ.get("ARANGO_PASS", "") or os.environ.get("ARANGO_PASSWORD", "")

    client = ArangoClient(hosts=host)
    db = client.db(db_name, username=user, password=password)
    col = db.collection(MONITOR_ALERTS_COLLECTION)

    now = datetime.now(timezone.utc).isoformat()
    cutoff = args.cutoff

    # 统计：按 type 分布
    stat_aql = (
        f"FOR a IN {MONITOR_ALERTS_COLLECTION} "
        f"FILTER a.status != 'resolved' "
        f"FILTER a.alert_type != 'ai_review_sample' "
        f"FILTER a.created_at < @cutoff "
        f"COLLECT t = a.alert_type WITH COUNT INTO n "
        f"SORT n DESC RETURN {{type: t, count: n}}"
    )
    stats = list(db.aql.execute(stat_aql, bind_vars={"cutoff": cutoff}, ttl=120))
    total = sum(s["count"] for s in stats)
    print(f"=== 旧格式未处理 alert（created_at < {cutoff}，排除 ai_review_sample）===")
    for s in stats:
        print(f"  {s['type']}: {s['count']}")
    print(f"  总计: {total}")

    if total == 0:
        print("无需 resolve，退出。")
        return

    if args.dry_run:
        print("\n[dry-run] 未执行 resolve。去掉 --dry-run 执行。")
        return

    # 执行批量 resolve
    print(f"\n执行批量 resolve（resolution_note 记录原因）...")
    resolve_aql = (
        f"FOR a IN {MONITOR_ALERTS_COLLECTION} "
        f"FILTER a.status != 'resolved' "
        f"FILTER a.alert_type != 'ai_review_sample' "
        f"FILTER a.created_at < @cutoff "
        f"UPDATE a WITH {{"
        f"  status: 'resolved', "
        f"  resolved_at: @now, "
        f"  resolution_note: '2026-08-21 SOP_03分诊后批量resolve：旧格式重复alert，去重修复已部署（commit 7d4addc），新格式alert代表真实当前问题'"
        f"}} IN {MONITOR_ALERTS_COLLECTION} "
        f"RETURN OLD._key"
    )
    resolved_keys = list(
        db.aql.execute(resolve_aql, bind_vars={"cutoff": cutoff, "now": now}, ttl=300)
    )
    print(f"✅ 已 resolve {len(resolved_keys)} 条旧格式 alert")

    # 验证：剩余未处理 alert
    remain_aql = (
        f"RETURN COUNT(FOR a IN {MONITOR_ALERTS_COLLECTION} "
        f"FILTER a.status != 'resolved' RETURN 1)"
    )
    remain = list(db.aql.execute(remain_aql))[0]
    print(f"剩余未处理 alert: {remain}（应为新格式 ~256 条 + ai_review_sample ~20 条）")


if __name__ == "__main__":
    main()
