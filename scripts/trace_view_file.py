#!/usr/bin/env python3
"""trace_view_file.py — 录入 view-file 相关关系到 trace.csv

录入3种关系：
  indexes:    view-file → document/code/script/data（看法文件索引哪些资产）
  indexed-by: document/code/script/data → view-file（反向，被看法文件索引）
  organizes:  document README.md → view-file（默认看法组织看法文件）

从 view-index.csv 读取映射，批量录入到 trace.csv。

用法：
    python3 scripts/trace_view_file.py
"""

import csv
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACE_PY = REPO_ROOT / "scripts" / "trace.py"
VIEW_INDEX_CSV = REPO_ROOT / "view-index.csv"


def add_relation(s_type, s_id, t_type, t_id, relation, note=""):
    cmd = ["python3", str(TRACE_PY), "add", s_type, s_id, t_type, t_id, relation]
    if note:
        cmd.append(note)
    subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def main():
    if not VIEW_INDEX_CSV.exists():
        print(f"错误：{VIEW_INDEX_CSV} 不存在")
        return

    with open(VIEW_INDEX_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    indexes_count = 0
    organizes_count = 0

    for r in rows:
        view_file = r["view_file"]
        asset_path = r["asset_path"]
        asset_type = r["asset_type"]

        # indexes: view-file → asset
        add_relation("view-file", view_file, asset_type, asset_path, "indexes",
                     f"{view_file}索引{asset_path}")
        indexes_count += 1

    # organizes: README.md → view-file（每个看法文件被README.md组织）
    view_files = set(r["view_file"] for r in rows)
    for vf in sorted(view_files):
        add_relation("document", "README.md", "view-file", vf, "organizes",
                     f"README.md组织{vf}")
        organizes_count += 1

    print(f"view-file 关系录入完成：indexes {indexes_count} + organizes {organizes_count} = {indexes_count + organizes_count} 条")


if __name__ == "__main__":
    main()
