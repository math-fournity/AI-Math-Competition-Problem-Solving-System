#!/usr/bin/env python3
"""recover_proofs_from_sessions_db.py — 从 sessions.db 恢复 018 事故丢失的 proof.md

018 事故删了 work_dir 中的 proof.md，但 devin cli 的 sessions.db（30GB）
保留了 AI 写 proof.md 时的 write tool_call 完整内容。
本脚本从 sessions.db 中提取 proof.md 内容，恢复到 work_dir 和 p27_continuation_results。

用法:
  python -m scripts.recover_proofs_from_sessions_db --dry-run    # 只看不写
  python -m scripts.recover_proofs_from_sessions_db              # 执行恢复
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from arango import ArangoClient

SESSIONS_DB = os.path.expanduser("~/.local/share/devin/cli/sessions.db")


def connect_db():
    host = os.environ.get('ARANGO_HOST', 'http://localhost:8529')
    dbname = os.environ.get('ARANGO_DB', 'xishujuzhen_math_glm52')
    user = os.environ.get('ARANGO_USER', 'root')
    password = os.environ.get('ARANGO_PASS', '')
    c = ArangoClient(hosts=host)
    return c.db(dbname, username=user, password=password)


def get_completed_without_proof(db):
    """获取 completed 但无 proof.md 的题"""
    q = ('FOR r IN p27_continuation_runs '
         'FILTER r.status == "completed" '
         'RETURN {pid: r.problem_id, work_dir: r.work_dir, '
         '        run_key: r._key, ended_at: r.ended_at, '
         '        rounds_log: r.rounds_log, proof_path: r.proof_path}')
    runs = list(db.aql.execute(q, ttl=60))
    return [r for r in runs
            if not os.path.exists(os.path.join(r.get('work_dir', ''), 'proof.md'))]


def find_proof_in_sessions_db(conn, work_dir):
    """在 sessions.db 中查找 write proof.md 的 tool_call，返回 proof 内容"""
    cur = conn.cursor()
    cur.execute("SELECT id FROM sessions WHERE working_directory = ?", (work_dir,))
    sessions = cur.fetchall()

    for (sid,) in sessions:
        cur.execute(
            "SELECT chat_message FROM message_nodes "
            "WHERE session_id = ? AND chat_message LIKE '%proof.md%'",
            (sid,))
        for (msg,) in cur.fetchall():
            try:
                m = json.loads(msg)
                for tc in m.get('tool_calls', []):
                    args = tc.get('arguments', {})
                    fp = args.get('file_path', '')
                    if 'proof.md' in fp and 'content' in args:
                        return args['content'], sid
            except (json.JSONDecodeError, KeyError):
                pass
    return None, None


def main():
    parser = argparse.ArgumentParser(description="从 sessions.db 恢复 018 事故丢失的 proof.md")
    parser.add_argument("--dry-run", action="store_true", help="只看不写")
    args = parser.parse_args()

    db = connect_db()
    no_proof = get_completed_without_proof(db)
    print(f"无 proof.md 的 completed 题: {len(no_proof)}")

    conn = sqlite3.connect(SESSIONS_DB)

    recovered = []
    not_found = []

    for r in no_proof:
        wd = r.get('work_dir', '')
        pid = r['pid']
        proof_content, sid = find_proof_in_sessions_db(conn, wd)
        if proof_content:
            recovered.append((r, proof_content, sid))
        else:
            not_found.append(r)

    print(f"  在 sessions.db 中找到 proof: {len(recovered)}")
    print(f"  未找到: {len(not_found)}")

    if not_found:
        print(f"\n未找到的题:")
        for r in not_found:
            print(f"  {r['pid']}  work_dir={r['work_dir']}")

    print(f"\n恢复样本（前5题）:")
    for r, content, sid in recovered[:5]:
        print(f"  {r['pid']}  session={sid}  proof_size={len(content)}")

    if args.dry_run:
        print(f"\n[dry-run] 不写入文件。")
        conn.close()
        return

    # 执行恢复
    print(f"\n恢复 {len(recovered)} 题的 proof.md...")

    # 1. 恢复到 work_dir/proof.md
    for r, content, sid in recovered:
        wd = r['work_dir']
        os.makedirs(wd, exist_ok=True)
        proof_path = os.path.join(wd, 'proof.md')
        with open(proof_path, 'w') as f:
            f.write(content)

    print(f"  ✅ 已恢复 {len(recovered)} 题的 proof.md 到 work_dir")

    # 2. 入库到 p27_continuation_results
    from src.continuation_db_schema import insert_result
    from monitoring.shared_logger import get_logger
    logger = get_logger("recover_proofs")

    inserted = 0
    for r, content, sid in recovered:
        try:
            insert_result(db, {
                "run_key": r['run_key'],
                "batch_id": "p27-full",
                "final_status": "COMPLETED",
                "round": None,
                "proof_text": content[:100000],
                "proof_path": r.get('proof_path', ''),
                "export_path": "",
                "elapsed": None,
                "done_reason": "recovered_from_sessions_db",
                "created_at": r.get('ended_at', ''),
                "recovered_from_session": sid,
            })
            inserted += 1
        except Exception as e:
            print(f"  ⚠️ 入库失败 {r['pid']}: {e}")

    print(f"  ✅ 已入库 {inserted} 题到 p27_continuation_results")

    conn.close()
    print(f"\n恢复完成: {len(recovered)} 题 proof.md 恢复 + {inserted} 题入库")


if __name__ == "__main__":
    main()
