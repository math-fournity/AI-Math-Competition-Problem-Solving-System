"""sop_05_report_worklog.py — SOP 步骤5：报告 + WORKLOG

写本轮检查+修复的完整报告，续写 WORKLOG.md，resolve 已处理的 alert。
这是 SOP 循环的最后一步——完成后回到 sop_01 开始新的一轮。

用法：
  python -m scripts.sop.sop_05_report_worklog
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import (
    check_order, advance, print_header, print_sop_doc, print_todo_directive,
    load_state,
)

STEP_NUM = "05"


def show_worklog_path():
    """显示 WORKLOG.md 路径"""
    repo_root = Path(__file__).parent.parent.parent
    worklog = repo_root / "WORKLOG.md"
    print("--- WORKLOG.md 信息 ---")
    print(f"路径: {worklog}")
    if worklog.exists():
        size = worklog.stat().st_size
        print(f"大小: {size} 字节（已存在，续写）")
    else:
        print("（不存在，需创建）")
    print()


def show_cycle_summary():
    """显示当前循环的摘要"""
    state = load_state()
    cycle = state.get("cycle", 0)
    print("--- 本轮循环摘要 ---")
    print(f"这是第 {cycle + 1} 轮 SOP 循环。")
    print(f"完成本步骤后，将开始第 {cycle + 2} 轮循环（回到 sop_01）。")
    print()
    print("你需要：")
    print("  1. 写本轮 MONITOR_EXEC_REPORT.md（检查了什么/发现了什么/修了什么）")
    print("  2. 续写 WORKLOG.md（追加本轮记录）")
    print("  3. resolve 已处理的 alert（DB 中 p27_monitor_alerts 集合）")
    print()


def main():
    ok, msg = check_order(STEP_NUM)
    if not ok:
        print(msg)
        sys.exit(1)

    print_header(STEP_NUM)
    print_sop_doc(STEP_NUM)
    show_worklog_path()
    show_cycle_summary()
    advance(STEP_NUM)
    print_todo_directive(STEP_NUM)


if __name__ == "__main__":
    main()
