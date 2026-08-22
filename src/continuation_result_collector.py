"""continuation_result_collector.py — POC-2.7续传Pipe结果收集组件

从DB中收集续传结果，生成汇总报告。
复用result_collector.py的模式。

用法：
  python -m src.continuation_result_collector --batch-id p27-full
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.continuation_config import (
    CONTINUATION_RUNS_COLLECTION, CONTINUATION_RESULTS_COLLECTION,
    RESULTS_FILE, POC_2_7_DIR,
)
from src.continuation_db_schema import connect_db, insert_result
from monitoring.shared_logger import get_logger, log_event

logger = get_logger("continuation_result_collector")


def collect_batch_results(batch_id):
    """收集批次结果，生成汇总"""
    log_event(logger, "info", "collect_results", batch_id=batch_id)
    db = connect_db()

    # 从DB取所有run
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=300)
    runs = list(cursor)

    print(f"=== 续传结果收集: {batch_id} ===")
    print(f"  总run数: {len(runs)}")

    # final_status为空时按当前状态分类。window_exhausted/ai_gave_up不是永久
    # 终态，必须在汇总中可见，不能都折叠成PENDING或思维错误。
    from collections import Counter
    status_counts = Counter()
    for run in runs:
        label = run.get("final_status") or run.get("status") or "PENDING"
        status_counts[label] += 1

    print(f"\n  最终状态分布:")
    total = len(runs)
    for status, count in status_counts.most_common():
        pct = count / total * 100 if total else 0
        print(f"    {status:25s} {count:>4} ({pct:.0f}%)")

    # WP-01：这里只报告已确认完成与可继续题，不再用窗口用完比例推断
    # “思维错误”。数学真理性确认将在WP-04/05接入形式化审计。
    completed = status_counts.get("COMPLETED", 0)
    legacy_truncated = status_counts.get("TRUNCATED_AT_MAX", 0)
    window_exhausted = status_counts.get("window_exhausted", 0)
    ai_gave_up = status_counts.get("ai_gave_up", 0)
    confirmed_rate = completed / total if total else 0

    print(f"\n  当前确认/继续资格:")
    print(f"    COMPLETED={completed} / total={total} = {confirmed_rate:.1%}")
    print(f"    window_exhausted={window_exhausted}（未来可开启新窗口）")
    print(f"    ai_gave_up={ai_gave_up}（本实例放弃，题目仍可继续）")
    print(f"    legacy TRUNCATED_AT_MAX={legacy_truncated}（历史状态，可迁移继续）")
    verdict = "未确认正确的题保留继续资格；窗口用完不再作为思维错误判据"
    print(f"    说明: {verdict}")

    # 按前缀分布
    prefix_counts = Counter()
    for run in runs:
        pid = run.get("problem_id", "")
        prefix = pid.split("_")[0] if "_" in pid else pid[:8]
        prefix_counts[prefix] += 1

    print(f"\n  前缀分布:")
    for prefix, count in prefix_counts.most_common():
        print(f"    {prefix:15s} {count:>4}")

    # 保存结果到results.json（兼容batch_continue_948.py的格式）
    results = {}
    for run in runs:
        pid = run.get("problem_id", "")
        results[pid] = {
            "status": run.get("status"),
            "final_status": run.get("final_status"),
            "continuation_eligible": run.get("continuation_eligible", False),
            "next_round": run.get("next_round"),
            "round_window_history": run.get("round_window_history", []),
            "rounds": run.get("rounds_log", []),
            "final_export": run.get("proof_path"),
        }

    # 原子写入
    tmp_path = RESULTS_FILE.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    tmp_path.rename(RESULTS_FILE)
    print(f"\n  results.json已保存: {RESULTS_FILE}")

    # 生成Markdown汇总报告
    report_path = POC_2_7_DIR / f"{batch_id}_summary.md"
    with open(report_path, "w") as f:
        f.write(f"# POC-2.7续传结果汇总: {batch_id}\n\n")
        f.write(f"**生成时间**: {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write(f"## 最终状态分布\n\n")
        f.write(f"| 状态 | 题数 | 占比 |\n")
        f.write(f"|---|---|---|\n")
        for status, count in status_counts.most_common():
            pct = count / total * 100 if total else 0
            f.write(f"| {status} | {count} | {pct:.0f}% |\n")
        f.write(f"\n## 当前确认/继续资格\n\n")
        f.write(f"COMPLETED={completed} / total={total} = {confirmed_rate:.1%}\n\n")
        f.write(f"window_exhausted={window_exhausted}；ai_gave_up={ai_gave_up}；"
                f"legacy TRUNCATED_AT_MAX={legacy_truncated}\n\n")
        f.write(f"**说明**: {verdict}\n\n")
        f.write(f"## 前缀分布\n\n")
        f.write(f"| 前缀 | 题数 |\n|---|---|\n")
        for prefix, count in prefix_counts.most_common():
            f.write(f"| {prefix} | {count} |\n")

    print(f"  汇总报告已保存: {report_path}")

    log_event(logger, "info", "collect_results_done", batch_id=batch_id,
              total=total, completed=completed,
              confirmed_rate=confirmed_rate,
              window_exhausted=window_exhausted)

    return results


def main():
    parser = argparse.ArgumentParser(description="POC-2.7续传结果收集")
    parser.add_argument("--batch-id", required=True, help="批次ID")
    args = parser.parse_args()

    collect_batch_results(args.batch_id)


if __name__ == "__main__":
    main()
