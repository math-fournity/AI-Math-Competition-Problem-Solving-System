#!/usr/bin/env python3
"""trace_checkpoints.py — 录入 checkpoint 关系（implements + specified-by + part-of）

从每个 checkpoint 文件提取：
  - 负责的WP → part-of 关系（checkpoint → wp）
  - 来源 → specified-by 关系（checkpoint → document）
  - 门类前缀 → implements 关系（checkpoint → code，按门类推断）

门类→代码文件推断规则：
  ENV-*    → src/config.py, src/continuation_config.py, .env.example
  SESS-*   → src/session_registry.py, src/continuation_db_schema.py
  LAUNCH-* → src/*_launcher.py, src/continuation_launcher.py
  MON-A*   → monitoring/analysis_control.py, monitoring/continuation_control.py
  MON-B*   → monitoring/continuation_control.py
  MON-C*   → monitoring/continuation_control.py
  EXEC-*   → src/monitor_continuation.py, src/continuation_launcher.py
  SELF-*   → src/monitor_continuation.py
  CTRL-*   → src/continuation_launcher.py, monitoring/continuation_control.py
  RUN-*    → scripts/monitor_check*.sh, monitoring/continuation_control.py
  AUDIT-*  → monitoring/verify_*.py, monitoring/reporter.py
  DOC-*    → docs/**/*.md
  HARD-*   → (贯穿全程，不关联具体代码)
  DEC-*    → (待决策，不关联代码)

用法：
    python3 scripts/trace_checkpoints.py
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACE_PY = REPO_ROOT / "scripts" / "trace.py"
CHECKLIST_DIR = REPO_ROOT / "checklist"


def add_relation(s_type, s_id, t_type, t_id, relation, note=""):
    cmd = ["python3", str(TRACE_PY), "add", s_type, s_id, t_type, t_id, relation]
    if note:
        cmd.append(note)
    subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def parse_checkpoint(md_path):
    """从 checkpoint 文件解析元数据"""
    content = md_path.read_text(encoding="utf-8")
    cp_id = md_path.stem

    # 提取 负责的WP
    wp_match = re.search(r"负责的WP\*\*:\s*(.+)", content)
    wps = []
    if wp_match:
        wp_text = wp_match.group(1).strip()
        wps = re.findall(r"WP-[\w-]+", wp_text)

    # 提取 来源
    src_match = re.search(r"来源\*\*:\s*(.+)", content)
    sources = []
    if src_match:
        src_text = src_match.group(1).strip()
        # 来源可能是文档名或章节引用
        sources = [s.strip() for s in src_text.split(",")]

    # 提取 门类
    cat_match = re.search(r"门类\*\*:\s*(\S+)", content)
    category = cat_match.group(1) if cat_match else ""

    return cp_id, wps, sources, category


# 门类→代码文件推断
CATEGORY_CODE_MAP = {
    "ENV": ["src/config.py", "src/continuation_config.py"],
    "SESS": ["src/session_registry.py", "src/continuation_db_schema.py"],
    "LAUNCH": ["src/analysis_launcher.py", "src/audit_launcher.py",
               "src/selection_launcher.py", "src/solver_launcher.py",
               "src/continuation_launcher.py"],
    "MON-A": ["monitoring/analysis_control.py", "monitoring/continuation_control.py"],
    "MON-B": ["monitoring/continuation_control.py"],
    "MON-C": ["monitoring/continuation_control.py"],
    "EXEC": ["src/monitor_continuation.py", "src/continuation_launcher.py"],
    "SELF": ["src/monitor_continuation.py"],
    "CTRL": ["src/continuation_launcher.py", "monitoring/continuation_control.py"],
    "RUN": ["monitoring/continuation_control.py"],
    "AUDIT": ["monitoring/verify_completeness.py", "monitoring/verify_result_integrity.py",
              "monitoring/reporter.py"],
    "DOC": [],  # 文档类，不关联代码
    "HARD": [],  # 贯穿全程
    "DEC": [],   # 待决策
}


def infer_code_files(cp_id, category):
    """根据 checkpoint 编号和门类推断关联的代码文件"""
    # 从编号提取门类前缀（如 MON-A1 → MON-A）
    parts = cp_id.split("-")
    if len(parts) < 2:
        return []

    # 处理 MON-A, MON-B, MON-C 等多段门类
    if parts[0] == "MON" and len(parts) > 1:
        prefix = f"MON-{parts[1][0]}"  # MON-A1 → MON-A
    else:
        prefix = parts[0]  # ENV → ENV

    return CATEGORY_CODE_MAP.get(prefix, [])


def infer_specified_by_docs(sources):
    """从来源字段推断文档路径"""
    docs = []
    for s in sources:
        s = s.strip()
        # 来源格式如 "AnalysisSystem.md §1/§7" 或 "p27_monitor_spec.md §2/§3"
        # 提取文档名
        doc_match = re.match(r"(\S+\.md)", s)
        if doc_match:
            doc_name = doc_match.group(1)
            # 尝试在 docs/ 下找到完整路径
            for candidate in [
                f"docs/system/{doc_name}",
                f"docs/specs/{doc_name}",
                f"docs/architecture/{doc_name}",
                f"docs/patterns/{doc_name}",
                doc_name,
                f"checklist/{doc_name}",
            ]:
                if (REPO_ROOT / candidate).exists():
                    docs.append(candidate)
                    break
            else:
                # 找不到完整路径，用文档名
                docs.append(doc_name)
    return docs


def main():
    partof_count = 0
    specifiedby_count = 0
    implements_count = 0

    for md in sorted(CHECKLIST_DIR.glob("*.md")):
        if md.name in ("README.md", "ExecDevin.md"):
            continue

        cp_id, wps, sources, category = parse_checkpoint(md)

        # part-of: checkpoint → wp
        for wp in wps:
            add_relation("checkpoint", cp_id, "wp", wp, "part-of", f"{cp_id}属于{wp}")
            partof_count += 1

        # specified-by: checkpoint → document
        docs = infer_specified_by_docs(sources)
        for doc in docs:
            add_relation("checkpoint", cp_id, "document", doc, "specified-by",
                         f"{cp_id}由{doc}规范定义")
            specifiedby_count += 1

        # implements: checkpoint → code（按门类推断）
        code_files = infer_code_files(cp_id, category)
        for code in code_files:
            add_relation("checkpoint", cp_id, "code", code, "implements",
                         f"{cp_id}由{code}实现")
            implements_count += 1

    print(f"checkpoint 关系录入完成：part-of {partof_count} + specified-by {specifiedby_count} + implements {implements_count} = {partof_count + specifiedby_count + implements_count} 条")


if __name__ == "__main__":
    main()
