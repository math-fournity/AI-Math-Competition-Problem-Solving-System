"""diag_20260820_incident_report.py — 016事故调查报告的数据取证脚本

用途：为 dev-docs/016-动态并发设置失效与amo_bench失控循环事故调查报告.md
     提供DB层面的精确证据（batch并发值 / session注册表统计 / 事件流统计）。

背景：2026-08-20凌晨，set-concurrency 4→1后实际devin cli并发仍为6，
     且amo_bench_00000006的handover被失控循环启动上千次。
     系统已于03:55强制cool down（进程/队列全清），本脚本只读DB，不做任何写操作。

用法：
  source .env && python -m scripts.diag_20260820_incident_report
"""
from src.continuation_db_schema import connect_db
from src.continuation_config import (
    CONTINUATION_BATCHES_COLLECTION,
    CONTINUATION_RUNS_COLLECTION,
    CONTINUATION_EVENTS_COLLECTION,
    SESSIONS_COLLECTION,
)

BATCH_ID = "p27-full"
RUN_KEY = "p27-full-amo_bench_00000006"


def main():
    db = connect_db()

    # === 1. batch 文档：并发值当前状态 ===
    b = db.collection(CONTINUATION_BATCHES_COLLECTION).get(BATCH_ID)
    print("=== 1. batch文档 ===")
    print(f"  concurrency = {b.get('concurrency')}")
    print(f"  status = {b.get('status')}, updated_at = {b.get('updated_at')}")

    # === 2. session注册表统计 ===
    print("\n=== 2. session注册表(p27_sessions)统计 ===")
    aql_total = f"FOR s IN {SESSIONS_COLLECTION} COLLECT WITH COUNT INTO c RETURN c"
    total = list(db.aql.execute(aql_total, ttl=30))[0]
    print(f"  总记录数: {total}")

    aql_type = (
        f"FOR s IN {SESSIONS_COLLECTION} "
        f"COLLECT t = s.session_type WITH COUNT INTO c SORT c DESC RETURN {{type: t, count: c}}"
    )
    for row in db.aql.execute(aql_type, ttl=30):
        print(f"  按类型: {row['type']} = {row['count']}")

    aql_amo = (
        f"FOR s IN {SESSIONS_COLLECTION} FILTER s.session_name LIKE '%amo_bench_00000006%' "
        f"COLLECT WITH COUNT INTO c RETURN c"
    )
    amo = list(db.aql.execute(aql_amo, ttl=30))[0]
    print(f"  amo_bench_00000006相关session记录: {amo}")

    aql_status = (
        f"FOR s IN {SESSIONS_COLLECTION} FILTER s.session_name LIKE '%amo_bench_00000006%' "
        f"COLLECT st = s.status WITH COUNT INTO c SORT c DESC RETURN {{status: st, count: c}}"
    )
    for row in db.aql.execute(aql_status, ttl=30):
        print(f"    amo_bench按status: {row['status']} = {row['count']}")

    # amo_bench session 的 seq 范围（反映失控循环启动了多少个）
    aql_seq = (
        f"FOR s IN {SESSIONS_COLLECTION} FILTER s.session_name LIKE '%amo_bench_00000006%' "
        f"FILTER s.seq != null SORT s.seq ASC LIMIT 1 RETURN s.seq"
    )
    seqs_min = list(db.aql.execute(aql_seq, ttl=30))
    aql_seq2 = (
        f"FOR s IN {SESSIONS_COLLECTION} FILTER s.session_name LIKE '%amo_bench_00000006%' "
        f"FILTER s.seq != null SORT s.seq DESC LIMIT 1 RETURN s.seq"
    )
    seqs_max = list(db.aql.execute(aql_seq2, ttl=30))
    if seqs_min and seqs_max:
        print(f"    amo_bench session seq范围: {seqs_min[0]} ~ {seqs_max[0]}")

    # === 3. 事件流统计 ===
    print("\n=== 3. 事件流(p27_continuation_events)统计 ===")
    aql_evt = (
        f"FOR e IN {CONTINUATION_EVENTS_COLLECTION} FILTER e.batch_id == @bid "
        f"COLLECT t = e.event_type WITH COUNT INTO c SORT c DESC RETURN {{type: t, count: c}}"
    )
    for row in db.aql.execute(aql_evt, bind_vars={"bid": BATCH_ID}, ttl=60):
        print(f"  {row['type']} = {row['count']}")

    # amo_bench 的 launch/truncated 事件
    aql_amo_evt = (
        f"FOR e IN {CONTINUATION_EVENTS_COLLECTION} FILTER e.run_key == 'amo_bench_00000006' "
        f"COLLECT t = e.event_type WITH COUNT INTO c SORT c DESC RETURN {{type: t, count: c}}"
    )
    rows = list(db.aql.execute(aql_amo_evt, ttl=30))
    if rows:
        print(f"  amo_bench_00000006的事件:")
        for row in rows:
            print(f"    {row['type']} = {row['count']}")
    else:
        print("  amo_bench_00000006: 无事件(可能run_key字段值不同)")

    # === 4. amo_bench run 记录最终状态 ===
    print("\n=== 4. amo_bench_00000006 run记录最终状态 ===")
    d = db.collection(CONTINUATION_RUNS_COLLECTION).get(RUN_KEY)
    if d:
        keys = ["status", "current_round", "tmux_session", "final_status",
                "retries", "updated_at"]
        for k in keys:
            print(f"  {k} = {d.get(k)}")
        print(f"  rounds_log长度 = {len(d.get('rounds_log', []))}")
        print(f"  verdict = {d.get('verdict')}")

    # === 5. DB进度快照 ===
    print("\n=== 5. DB进度快照 ===")
    aql_prog = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} FILTER run.batch_id == @bid "
        f"COLLECT st = run.status WITH COUNT INTO c SORT c DESC RETURN {{status: st, count: c}}"
    )
    for row in db.aql.execute(aql_prog, bind_vars={"bid": BATCH_ID}, ttl=60):
        print(f"  {row['status']} = {row['count']}")


if __name__ == "__main__":
    main()
