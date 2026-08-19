#!/usr/bin/env python3
"""trace.py — 项目全维度追溯索引（CSV后端，git可追踪）

记录项目中所有资产之间的有向关系：需求↔代码、需求↔工作包、工作包↔方案、
资产↔commit等。一张通用关系表表达整个项目的追溯网络。

数据存储在 trace.csv（文本文件，git可逐行diff，保留完整变更历史）。

== 资产寻址方案（XPath-like） ==

资产是分层的，source_id / target_id 必须是能在整个项目资产树中唯一定位的路径表达式。

代码资产：
  文件级    monitoring/continuation_control.py
  类级      monitoring/continuation_control.py::ContinuationControl
  函数级    monitoring/continuation_control.py::start
  方法级    monitoring/continuation_control.py::ContinuationControl.start

文档资产：
  文件级    docs/system/AnalysisSystemOps.md
  章节级    docs/system/AnalysisSystemOps.md#接手指南
  子章节级  docs/system/AnalysisSystemOps.md#接手指南>环境检查

看法文件资产：
  文件级    views/src.md
  章节级    views/src.md#monitoring模块

checkpoint / wp 资产：
  编号级    MON-A1 / WP-09
  文件级    checklist/MON-A1.md / working-packages/WP-09.md
  章节级    checklist/MON-A1.md#验证方法

commit 资产：
  hash      a4f3a61

分隔符：
  ::  代码符号导航（文件→类/函数）
  #   文档章节导航（文件→章节）
  >   章节嵌套（章节→子章节）
  .   类内方法导航（Class.method）

规则：
  - 不含 :: 或 # 的路径 = 文件级
  - 含 :: 的路径 = 代码符号级（类/函数/方法）
  - 含 # 的路径 = 文档章节级
  - 含 > 的路径 = 子章节级（必须先有 #）

== 资产分层 ==

第0层 原子单元：代码函数/类、文档叶子小节
第1层 文件：.py / .md / .sh
第2层 看法文件：views/ 下专门维护的索引
第3层 默认看法：checklist/ working-packages/ dev-docs/（repo结构自带的项目级分类法）

追溯链可以跨层：需求(第3层) → 看法文件(第2层) → 代码文件(第1层) → 函数(第0层) → commit

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
    python3 scripts/trace.py query-prefix <type> <id_prefix>   # 查某文件下所有子资产的关系（如查某.py的所有函数）
    python3 scripts/trace.py trace <type> <id>                 # 从某资产出发，递归追溯关系链
    python3 scripts/trace.py level <type> <id>                 # 显示某资产的层级深度
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
    # 第3层：默认看法（repo结构自带的项目级分类法）
    "checkpoint": "需求点（checklist/中的checkpoint）",
    "wp": "工作包（working-packages/中的WP）",
    "dev-doc": "方案文档（dev-docs/中的方案记录）",
    # 第2层：看法文件（views/下专门维护的索引）
    "view-file": "看法文件（分类法的索引文件）",
    # 第1层：文件
    "document": "文档（docs/中的文档）",
    "code": "代码（src/或monitoring/中的.py文件）",
    "script": "脚本（scripts/中的.sh或.py脚本）",
    "data": "数据资产",
    "config": "配置文件（.env.example/src/config.py等）",
    "template": "prompt模板文件（docs/templates/下的模板）",
    # 运行时资产（不在repo文件树中，通过路径常量/环境变量引用）
    "db-collection": "ArangoDB集合（如analysis_runs/p27_continuation_runs等）",
    "runtime-asset": "运行时路径资产（如SOLVER_BASE/TRAJECTORY_BASE等路径常量）",
    # 第0层：原子单元（通过XPath-like路径表达，type仍用code/document等）
    #   代码函数/类：code类型，id含 :: 分隔符
    #   文档章节：document类型，id含 # 分隔符
    # 跨层
    "commit": "git commit",
}

RELATION_TYPES = {
    # 跨层关系
    "implements": "需求实现为代码（checkpoint→code/function）",
    "specified-by": "需求由文档规范定义（checkpoint→document/section）",
    "part-of": "需求属于工作包（checkpoint→wp）",
    "changes": "工作包/方案改动代码（wp/dev-doc→code/function）",
    "produces": "工作包/方案产生文档（wp/dev-doc→document）",
    "creates": "工作包创建需求点（wp→checkpoint）",
    "comes-from": "工作包来自方案（wp→dev-doc）",
    "changed-in": "资产在commit中被改动（任意→commit）",
    "depends-on": "依赖关系（任意→任意）",
    "verifies": "验证关系（document→checkpoint）",
    "indexed-by": "被看法文件索引（document/code→view-file）",
    "traces-to": "追踪到（任意→任意，通用追溯）",
    # 层级内关系
    "contains": "包含关系（文件→函数/章节，高层→低层）",
    "organizes": "组织关系（默认看法→看法文件，第3层→第2层）",
    # 运行时关系（WP-TRACE-01新增，2026-08-19）
    "reads-from": "代码读DB集合（code→db-collection）",
    "writes-to": "代码写DB集合（code→db-collection）",
    "configures": "配置项被代码引用（config→code）",
    "generates": "代码生成运行时产物（code→runtime-asset）",
    "uses-template": "launcher使用prompt模板（code→template）",
    "indexes": "看法文件索引文档（view-file→document，indexed-by的反向）",
}


def asset_level(asset_id):
    """判断资产的层级深度

    返回：
      0 = 原子单元（函数/类/文档章节）
      1 = 文件
      2+ = 更高层（checkpoint/wp等编号型资产）
      -1 = commit（不在文件层级体系中）
    """
    if not asset_id:
        return -1
    # commit hash
    if all(c in "0123456789abcdef" for c in asset_id.lower()) and len(asset_id) >= 7:
        return -1
    # 含 :: 或 # 的路径 = 原子单元（第0层）
    if "::" in asset_id or "#" in asset_id:
        return 0
    # 不含分隔符的纯编号（如 MON-A1, WP-09）= 第2层及以上
    if "/" not in asset_id and "." not in asset_id:
        return 2
    # 含路径分隔符的文件 = 第1层
    return 1


def asset_file_part(asset_id):
    """从XPath-like路径中提取文件部分

    'monitoring/continuation_control.py::ContinuationControl.start' → 'monitoring/continuation_control.py'
    'docs/system/AnalysisSystemOps.md#接手指南>环境检查' → 'docs/system/AnalysisSystemOps.md'
    'MON-A1' → 'MON-A1'
    """
    if "::" in asset_id:
        return asset_id.split("::", 1)[0]
    if "#" in asset_id:
        return asset_id.split("#", 1)[0]
    return asset_id


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
    print(f"\n资产层级（由asset_id中的分隔符决定）：")
    print(f"  第0层 原子单元：id含 :: 或 # （函数/类/章节）")
    print(f"  第1层 文件：id是文件路径（含 / 和 .py/.md等后缀）")
    print(f"  第2层+ 编号型：id是纯编号（如 MON-A1, WP-09）")
    print(f"  -1层 commit：id是git hash")


def cmd_query_prefix(a_type, id_prefix):
    """查某前缀下所有资产的关系——用于查某文件下所有子资产（函数/章节）的关系"""
    rows = read_all()
    # 匹配 source 或 target 中以 id_prefix 开头（后跟 :: # > 或精确匹配）的记录
    matches = []
    for r in rows:
        s_match = (r["source_type"] == a_type and
                   (r["source_id"] == id_prefix or r["source_id"].startswith(id_prefix + "::") or r["source_id"].startswith(id_prefix + "#")))
        t_match = (r["target_type"] == a_type and
                   (r["target_id"] == id_prefix or r["target_id"].startswith(id_prefix + "::") or r["target_id"].startswith(id_prefix + "#")))
        if s_match or t_match:
            matches.append(r)
    if not matches:
        print(f"没有以 [{a_type}]{id_prefix} 为前缀的资产关系")
    else:
        print(f"[{a_type}]{id_prefix} 及其子资产的关系（{len(matches)}条）：")
        for r in sorted(matches, key=lambda x: (x["source_id"], x["target_id"])):
            cmt = f" (commit: {r['commit_id']})" if r["commit_id"] else ""
            note_str = f" — {r['note']}" if r["note"] else ""
            print(f"  [{r['source_type']}]{r['source_id']} --{r['relation']}--> [{r['target_type']}]{r['target_id']}{note_str}{cmt}")


def cmd_level(a_type, a_id):
    """显示某资产的层级深度"""
    lvl = asset_level(a_id)
    file_part = asset_file_part(a_id)
    level_names = {-1: "commit（不在文件层级体系中）", 0: "原子单元（函数/类/章节）", 1: "文件", 2: "编号型（checkpoint/wp等）"}
    print(f"[{a_type}]{a_id}")
    print(f"  层级：第{lvl}层 — {level_names.get(lvl, '未知')}")
    print(f"  文件部分：{file_part}")
    if a_id != file_part:
        symbol_part = a_id[len(file_part):].lstrip(":").lstrip("#")
        print(f"  符号/章节部分：{symbol_part}")


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
    elif cmd == "query-prefix":
        if len(sys.argv) < 4:
            print("用法: query-prefix <type> <id_prefix>")
            sys.exit(1)
        cmd_query_prefix(sys.argv[2], sys.argv[3])
    elif cmd == "level":
        if len(sys.argv) < 4:
            print("用法: level <type> <id>")
            sys.exit(1)
        cmd_level(sys.argv[2], sys.argv[3])
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
