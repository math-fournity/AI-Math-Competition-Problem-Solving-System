#!/usr/bin/env python3
"""enumerate_assets.py — 全repo资产枚举

扫描 repo 中所有资产，产出 asset_inventory.csv（全资产底表）。
作为 trace.csv 关系录入的基础——确保每个资产都被覆盖。

产出文件：scripts/asset_inventory.csv
列：asset_type, asset_id, file_path, description

扫描范围：
  src/*.py, monitoring/*.py          → code
  scripts/*.sh, scripts/*.py         → script
  docs/**/*.md                       → document
  checklist/*.md                     → checkpoint（从文件名提取编号）
  working-packages/WP-*.md           → wp
  dev-docs/*.md                      → dev-doc
  docs/templates/*.md                → template
  .env.example, src/config.py,
    src/continuation_config.py       → config
  git log --oneline --all            → commit
  config.py/continuation_config.py
    静态提取                          → db-collection, runtime-asset

用法：
    python3 scripts/enumerate_assets.py
"""

import csv
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_CSV = REPO_ROOT / "scripts" / "asset_inventory.csv"

FIELDS = ["asset_type", "asset_id", "file_path", "description"]


def collect_code():
    """src/*.py + monitoring/*.py → code"""
    assets = []
    for d in ["src", "monitoring"]:
        for p in sorted((REPO_ROOT / d).glob("*.py")):
            rel = str(p.relative_to(REPO_ROOT))
            desc = p.stem
            assets.append(("code", rel, rel, desc))
    return assets


def collect_scripts():
    """scripts/*.sh + scripts/*.py → script"""
    assets = []
    for p in sorted((REPO_ROOT / "scripts").glob("*.sh")):
        rel = str(p.relative_to(REPO_ROOT))
        assets.append(("script", rel, rel, p.stem))
    for p in sorted((REPO_ROOT / "scripts").glob("*.py")):
        rel = str(p.relative_to(REPO_ROOT))
        assets.append(("script", rel, rel, p.stem))
    return assets


def collect_documents():
    """docs/**/*.md → document（排除 templates/，templates 单独归类）"""
    assets = []
    for p in sorted((REPO_ROOT / "docs").rglob("*.md")):
        if "templates" in p.parts:
            continue
        rel = str(p.relative_to(REPO_ROOT))
        assets.append(("document", rel, rel, p.stem))
    return assets


def collect_checkpoints():
    """checklist/*.md → checkpoint（从文件名提取编号）"""
    assets = []
    for p in sorted((REPO_ROOT / "checklist").glob("*.md")):
        if p.name in ("README.md", "ExecDevin.md"):
            # README 和 ExecDevin 是索引文件，归为 document
            rel = str(p.relative_to(REPO_ROOT))
            assets.append(("document", rel, rel, p.stem))
            continue
        # 文件名即编号（如 ENV-01.md → ENV-01）
        cp_id = p.stem
        rel = str(p.relative_to(REPO_ROOT))
        assets.append(("checkpoint", cp_id, rel, f"checkpoint {cp_id}"))
    return assets


def collect_working_packages():
    """working-packages/WP-*.md → wp"""
    assets = []
    for p in sorted((REPO_ROOT / "working-packages").glob("*.md")):
        if p.name in ("README.md", "INDEX.md"):
            rel = str(p.relative_to(REPO_ROOT))
            assets.append(("document", rel, rel, p.stem))
            continue
        # WP-01-xxx.md → WP-01；WP-TRACE.md → WP-TRACE
        stem = p.stem
        m = re.match(r"(WP-[A-Z]+(?:-\d+)?(?:-TRACE)?)", stem)
        wp_id = m.group(1) if m else stem
        rel = str(p.relative_to(REPO_ROOT))
        assets.append(("wp", wp_id, rel, f"工作包 {wp_id}"))
    return assets


def collect_dev_docs():
    """dev-docs/*.md → dev-doc"""
    assets = []
    for p in sorted((REPO_ROOT / "dev-docs").glob("*.md")):
        rel = str(p.relative_to(REPO_ROOT))
        assets.append(("dev-doc", rel, rel, p.stem))
    return assets


def collect_templates():
    """docs/templates/*.md → template"""
    assets = []
    for p in sorted((REPO_ROOT / "docs" / "templates").glob("*.md")):
        rel = str(p.relative_to(REPO_ROOT))
        assets.append(("template", rel, rel, p.stem))
    return assets


def collect_configs():
    """.env.example, src/config.py, src/continuation_config.py → config"""
    assets = []
    config_files = [".env.example", "src/config.py", "src/continuation_config.py"]
    for f in config_files:
        p = REPO_ROOT / f
        if p.exists():
            assets.append(("config", f, f, p.stem))
    return assets


def collect_commits():
    """git log --oneline --all → commit"""
    assets = []
    result = subprocess.run(
        ["git", "log", "--oneline", "--all"],
        cwd=REPO_ROOT, capture_output=True, text=True
    )
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split(" ", 1)
        h = parts[0]
        msg = parts[1] if len(parts) > 1 else ""
        assets.append(("commit", h, "", msg[:80]))
    return assets


def collect_db_collections():
    """从 config.py + continuation_config.py 静态提取 DB collection 名"""
    assets = []
    # config.py 中的 collection 常量
    config_content = (REPO_ROOT / "src" / "config.py").read_text()
    for m in re.finditer(r'^(\w+_COLLECTION)\s*=\s*"(\w+)"', config_content, re.MULTILINE):
        const_name, col_name = m.group(1), m.group(2)
        assets.append(("db-collection", col_name, "src/config.py", f"{const_name}={col_name}"))
    # db_schema.py 中的额外 collection
    db_schema_content = (REPO_ROOT / "src" / "db_schema.py").read_text()
    for m in re.finditer(r'^(\w+_COLLECTION)\s*=\s*"(\w+)"', db_schema_content, re.MULTILINE):
        const_name, col_name = m.group(1), m.group(2)
        assets.append(("db-collection", col_name, "src/db_schema.py", f"{const_name}={col_name}"))
    # continuation_config.py 中的 collection 常量
    cont_content = (REPO_ROOT / "src" / "continuation_config.py").read_text()
    for m in re.finditer(r'^(\w+_COLLECTION)\s*=\s*"(\w+)"', cont_content, re.MULTILINE):
        const_name, col_name = m.group(1), m.group(2)
        assets.append(("db-collection", col_name, "src/continuation_config.py", f"{const_name}={col_name}"))
    # continuation_config.py 中的 SESSION_COUNTER_KEY（特殊：是文档key不是collection，但相关）
    for m in re.finditer(r'^SESSION_COUNTER_KEY\s*=\s*"(\w+)"', cont_content, re.MULTILINE):
        assets.append(("db-collection", m.group(1), "src/continuation_config.py", "session counter key"))
    # 去重（按 asset_id）
    seen = set()
    unique = []
    for a in assets:
        if a[1] not in seen:
            seen.add(a[1])
            unique.append(a)
    return unique


def collect_runtime_assets():
    """从 config.py + continuation_config.py 静态提取运行时路径常量"""
    assets = []
    # 环境变量输入（.env.example 中定义）
    env_vars = ["SOLVER_BASE", "TRAJECTORY_BASE", "DATASET_BASE", "KNOWLEDGE_BASE"]
    for v in env_vars:
        assets.append(("runtime-asset", v, ".env.example", f"环境变量 {v}"))
    # config.py 中的派生路径常量
    config_content = (REPO_ROOT / "src" / "config.py").read_text()
    derived_config = ["ANALYSIS_SOLVER_BASE", "ANALYSIS_TRAJECTORY_BASE", "OUTPUT_BASE"]
    for v in derived_config:
        assets.append(("runtime-asset", v, "src/config.py", f"派生路径 {v}"))
    # continuation_config.py 中的派生路径常量
    cont_content = (REPO_ROOT / "src" / "continuation_config.py").read_text()
    derived_cont = ["CONTINUATION_SOLVER_BASE", "CONTINUATION_TRAJECTORY_BASE",
                    "MONITOR_EXEC_EXPORT_BASE", "POC_2_7_DIR"]
    for v in derived_cont:
        assets.append(("runtime-asset", v, "src/continuation_config.py", f"派生路径 {v}"))
    return assets


def main():
    all_assets = []
    all_assets.extend(collect_code())
    all_assets.extend(collect_scripts())
    all_assets.extend(collect_documents())
    all_assets.extend(collect_checkpoints())
    all_assets.extend(collect_working_packages())
    all_assets.extend(collect_dev_docs())
    all_assets.extend(collect_templates())
    all_assets.extend(collect_configs())
    all_assets.extend(collect_commits())
    all_assets.extend(collect_db_collections())
    all_assets.extend(collect_runtime_assets())

    # 写 CSV
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for a in all_assets:
            w.writerow({"asset_type": a[0], "asset_id": a[1], "file_path": a[2], "description": a[3]})

    # 统计
    from collections import Counter
    by_type = Counter(a[0] for a in all_assets)
    print(f"资产枚举完成：{len(all_assets)} 个资产 → {OUTPUT_CSV}")
    print(f"\n按类型分布：")
    for t, c in by_type.most_common():
        print(f"  {t}: {c}")


if __name__ == "__main__":
    main()
