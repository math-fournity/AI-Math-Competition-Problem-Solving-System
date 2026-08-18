"""selection_collector.py — Pipe 3选题数据收集组件

从audit_results集合读取PASS_SELECTABLE的审计结果，
join到analysis_results获取Pipe 1的完整分析字段，
构造选题用的AGENTS.md。

与audit_collector.py的区别：
  - audit_collector从analysis_results读取（Pipe 1结果）
  - selection_collector从audit_results读取（Pipe 2结果）+ join analysis_results（Pipe 1结果）
  - 选题AI同时看到Pipe 1的分析结果和Pipe 2的审计状态

用法：
  python -m src.selection_collector --batch-id selection-1 --source-batch-id audit-full1
  python -m src.selection_collector --batch-id selection-1 --source-batch-id audit-full1 --limit 10
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import (
    ANALYSIS_SOLVER_BASE, OUTPUT_BASE,
)
from src.db_schema import connect_db, ensure_schema
from src.audit_collector import AUDIT_RESULTS_COLLECTION, format_analysis_result_text
from monitoring.shared_logger import get_logger

logger = get_logger("selection_collector")

# 选题模板
SELECTION_TEMPLATE = Path(__file__).parent.parent / "templates" / "selection_agents_md.md"

# 选题用的DB集合名
SELECTION_BATCHES_COLLECTION = "selection_batches"
SELECTION_RUNS_COLLECTION = "selection_runs"
SELECTION_RESULTS_COLLECTION = "selection_results"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_pass_selectable_results(source_batch_id, limit=None):
    """从audit_results读取PASS_SELECTABLE结果，join analysis_results获取完整字段

    Returns:
        list of dict, each containing:
          - audit_result_key: audit_results的_key
          - problem_id
          - source_result_key: analysis_results的_key
          - audit_status: PASS_SELECTABLE
          - analysis_result: analysis_results的完整文档（含d1/d2/d1_exp/d2_exp等）
    """
    db = connect_db()

    aql = """
    FOR r IN @@audit_results
      FILTER r.batch_id == @source_batch_id
      FILTER r.audit_status == 'PASS_SELECTABLE'
      FILTER r.problem_id NOT IN (
        FOR s IN selection_runs
          FILTER s.status IN ['prepared', 'running', 'completed']
          RETURN s.problem_id
      )
      FOR a IN analysis_results
        FILTER a._key == r.source_result_key
        RETURN {
          audit_result_key: r._key,
          problem_id: r.problem_id,
          source_result_key: r.source_result_key,
          audit_status: r.audit_status,
          analysis_result: a
        }
    """
    cursor = db.aql.execute(aql, bind_vars={
        "@audit_results": AUDIT_RESULTS_COLLECTION,
        "source_batch_id": source_batch_id,
    }, ttl=120)

    results = list(cursor)
    if limit:
        results = results[:limit]

    logger.info(f"从audit_results读取{len(results)}条PASS_SELECTABLE（source={source_batch_id}）")
    return results


def build_selection_agents_md(problem_id, audit_status, analysis_result):
    """构造选题用的AGENTS.md

    用手动替换而非str.format——分析结果文本中可能包含花括号。
    """
    template = SELECTION_TEMPLATE.read_text(encoding="utf-8")
    result_text = format_analysis_result_text(analysis_result)

    out = template.replace("{problem_id}", str(problem_id))
    out = out.replace("{audit_status}", str(audit_status))
    out = out.replace("{analysis_result_text}", result_text)
    return out


def collect_and_prepare_selection(batch_id, source_batch_id, limit=None):
    """收集PASS_SELECTABLE结果，构造选题AGENTS.md，写入工作目录

    Args:
        batch_id: 选题批次ID（如selection-1）
        source_batch_id: 审计批次ID（如audit-full1）
        limit: 限制题数（调试用）
    """
    logger.info(f"选题数据收集开始 batch={batch_id} source={source_batch_id} limit={limit}")
    print(f"=== 选题数据收集 batch={batch_id} source={source_batch_id} ===")

    # 1. 读取PASS_SELECTABLE结果
    print("  读取PASS_SELECTABLE审计结果...")
    results = get_pass_selectable_results(source_batch_id, limit=limit)
    print(f"  读取到{len(results)}条PASS_SELECTABLE")
    logger.info(f"读取到{len(results)}条PASS_SELECTABLE")

    # 2. 连接DB，确保集合存在
    db = connect_db()
    ensure_schema(db)
    for col_name in [SELECTION_BATCHES_COLLECTION, SELECTION_RUNS_COLLECTION, SELECTION_RESULTS_COLLECTION]:
        if not db.has_collection(col_name):
            db.create_collection(col_name)

    # 3. 写入batch记录
    now = _utc_now()
    batch_doc = {
        "_key": batch_id,
        "status": "collecting",
        "created_at": now,
        "updated_at": now,
        "source_batch_id": source_batch_id,
        "total_pass_selectable": len(results),
    }
    try:
        db.collection(SELECTION_BATCHES_COLLECTION).insert(batch_doc)
    except Exception:
        update_data = {k: v for k, v in batch_doc.items() if k != "_key"}
        update_data["_key"] = batch_id
        db.collection(SELECTION_BATCHES_COLLECTION).update(update_data)

    # 4. 为每条结果构造选题AGENTS.md
    print(f"  构造选题AGENTS.md（{len(results)}条）...")
    batch_dir = ANALYSIS_SOLVER_BASE / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    prepared = 0
    for i, item in enumerate(results):
        pid = item["problem_id"]
        audit_key = item["audit_result_key"]
        source_key = item["source_result_key"]
        analysis_result = item["analysis_result"]

        if (i + 1) % 200 == 0:
            print(f"    进度: {i+1}/{len(results)}")
            logger.info(f"进度: {i+1}/{len(results)}")

        # 构造选题AGENTS.md
        agents_md = build_selection_agents_md(pid, item["audit_status"], analysis_result)

        # 生成选题exp_id
        selection_exp_id = f"sel-{batch_id}-{i:05d}-{pid}"
        work_dir = ANALYSIS_SOLVER_BASE / selection_exp_id
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "AGENTS.md").write_text(agents_md, encoding="utf-8")

        # 写入selection_run记录
        run_doc = {
            "_key": selection_exp_id,
            "problem_id": pid,
            "batch_id": batch_id,
            "source_result_key": source_key,
            "audit_result_key": audit_key,
            "selection_exp_id": selection_exp_id,
            "work_dir": str(work_dir),
            "status": "prepared",
            "created_at": _utc_now(),
        }
        try:
            db.collection(SELECTION_RUNS_COLLECTION).insert(run_doc)
        except Exception as e:
            logger.warning(f"写入selection_run失败: {e}")
            update_data = {k: v for k, v in run_doc.items() if k != "_key"}
            update_data["_key"] = selection_exp_id
            db.collection(SELECTION_RUNS_COLLECTION).update(update_data)

        prepared += 1

    # 5. 更新batch状态
    update_data = {"status": "prepared", "updated_at": _utc_now(), "prepared_count": prepared}
    update_data["_key"] = batch_id
    db.collection(SELECTION_BATCHES_COLLECTION).update(update_data)

    print(f"  选题数据准备完成: {prepared}条")
    logger.info(f"选题数据准备完成: {prepared}条")
    return prepared


def main():
    parser = argparse.ArgumentParser(description="Pipe 3选题数据收集")
    parser.add_argument("--batch-id", required=True, help="选题批次ID（如selection-1）")
    parser.add_argument("--source-batch-id", required=True, help="审计批次ID（如audit-full1）")
    parser.add_argument("--limit", type=int, help="限制题数（调试用）")
    args = parser.parse_args()

    count = collect_and_prepare_selection(args.batch_id, args.source_batch_id, limit=args.limit)
    print(f"\n完成: {count}条选题任务已准备")


if __name__ == "__main__":
    main()
