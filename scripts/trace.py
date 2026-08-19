#!/usr/bin/env python3
"""trace.py — 项目全维度追溯索引（CSV后端，git可追踪）

记录项目中所有资产之间的有向关系：需求↔代码、需求↔工作包、工作包↔方案、
资产↔commit等。一张通用关系表表达整个项目的追溯网络。

数据存储在 trace.csv（文本文件，git可逐行diff，保留完整变更历史）。

和 view_index.py 的关系：
- view_index.py 专门管理"看法文件↔文档"的映射（read-sync skill 用）
- trace.py 管理全维度追溯（需求/工作包/代码/文档/方案/commit 之间的所有关系）
- 两者各自操作独立的CSV文件

用法：
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

import csv
import sys
from pathlib import Path
from collections import deque

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "trace.csv"

FIELDS = ["source_type", "source_id", "target_type", "target_id", "relation", "note", "commit_id"]

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


def read_all():
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_all(rows):
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def cmd_add(s_type, s_id, t_type, t_id, relation, note="", commit_id=""):
    rows = read_all()
    for r in rows:
        if (r["source_type"] == s_type and r["source_id"] == s_id
                and r["target_type"] == t_type and r["target_id"] == t_id
                and r["relation"] == relation):
            print(f"已存在：[{s_type}]{s_id} --{relation}--> [{t_type}]{t_id}（跳过）")
            return
    rows.append({
        "source_type": s_type, "source_id": s_id,
        "target_type": t_type, "target_id": t_id,
        "relation": relation, "note": note, "commit_id": commit_id
    })
    rows.sort(key=lambda r: (r["source_type"], r["source_id"], r["target_type"], r["target_id"], r["relation"]))
    write_all(rows)
    cmt = f" (commit: {commit_id})" if commit_id else ""
    note_str = f" — {note}" if note else ""
    print(f"已添加：[{s_type}]{s_id} --{relation}--> [{t_type}]{t_id}{note_str}{cmt}")


def cmd_remove(s_type, s_id, t_type, t_id, relation):
    rows = read_all()
    before = len(rows)
    rows = [r for r in rows if not (
        r["source_type"] == s_type and r["source_id"] == s_id
        and r["target_type"] == t_type and r["target_id"] == t_id
        and r["relation"] == relation)]
    after = len(rows)
    write_all(rows)
    print(f"已删除 {before - after} 条关系")


def cmd_query(a_type, a_id):
    rows = read_all()
    outgoing = [r for r in rows if r["source_type"] == a_type and r["source_id"] == a_id]
    incoming = [r for r in rows if r["target_type"] == a_type and r["target_id"] == a_id]

    if not outgoing and not incoming:
        print(f"[{a_type}]{a_id} 没有任何追溯关系")
        return

    print(f"[{a_type}]{a_id} 的追溯关系：")
    if outgoing:
        print(f"\n  outgoing（它指向什么）:")
        for r in sorted(outgoing, key=lambda x: (x["relation"], x["target_type"], x["target_id"])):
            cmt = f" (commit: {r['commit_id']})" if r["commit_id"] else ""
            note_str = f" — {r['note']}" if r["note"] else ""
            print(f"    --{r['relation']}--> [{r['target_type']}]{r['target_id']}{note_str}{cmt}")
    if incoming:
        print(f"\n  incoming（什么指向它）:")
        for r in sorted(incoming, key=lambda x: (x["relation"], x["source_type"], x["source_id"])):
            cmt = f" (commit: {r['commit_id']})" if r["commit_id"] else ""
            note_str = f" — {r['note']}" if r["note"] else ""
            print(f"    [{r['source_type']}]{r['source_id']} --{r['relation']}-->{note_str}{cmt}")


def cmd_query_out(s_type, s_id):
    rows = read_all()
    matches = [r for r in rows if r["source_type"] == s_type and r["source_id"] == s_id]
    if not matches:
        print(f"[{s_type}]{s_id} 没有outgoing关系")
    else:
        print(f"[{s_type}]{s_id} 的outgoing关系：")
        for r in sorted(matches, key=lambda x: (x["relation"], x["target_type"], x["target_id"])):
            cmt = f" (commit: {r['commit_id']})" if r["commit_id"] else ""
            note_str = f" — {r['note']}" if r["note"] else ""
            print(f"  --{r['relation']}--> [{r['target_type']}]{r['target_id']}{note_str}{cmt}")


def cmd_query_in(t_type, t_id):
    rows = read_all()
    matches = [r for r in rows if r["target_type"] == t_type and r["target_id"] == t_id]
    if not matches:
        print(f"[{t_type}]{t_id} 没有incoming关系")
    else:
        print(f"[{t_type}]{t_id} 的incoming关系：")
        for r in sorted(matches, key=lambda x: (x["relation"], x["source_type"], x["source_id"])):
            cmt = f" (commit: {r['commit_id']})" if r["commit_id"] else ""
            note_str = f" — {r['note']}" if r["note"] else ""
            print(f"  [{r['source_type']}]{r['source_id']} --{r['relation']}-->{note_str}{cmt}")


def cmd_query_relation(relation):
    rows = read_all()
    matches = [r for r in rows if r["relation"] == relation]
    if not matches:
        print(f"没有 relation={relation} 的记录")
    else:
        print(f"relation={relation} 的所有记录（{len(matches)}条）：")
        for r in sorted(matches, key=lambda x: (x["source_type"], x["source_id"], x["target_type"], x["target_id"])):
            cmt = f" (commit: {r['commit_id']})" if r["commit_id"] else ""
            note_str = f" — {r['note']}" if r["note"] else ""
            print(f"  [{r['source_type']}]{r['source_id']} --> [{r['target_type']}]{r['target_id']}{note_str}{cmt}")


def cmd_trace(a_type, a_id, max_depth=5):
    rows = read_all()
    # 构建邻接表
    adj = {}
    for r in rows:
        key = (r["source_type"], r["source_id"])
        adj.setdefault(key, []).append((r["relation"], r["target_type"], r["target_id"]))

    visited = set()
    queue = deque([(a_type, a_id, 0, [])])
    results = []

    while queue:
        s_type, s_id, depth, path = queue.popleft()
        key = (s_type, s_id)
        if key in visited or depth > max_depth:
            continue
        visited.add(key)

        for relation, t_type, t_id in adj.get(key, []):
            new_path = path + [f"--{relation}--> [{t_type}]{t_id}"]
            results.append((depth, " → ".join([f"[{a_type}]{a_id}"] + new_path)))
            if (t_type, t_id) not in visited:
                queue.append((t_type, t_id, depth + 1, new_path))

    if not results:
        print(f"[{a_type}]{a_id} 没有可追溯的关系链")
    else:
        print(f"从 [{a_type}]{a_id} 出发的追溯链：")
        for depth, path in results:
            indent = "  " * depth
            print(f"{indent}{path}")


def cmd_stats():
    rows = read_all()
    if not rows:
        print(f"CSV为空：{CSV_PATH}")
        return
    from collections import Counter
    by_relation = Counter(r["relation"] for r in rows)
    by_source = Counter(r["source_type"] for r in rows)
    by_target = Counter(r["target_type"] for r in rows)
    with_commit = sum(1 for r in rows if r["commit_id"])
    print(f"追溯关系总数：{len(rows)}")
    print(f"含commit id的记录：{with_commit}")
    print(f"\n按关系类型分布：")
    for r, c in by_relation.most_common():
        print(f"  {r}: {c}")
    print(f"\n按source类型分布：")
    for r, c in by_source.most_common():
        print(f"  {r}: {c}")
    print(f"\n按target类型分布：")
    for r, c in by_target.most_common():
        print(f"  {r}: {c}")


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

    if cmd == "add":
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
