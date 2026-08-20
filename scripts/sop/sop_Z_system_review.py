"""sop_Z_system_review.py — SOP系统整体检查

检查整个 SOP 脚本系统是否需要调整和修改。
这是循环的最后一步——完成后回到 sop_01 开始新的一轮。

检查内容：
  - 5步划分是否还合理？需要新增/删除步骤吗？
  - 步骤顺序是否需要调整？
  - _state.json 机制是否可靠？
  - SOP系统与目标系统的适配度
  - 元检查机制本身是否有效？
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import (
    check_order, advance, print_header, print_sop_doc, print_todo_directive,
    load_state, SOP_STEPS, SOP_SCRIPTS,
)

STEP_NUM = "Z"


def show_system_overview():
    """显示 SOP 系统全貌"""
    state = load_state()
    cycle = state.get("cycle", 0)
    print("--- SOP 系统全貌 ---")
    print(f"循环轮次: 第{cycle + 1}轮（即将完成）")
    print(f"步骤总数: {len(SOP_STEPS)}")
    print()
    print("当前循环结构：")
    for step in SOP_STEPS:
        script = SOP_SCRIPTS[step]
        if step.endswith("m"):
            target = step[:-1]
            print(f"  {step:4s} {script:40s} （元检查：检查sop_{target}的合理性）")
        elif step == "Z":
            print(f"  {step:4s} {script:40s} （整体检查）")
        else:
            print(f"  {step:4s} {script:40s}")
    print()
    print("所有 SOP 文档：docs/sop/")
    print("所有 SOP 脚本：scripts/sop/")
    print("状态文件：scripts/sop/_state.json")
    print()


def main():
    ok, msg = check_order(STEP_NUM)
    if not ok:
        print(msg)
        sys.exit(1)

    print_header(STEP_NUM)
    show_system_overview()
    print_sop_doc(STEP_NUM)
    advance(STEP_NUM)
    print_todo_directive(STEP_NUM)


if __name__ == "__main__":
    main()
