#!/usr/bin/env python3
"""refactor_paths_pass2.py — 第二轮替换：处理 cd analysis-devin-failure-system 残留

第一轮替换了带斜杠的路径，但 `cd analysis-devin-failure-system`（行尾无斜杠）
和 `cd ../../analysis-devin-failure-system` 没被替换。扁平化后不需要 cd 进子系统，
直接删掉 cd 前缀即可。

用法：
    python3 scripts/refactor_paths_pass2.py          # 执行替换
    python3 scripts/refactor_paths_pass2.py --dry    # 只预览
"""

import re
import sys
from pathlib import Path

# 替换规则：cd analysis-devin-failure-system 相关
RULES = [
    # cd ../../analysis-devin-failure-system → cd ..（从子目录回到根）
    # 实际上这些命令原本是从 docs/system/ 等子目录 cd 进子系统，现在子系统没了，cd 到根即可
    # 但更准确的是：这些命令在文档中是"从某处 cd 到子系统"，扁平化后子系统=根，所以 cd 到根
    # 简单处理：删除 cd ../../analysis-devin-failure-system，改为 cd ..（回到repo根）
    ("cd ../../analysis-devin-failure-system", "cd .."),
    # cd analysis-devin-failure-system → 删除（已在根目录，不需要cd）
    ("cd analysis-devin-failure-system ", ""),
    ("cd analysis-devin-failure-system\n", "\n"),
    ("cd analysis-devin-failure-system$", ""),
    # analysis-devin-failure-system 作为目录名引用（非路径）→ 根目录
    # 注意：这里只处理剩余的裸词引用，路径已在第一轮处理
]


def process_file(filepath: Path, dry_run: bool) -> dict:
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

    # 用正则处理 cd analysis-devin-failure-system 在行尾的情况
    remaining = re.findall(r"cd analysis-devin-failure-system", content)
    if remaining:
        content = re.sub(r"cd analysis-devin-failure-system\b", "", content)
        counts["cd analysis-devin-failure-system (regex)"] = len(remaining)

    if content != original:
        if not dry_run:
            filepath.write_text(content, encoding="utf-8")
        return {"changed": True, "counts": counts}
    return {"changed": False}


def main():
    dry_run = "--dry" in sys.argv
    repo_root = Path(__file__).resolve().parent.parent

    exclude_dirs = {".venv", ".git", "dev-docs", "__pycache__"}
    md_files = []
    for f in repo_root.rglob("*.md"):
        if not any(part in exclude_dirs for part in f.parts):
            md_files.append(f)

    md_files.sort()
    print(f"扫描 {len(md_files)} 个 .md 文件（排除 dev-docs）")
    print(f"模式: {'预览(dry-run)' if dry_run else '实际替换'}")
    print("=" * 60)

    total_replacements = 0
    total_files_changed = 0

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
                print(f"    {old[:50]:50s} : {count}")

    print("=" * 60)
    print(f"总计: {total_files_changed} 个文件, {total_replacements} 处替换")


if __name__ == "__main__":
    main()
