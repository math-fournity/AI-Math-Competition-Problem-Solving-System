"""sop_02_alert_triage.py — SOP 步骤2：alert 分类处理

从 DB 的 p27_monitor_alerts 集合读取所有未处理 alert，
逐个分类为：代码bug / 数据问题 / 基础设施问题 / 需重跑。
分类结果为后续步骤（AI判断/修复）提供输入。

用法：
  python -m scripts.sop.sop_02_alert_triage
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import (
    check_order, advance, print_header, print_sop_doc, print_todo_directive,
)

STEP_NUM = "02"
ALERTS_COLLECTION = "p27_monitor_alerts"


def query_unresolved_alerts():
    """从 DB 查询所有未处理 alert（status != resolved）"""
    try:
        from src.continuation_db_schema import connect_db
        db = connect_db()
        aql = (
            f"FOR a IN {ALERTS_COLLECTION} "
            f"FILTER a.status != 'resolved' "
            f"SORT a.created_at DESC "
            f"LIMIT 50 "
            f"RETURN a"
        )
        cursor = db.aql.execute(aql, ttl=60)
        return list(cursor)
    except Exception as e:
        print(f"⚠️ 查询 alert 失败: {e}")
        return []


def run_alert_triage():
    """查询并展示未处理 alert"""
    alerts = query_unresolved_alerts()
    print("--- 未处理 alert 列表 ---")
    if not alerts:
        print("（无未处理 alert）")
        print()
        return

    print(f"共 {len(alerts)} 个未处理 alert：\n")
    for a in alerts:
        severity = a.get("severity", "unknown")
        alert_type = a.get("alert_type", "unknown")
        details = a.get("details", {})
        summary = details.get("summary", "") if isinstance(details, dict) else str(details)
        print(f"  [{severity}] {alert_type} (key={a.get('_key', '?')})")
        if summary:
            print(f"    摘要: {summary}")
        print()

    print("分类指引（见 SOP 文档）：")
    print("  - 代码bug（export_missing/rounds_log_integrity/...）→ 步骤04修复")
    print("  - 数据问题（proof_missing但题没做出来）→ 记录为模型能力问题")
    print("  - 基础设施问题（rate_limit/failed_connection）→ 等恢复")
    print("  - 需重跑的题 → 改 DB status 为 prepared 重新入队")
    print()


def main():
    ok, msg = check_order(STEP_NUM)
    if not ok:
        print(msg)
        sys.exit(1)

    print_header(STEP_NUM)
    print_sop_doc(STEP_NUM)
    run_alert_triage()
    advance(STEP_NUM)
    print_todo_directive(STEP_NUM)


if __name__ == "__main__":
    main()
