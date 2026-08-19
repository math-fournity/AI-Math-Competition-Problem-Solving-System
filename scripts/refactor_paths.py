#!/usr/bin/env python3
"""refactor_paths.py — 目录重组后的文档引用路径批量替换

按 dev-docs/001 方案§5.1 的13条规则，批量更新所有 .md 文件中的路径引用。
长路径先替换，避免短路径误匹配。

用法：
    python3 scripts/refactor_paths.py          # 执行替换
    python3 scripts/refactor_paths.py --dry    # 只预览，不写文件
"""

import re
import sys
from pathlib import Path

# 13条替换规则（按优先级排序，长路径先替换）
RULES = [
    # 规则1-8：处理 analysis-devin-failure-system/ 和 AnalysisSystem开发/ 前缀
    ("analysis-devin-failure-system/docs/", "docs/architecture/"),
    ("analysis-devin-failure-system/specs/", "docs/specs/"),
    ("analysis-devin-failure-system/templates/", "docs/templates/"),
    ("analysis-devin-failure-system/scripts/", "scripts/"),
    ("analysis-devin-failure-system/monitoring/", "monitoring/"),
    ("analysis-devin-failure-system/src/", "src/"),
    # 规则7：单独出现的 analysis-devin-failure-system（如 cd 命令）
    # 注意：此时前面的子路径已替换完，剩下的 analysis-devin-failure-system/ 都是目录本身
    ("analysis-devin-failure-system/", ""),
    # 规则8：中文目录名
    ("AnalysisSystem开发/", "dev/"),
    # 规则9-13：根 docs/ 下的文件移到子目录
    ("docs/AnalysisSystem.md", "docs/system/AnalysisSystem.md"),
    ("docs/AnalysisSystemDesign.md", "docs/system/AnalysisSystemDesign.md"),
    ("docs/AnalysisSystemOps.md", "docs/system/AnalysisSystemOps.md"),
    ("docs/MonitorPipe.md", "docs/patterns/MonitorPipe.md"),
    ("docs/续传规范文档.md", "docs/patterns/续传规范文档.md"),
]


def process_file(filepath: Path, dry_run: bool) -> dict:
    """处理单个文件，返回各规则的替换计数"""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return {"error": str(e)}

    original = content
    counts = {}

    for old, new in RULES:
        count = content.count(old)
        if count > 0:
            content = content.replace(old, new)
            counts[old] = count

    if content != original:
        if not dry_run:
            filepath.write_text(content, encoding="utf-8")
        return {"changed": True, "counts": counts, "dry": dry_run}
    return {"changed": False}


def main():
    dry_run = "--dry" in sys.argv
    repo_root = Path(__file__).resolve().parent.parent

    # 遍历所有 .md 文件（排除 .venv、.git、dev-docs）
    exclude_dirs = {".venv", ".git", "dev-docs", "__pycache__"}
    md_files = []
    for f in repo_root.rglob("*.md"):
        if not any(part in exclude_dirs for part in f.parts):
            md_files.append(f)

    md_files.sort()
    print(f"扫描 {len(md_files)} 个 .md 文件")
    print(f"模式: {'预览(dry-run)' if dry_run else '实际替换'}")
    print("=" * 60)

    total_replacements = 0
    total_files_changed = 0
    rule_totals = {}

    for f in md_files:
        result = process_file(f, dry_run)
        if "error" in result:
            print(f"  错误 {f}: {result['error']}")
            continue
        if result.get("changed"):
            total_files_changed += 1
            rel = f.relative_to(repo_root)
            counts = result["counts"]
            file_total = sum(counts.values())
            total_replacements += file_total
            print(f"  {rel}: {file_total} 处替换")
            for old, count in counts.items():
                rule_totals[old] = rule_totals.get(old, 0) + count
                print(f"    {old} → ... : {count}")

    print("=" * 60)
    print(f"总计: {total_files_changed} 个文件, {total_replacements} 处替换")
    print("\n各规则替换统计:")
    for old, new in RULES:
        total = rule_totals.get(old, 0)
        if total > 0:
            print(f"  {old:50s} → {new:40s} : {total}")


if __name__ == "__main__":
    main()
