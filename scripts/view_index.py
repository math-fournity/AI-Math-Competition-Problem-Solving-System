#!/usr/bin/env python3
"""view_index.py — 看法文件与文档/代码/资产的映射索引（CSV后端，git可追踪）

记录"哪个看法文件索引了哪些文档/代码/资产"。
当文档/代码变更时，查表知道要更新哪些看法文件。
当看法文件要更新时，查表知道它索引了哪些文档。

数据存储在 view-index.csv（文本文件，git可逐行diff，保留完整变更历史）。

用法：
    python3 scripts/view_index.py list-views              # 列出所有分类法
    python3 scripts/view_index.py query-by-asset <path>   # 某文档变更时，查哪些看法文件需要更新
    python3 scripts/view_index.py query-by-view <view>    # 某看法文件索引了哪些文档
    python3 scripts/view_index.py add <taxonomy> <view_file> <asset_path> <asset_type> [title]  # 添加映射
    python3 scripts/view_index.py remove <view_file> <asset_path>  # 删除映射
    python3 scripts/view_index.py stats                   # 统计信息
"""

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "view-index.csv"

FIELDS = ["taxonomy", "view_file", "asset_path", "asset_type", "asset_title"]


def read_all():
    """读取全部记录，返回 list[dict]"""
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_all(rows):
    """写入全部记录"""
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def cmd_list_views():
    rows = read_all()
    if not rows:
        print(f"CSV为空：{CSV_PATH}")
        return
    from collections import Counter
    by_view = Counter()
    taxonomy_of = {}
    for r in rows:
        key = (r["taxonomy"], r["view_file"])
        by_view[key] += 1
        taxonomy_of[key] = r["taxonomy"]
    print(f"{'分类法':<12} {'看法文件':<35} {'索引数':>6}")
    print("-" * 60)
    for (taxonomy, view_file), count in sorted(by_view.items()):
        print(f"{taxonomy:<12} {view_file:<35} {count:>6}")


def cmd_query_by_asset(asset_path):
    rows = read_all()
    matches = [r for r in rows if r["asset_path"] == asset_path]
    if not matches:
        print(f"没有看法文件索引 {asset_path}")
        print("可能不需要更新任何看法文件，或者映射表未维护")
    else:
        print(f"文档 {asset_path} 被以下看法文件索引：")
        for r in matches:
            print(f"  [{r['taxonomy']}] {r['view_file']}")
            if r["asset_title"]:
                print(f"    标题：{r['asset_title']}")
        print(f"\n共 {len(matches)} 个看法文件需要检查更新")


def cmd_query_by_view(view_file):
    rows = read_all()
    matches = [r for r in rows if r["view_file"] == view_file]
    if not matches:
        print(f"看法文件 {view_file} 没有索引任何文档，或映射表未维护")
    else:
        print(f"看法文件 {view_file} 索引了以下 {len(matches)} 个文档/代码/资产：")
        for r in sorted(matches, key=lambda x: (x["asset_type"], x["asset_path"])):
            title = f" — {r['asset_title']}" if r["asset_title"] else ""
            print(f"  [{r['asset_type']}] {r['asset_path']}{title}")


def cmd_add(taxonomy, view_file, asset_path, asset_type, title=""):
    rows = read_all()
    # 检查是否已存在
    for r in rows:
        if r["view_file"] == view_file and r["asset_path"] == asset_path:
            print(f"已存在：{view_file} → {asset_path}（跳过）")
            return
    rows.append({
        "taxonomy": taxonomy, "view_file": view_file,
        "asset_path": asset_path, "asset_type": asset_type, "asset_title": title
    })
    # 排序：按 taxonomy, view_file, asset_path
    rows.sort(key=lambda r: (r["taxonomy"], r["view_file"], r["asset_path"]))
    write_all(rows)
    print(f"已添加：[{taxonomy}] {view_file} → {asset_path}")


def cmd_remove(view_file, asset_path):
    rows = read_all()
    before = len(rows)
    rows = [r for r in rows if not (r["view_file"] == view_file and r["asset_path"] == asset_path)]
    after = len(rows)
    write_all(rows)
    print(f"已删除 {before - after} 条映射：{view_file} → {asset_path}")


def cmd_stats():
    rows = read_all()
    if not rows:
        print(f"CSV为空：{CSV_PATH}")
        return
    from collections import Counter
    by_type = Counter(r["asset_type"] for r in rows)
    views = set(r["view_file"] for r in rows)
    taxonomies = set(r["taxonomy"] for r in rows)
    print(f"映射总数：{len(rows)}")
    print(f"分类法数：{len(taxonomies)}")
    print(f"看法文件数：{len(views)}")
    print(f"按类型分布：")
    for t, c in by_type.most_common():
        print(f"  {t}: {c}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list-views":
        cmd_list_views()
    elif cmd == "query-by-asset":
        if len(sys.argv) < 3:
            print("用法: query-by-asset <asset_path>")
            sys.exit(1)
        cmd_query_by_asset(sys.argv[2])
    elif cmd == "query-by-view":
        if len(sys.argv) < 3:
            print("用法: query-by-view <view_file>")
            sys.exit(1)
        cmd_query_by_view(sys.argv[2])
    elif cmd == "add":
        if len(sys.argv) < 6:
            print("用法: add <taxonomy> <view_file> <asset_path> <asset_type> [title]")
            sys.exit(1)
        title = sys.argv[6] if len(sys.argv) > 6 else ""
        cmd_add(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], title)
    elif cmd == "remove":
        if len(sys.argv) < 4:
            print("用法: remove <view_file> <asset_path>")
            sys.exit(1)
        cmd_remove(sys.argv[2], sys.argv[3])
    elif cmd == "stats":
        cmd_stats()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
