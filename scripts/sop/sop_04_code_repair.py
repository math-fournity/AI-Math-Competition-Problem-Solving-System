"""sop_04_code_repair.py — SOP 步骤4：代码修复

修复步骤02分类为"代码bug"的问题——读代码→定位根因→修复→py_compile验证→git commit。

注意约束（见 SOP 文档）：
  - 不能 push 代码（只 commit 到本地）
  - 不能修改 AGENTS.md / spec / MonitorPipe.md 的架构定义
  - 修完必须 py_compile 验证
  - git 显式路径 add（禁止 git add -A/.-u）
  - 只修本轮发现的问题，不重构不改架构

用法：
  python -m scripts.sop.sop_04_code_repair
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import (
    check_order, advance, print_header, print_sop_doc, print_todo_directive,
)

STEP_NUM = "04"


def run_recent_commits():
    """显示最近的 git log，帮助了解上下文"""
    import subprocess
    repo_root = Path(__file__).parent.parent.parent
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True, text=True, timeout=10,
            cwd=str(repo_root),
        )
        print("--- 最近 5 个 commit ---")
        print(result.stdout)
    except Exception as e:
        print(f"⚠️ git log 失败: {e}")
    print()


def main():
    ok, msg = check_order(STEP_NUM)
    if not ok:
        print(msg)
        sys.exit(1)

    print_header(STEP_NUM)
    print_sop_doc(STEP_NUM)
    run_recent_commits()
    advance(STEP_NUM)
    print_todo_directive(STEP_NUM)


if __name__ == "__main__":
    main()
