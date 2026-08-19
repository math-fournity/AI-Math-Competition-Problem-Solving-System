#!/usr/bin/env python3
"""trace_contains.py — 录入 contains 关系（文件→函数/章节）

扫描所有代码文件的 def 行和所有文档文件的 ## 行，
生成 contains 关系并调用 trace.py add 录入。

关系：
  code <file> contains code <file>::<function>
  document <file> contains document <file>#<section>

用法：
    python3 scripts/trace_contains.py
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACE_PY = REPO_ROOT / "scripts" / "trace.py"


def extract_functions(py_path):
    """从 Python 文件提取顶层 def/class 名"""
    content = py_path.read_text(encoding="utf-8")
    symbols = []
    for m in re.finditer(r"^(class|def)\s+(\w+)", content, re.MULTILINE):
        kind, name = m.group(1), m.group(2)
        symbols.append((kind, name))
    return symbols


def extract_sections(md_path):
    """从 Markdown 文件提取 ## 和 ### 级标题"""
    content = md_path.read_text(encoding="utf-8")
    sections = []
    for m in re.finditer(r"^(#{2,3})\s+(.+)$", content, re.MULTILINE):
        level, title = m.group(1), m.group(2).strip()
        sections.append((level, title))
    return sections


def add_relation(s_type, s_id, t_type, t_id, relation, note=""):
    cmd = ["python3", str(TRACE_PY), "add", s_type, s_id, t_type, t_id, relation]
    if note:
        cmd.append(note)
    subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def main():
    code_count = 0
    doc_count = 0

    # === 代码文件 → 函数 ===
    for d in ["src", "monitoring"]:
        for py in sorted((REPO_ROOT / d).glob("*.py")):
            rel = str(py.relative_to(REPO_ROOT))
            symbols = extract_functions(py)
            for kind, name in symbols:
                if kind == "class":
                    target = f"{rel}::{name}"
                else:
                    target = f"{rel}::{name}"
                add_relation("code", rel, "code", target, "contains")
                code_count += 1

    # === 文档文件 → 章节 ===
    # docs/**/*.md（排除 templates）
    for py in sorted((REPO_ROOT / "docs").rglob("*.md")):
        if "templates" in py.parts:
            continue
        rel = str(py.relative_to(REPO_ROOT))
        sections = extract_sections(py)
        for level, title in sections:
            # 章节id：文件路径#章节标题
            target = f"{rel}#{title}"
            add_relation("document", rel, "document", target, "contains")
            doc_count += 1

    # checklist/*.md（README 和 ExecDevin 归为 document）
    for md in sorted((REPO_ROOT / "checklist").glob("*.md")):
        rel = str(md.relative_to(REPO_ROOT))
        sections = extract_sections(md)
        for level, title in sections:
            target = f"{rel}#{title}"
            add_relation("document", rel, "document", target, "contains")
            doc_count += 1

    # working-packages/*.md
    for md in sorted((REPO_ROOT / "working-packages").glob("*.md")):
        rel = str(md.relative_to(REPO_ROOT))
        sections = extract_sections(md)
        for level, title in sections:
            target = f"{rel}#{title}"
            add_relation("document", rel, "document", target, "contains")
            doc_count += 1

    # dev-docs/*.md
    for md in sorted((REPO_ROOT / "dev-docs").glob("*.md")):
        rel = str(md.relative_to(REPO_ROOT))
        sections = extract_sections(md)
        for level, title in sections:
            target = f"{rel}#{title}"
            add_relation("document", rel, "document", target, "contains")
            doc_count += 1

    print(f"contains 关系录入完成：代码函数 {code_count} 条 + 文档章节 {doc_count} 条 = {code_count + doc_count} 条")


if __name__ == "__main__":
    main()
