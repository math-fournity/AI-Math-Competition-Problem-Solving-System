"""sop_meta_base.py — 元检查脚本的共用逻辑

所有 01m/02m/03m/04m/05m 脚本共用此模块。
元检查 = 检查前一步 SOP 本身的合理性，不是重做前一步的工作。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import (
    check_order, advance, print_header, print_sop_doc, print_todo_directive,
    print_meta_context, get_meta_target, SOP_SCRIPTS,
)


def run_meta_check(meta_step):
    """元检查脚本的共用入口。

    Args:
        meta_step: 元检查步骤编号（如 "01m"）
    """
    # 1. 顺序校验
    ok, msg = check_order(meta_step)
    if not ok:
        print(msg)
        sys.exit(1)

    # 2. 打印头部
    print_header(meta_step)

    # 3. 打印被检查的主步骤的SOP文档（作为上下文）
    target = get_meta_target(meta_step)
    if target:
        print(f"你正在检查 sop_{target}（{SOP_SCRIPTS[target]}）的合理性。")
        print(f"下面先打印被检查的 SOP 文档，然后打印元检查指令。")
        print()
        print_meta_context(meta_step)

    # 4. 打印元检查自身的SOP文档
    print_sop_doc(meta_step)

    # 5. 推进状态
    advance(meta_step)

    # 6. 打印 todo 指令
    print_todo_directive(meta_step)
