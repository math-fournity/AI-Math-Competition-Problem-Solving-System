"""audit_collector.py — Pipe 2审计数据收集组件

从analysis_results集合读取Pipe 1的分析结果，去重，构造审计用的AGENTS.md。

与data_collector.py的区别：
  - data_collector从devin_problem_runs+题库+trajectory收集数据（读原题/标准解答/thinking）
  - audit_collector从analysis_results集合读取已分析结果（不读原题/标准解答/thinking）

去重规则（方案§八.1）：
  同一problem_id多条结果时，保留优先级：
    1. confidence=high
    2. 7个字段非空数最多的
    3. 最新时间

用法：
  python -m src.audit_collector --batch-id audit-1 --limit 100
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import (
    ANALYSIS_SOLVER_BASE, OUTPUT_BASE,
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
)
from src.db_schema import connect_db, ensure_schema
from monitoring.shared_logger import get_logger

logger = get_logger("audit_collector")

# 审计模板
AUDIT_TEMPLATE = Path(__file__).parent.parent / "templates" / "audit_agents_md.md"

# 审计用的DB集合名（在db_schema.py中定义）
AUDIT_BATCHES_COLLECTION = "audit_batches"
AUDIT_RUNS_COLLECTION = "audit_runs"
AUDIT_RESULTS_COLLECTION = "audit_results"

# Pipe 1结果中的7个关键字段（用于去重时的字段完整性评分）
KEY_FIELDS = [
    "dimension1_verdict",
    "dimension1_explanation",
    "dimension2_turning_point_type",
    "dimension2_explanation",
    "ai_direction_summary",
    "standard_solution_key_technique",
    "confidence",
]


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_analysis_results(limit=None):
    """从analysis_results集合读取所有Pipe 1结果，去重

    去重规则：
      1. confidence=high优先
      2. 同confidence中，7个字段非空数最多的
      3. 同字段完整度中，最新时间

    Returns:
      (kept_results, dedup_info)
      kept_results: 去重后保留的结果列表
      dedup_info: {"total": N, "deduped": M, "kept": K}
    """
    db = connect_db()
    aql = "FOR r IN analysis_results RETURN r"
    all_results = list(db.aql.execute(aql, ttl=120))
    total = len(all_results)
    logger.info(f"从analysis_results读取{total}条")

    # 按problem_id分组
    by_pid = {}
    for r in all_results:
        pid = r.get("problem_id", "")
        if pid not in by_pid:
            by_pid[pid] = []
        by_pid[pid].append(r)

    # 去重
    kept = []
    deduped_count = 0
    for pid, results in by_pid.items():
        if len(results) == 1:
            kept.append(results[0])
            continue

        # 多条结果——按优先级排序
        def score(r):
            """返回排序key: (confidence_high, field_completeness, timestamp)"""
            conf = 1 if r.get("confidence") == "high" else 0
            completeness = sum(1 for f in KEY_FIELDS if r.get(f) and str(r.get(f)).strip())
            ts = r.get("analyzed_at", r.get("created_at", ""))
            return (conf, completeness, ts)

        results_sorted = sorted(results, key=score, reverse=True)
        kept.append(results_sorted[0])
        deduped_count += len(results) - 1

    if limit:
        kept = kept[:limit]

    dedup_info = {"total": total, "deduped": deduped_count, "kept": len(kept)}
    logger.info(f"去重: total={total}, deduped={deduped_count}, kept={len(kept)}")
    return kept, dedup_info


def format_analysis_result_text(result):
    """把Pipe 1的分析结果格式化为文本，填入审计prompt

    审计AI只看到Pipe 1的分析结果文本，不看到原题/标准解答/thinking。
    """
    fields = [
        ("problem_id", result.get("problem_id", "")),
        ("dimension1_verdict", result.get("dimension1_verdict") or "[null]"),
        ("dimension1_explanation", result.get("dimension1_explanation") or "[null]"),
        ("dimension2_turning_point_type", result.get("dimension2_turning_point_type") or "[null]"),
        ("dimension2_explanation", result.get("dimension2_explanation") or "[null]"),
        ("ai_direction_summary", result.get("ai_direction_summary") or "[null]"),
        ("standard_solution_key_technique", result.get("standard_solution_key_technique") or "[null]"),
        ("confidence", result.get("confidence") or "[null]"),
    ]
    lines = []
    for name, value in fields:
        lines.append(f"  {name}: {value}")
    return "\n".join(lines)


def build_audit_agents_md(analysis_result_key, problem_id, result):
    """构造审计用的AGENTS.md

    用手动替换而非str.format——分析结果文本中可能包含花括号。
    """
    template = AUDIT_TEMPLATE.read_text(encoding="utf-8")
    result_text = format_analysis_result_text(result)
    # 替换占位符
    out = template.replace("{analysis_result_key}", str(analysis_result_key))
    out = out.replace("{problem_id}", str(problem_id))
    out = out.replace("{analysis_result_text}", result_text)
    return out


def collect_and_prepare_audit(batch_id, limit=None):
    """收集Pipe 1结果，去重，构造审计AGENTS.md，写入工作目录"""
    logger.info(f"审计数据收集开始 batch={batch_id} limit={limit}")
    print(f"=== 审计数据收集 batch={batch_id} ===")

    # 1. 读取Pipe 1结果并去重
    print("  读取Pipe 1分析结果并去重...")
    results, dedup_info = get_analysis_results(limit=limit)
    print(f"  去重结果: total={dedup_info['total']}, deduped={dedup_info['deduped']}, kept={dedup_info['kept']}")
    logger.info(f"去重结果: {dedup_info}")

    # 2. 连接DB，确保集合存在
    db = connect_db()
    ensure_schema(db)
    # 确保审计集合存在
    for col_name in [AUDIT_BATCHES_COLLECTION, AUDIT_RUNS_COLLECTION, AUDIT_RESULTS_COLLECTION]:
        if not db.has_collection(col_name):
            db.create_collection(col_name)

    # 3. 写入batch记录
    now = _utc_now()
    batch_doc = {
        "_key": batch_id,
        "status": "collecting",
        "created_at": now,
        "updated_at": now,
        "total_pipe1_results": dedup_info["total"],
        "deduped_count": dedup_info["deduped"],
        "to_audit_count": dedup_info["kept"],
    }
    try:
        db.collection(AUDIT_BATCHES_COLLECTION).insert(batch_doc)
    except Exception:
        # batch已存在，更新
        update_data = {k: v for k, v in batch_doc.items() if k != "_key"}
        update_data["_key"] = batch_id
        db.collection(AUDIT_BATCHES_COLLECTION).update(update_data)

    # 4. 为每条结果构造审计AGENTS.md
    print(f"  构造审计AGENTS.md（{len(results)}条）...")
    batch_dir = ANALYSIS_SOLVER_BASE / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    prepared = 0
    for i, result in enumerate(results):
        pid = result.get("problem_id", f"unknown_{i}")
        result_key = result.get("_key", result.get("_id", f"r{i}"))

        if (i + 1) % 200 == 0:
            print(f"    进度: {i+1}/{len(results)}")
            logger.info(f"进度: {i+1}/{len(results)}")

        # 构造审计AGENTS.md
        agents_md = build_audit_agents_md(result_key, pid, result)

        # 生成审计exp_id
        audit_exp_id = f"audit-{batch_id}-{i:05d}-{pid}"
        work_dir = ANALYSIS_SOLVER_BASE / audit_exp_id
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "AGENTS.md").write_text(agents_md, encoding="utf-8")

        # 写入audit_run记录
        run_doc = {
            "_key": audit_exp_id,
            "problem_id": pid,
            "batch_id": batch_id,
            "source_result_key": result_key,
            "audit_exp_id": audit_exp_id,
            "work_dir": str(work_dir),
            "status": "prepared",
            "created_at": _utc_now(),
        }
        try:
            db.collection(AUDIT_RUNS_COLLECTION).insert(run_doc)
        except Exception as e:
            logger.warning(f"写入audit_run失败: {e}")
            # 更新已有记录
            update_data = {k: v for k, v in run_doc.items() if k != "_key"}
            update_data["_key"] = audit_exp_id
            db.collection(AUDIT_RUNS_COLLECTION).update(update_data)

        prepared += 1

    # 5. 更新batch状态
    update_data = {"status": "prepared", "updated_at": _utc_now(), "prepared_count": prepared}
    update_data["_key"] = batch_id
    db.collection(AUDIT_BATCHES_COLLECTION).update(update_data)

    print(f"  审计数据准备完成: {prepared}条")
    logger.info(f"审计数据准备完成: {prepared}条")
    return prepared


def main():
    parser = argparse.ArgumentParser(description="Pipe 2审计数据收集")
    parser.add_argument("--batch-id", required=True, help="审计批次ID")
    parser.add_argument("--limit", type=int, help="限制题数（调试用）")
    args = parser.parse_args()

    count = collect_and_prepare_audit(args.batch_id, limit=args.limit)
    print(f"\n完成: {count}条审计任务已准备")


if __name__ == "__main__":
    main()
