#!/usr/bin/env python3
"""trace_wp_devdoc.py — 录入 dev-doc/wp 关系（produces + changes + comes-from + creates）

1. creates: WP → checkpoint（从已有 part-of 关系反推）
2. comes-from: WP → dev-doc（扫描 WP 文件内容中的 dev-docs/ 引用）
3. produces/changes: dev-doc → document/code（扫描 dev-doc 内容中的文件路径引用）

用法：
    python3 scripts/trace_wp_devdoc.py
"""

import csv
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACE_PY = REPO_ROOT / "scripts" / "trace.py"
TRACE_CSV = REPO_ROOT / "trace.csv"
WP_DIR = REPO_ROOT / "working-packages"
DEVDOCS_DIR = REPO_ROOT / "dev-docs"


def add_relation(s_type, s_id, t_type, t_id, relation, note=""):
    cmd = ["python3", str(TRACE_PY), "add", s_type, s_id, t_type, t_id, relation]
    if note:
        cmd.append(note)
    subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def derive_creates_from_partof():
    """从已有 part-of 关系反推 creates 关系"""
    with open(TRACE_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    creates_pairs = set()
    for r in rows:
        if r["relation"] == "part-of" and r["source_type"] == "checkpoint" and r["target_type"] == "wp":
            cp = r["source_id"]
            wp = r["target_id"]
            creates_pairs.add((wp, cp))

    count = 0
    for wp, cp in sorted(creates_pairs):
        add_relation("wp", wp, "checkpoint", cp, "creates", f"{wp}创建checkpoint {cp}")
        count += 1
    return count


def scan_wp_comes_from():
    """扫描 WP 文件内容中的 dev-docs/ 引用"""
    count = 0
    for md in sorted(WP_DIR.glob("WP-*.md")):
        wp_id = md.stem
        content = md.read_text(encoding="utf-8")
        # 找 dev-docs/xxx.md 引用
        refs = re.findall(r"dev-docs/[\w.-]+\.md", content)
        for ref in set(refs):
            add_relation("wp", wp_id, "dev-doc", ref, "comes-from", f"{wp_id}引用{ref}")
            count += 1
    return count


def scan_devdoc_produces_changes():
    """扫描 dev-doc 内容中的文件路径引用，补充 produces/changes 关系"""
    count = 0
    # 已知的代码/文档/脚本路径模式
    path_patterns = [
        (r"src/[\w/]+\.py", "code"),
        (r"monitoring/[\w/]+\.py", "code"),
        (r"scripts/[\w/]+\.py", "script"),
        (r"scripts/[\w/]+\.sh", "script"),
        (r"docs/[\w/]+\.md", "document"),
        (r"checklist/[\w/]+\.md", "document"),
        (r"working-packages/[\w/]+\.md", "document"),
    ]

    for md in sorted(DEVDOCS_DIR.glob("*.md")):
        devdoc_id = str(md.relative_to(REPO_ROOT))
        content = md.read_text(encoding="utf-8")

        for pattern, asset_type in path_patterns:
            refs = re.findall(pattern, content)
            for ref in set(refs):
                # produces: dev-doc → document
                if asset_type == "document":
                    add_relation("dev-doc", devdoc_id, "document", ref, "produces",
                                 f"{devdoc_id}提及{ref}")
                # changes: dev-doc → code/script
                else:
                    add_relation("dev-doc", devdoc_id, asset_type, ref, "changes",
                                 f"{devdoc_id}提及{ref}")
                count += 1
    return count


def main():
    creates_count = derive_creates_from_partof()
    comesfrom_count = scan_wp_comes_from()
    produces_changes_count = scan_devdoc_produces_changes()

    print(f"dev-doc/wp 关系录入完成：creates {creates_count} + comes-from {comesfrom_count} + produces/changes {produces_changes_count} = {creates_count + comesfrom_count + produces_changes_count} 条")


if __name__ == "__main__":
    main()
