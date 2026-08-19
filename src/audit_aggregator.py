"""audit_aggregator.py — Pipe 2审计汇总组件

从audit_results集合汇总审计结果，产出audit_summary.md。

用法：
  python -m src.audit_aggregator --batch-id audit-1
"""

import argparse
import json
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import OUTPUT_BASE
from src.db_schema import connect_db
from src.audit_collector import AUDIT_BATCHES_COLLECTION, AUDIT_RESULTS_COLLECTION
from monitoring.shared_logger import get_logger

logger = get_logger("audit_aggregator")


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def aggregate(batch_id):
    """汇总审计结果，产出audit_summary.md"""
    logger.info(f"审计汇总开始 batch={batch_id}")
    print(f"=== 审计汇总 batch={batch_id} ===")

    db = connect_db()

    # 读取所有审计结果
    aql = f"FOR r IN {AUDIT_RESULTS_COLLECTION} FILTER r.batch_id == @bid RETURN r"
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=120)
    results = list(cursor)
    print(f"  审计结果总数: {len(results)}")

    if not results:
        print("  无审计结果，跳过汇总")
        return

    # 1. 审计状态分布
    status_counts = Counter(r.get("audit_status", "UNKNOWN") for r in results)
    print(f"  审计状态分布:")
    for status, count in status_counts.most_common():
        print(f"    {status}: {count}")

    # 2. 各检查项的通过率
    check_pass = Counter()
    check_fail = Counter()
    for r in results:
        checks = r.get("check_results", {})
        for check_id, value in checks.items():
            if isinstance(value, str):
                if value.startswith("PASS"):
                    check_pass[check_id] += 1
                elif value.startswith("FAIL"):
                    check_fail[check_id] += 1

    all_check_ids = sorted(set(list(check_pass.keys()) + list(check_fail.keys())))
    print(f"  各检查项通过率:")
    for check_id in all_check_ids:
        p = check_pass.get(check_id, 0)
        f = check_fail.get(check_id, 0)
        total = p + f
        rate = 100 * p / total if total > 0 else 0
        print(f"    {check_id}: {p}/{total} ({rate:.1f}%)")

    # 3. 选题池大小
    selectable = sum(1 for r in results if r.get("audit_status") == "PASS_SELECTABLE")
    pass_count = sum(1 for r in results if r.get("audit_status") == "PASS")
    not_selectable = sum(1 for r in results if r.get("audit_status") == "PASS_NOT_SELECTABLE")
    print(f"  选题池:")
    print(f"    PASS_SELECTABLE: {selectable}")
    print(f"    PASS: {pass_count}")
    print(f"    PASS_NOT_SELECTABLE: {not_selectable}")
    print(f"    总可选题池: {selectable + pass_count}")

    # 4. 主要问题分布
    issues = Counter()
    for r in results:
        issues_str = r.get("issues_found", "")
        if issues_str and issues_str.lower() != "none":
            for issue in issues_str.split(","):
                issue = issue.strip()
                if issue:
                    issues[issue] += 1
    print(f"  主要问题:")
    for issue, count in issues.most_common(10):
        print(f"    {issue}: {count}")

    # 5. 产出audit_summary.md
    summary_path = OUTPUT_BASE / batch_id / "audit_summary.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# 审计汇总报告 — batch={batch_id}",
        "",
        f"> 生成时间: {_utc_now()}",
        f"> 审计结果总数: {len(results)}",
        "",
        "## 1. 审计状态分布",
        "",
        "| 审计状态 | 数量 | 占比 | 说明 |",
        "|---|---|---|---|",
    ]
    status_desc = {
        "PASS": "通过（A-C全通过）",
        "PASS_SELECTABLE": "通过且可选题（d1=DE + D1-D4通过）",
        "PASS_NOT_SELECTABLE": "通过但不可操作（D1-D4不通过）",
        "FAIL_PARSE_ERROR": "解析失败（d1=null或非法）",
        "FAIL_INCOMPLETE": "不完整（A2-A6任一不通过）",
        "FAIL_CONTENT_CORRUPT": "内容损坏（XML泄漏/占位符泄漏）",
        "FAIL_INCONSISTENT": "不一致（C1-C3任一不通过）",
        "PARSE_FAILED": "XML提取失败",
        "UNKNOWN": "未知状态",
    }
    for status, count in status_counts.most_common():
        pct = 100 * count / len(results)
        desc = status_desc.get(status, "")
        lines.append(f"| {status} | {count} | {pct:.1f}% | {desc} |")

    lines.extend([
        "",
        "## 2. 各检查项通过率",
        "",
        "| 检查项 | PASS | FAIL | 通过率 |",
        "|---|---|---|---|",
    ])
    for check_id in all_check_ids:
        p = check_pass.get(check_id, 0)
        f = check_fail.get(check_id, 0)
        total = p + f
        rate = 100 * p / total if total > 0 else 0
        lines.append(f"| {check_id} | {p} | {f} | {rate:.1f}% |")

    lines.extend([
        "",
        "## 3. 选题池大小",
        "",
        f"- **PASS_SELECTABLE**（优先选题）: {selectable}",
        f"- **PASS**（可进入选题）: {pass_count}",
        f"- **PASS_NOT_SELECTABLE**（通过但不可操作）: {not_selectable}",
        f"- **总可选题池**: {selectable + pass_count}",
        f"- **不通过**: {sum(status_counts[s] for s in status_counts if s.startswith('FAIL'))}",
        "",
        "## 4. 主要问题分布",
        "",
        "| 问题 | 数量 |",
        "|---|---|",
    ])
    for issue, count in issues.most_common(10):
        lines.append(f"| {issue} | {count} |")

    lines.extend([
        "",
        "## 5. 结论",
        "",
    ])
    total_pass = pass_count + selectable + not_selectable
    pass_rate = 100 * total_pass / len(results) if results else 0
    lines.append(f"- 审计通过率: {total_pass}/{len(results)} ({pass_rate:.1f}%)")
    lines.append(f"- 可选题池: {selectable + pass_count}题")
    if pass_rate > 80:
        lines.append("- 审计通过率>80%，整体质量可信，可进入Pipe 3选题阶段")
    else:
        lines.append("- ⚠️ 审计通过率<80%，需要分析常见问题并修正后再选题")

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  汇总报告保存到: {summary_path}")

    # 更新batch记录
    try:
        db.collection(AUDIT_BATCHES_COLLECTION).update({
            "_key": batch_id,
            "status": "aggregated",
            "updated_at": _utc_now(),
            "pass_rate": pass_rate,
            "selectable_count": selectable + pass_count,
        })
    except Exception:
        pass

    logger.info(f"审计汇总完成: pass_rate={pass_rate:.1f}%, selectable={selectable + pass_count}")
    return pass_rate


def main():
    parser = argparse.ArgumentParser(description="Pipe 2审计汇总")
    parser.add_argument("--batch-id", required=True, help="审计批次ID")
    args = parser.parse_args()

    aggregate(args.batch_id)


if __name__ == "__main__":
    main()
