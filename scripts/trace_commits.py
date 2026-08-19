#!/usr/bin/env python3
"""trace_commits.py — 录入 changed-in 关系（资产→commit）

用 git log --name-only --all 提取每个 commit 改动的文件，
生成 changed-in 关系：<type> <file> changed-in commit <hash>

文件类型推断：
  .py in src/ or monitoring/ → code
  .py in scripts/            → script
  .sh in scripts/            → script
  .md in docs/               → document
  .md in checklist/          → checkpoint（用文件名编号作为id）
  .md in working-packages/   → wp（用WP编号作为id）
  .md in dev-docs/           → dev-doc
  .md in docs/templates/     → template
  .env.example, config.py    → config
  trace.csv, asset_inventory.csv → data
  AGENTS.md, README.md       → document

用法：
    python3 scripts/trace_commits.py
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACE_PY = REPO_ROOT / "scripts" / "trace.py"


def add_relation(s_type, s_id, t_type, t_id, relation, note="", commit_id=""):
    cmd = ["python3", str(TRACE_PY), "add", s_type, s_id, t_type, t_id, relation]
    if note:
        cmd.append(note)
    if commit_id:
        cmd.append(commit_id)
    subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def infer_asset_type(file_path):
    """从文件路径推断资产类型和id"""
    if not file_path or file_path == "/dev/null":
        return None, None

    p = Path(file_path)

    # 代码
    if p.suffix == ".py":
        if file_path.startswith("src/") or file_path.startswith("monitoring/"):
            return "code", file_path
        if file_path.startswith("scripts/"):
            return "script", file_path
        return "code", file_path

    # 脚本
    if p.suffix == ".sh":
        return "script", file_path

    # 文档类
    if p.suffix == ".md":
        if file_path.startswith("checklist/"):
            if p.name in ("README.md", "ExecDevin.md"):
                return "document", file_path
            return "checkpoint", p.stem
        if file_path.startswith("working-packages/"):
            if p.name in ("README.md", "INDEX.md"):
                return "document", file_path
            # WP-01-xxx.md → WP-01
            import re
            m = re.match(r"(WP-[A-Z]+(?:-\d+)?(?:-TRACE)?)", p.stem)
            return "wp", m.group(1) if m else p.stem
        if file_path.startswith("dev-docs/"):
            return "dev-doc", file_path
        if file_path.startswith("docs/templates/"):
            return "template", file_path
        return "document", file_path

    # 配置
    if file_path == ".env.example":
        return "config", file_path
    if file_path == "src/config.py" or file_path == "src/continuation_config.py":
        return "config", file_path

    # 数据
    if file_path in ("trace.csv", "scripts/asset_inventory.csv"):
        return "data", file_path

    # 其他
    if file_path in ("AGENTS.md", "README.md", ".gitignore"):
        return "document", file_path

    # 默认
    return "data", file_path


def main():
    # git log --name-only --all，格式：commit行 + 空行 + 文件列表 + 空行
    result = subprocess.run(
        ["git", "log", "--name-only", "--all", "--pretty=format:COMMIT %H %s"],
        cwd=REPO_ROOT, capture_output=True, text=True
    )

    lines = result.stdout.split("\n")
    count = 0
    current_hash = None
    current_msg = ""

    for line in lines:
        line = line.strip()
        if line.startswith("COMMIT "):
            parts = line.split(" ", 2)
            current_hash = parts[1]
            current_msg = parts[2] if len(parts) > 2 else ""
        elif line and current_hash:
            # 这是一个被改动的文件
            asset_type, asset_id = infer_asset_type(line)
            if asset_type:
                add_relation(asset_type, asset_id, "commit", current_hash[:7],
                             "changed-in", current_msg[:60], current_hash[:7])
                count += 1

    print(f"changed-in 关系录入完成：{count} 条")


if __name__ == "__main__":
    main()
