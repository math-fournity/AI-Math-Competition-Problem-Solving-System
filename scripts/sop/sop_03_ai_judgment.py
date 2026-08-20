"""sop_03_ai_judgment.py — SOP 步骤3：C 类 AI 判断

对检查脚本标记 needs_ai_review 的条目，做真正的 AI 判断：
  C1 proof_quality — 读 proof.md，判断数学正确性
  C2 proof_hallucination — 判断是否有幻觉
  C3 answer_leak — 判断是否答案泄漏
  C4 handover_quality — 读 HANDOVER.md，判断交接文档质量
  C5 continuation_direction — 判断续传方向是否正确

这些是 Python 做不了的，必须由 Master Agent（你）做 AI 判断。

用法：
  python -m scripts.sop.sop_03_ai_judgment
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import (
    check_order, advance, print_header, print_sop_doc, print_todo_directive,
)

STEP_NUM = "03"


def query_ai_review_candidates():
    """查询标记 needs_ai_review 的 run"""
    try:
        from src.continuation_db_schema import connect_db
        from src.continuation_config import CONTINUATION_RUNS_COLLECTION
        db = connect_db()
        aql = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.needs_ai_review == true "
            f"FILTER run.ai_review_done != true "
            f"LIMIT 10 "
            f"RETURN {{_key: run._key, problem_id: run.problem_id, "
            f"rounds_log: run.rounds_log, work_dir: run.work_dir}}"
        )
        cursor = db.aql.execute(aql, ttl=60)
        return list(cursor)
    except Exception as e:
        print(f"⚠️ 查询 AI review 候选失败: {e}")
        return []


def run_ai_judgment_listing():
    """列出需要 AI 判断的条目"""
    candidates = query_ai_review_candidates()
    print("--- 待 AI 判断的条目 ---")
    if not candidates:
        print("（无待 AI 判断的条目）")
        print()
        return

    print(f"共 {len(candidates)} 个条目需要 AI 判断：\n")
    for c in candidates:
        pid = c.get("problem_id", "?")
        work_dir = c.get("work_dir", "")
        rounds_log = c.get("rounds_log", [])
        print(f"  [{pid}] work_dir={work_dir}")
        if rounds_log:
            last_round = rounds_log[-1] if isinstance(rounds_log, list) else {}
            proof_path = last_round.get("proof_path", "（无）")
            handover_path = last_round.get("handover_path", "（无）")
            export_path = last_round.get("export", "（无）")
            print(f"    proof: {proof_path}")
            print(f"    handover: {handover_path}")
            print(f"    export: {export_path}")
        print()

    print("你需要逐个读这些文件并做 C1-C5 判断（见 SOP 文档）。")
    print()


def main():
    ok, msg = check_order(STEP_NUM)
    if not ok:
        print(msg)
        sys.exit(1)

    print_header(STEP_NUM)
    print_sop_doc(STEP_NUM)
    run_ai_judgment_listing()
    advance(STEP_NUM)
    print_todo_directive(STEP_NUM)


if __name__ == "__main__":
    main()
