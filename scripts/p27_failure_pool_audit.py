#!/usr/bin/env python3
"""p27失败题池审计——盘点"被续传系统启动过、AI最终没解出"的题目。

三个核查面（2026-08-21首次调查的方法固化，配套dev-docs/039号文档）：
  1. DB面：p27_continuation_runs的status×final_status分布、rounds_log非空的run、
     最后一轮判定分类（truncated截断 vs dead_session/stall基础设施失败）。
  2. 硬盘面：traj_dir的round{N}目录分布、关键题组的conversation.json留存率。
  3. sessions.db面：p27-continuation相关session数、transcripts覆盖情况。

用法：
  cd /Users/user/AI-Math-Competition-Problem-Solving-System
  source .env   # 确认ARANGO_DB=xishujuzhen_math_glm52
  .venv/bin/python3 scripts/p27_failure_pool_audit.py

只读审计，不写DB不改文件。退出码0=正常。
"""

import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.continuation_config import (  # noqa: E402
    CONTINUATION_SOLVER_BASE,
    CONTINUATION_TRAJECTORY_BASE,
)
from src.continuation_db_schema import connect_db  # noqa: E402

SESSIONS_DB = Path(os.environ.get(
    "DEVIN_SESSIONS_DB",
    Path.home() / ".local/share/devin/cli/sessions.db",
))
TRANSCRIPTS_DIR = SESSIONS_DB.parent / "transcripts"


def section(title):
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def audit_db(db):
    section("1. DB面：p27_continuation_runs")
    runs = list(db.collection("p27_continuation_runs").all())

    combo = Counter((r.get("status"), r.get("final_status")) for r in runs)
    print("[status × final_status 全组合]")
    for (status, fs), n in combo.most_common():
        print(f"  status={status:<14} final_status={str(fs):<18} {n}")

    hard_fail = [r for r in runs if r.get("final_status") in
                 ("TRUNCATED_AT_MAX", "ABANDONED", "FAILED")]
    print(f"[终态失败题] TRUNCATED_AT_MAX/ABANDONED/FAILED: {len(hard_fail)}")

    started_unsolved = [r for r in runs
                        if r.get("status") == "prepared"
                        and len(r.get("rounds_log") or []) > 0]
    print(f"[启动过但停在prepared的题] rounds_log非空: {len(started_unsolved)}")

    trunc, infra = [], []
    for r in started_unsolved:
        last = (r.get("rounds_log") or [-1])[-1]
        (trunc if last.get("truncated") else infra).append(r)
    print(f"  - 最后一轮truncated=true（AI thinking spin截断）: {len(trunc)}")
    print(f"  - 最后一轮dead_session/stall（基础设施失败）: {len(infra)}")

    rounds_dist = Counter(len(r.get("rounds_log") or []) for r in started_unsolved)
    print(f"  - 轮次记录分布: {dict(sorted(rounds_dist.items()))}")
    cr = Counter(r.get("current_round") for r in started_unsolved)
    print(f"  - current_round分布: {dict(sorted(cr.items()))}")
    return runs, trunc, infra


def audit_disk(runs, trunc):
    section("2. 硬盘面：traj_dir / work_dir")
    traj_dirs = [p for p in CONTINUATION_TRAJECTORY_BASE.iterdir() if p.is_dir()] \
        if CONTINUATION_TRAJECTORY_BASE.exists() else []
    print(f"traj_dir题目目录总数: {len(traj_dirs)}")

    round_count = Counter()
    for d in traj_dirs:
        n = len([x for x in d.iterdir()
                 if x.is_dir() and x.name.startswith("round")])
        round_count[n] += 1
    print(f"[每题round{chr(123)}N{chr(125)}子目录数分布] {dict(sorted(round_count.items()))}")

    max_round = max(
        (int(x.name.replace("round", ""))
         for d in traj_dirs for x in d.iterdir()
         if x.is_dir() and x.name.startswith("round")),
        default=0,
    )
    print(f"全池最大轮次编号: {max_round}")

    kept = sum(1 for r in trunc
               if (CONTINUATION_TRAJECTORY_BASE / r["_key"]
                   / "round2" / "exports" / "conversation.json").is_file())
    print(f"[截断题数据留存] round2 conversation.json存在: {kept}/{len(trunc)}")

    lost = 0
    completed = [r for r in runs if r.get("status") == "completed"]
    for r in completed:
        if not (CONTINUATION_TRAJECTORY_BASE / r["_key"]
                / "round2" / "exports" / "conversation.json").is_file():
            lost += 1
    print(f"[completed题export丢失] 无round2 conversation.json: "
          f"{lost}/{len(completed)}")


def audit_sessions_db():
    section("3. sessions.db面：devin cli session元数据")
    if not SESSIONS_DB.exists():
        print(f"sessions.db不存在: {SESSIONS_DB}")
        return
    conn = sqlite3.connect(f"file:{SESSIONS_DB}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM sessions WHERE working_directory LIKE ?",
        ("%p27-continuation%",),
    )
    ids = [row[0] for row in cur.fetchall()]
    print(f"p27-continuation相关session总数: {len(ids)}")

    have = sum(1 for i in ids if (TRANSCRIPTS_DIR / f"{i}.json").is_file())
    print(f"其中transcript文件存在: {have}/{len(ids)}")
    summaries = SESSIONS_DB.parent / "summaries"
    if summaries.exists():
        print(f"summaries/文件总数（hash命名，与session关联机制未打通）: "
              f"{len(list(summaries.glob('history_*.md')))}")
    conn.close()


def main():
    print(f"ARANGO_DB={os.environ.get('ARANGO_DB', '<未设置!>')}")
    db = connect_db()
    runs, trunc, _infra = audit_db(db)
    audit_disk(runs, trunc)
    audit_sessions_db()
    section("结论口径")
    print("""终态失败(TRUNCATED_AT_MAX等)计数=最终判死的题；
prepared+rounds_log非空=启动过但卡在中间态的题（含AI截断与基础设施失败两类），
它们是未来TRUNCATED_AT_MAX的直接候选池。两者勿混淆。""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
