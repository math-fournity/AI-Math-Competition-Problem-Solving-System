#!/usr/bin/env python3
"""generate_checkpoint.py — 生成单个 checkpoint 模板文件

在 checklist/ 下为指定编号生成一个模板文件。如果文件已存在则跳过（不覆盖）。

用法：
    python3 scripts/generate_checkpoint.py ENV-07
    python3 scripts/generate_checkpoint.py MON-A13
    python3 scripts/generate_checkpoint.py SELF-S18

生成的文件：
    checklist/<编号>.md（编号中 ! 替换为 -issue-）

文件名中 ! 替换为 -issue-（如 MON-A!01 → MON-A-issue-01.md）
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKLIST_DIR = REPO_ROOT / "checklist"

# 门类代号 → 中文名 映射
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

# 门类代号 → 负责的WP
CATEGORY_WPS = {
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


def parse_category(req_id: str) -> str:
    """从需求点编号提取门类代号"""
    for cat in sorted(CATEGORY_NAMES.keys(), key=len, reverse=True):
        if req_id.startswith(cat + "-") or req_id.startswith(cat):
            return cat
    raise ValueError(f"无法识别门类: {req_id}")


def safe_filename(req_id: str) -> str:
    """编号转文件名——! 替换为 -issue-"""
    return req_id.replace("!", "-issue-") + ".md"


def generate_template(req_id: str) -> str:
    """生成单个 checkpoint 模板文件内容"""
    cat = parse_category(req_id)
    cat_name = CATEGORY_NAMES.get(cat, cat)
    wp = CATEGORY_WPS.get(cat, "")

    return f"""# {req_id}: <一句话描述>

> **门类**: {cat} · {cat_name}
> **状态**: [ ]
> **负责的WP**: {wp}
> **来源**: <这个 checkpoint 从哪个文档/规范中提取>

## 需求描述

<这个 checkpoint 要求什么>

## 验证方法

<如何验证这个 checkpoint 已满足>

## 涉及的文档和代码

- <关联的设计文档、规范、代码文件>

## 变更记录

- v1 · <日期> · 初始创建
"""


def main():
    if len(sys.argv) < 2:
        print("用法: python3 scripts/generate_checkpoint.py <编号>")
        print("示例: python3 scripts/generate_checkpoint.py ENV-07")
        print("      python3 scripts/generate_checkpoint.py MON-A13")
        sys.exit(1)

    req_id = sys.argv[1]

    # 验证编号格式
    if not re.match(r"^[A-Z]+(-[A-Z])?[-!]", req_id):
        print(f"错误: 编号格式不正确: {req_id}")
        print("格式: <门类代号>-<序号>，如 ENV-07、MON-A13、SELF-S18")
        sys.exit(1)

    filename = safe_filename(req_id)
    filepath = CHECKLIST_DIR / filename

    if filepath.exists():
        print(f"跳过: {filepath} 已存在（不覆盖）")
        sys.exit(0)

    if not CHECKLIST_DIR.exists():
        print(f"错误: checklist/ 目录不存在: {CHECKLIST_DIR}")
        sys.exit(1)

    content = generate_template(req_id)
    filepath.write_text(content, encoding="utf-8")
    print(f"生成: {filepath.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
