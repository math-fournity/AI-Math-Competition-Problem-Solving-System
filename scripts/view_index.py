#!/usr/bin/env python3
"""view_index.py — 看法文件与文档/代码/资产的映射索引（SQLite）

记录"哪个看法文件索引了哪些文档/代码/资产"。
当文档/代码变更时，查表知道要更新哪些看法文件。
当看法文件要更新时，查表知道它索引了哪些文档。

用法：
    python3 scripts/view_index.py init                    # 初始化数据库+建表
    python3 scripts/view_index.py list-views              # 列出所有分类法
    python3 scripts/view_index.py query-by-asset <path>   # 某文档变更时，查哪些看法文件需要更新
    python3 scripts/view_index.py query-by-view <view>    # 某看法文件索引了哪些文档
    python3 scripts/view_index.py add <taxonomy> <view_file> <asset_path> <asset_type> [title]  # 添加映射
    python3 scripts/view_index.py remove <view_file> <asset_path>  # 删除映射
    python3 scripts/view_index.py stats                   # 统计信息
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "view-index.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_init():
    """初始化数据库+建表"""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS view_index (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            taxonomy    TEXT NOT NULL,      -- 分类法名称，如"系统认知"、"源码"
            view_file   TEXT NOT NULL,      -- 看法文件路径，如"docs/system/README.md"
            asset_path  TEXT NOT NULL,      -- 文档/代码路径，如"docs/system/AnalysisSystem.md"
            asset_type  TEXT NOT NULL,      -- 类型：document/code/script/data
            asset_title TEXT,               -- 一句话标题（可选）
            UNIQUE(view_file, asset_path)
        );
        CREATE INDEX IF NOT EXISTS idx_asset ON view_index(asset_path);
        CREATE INDEX IF NOT EXISTS idx_view ON view_index(view_file);
        CREATE INDEX IF NOT EXISTS idx_taxonomy ON view_index(taxonomy);
    """)
    conn.commit()
    conn.close()
    print(f"数据库已初始化：{DB_PATH}")


def cmd_list_views():
    """列出所有分类法"""
    conn = get_db()
    rows = conn.execute("""
        SELECT taxonomy, view_file, COUNT(*) as asset_count
        FROM view_index
        GROUP BY taxonomy, view_file
        ORDER BY taxonomy
    """).fetchall()
    if not rows:
        print("数据库为空，先 add 映射或 init + 导入")
        conn.close()
        return
    print(f"{'分类法':<12} {'看法文件':<35} {'索引数':>6}")
    print("-" * 60)
    for r in rows:
        print(f"{r['taxonomy']:<12} {r['view_file']:<35} {r['asset_count']:>6}")
    conn.close()


def cmd_query_by_asset(asset_path: str):
    """某文档变更时，查哪些看法文件需要更新"""
    conn = get_db()
    rows = conn.execute("""
        SELECT taxonomy, view_file, asset_title
        FROM view_index
        WHERE asset_path = ?
        ORDER BY taxonomy
    """, (asset_path,)).fetchall()
    if not rows:
        print(f"没有看法文件索引 {asset_path}")
        print("可能不需要更新任何看法文件，或者映射表未维护")
    else:
        print(f"文档 {asset_path} 被以下看法文件索引：")
        for r in rows:
            print(f"  [{r['taxonomy']}] {r['view_file']}")
            if r['asset_title']:
                print(f"    标题：{r['asset_title']}")
        print(f"\n共 {len(rows)} 个看法文件需要检查更新")
    conn.close()


def cmd_query_by_view(view_file: str):
    """某看法文件索引了哪些文档"""
    conn = get_db()
    rows = conn.execute("""
        SELECT asset_path, asset_type, asset_title
        FROM view_index
        WHERE view_file = ?
        ORDER BY asset_type, asset_path
    """, (view_file,)).fetchall()
    if not rows:
        print(f"看法文件 {view_file} 没有索引任何文档，或映射表未维护")
    else:
        print(f"看法文件 {view_file} 索引了以下 {len(rows)} 个文档/代码/资产：")
        for r in rows:
            title = f" — {r['asset_title']}" if r['asset_title'] else ""
            print(f"  [{r['asset_type']}] {r['asset_path']}{title}")
    conn.close()


def cmd_add(taxonomy: str, view_file: str, asset_path: str, asset_type: str, title: str = ""):
    """添加映射"""
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO view_index (taxonomy, view_file, asset_path, asset_type, asset_title)
            VALUES (?, ?, ?, ?, ?)
        """, (taxonomy, view_file, asset_path, asset_type, title))
        conn.commit()
        print(f"已添加：[{taxonomy}] {view_file} → {asset_path}")
    except sqlite3.IntegrityError:
        print(f"已存在：{view_file} → {asset_path}（跳过）")
    conn.close()


def cmd_remove(view_file: str, asset_path: str):
    """删除映射"""
    conn = get_db()
    cur = conn.execute("DELETE FROM view_index WHERE view_file=? AND asset_path=?", (view_file, asset_path))
    conn.commit()
    print(f"已删除 {cur.rowcount} 条映射：{view_file} → {asset_path}")
    conn.close()


def cmd_stats():
    """统计信息"""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM view_index").fetchone()[0]
    views = conn.execute("SELECT COUNT(DISTINCT view_file) FROM view_index").fetchone()[0]
    taxonomies = conn.execute("SELECT COUNT(DISTINCT taxonomy) FROM view_index").fetchone()[0]
    by_type = conn.execute("""
        SELECT asset_type, COUNT(*) as c
        FROM view_index
        GROUP BY asset_type
        ORDER BY c DESC
    """).fetchall()
    conn.close()
    print(f"映射总数：{total}")
    print(f"分类法数：{taxonomies}")
    print(f"看法文件数：{views}")
    print(f"按类型分布：")
    for r in by_type:
        print(f"  {r['asset_type']}: {r['c']}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "init":
        cmd_init()
    elif cmd == "list-views":
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
