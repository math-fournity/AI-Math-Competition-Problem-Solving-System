"""deep_checks_02.py — SOP_02 深度检查持久化脚本（020-P02-1）

SOP_02 的 2a-2c 深度检查原用 inline `python3 -c "..."` 代码，上下文压缩后
命令丢失。提取成本脚本，AI 执行 `python -m scripts.sop.deep_checks_02` 即可。

覆盖：
  2a. DB 记录和文件状态一致性（抽查 completed/running/prepared run）
  2b. Redis 队列和 DB status 一致性
  2c. session 注册表数据完整性

不覆盖：
  2d. 事件流完整性——已在 check_02 自动化检查中覆盖（events 完整性检查段）
  2e. 跨题目模式分析——AI 判断项，不适合脚本化
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def check_2a_db_file_consistency(batch_id):
    """2a. DB 记录和文件状态一致性——抽查 completed/running/prepared run"""
    print("=== 2a. DB 记录和文件状态一致性 ===")
    try:
        from src.continuation_db_schema import connect_db
        from src.continuation_config import CONTINUATION_RUNS_COLLECTION
        db = connect_db()

        # 抽查 5 个 COMPLETED 的 run——proof_path 指向的文件确实存在
        aql_completed = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.final_status == 'COMPLETED' "
            f"LIMIT 5 "
            f"RETURN {{_key: run._key, pid: run.problem_id, "
            f"work_dir: run.work_dir, rounds_log: run.rounds_log}}"
        )
        cursor = db.aql.execute(aql_completed, bind_vars={"bid": batch_id}, ttl=60)
        completed_runs = list(cursor)
        print(f"  抽查 {len(completed_runs)} 个 COMPLETED run 的 proof_path：")
        for run in completed_runs:
            pid = run.get("pid", "?")
            rounds_log = run.get("rounds_log", [])
            proof_path = ""
            if rounds_log:
                last = rounds_log[-1] if isinstance(rounds_log, list) else {}
                proof_path = last.get("proof_path", "")
            if not proof_path:
                work_dir = run.get("work_dir", "")
                if work_dir:
                    proof_path = str(Path(work_dir) / "proof.md")
            if proof_path and Path(proof_path).exists():
                print(f"    ✅ [{pid}] proof_path 存在: {proof_path}")
            else:
                print(f"    ❌ [{pid}] proof_path 不存在: {proof_path}")

        # 抽查 5 个 running 的 run——对应 tmux session 是否在运行
        aql_running = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status == 'running' "
            f"LIMIT 5 "
            f"RETURN {{_key: run._key, pid: run.problem_id, "
            f"session_name: run.session_name}}"
        )
        cursor = db.aql.execute(aql_running, bind_vars={"bid": batch_id}, ttl=60)
        running_runs = list(cursor)
        if running_runs:
            import subprocess
            tmux_result = subprocess.run(
                ["tmux", "list-sessions"], capture_output=True, text=True, timeout=5
            )
            active_sessions = tmux_result.stdout if tmux_result.returncode == 0 else ""
            print(f"  抽查 {len(running_runs)} 个 running run 的 tmux session：")
            for run in running_runs:
                pid = run.get("pid", "?")
                sname = run.get("session_name", "")
                if sname and sname in active_sessions:
                    print(f"    ✅ [{pid}] tmux session 活跃: {sname}")
                else:
                    print(f"    ❌ [{pid}] tmux session 不在: {sname}")
        else:
            print("  （无 running 状态的 run）")

        # 抽查 5 个 prepared 的 run——work_dir 存在且 problem.txt 存在
        aql_prepared = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status == 'prepared' "
            f"LIMIT 5 "
            f"RETURN {{_key: run._key, pid: run.problem_id, work_dir: run.work_dir}}"
        )
        cursor = db.aql.execute(aql_prepared, bind_vars={"bid": batch_id}, ttl=60)
        prepared_runs = list(cursor)
        if prepared_runs:
            print(f"  抽查 {len(prepared_runs)} 个 prepared run 的 work_dir/problem.txt：")
            for run in prepared_runs:
                pid = run.get("pid", "?")
                wd = Path(run.get("work_dir", ""))
                if not wd.exists():
                    print(f"    ❌ [{pid}] work_dir 不存在: {wd}")
                elif not (wd / "problem.txt").exists():
                    print(f"    ❌ [{pid}] problem.txt 不存在: {wd}")
                else:
                    print(f"    ✅ [{pid}] work_dir + problem.txt 存在")
        else:
            print("  （无 prepared 状态的 run）")
        print()
    except Exception as e:
        print(f"  ⚠️ 2a 检查失败: {e}")
        print()


def check_2b_redis_db_consistency(batch_id):
    """2b. Redis 队列和 DB status 一致性"""
    print("=== 2b. Redis 队列和 DB status 一致性 ===")
    try:
        from src.continuation_redis_queue import get_redis, pending_count, running_count
        r = get_redis()
        redis_pending = pending_count(r)
        redis_running = running_count(r)
        print(f"  Redis pending: {redis_pending}")
        print(f"  Redis running: {redis_running}")

        from src.continuation_db_schema import connect_db
        from src.continuation_config import CONTINUATION_RUNS_COLLECTION
        db = connect_db()
        aql = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status == 'prepared' "
            f"COLLECT WITH COUNT INTO cnt RETURN cnt"
        )
        prepared_count = list(db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60))[0]
        print(f"  DB prepared: {prepared_count}")
        if prepared_count > 0 and redis_pending == 0:
            print(f"  ⚠️ {prepared_count} 个 prepared 但 Redis pending=0——feeder 可能没在入队")
        elif prepared_count > redis_pending * 10:
            print(f"  ⚠️ prepared({prepared_count}) 远大于 pending({redis_pending})——入队速度跟不上")
        else:
            print(f"  ✅ prepared/pending 比例正常")
        print()
    except Exception as e:
        print(f"  ⚠️ 2b 检查失败: {e}")
        print()


def check_2c_session_registry_integrity(batch_id):
    """2c. session 注册表数据完整性"""
    print("=== 2c. session 注册表数据完整性 ===")
    try:
        from src.continuation_db_schema import connect_db
        from src.session_registry import list_sessions
        db = connect_db()

        # running 状态的 session——export_path 父目录是否存在
        sessions = list_sessions(db, status="running", limit=20)
        print(f"  running session（{len(sessions)}个）——检查 export_path 父目录：")
        for s in sessions:
            export_path = s.get("export_path", "")
            if export_path:
                parent = Path(export_path).parent
                if parent.exists():
                    print(f"    ✅ {s.get('_key', '?')}: export_path 父目录存在")
                else:
                    print(f"    ❌ {s.get('_key', '?')}: export_path 父目录不存在: {parent}")
            else:
                print(f"    ⚠️ {s.get('_key', '?')}: 无 export_path")

        # done 状态的 session——done_md 是否为 True
        done_sessions = list_sessions(db, status="done", limit=20)
        print(f"  done session（{len(done_sessions)}个）——检查 done_md：")
        for s in done_sessions:
            done_md = s.get("done_md", False)
            status_mark = "✅" if done_md else "❌"
            print(f"    {status_mark} {s.get('_key', '?')}: done_md={done_md}")

        # stuck 状态的 session——notes 字段是否记录了原因
        stuck_sessions = list_sessions(db, status="stuck", limit=20)
        print(f"  stuck session（{len(stuck_sessions)}个）——检查 notes：")
        for s in stuck_sessions:
            notes = s.get("notes", "")
            if notes:
                print(f"    ✅ {s.get('_key', '?')}: notes={notes[:80]}")
            else:
                print(f"    ⚠️ {s.get('_key', '?')}: 无 notes（stuck 原因未记录）")
        print()
    except Exception as e:
        print(f"  ⚠️ 2c 检查失败: {e}")
        print()


def main():
    import argparse
    from scripts.sop.sop_log import get_logger
    log = get_logger("deep_checks_02")

    parser = argparse.ArgumentParser(description="SOP_02 深度检查（2a/2b/2c）")
    parser.add_argument("--batch-id", default="p27-full", help="batch_id")
    args = parser.parse_args()

    log.info(f"deep_checks_02: start batch={args.batch_id}")
    print("--- SOP_02 深度检查（2a/2b/2c 持久化脚本）---")
    print(f"batch_id: {args.batch_id}")
    print()

    check_2a_db_file_consistency(args.batch_id)
    check_2b_redis_db_consistency(args.batch_id)
    check_2c_session_registry_integrity(args.batch_id)

    print("--- 深度检查完成 ---")
    print("2d 事件流完整性：已在 check_02 自动化检查中覆盖（events 完整性检查段）")
    print("2e 跨题目模式分析：AI 判断项，参考自动化检查输出的按题源完成率统计")
    print()


if __name__ == "__main__":
    main()
