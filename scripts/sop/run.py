"""run.py — SOP 循环的唯一入口

每次运行此脚本，它读取 _state.json 决定当前应该执行哪个步骤，
打印对应的 SOP 文档，执行该步骤的自动化检查逻辑，推进状态。

用法：
  python -m scripts.sop.run          # 执行当前步骤
  python -m scripts.sop.run --step 03  # 强制执行步骤03（需先通过顺序校验）

自驱动机制：
  脚本输出末尾要求用 todo_write 建 todo list，
  最后一项是"执行 python -m scripts.sop.run"——完成 todo 后自动触发下一步。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import (
    load_state, check_order, advance,
    print_header, print_sop_doc, print_todo_directive,
    SOP_STEPS, SOP_NAMES,
)
from scripts.sop import checks


# 步骤编号 → 检查函数映射
STEP_CHECKS = {
    "01": checks.check_01_system_health,
    "02": checks.check_02_data_integrity,
    "03": checks.check_03_alert_triage,
    "04": checks.check_04_ai_judgment,
    "05": checks.check_05_code_repair,
    "06": checks.check_06_report_worklog_selfcheck,
    "Z": checks.check_Z_meta_system_review,
}


def main():
    parser = argparse.ArgumentParser(description="SOP 循环入口")
    parser.add_argument("--step", help="强制执行指定步骤（需通过顺序校验）")
    args = parser.parse_args()

    # 确定要执行的步骤
    if args.step:
        step_num = args.step
    else:
        state = load_state()
        step_num = state["next"]

    # 顺序校验
    ok, msg = check_order(step_num)
    if not ok:
        print(msg)
        sys.exit(1)

    # 获取 batch_id
    state = load_state()
    batch_id = state.get("batch_id", "p27-full")

    # 打印头部 + SOP 文档
    print_header(step_num)
    print_sop_doc(step_num)

    # 执行该步骤的自动化检查逻辑
    check_fn = STEP_CHECKS.get(step_num)
    if check_fn:
        check_fn(batch_id)

    # 推进状态
    advance(step_num)

    # 打印 todo 指令
    print_todo_directive(step_num)


if __name__ == "__main__":
    main()
