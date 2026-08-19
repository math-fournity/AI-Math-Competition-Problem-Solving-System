#!/usr/bin/env python3
"""trace_infra.py — 录入基础设施层关系

录入5种关系：
  reads-from:   code → db-collection（代码读哪些DB表）
  writes-to:    code → db-collection（代码写哪些DB表）
  configures:   config → code（配置项被哪些代码引用）
  generates:    code → runtime-asset（代码生成哪些运行时产物）
  uses-template: code → template（launcher用哪个prompt模板）

方法：
  - grep 代码中的 collection 常量引用 → reads-from/writes-to
  - grep 代码中的 from .config import / from .continuation_config import → configures
  - grep 代码中的路径常量引用 → generates
  - grep 代码中的模板常量引用 → uses-template

用法：
    python3 scripts/trace_infra.py
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACE_PY = REPO_ROOT / "scripts" / "trace.py"


def add_relation(s_type, s_id, t_type, t_id, relation, note=""):
    cmd = ["python3", str(TRACE_PY), "add", s_type, s_id, t_type, t_id, relation]
    if note:
        cmd.append(note)
    subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


# DB collection 名清单（从 config.py + continuation_config.py + db_schema.py 提取）
DB_COLLECTIONS = [
    "analysis_batches", "analysis_runs", "analysis_events", "analysis_results",
    "analysis_counters", "p27_continuation_batches", "p27_continuation_runs",
    "p27_continuation_events", "p27_continuation_results", "p27_monitor_alerts",
    "p27_sessions", "p27_session_counter",
]

# 运行资产常量名清单
RUNTIME_ASSETS = [
    "SOLVER_BASE", "TRAJECTORY_BASE", "DATASET_BASE", "KNOWLEDGE_BASE",
    "ANALYSIS_SOLVER_BASE", "ANALYSIS_TRAJECTORY_BASE", "OUTPUT_BASE",
    "CONTINUATION_SOLVER_BASE", "CONTINUATION_TRAJECTORY_BASE",
    "MONITOR_EXEC_EXPORT_BASE", "POC_2_7_DIR",
]

# 模板文件清单
TEMPLATES = [
    "docs/templates/analysis_agents_md.md",
    "docs/templates/audit_agents_md.md",
    "docs/templates/selection_agents_md.md",
    "docs/templates/selfrun_subagent_task.md",
]


def scan_db_relations():
    """扫描代码中的 DB collection 引用，生成 reads-from/writes-to 关系"""
    count = 0
    # 扫描所有 .py 文件
    for d in ["src", "monitoring"]:
        for py in sorted((REPO_ROOT / d).glob("*.py")):
            rel = str(py.relative_to(REPO_ROOT))
            content = py.read_text(encoding="utf-8")

            for col in DB_COLLECTIONS:
                # 检查是否引用了这个 collection
                if col in content:
                    # 判断是读还是写：insert/update/create → writes-to；query/get/find → reads-from
                    # 简化判断：如果文件中有 insert/update/create 操作引用该 collection，则 writes-to
                    # 如果有 query/get/find/aql 操作，则 reads-from
                    # 大多数文件既读又写，所以两个关系都加
                    has_write = bool(re.search(
                        r"(insert|update|create|delete|remove|upsert).*" + re.escape(col),
                        content, re.DOTALL))
                    has_read = bool(re.search(
                        r"(query|get|find|aql|execute|fetch|has).*" + re.escape(col),
                        content, re.DOTALL))

                    if has_write:
                        add_relation("code", rel, "db-collection", col, "writes-to",
                                     f"{rel}写入{col}")
                        count += 1
                    if has_read:
                        add_relation("code", rel, "db-collection", col, "reads-from",
                                     f"{rel}读取{col}")
                        count += 1
                    if not has_write and not has_read:
                        # 引用了但无法判断读写，默认两个都加
                        add_relation("code", rel, "db-collection", col, "reads-from",
                                     f"{rel}引用{col}")
                        count += 1
    return count


def scan_configures():
    """扫描代码中的 from .config import / from .continuation_config import，生成 configures 关系"""
    count = 0
    config_files = {
        "src/config.py": [".config", "from .config", "from src.config", "import config"],
        "src/continuation_config.py": [".continuation_config", "from .continuation_config",
                                        "from src.continuation_config", "import continuation_config"],
    }

    for d in ["src", "monitoring"]:
        for py in sorted((REPO_ROOT / d).glob("*.py")):
            rel = str(py.relative_to(REPO_ROOT))
            content = py.read_text(encoding="utf-8")

            for config_path, patterns in config_files.items():
                for pattern in patterns:
                    if pattern in content:
                        add_relation("config", config_path, "code", rel, "configures",
                                     f"{config_path}被{rel}引用")
                        count += 1
                        break  # 一个文件只加一次
    return count


def scan_generates():
    """扫描代码中的运行资产常量引用，生成 generates 关系"""
    count = 0
    for d in ["src", "monitoring"]:
        for py in sorted((REPO_ROOT / d).glob("*.py")):
            rel = str(py.relative_to(REPO_ROOT))
            content = py.read_text(encoding="utf-8")

            for asset in RUNTIME_ASSETS:
                if asset in content:
                    add_relation("code", rel, "runtime-asset", asset, "generates",
                                 f"{rel}引用运行资产{asset}")
                    count += 1
    return count


def scan_uses_template():
    """扫描代码中的模板常量引用，生成 uses-template 关系"""
    count = 0
    # 模板常量名 → 模板文件路径
    template_constants = {
        "AGENTS_MD_TEMPLATE": "docs/templates/analysis_agents_md.md",
        "ANALYSIS_AGENTS_MD_TEMPLATE": "docs/templates/analysis_agents_md.md",
        "AUDIT_AGENTS_MD_TEMPLATE": "docs/templates/audit_agents_md.md",
        "SELECTION_AGENTS_MD_TEMPLATE": "docs/templates/selection_agents_md.md",
        "SELFRUN_SUBAGENT_TASK_TEMPLATE": "docs/templates/selfrun_subagent_task.md",
    }

    for d in ["src", "monitoring"]:
        for py in sorted((REPO_ROOT / d).glob("*.py")):
            rel = str(py.relative_to(REPO_ROOT))
            content = py.read_text(encoding="utf-8")

            for const_name, template_path in template_constants.items():
                if const_name in content or template_path in content:
                    add_relation("code", rel, "template", template_path, "uses-template",
                                 f"{rel}使用模板{template_path}")
                    count += 1
    return count


def main():
    db_count = scan_db_relations()
    configures_count = scan_configures()
    generates_count = scan_generates()
    template_count = scan_uses_template()

    print(f"基础设施关系录入完成：reads-from/writes-to {db_count} + configures {configures_count} + generates {generates_count} + uses-template {template_count} = {db_count + configures_count + generates_count + template_count} 条")


if __name__ == "__main__":
    main()
