#!/usr/bin/env python3
"""trace.py — 项目全维度追溯索引（SQLite）

记录项目中所有资产之间的有向关系：需求↔代码、需求↔工作包、工作包↔方案、
资产↔commit等。一张通用关系表表达整个项目的追溯网络。

和 view_index.py 的关系：
- view_index.py 专门管理"看法文件↔文档"的映射（read-sync skill 用）
- trace.py 管理全维度追溯（需求/工作包/代码/文档/方案/commit 之间的所有关系）
- 两者共用同一个 view-index.db，各自操作不同的表

用法：
    python3 scripts/trace.py init                              # 初始化trace表
    python3 scripts/trace.py add <s_type> <s_id> <t_type> <t_id> <relation> [note] [commit_id]
    python3 scripts/trace.py remove <s_type> <s_id> <t_type> <t_id> <relation>
    python3 scripts/trace.py query <type> <id>                 # 查某资产的所有关系（双向）
    python3 scripts/trace.py query-out <type> <id>             # 查某资产作为source的 outgoing 关系
    python3 scripts/trace.py query-in <type> <id>              # 查某资产作为target的 incoming 关系
    python3 scripts/trace.py query-relation <relation>         # 查某种关系类型的所有记录
    python3 scripts/trace.py trace <type> <id>                 # 从某资产出发，递归追溯关系链
    python3 scripts/trace.py stats                             # 统计信息
    python3 scripts/trace.py list-types                        # 列出所有资产类型和关系类型
"""

import sqlite3
import sys
from pathlib import Path
from collections import deque

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "view-index.db"

# 资产类型枚举（参考，不强制）
ASSET_TYPES = {
    "checkpoint": "需求点（checklist/中的checkpoint）",
    "wp": "工作包（working-packages/中的WP）",
    "document": "文档（docs/中的文档）",
    "code": "代码（src/或monitoring/中的.py文件）",
    "script": "脚本（scripts/中的.sh或.py脚本）",
    "dev-doc": "方案文档（dev-docs/中的方案记录）",
    "view-file": "看法文件（分类法的索引文件）",
    "commit": "git commit",
    "data": "数据资产",
}

# 关系类型枚举（参考，不强制）
RELATION_TYPES = {
    "implements": "需求实现为代码（checkpoint→code）",
    "specified-by": "需求由文档规范定义（checkpoint→document）",
    "part-of": "需求属于工作包（checkpoint→wp）",
    "changes": "工作包改动代码（wp→code）",
    "produces": "工作包产生文档（wp→document）",
    "creates": "工作包创建需求点（wp→checkpoint）",
    "comes-from": "工作包来自方案（wp→dev-doc）",
    "changed-in": "资产在commit中被改动（code/document→commit）",
    "depends-on": "依赖关系（任意→任意）",
    "verifies": "验证关系（document→checkpoint）",
    "indexed-by": "被看法文件索引（document/code→view-file）",
    "traces-to": "追踪到（任意→任意，通用追溯）",
}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def cmd_init():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trace (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id   TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id   TEXT NOT NULL,
            relation    TEXT NOT NULL,
            note        TEXT,
            commit_id   TEXT,
            created_at  TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(source_type, source_id, target_type, target_id, relation)
        );
        CREATE INDEX IF NOT EXISTS idx_trace_source ON trace(source_type, source_id);
        CREATE INDEX IF NOT EXISTS idx_trace_target ON trace(target_type, target_id);
        CREATE INDEX IF NOT EXISTS idx_trace_relation ON trace(relation);
        CREATE INDEX IF NOT EXISTS idx_trace_commit ON trace(commit_id);
    """)
    conn.commit()
    conn.close()
    print("trace表已初始化")


def cmd_add(s_type, s_id, t_type, t_id, relation, note="", commit_id=""):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO trace (source_type, source_id, target_type, target_id, relation, note, commit_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (s_type, s_id, t_type, t_id, relation, note, commit_id))
        conn.commit()
        cmt = f" (commit: {commit_id})" if commit_id else ""
        note_str = f" — {note}" if note else ""
        print(f"已添加：[{s_type}]{s_id} --{relation}--> [{t_type}]{t_id}{note_str}{cmt}")
    except sqlite3.IntegrityError:
        print(f"已存在：[{s_type}]{s_id} --{relation}--> [{t_type}]{t_id}（跳过）")
    conn.close()


def cmd_remove(s_type, s_id, t_type, t_id, relation):
    conn = get_db()
    cur = conn.execute("""
        DELETE FROM trace
        WHERE source_type=? AND source_id=? AND target_type=? AND target_id=? AND relation=?
    """, (s_type, s_id, t_type, t_id, relation))
    conn.commit()
    print(f"已删除 {cur.rowcount} 条关系")
    conn.close()


def cmd_query(a_type, a_id):
    """查某资产的所有关系（双向：作为source和作为target）"""
    conn = get_db()
    outgoing = conn.execute("""
        SELECT relation, target_type, target_id, note, commit_id
        FROM trace WHERE source_type=? AND source_id=?
        ORDER BY relation, target_type, target_id
    """, (a_type, a_id)).fetchall()
    incoming = conn.execute("""
        SELECT relation, source_type, source_id, note, commit_id
        FROM trace WHERE target_type=? AND target_id=?
        ORDER BY relation, source_type, source_id
    """, (a_type, a_id)).fetchall()
    conn.close()

    if not outgoing and not incoming:
        print(f"[{a_type}]{a_id} 没有任何追溯关系")
        return

    print(f"[{a_type}]{a_id} 的追溯关系：")
    if outgoing:
        print(f"\n  outgoing（它指向什么）:")
        for r in outgoing:
            cmt = f" (commit: {r['commit_id']})" if r['commit_id'] else ""
            note_str = f" — {r['note']}" if r['note'] else ""
            print(f"    --{r['relation']}--> [{r['target_type']}]{r['target_id']}{note_str}{cmt}")
    if incoming:
        print(f"\n  incoming（什么指向它）:")
        for r in incoming:
            cmt = f" (commit: {r['commit_id']})" if r['commit_id'] else ""
            note_str = f" — {r['note']}" if r['note'] else ""
            print(f"    [{r['source_type']}]{r['source_id']} --{r['relation']}-->{note_str}{cmt}")


def cmd_query_out(s_type, s_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT relation, target_type, target_id, note, commit_id
        FROM trace WHERE source_type=? AND source_id=?
        ORDER BY relation, target_type, target_id
    """, (s_type, s_id)).fetchall()
    conn.close()
    if not rows:
        print(f"[{s_type}]{s_id} 没有outgoing关系")
    else:
        print(f"[{s_type}]{s_id} 的outgoing关系：")
        for r in rows:
            cmt = f" (commit: {r['commit_id']})" if r['commit_id'] else ""
            note_str = f" — {r['note']}" if r['note'] else ""
            print(f"  --{r['relation']}--> [{r['target_type']}]{r['target_id']}{note_str}{cmt}")


def cmd_query_in(t_type, t_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT relation, source_type, source_id, note, commit_id
        FROM trace WHERE target_type=? AND target_id=?
        ORDER BY relation, source_type, source_id
    """, (t_type, t_id)).fetchall()
    conn.close()
    if not rows:
        print(f"[{t_type}]{t_id} 没有incoming关系")
    else:
        print(f"[{t_type}]{t_id} 的incoming关系：")
        for r in rows:
            cmt = f" (commit: {r['commit_id']})" if r['commit_id'] else ""
            note_str = f" — {r['note']}" if r['note'] else ""
            print(f"  [{r['source_type']}]{r['source_id']} --{r['relation']}-->{note_str}{cmt}")


def cmd_query_relation(relation):
    conn = get_db()
    rows = conn.execute("""
        SELECT source_type, source_id, target_type, target_id, note, commit_id
        FROM trace WHERE relation=?
        ORDER BY source_type, source_id, target_type, target_id
    """, (relation,)).fetchall()
    conn.close()
    if not rows:
        print(f"没有 relation={relation} 的记录")
    else:
        print(f"relation={relation} 的所有记录（{len(rows)}条）：")
        for r in rows:
            cmt = f" (commit: {r['commit_id']})" if r['commit_id'] else ""
            note_str = f" — {r['note']}" if r['note'] else ""
            print(f"  [{r['source_type']}]{r['source_id']} --> [{r['target_type']}]{r['target_id']}{note_str}{cmt}")


def cmd_trace(a_type, a_id, max_depth=5):
    """从某资产出发，递归追溯关系链（BFS）"""
    conn = get_db()
    visited = set()
    queue = deque([(a_type, a_id, 0, [])])
    results = []

    while queue:
        s_type, s_id, depth, path = queue.popleft()
        key = (s_type, s_id)
        if key in visited or depth > max_depth:
            continue
        visited.add(key)

        rows = conn.execute("""
            SELECT relation, target_type, target_id
            FROM trace WHERE source_type=? AND source_id=?
        """, (s_type, s_id)).fetchall()

        for r in rows:
            new_path = path + [f"--{r['relation']}--> [{r['target_type']}]{r['target_id']}"]
            results.append((depth, " → ".join([f"[{a_type}]{a_id}"] + new_path)))
            if (r['target_type'], r['target_id']) not in visited:
                queue.append((r['target_type'], r['target_id'], depth + 1, new_path))

    conn.close()
    if not results:
        print(f"[{a_type}]{a_id} 没有可追溯的关系链")
    else:
        print(f"从 [{a_type}]{a_id} 出发的追溯链：")
        for depth, path in results:
            indent = "  " * depth
            print(f"{indent}{path}")


def cmd_stats():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM trace").fetchone()[0]
    by_relation = conn.execute("""
        SELECT relation, COUNT(*) as c
        FROM trace GROUP BY relation ORDER BY c DESC
    """).fetchall()
    by_source_type = conn.execute("""
        SELECT source_type, COUNT(*) as c
        FROM trace GROUP BY source_type ORDER BY c DESC
    """).fetchall()
    by_target_type = conn.execute("""
        SELECT target_type, COUNT(*) as c
        FROM trace GROUP BY target_type ORDER BY c DESC
    """).fetchall()
    with_commit = conn.execute("SELECT COUNT(*) FROM trace WHERE commit_id IS NOT NULL AND commit_id != ''").fetchone()[0]
    conn.close()
    print(f"追溯关系总数：{total}")
    print(f"含commit id的记录：{with_commit}")
    print(f"\n按关系类型分布：")
    for r in by_relation:
        print(f"  {r['relation']}: {r['c']}")
    print(f"\n按source类型分布：")
    for r in by_source_type:
        print(f"  {r['source_type']}: {r['c']}")
    print(f"\n按target类型分布：")
    for r in by_target_type:
        print(f"  {r['target_type']}: {r['c']}")


def cmd_list_types():
    print("资产类型（source_type/target_type）：")
    for k, v in ASSET_TYPES.items():
        print(f"  {k}: {v}")
    print(f"\n关系类型（relation）：")
    for k, v in RELATION_TYPES.items():
        print(f"  {k}: {v}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "init":
        cmd_init()
    elif cmd == "add":
        if len(sys.argv) < 7:
            print("用法: add <s_type> <s_id> <t_type> <t_id> <relation> [note] [commit_id]")
            sys.exit(1)
        note = sys.argv[7] if len(sys.argv) > 7 else ""
        commit_id = sys.argv[8] if len(sys.argv) > 8 else ""
        cmd_add(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6], note, commit_id)
    elif cmd == "remove":
        if len(sys.argv) < 7:
            print("用法: remove <s_type> <s_id> <t_type> <t_id> <relation>")
            sys.exit(1)
        cmd_remove(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
    elif cmd == "query":
        if len(sys.argv) < 4:
            print("用法: query <type> <id>")
            sys.exit(1)
        cmd_query(sys.argv[2], sys.argv[3])
    elif cmd == "query-out":
        if len(sys.argv) < 4:
            print("用法: query-out <type> <id>")
            sys.exit(1)
        cmd_query_out(sys.argv[2], sys.argv[3])
    elif cmd == "query-in":
        if len(sys.argv) < 4:
            print("用法: query-in <type> <id>")
            sys.exit(1)
        cmd_query_in(sys.argv[2], sys.argv[3])
    elif cmd == "query-relation":
        if len(sys.argv) < 3:
            print("用法: query-relation <relation>")
            sys.exit(1)
        cmd_query_relation(sys.argv[2])
    elif cmd == "trace":
        if len(sys.argv) < 4:
            print("用法: trace <type> <id>")
            sys.exit(1)
        cmd_trace(sys.argv[2], sys.argv[3])
    elif cmd == "stats":
        cmd_stats()
    elif cmd == "list-types":
        cmd_list_types()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
