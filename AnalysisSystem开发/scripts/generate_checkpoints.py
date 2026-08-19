#!/usr/bin/env python3
"""
从 CheckList.md 解析所有需求点，在 CheckPoints/ 下为每个需求点生成一个详情文件。

用法：
    cd AnalysisSystem开发
    python3 scripts/generate_checkpoints.py

生成的文件结构：
    CheckPoints/<门类>/<编号>.md

文件名中 ! 替换为 -issue-（如 MON-A!01 → MON-A-issue-01.md）
"""

import re
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CHECKLIST = BASE_DIR / "CheckList.md"
CHECKPOINTS_DIR = BASE_DIR / "CheckPoints"

# 门类代号 → 子目录名映射
CATEGORY_DIRS = {
    "ENV": "ENV",
    "SESS": "SESS",
    "LAUNCH": "LAUNCH",
    "MON-A": "MON-A",
    "MON-B": "MON-B",
    "MON-C": "MON-C",
    "EXEC": "EXEC",
    "SELF": "SELF",
    "CTRL": "CTRL",
    "RUN": "RUN",
    "AUDIT": "AUDIT",
    "DOC": "DOC",
    "HARD": "HARD",
    "DEC": "DECISION",
}

# 门类中文名
CATEGORY_NAMES = {
    "ENV": "环境与基础设施",
    "SESS": "Session编号化管理",
    "LAUNCH": "Launcher启动与续传控制",
    "MON-A": "Monitor Pipe A类自动检查",
    "MON-B": "Monitor Pipe B类续传质量检查",
    "MON-C": "Monitor Pipe C类AI判断",
    "EXEC": "Monitor Exec Devin",
    "SELF": "Exec Devin self-check",
    "CTRL": "控制命令与查看支持",
    "RUN": "POC-2.7运行与监控",
    "AUDIT": "系统审计",
    "DOC": "文档同步",
    "HARD": "硬约束",
    "DEC": "待决策问题",
}

# 需求点编号的正则——匹配 | <门类>-<序号> 或 | <门类>-!<序号> 或 | <门类>-S<序号>
# 门类代号：ENV, SESS, LAUNCH, MON-A, MON-B, MON-C, EXEC, SELF, CTRL, RUN, AUDIT, DOC, HARD, DEC
ID_PATTERN = re.compile(
    r"^\|\s*"
    r"(ENV-\d+|SESS-\d+|LAUNCH-\d+|MON-A\d+|MON-A!\d+|MON-B\d+|MON-B\d+[a-z]|MON-C\d+|EXEC-\d+|SELF-S\d+|CTRL-\d+|RUN-\d+|AUDIT-\d+|DOC-\d+|HARD-\d+|DEC-\d+)"
    r"\s*\|"
)


def parse_category_from_id(req_id: str) -> str:
    """从需求点编号提取门类代号"""
    for cat in sorted(CATEGORY_DIRS.keys(), key=len, reverse=True):
        if req_id.startswith(cat + "-") or req_id.startswith(cat):
            # MON-A1 的门类是 MON-A，MON-A!01 的门类也是 MON-A
            if cat == "MON-A" and (req_id.startswith("MON-A")):
                return "MON-A"
            if cat == "MON-B" and req_id.startswith("MON-B"):
                return "MON-B"
            if cat == "MON-C" and req_id.startswith("MON-C"):
                return "MON-C"
            if req_id.startswith(cat + "-"):
                return cat
    # fallback
    if req_id.startswith("MON-A"):
        return "MON-A"
    if req_id.startswith("MON-B"):
        return "MON-B"
    if req_id.startswith("MON-C"):
        return "MON-C"
    raise ValueError(f"无法识别门类: {req_id}")


def safe_filename(req_id: str) -> str:
    """编号转文件名——! 替换为 -issue-"""
    return req_id.replace("!", "-issue-") + ".md"


def parse_table_row(line: str) -> dict:
    """解析表格行，返回 {id, columns: [所有列内容]}"""
    # 去掉首尾的 |，按 | 分割
    parts = line.strip().strip("|").split("|")
    parts = [p.strip() for p in parts]
    req_id = parts[0]
    return {"id": req_id, "columns": parts}


def find_section_title(lines: list, line_idx: int) -> str:
    """从表格行往上找最近的 ## 或 ### 标题"""
    for i in range(line_idx - 1, -1, -1):
        line = lines[i]
        if line.startswith("## ") or line.startswith("### "):
            return line.lstrip("# ").strip()
    return ""


def determine_wp_for_category(cat: str) -> str:
    """根据门类返回负责的WP"""
    wp_map = {
        "ENV": "WP-01, WP-09",
        "SESS": "WP-01",
        "LAUNCH": "WP-01, WP-02",
        "MON-A": "WP-02, WP-05",
        "MON-B": "WP-02, WP-05",
        "MON-C": "WP-05, WP-07",
        "EXEC": "WP-03, WP-04, WP-05",
        "SELF": "WP-04, WP-07",
        "CTRL": "WP-01, WP-06",
        "RUN": "WP-09",
        "AUDIT": "WP-10",
        "DOC": "WP-08",
        "HARD": "全部",
        "DEC": "实施时确定",
    }
    return wp_map.get(cat, "")


def generate_file_content(req_id: str, columns: list, section: str, cat: str) -> str:
    """生成单个需求点文件的内容"""
    cat_name = CATEGORY_NAMES.get(cat, cat)
    wp = determine_wp_for_category(cat)

    # 根据列数确定各字段
    # 大部分表格: | 编号 | 描述 | 来源 | 状态 | 验证方法 |
    # MON-A/B: | 编号 | 检查项 | alert_type | severity | 阈值 | 说明 |
    # MON-C: | 编号 | 检查项 | AI需要检查什么 | 通过标准 |
    # SELF: | 编号 | 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
    # HARD: | 编号 | 硬约束 | 来源 | 验证方法 |
    # DEC: | 编号 | 待决策问题 | 当前默认 | 需要决策的时机 |

    desc = ""
    source = ""
    status = "[ ]"
    verify = ""
    extra_fields = {}

    if cat in ("MON-A", "MON-B"):
        # 已知问题表格: | 编号 | 问题 | 状态 | WP |（4列）
        if "!" in req_id:
            if len(columns) >= 4:
                desc = columns[1]
                status = columns[2]
                extra_fields["对应WP"] = columns[3]
                source = "CheckList.md MON-A已知问题 / p27_monitor_pipe_operations.md §3.1.1"
        # 普通A/B类表格: | 编号 | 检查项 | alert_type | severity | 阈值 | 说明 |（6列）
        elif len(columns) >= 6:
            desc = columns[1]
            extra_fields["alert_type"] = columns[2]
            extra_fields["severity"] = columns[3]
            extra_fields["阈值"] = columns[4]
            extra_fields["说明"] = columns[5]
            source = "p27_monitor_spec.md §2/§3"
    elif cat == "MON-C":
        # | 编号 | 检查项 | AI需要检查什么 | 通过标准 |
        if len(columns) >= 4:
            desc = columns[1]
            extra_fields["AI需要检查什么"] = columns[2]
            extra_fields["通过标准"] = columns[3]
            source = "p27_monitor_spec.md §2.3"
    elif cat == "SELF":
        # | 编号 | 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
        if len(columns) >= 5:
            desc = columns[1]
            extra_fields["检查方法"] = columns[2]
            extra_fields["通过标准"] = columns[3]
            extra_fields["不通过时怎么办"] = columns[4]
            source = "p27_monitor_pipe_operations.md §4"
    elif cat == "HARD":
        # | 编号 | 硬约束 | 来源 | 验证方法 |
        if len(columns) >= 4:
            desc = columns[1]
            source = columns[2]
            verify = columns[3]
    elif cat == "DEC":
        # | 编号 | 待决策问题 | 当前默认 | 需要决策的时机 |
        if len(columns) >= 4:
            desc = columns[1]
            extra_fields["当前默认"] = columns[2]
            extra_fields["需要决策的时机"] = columns[3]
            source = "p27_session_management_and_polish_spec.md §G"
    else:
        # 通用格式: | 编号 | 描述 | 来源 | 状态 | 验证方法 |
        if len(columns) >= 5:
            desc = columns[1]
            source = columns[2]
            status = columns[3]
            verify = columns[4]
        elif len(columns) >= 3:
            desc = columns[1]
            source = columns[2] if len(columns) > 2 else ""

    # 状态标记检测——如果是 [x] 或 [!] 等
    for col in columns:
        if col.strip() in ("[ ]", "[x]", "[!]", "[~]", "[-]"):
            status = col.strip()
            break

    content = f"""# {req_id}: {desc}

> **门类**: {cat} · {cat_name}
> **状态**: {status}
> **负责的WP**: {wp}
> **来源**: {source}
> **所属章节**: {section}

## 需求描述

{desc}
"""

    if extra_fields:
        content += "\n## 详细信息\n\n"
        for key, val in extra_fields.items():
            content += f"- **{key}**: {val}\n"

    if verify:
        content += f"""
## 验证方法

{verify}
"""

    content += f"""
## 关联文件

- `AnalysisSystem开发/CheckList.md`（需求点全集）
- `AnalysisSystem开发/CheckList-ExecDevin.md`（如在本需求点在子集中）

## 变更记录

- v1 · 2026-08-19 · 初始创建（由 generate_checkpoints.py 从 CheckList.md 自动生成）
"""

    return content


def main():
    if not CHECKLIST.exists():
        print(f"错误: 找不到 {CHECKLIST}")
        return

    lines = CHECKLIST.read_text(encoding="utf-8").splitlines()

    generated = 0
    skipped = 0

    for i, line in enumerate(lines):
        m = ID_PATTERN.match(line)
        if not m:
            continue

        req_id = m.group(1)
        row = parse_table_row(line)
        cat = parse_category_from_id(req_id)
        section = find_section_title(lines, i)

        # 跳过分隔行（如 |---|---|）
        if req_id.startswith("---"):
            continue

        # 确定子目录
        subdir_name = CATEGORY_DIRS.get(cat)
        if not subdir_name:
            print(f"  跳过: 未知门类 {req_id}")
            skipped += 1
            continue

        subdir = CHECKPOINTS_DIR / subdir_name
        subdir.mkdir(parents=True, exist_ok=True)

        filename = safe_filename(req_id)
        filepath = subdir / filename

        content = generate_file_content(req_id, row["columns"], section, cat)
        filepath.write_text(content, encoding="utf-8")
        generated += 1
        print(f"  生成: {filepath.relative_to(BASE_DIR)}")

    print(f"\n完成: 生成 {generated} 个文件, 跳过 {skipped} 个")


if __name__ == "__main__":
    main()
