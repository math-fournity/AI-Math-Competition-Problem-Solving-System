"""aggregator.py — 汇总组件

汇总所有分析结果，按维度1/维度2统计，输出JSON报告和CSV。

用法：
  python -m src.aggregator --batch-id analysis-1
  python -m src.aggregator --batch-id analysis-1 --format csv --output results.csv
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import OUTPUT_BASE
from monitoring.shared_logger import get_logger

logger = get_logger("aggregator")


def aggregate(batch_id):
    """汇总一个批次的分析结果"""
    logger.info(f"汇总开始 batch={batch_id}")
    print(f"=== 汇总结果 batch={batch_id} ===")

    collected_path = OUTPUT_BASE / batch_id / "collected_results.json"
    if not collected_path.exists():
        print(f"ERROR: collected_results.json not found at {collected_path}")
        print("请先运行 result_collector")
        return None

    with open(str(collected_path)) as f:
        data = json.load(f)

    results = data["results"]
    parsed = [r for r in results if r.get("status") == "parsed"]

    print(f"  总结果: {len(results)}")
    print(f"  成功解析: {len(parsed)}")

    if not parsed:
        print("  无可汇总结果")
        return None

    # === 维度1统计 ===
    verdicts = Counter(r.get("dimension1_verdict", "unknown") for r in parsed)
    print(f"\n  维度1（失败类型）:")
    for v, c in verdicts.most_common():
        print(f"    {v}: {c} ({c * 100 // len(parsed)}%)")

    # === 维度2统计（仅DIRECTION_ERROR和PARTIAL_PROGRESS） ===
    direction_error = [r for r in parsed if r.get("dimension1_verdict") == "DIRECTION_ERROR"]
    partial_progress = [r for r in parsed if r.get("dimension1_verdict") == "PARTIAL_PROGRESS"]
    target_problems = direction_error + partial_progress

    if target_problems:
        turning_points = Counter(r.get("dimension2_turning_point_type", "unknown") for r in target_problems)
        print(f"\n  维度2（卡点类型，{len(target_problems)}道DIRECTION_ERROR+PARTIAL_PROGRESS）:")
        for tp, c in turning_points.most_common():
            print(f"    {tp}: {c}")

    # === 按题库分布 ===
    # 从problem_id前缀推断题库
    import re
    by_source = Counter()
    for r in parsed:
        pid = r.get("problem_id", "")
        m = re.match(r"^([a-z_]+)", pid)
        prefix = m.group(1) if m else "unknown"
        by_source[prefix] += 1

    print(f"\n  按题库分布:")
    for src, c in by_source.most_common():
        print(f"    {src}: {c}")

    # === 交叉表：维度1 × 维度2 ===
    if target_problems:
        print(f"\n  交叉表（维度1 × 维度2）:")
        cross = Counter()
        for r in target_problems:
            v1 = r.get("dimension1_verdict", "unknown")
            v2 = r.get("dimension2_turning_point_type", "unknown")
            cross[(v1, v2)] += 1

        for (v1, v2), c in cross.most_common():
            print(f"    {v1} × {v2}: {c}")

    # === 信心度统计 ===
    confidence = Counter(r.get("confidence", "unknown") for r in parsed)
    print(f"\n  信心度:")
    for conf, c in confidence.most_common():
        print(f"    {conf}: {c}")

    # === 保存汇总报告 ===
    report = {
        "batch_id": batch_id,
        "total": len(results),
        "parsed": len(parsed),
        "dimension1_distribution": dict(verdicts),
        "dimension2_distribution": dict(turning_points) if target_problems else {},
        "by_source": dict(by_source),
        "cross_table": {f"{v1}×{v2}": c for (v1, v2), c in cross.items()} if target_problems else {},
        "confidence_distribution": dict(confidence),
        "direction_error_problems": [
            r["problem_id"] for r in direction_error
        ],
        "partial_progress_problems": [
            r["problem_id"] for r in partial_progress
        ],
    }

    report_path = OUTPUT_BASE / batch_id / "aggregated_report.json"
    with open(str(report_path), "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  报告保存到: {report_path}")

    # === 保存CSV ===
    csv_path = OUTPUT_BASE / batch_id / "results.csv"
    with open(str(csv_path), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "problem_id", "dimension1_verdict", "dimension1_explanation",
            "dimension2_turning_point_type", "dimension2_explanation",
            "ai_direction_summary", "standard_solution_key_technique",
            "confidence", "status",
        ])
        writer.writeheader()
        for r in parsed:
            writer.writerow({k: r.get(k, "") for k in writer.fieldnames})
    print(f"  CSV保存到: {csv_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="汇总分析结果")
    parser.add_argument("--batch-id", required=True, help="批次ID")
    args = parser.parse_args()

    aggregate(args.batch_id)


if __name__ == "__main__":
    main()
