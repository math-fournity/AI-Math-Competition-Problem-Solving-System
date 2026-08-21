"""proof_audit_collector.py — Pipe 5 审计 Pipe 数据收集组件（管线入口）

从 ArangoDB 查询续传系统中 status=completed 且未审计（audit_passed=None）的题，
为每道题创建审计 run 记录（p27_proof_audit_runs），入 Redis paudit:pending 队列。

数据源是 ArangoDB 查询（不是 problem_list.json），因为审计的是续传系统的产出。

步骤：
  1. 查 p27_continuation_runs 中 status=completed 且 audit_passed=None 的题
  2. 从 p27_continuation_results 获取 proof_text（双写备份）
  3. 为每题创建 p27_proof_audit_runs 记录（status=prepared）
  4. 入 Redis paudit:pending 队列

用法：
  python -m src.proof_audit_collector --batch-id paudit-p27-full
  python -m src.proof_audit_collector --batch-id paudit-test --limit 10
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.proof_audit_config import (
    PROOF_AUDIT_RUNS_COLLECTION,
    CONTINUATION_RUNS_COLLECTION,
    CONTINUATION_RESULTS_COLLECTION,
    AUDIT_SOLVER_BASE,
    AUDIT_TRAJECTORY_BASE,
    AUDIT_PENDING_KEY,
)
from src.proof_audit_db_schema import (
    connect_db, ensure_schema, insert_audit_run,
)
from src.proof_audit_redis_queue import get_redis, enqueue_pending, ping as redis_ping
from src.continuation_db_schema import connect_db as connect_continuation_db
from monitoring.shared_logger import get_logger, log_event

logger = get_logger("proof_audit_collector")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def collect_completed_for_audit(batch_id, limit=None, filter_prefix=None):
    """收集续传系统中 completed 但未审计的题，创建审计 run 记录入队。

    Args:
        batch_id: 审计批次ID（如 paudit-p27-full）
        limit: 限制题数（测试用）
        filter_prefix: 题目ID前缀过滤
    """
    db = connect_db()
    ensure_schema(db)

    # 查 completed 且未审计的题
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.status == 'completed' "
        f"FILTER run.audit_passed == null "
        f"SORT run.problem_id "
    )
    if filter_prefix:
        aql += f"FILTER run.problem_id LIKE @prefix "
    aql += f"LIMIT @limit RETURN run"

    bind_vars = {"limit": limit or 10000}
    if filter_prefix:
        bind_vars["prefix"] = filter_prefix + "%"

    cursor = db.aql.execute(aql, bind_vars=bind_vars, ttl=120)
    candidates = list(cursor)

    print(f"\n=== Pipe 5 审计数据收集 ===")
    print(f"  batch_id: {batch_id}")
    print(f"  待审计题数: {len(candidates)}")

    if not candidates:
        print("  （无待审计题）")
        return 0

    # 连接 Redis
    if not redis_ping():
        print("  ERROR: Redis 不可达")
        return 0
    r = get_redis()

    prepared = 0
    skipped = 0

    for run in candidates:
        run_key = run["_key"]
        pid = run.get("problem_id", "?")

        # 生成审计 run key
        audit_run_key = f"paudit-{run_key}"

        # 检查是否已存在审计 run（断点续传）
        existing = db.collection(PROOF_AUDIT_RUNS_COLLECTION).get(audit_run_key)
        if existing and existing.get("status") in ("completed", "running"):
            print(f"  [skip] {pid}: 审计已存在且状态={existing.get('status')}")
            skipped += 1
            continue

        # 从 p27_continuation_results 获取 proof_text
        proof_text = None
        proof_result = None
        try:
            result_aql = (
                f"FOR res IN {CONTINUATION_RESULTS_COLLECTION} "
                f"FILTER res.run_key == @rk "
                f"LIMIT 1 RETURN res"
            )
            result_cursor = db.aql.execute(result_aql, bind_vars={"rk": run_key}, ttl=60)
            results = list(result_cursor)
            if results:
                proof_result = results[0]
                proof_text = proof_result.get("proof_text", "")
        except Exception as e:
            log_event(logger, "warning", "query_proof_result_failed",
                      run_key=run_key, error=str(e))

        if not proof_text:
            # fallback: 从硬盘读 proof.md
            work_dir = run.get("work_dir", "")
            proof_path_str = run.get("proof_path", "")
            if not proof_path_str and work_dir:
                proof_path_str = str(Path(work_dir) / "proof.md")
            if proof_path_str and Path(proof_path_str).exists():
                try:
                    proof_text = Path(proof_path_str).read_text()
                except Exception as e:
                    log_event(logger, "warning", "read_proof_file_failed",
                              run_key=run_key, path=proof_path_str, error=str(e))

        if not proof_text:
            print(f"  [skip] {pid}: 无 proof_text（DB和硬盘都没有）")
            log_event(logger, "info", "skip_audit", run_key=run_key,
                      problem_id=pid, reason="无proof_text")
            skipped += 1
            continue

        # 获取题目文本
        problem_text = run.get("problem_text", "")
        if not problem_text:
            # fallback: 从 work_dir/problem.txt 读
            work_dir = run.get("work_dir", "")
            if work_dir and Path(work_dir).exists():
                problem_file = Path(work_dir) / "problem.txt"
                if problem_file.exists():
                    try:
                        problem_text = problem_file.read_text()
                    except Exception:
                        pass

        # 获取标准答案（从 problem_list 或 DB 的其他集合——暂用 proof_result 中的字段）
        standard_answer = ""
        if proof_result:
            standard_answer = proof_result.get("standard_answer", "")

        # 创建审计工作目录
        audit_work_dir = AUDIT_SOLVER_BASE / audit_run_key
        audit_work_dir.mkdir(parents=True, exist_ok=True)

        audit_traj_dir = AUDIT_TRAJECTORY_BASE / audit_run_key
        audit_traj_dir.mkdir(parents=True, exist_ok=True)
        (audit_traj_dir / "exports").mkdir(exist_ok=True)
        (audit_traj_dir / "tmux").mkdir(exist_ok=True)

        # 创建/更新审计 run 记录
        audit_run_doc = {
            "_key": audit_run_key,
            "source_run_key": run_key,
            "problem_id": pid,
            "batch_id": batch_id,
            "status": "prepared",
            "audit_status": None,
            "audit_passed": None,
            "work_dir": str(audit_work_dir),
            "export_path": str(audit_traj_dir / "exports" / "conversation.json"),
            "proof_text": proof_text[:50000],  # DB中存前50KB
            "problem_text": problem_text[:10000],
            "standard_answer": standard_answer,
            "started_at": None,
            "ended_at": None,
            "audited_at": None,
            "error_message": None,
            "created_at": utc_now(),
        }

        if existing:
            # 断点续传——更新现有记录
            from src.proof_audit_db_schema import update_audit_run
            update_audit_run(db, audit_run_key, {
                "status": "prepared",
                "proof_text": proof_text[:50000],
                "problem_text": problem_text[:10000],
                "standard_answer": standard_answer,
            })
        else:
            insert_audit_run(db, audit_run_doc)

        # 入 Redis 队列
        enqueue_pending(r, audit_run_key, priority=0)

        prepared += 1
        log_event(logger, "info", "prepare_audit",
                  audit_run_key=audit_run_key, problem_id=pid, batch_id=batch_id)

    print(f"\n=== 收集完成 ===")
    print(f"  prepared: {prepared}")
    print(f"  skipped: {skipped}")
    print(f"  batch_id: {batch_id}")
    print(f"  Redis paudit:pending: {r.zcard(AUDIT_PENDING_KEY)}")

    log_event(logger, "info", "collect_done",
              batch_id=batch_id, prepared=prepared, skipped=skipped)

    return prepared


def main():
    parser = argparse.ArgumentParser(description="Pipe 5 审计数据收集")
    parser.add_argument("--batch-id", required=True, help="审计批次ID（如 paudit-p27-full）")
    parser.add_argument("--limit", type=int, default=10000, help="限制题数（默认10000）")
    parser.add_argument("--filter-prefix", help="题目ID前缀过滤")
    args = parser.parse_args()

    count = collect_completed_for_audit(
        args.batch_id, limit=args.limit, filter_prefix=args.filter_prefix)
    print(f"\n完成: {count}条审计任务已准备")


if __name__ == "__main__":
    main()
