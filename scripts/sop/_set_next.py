"""_set_next.py — 强制设定 SOP 流程的下一步

当需要跳过某个步骤或回退到某个步骤时使用。
正常情况下不需要调用此脚本——SOP 脚本会自动推进 next。

用法：
  python -m scripts.sop._set_next 03    # 强制设定下一步为 sop_03
  python -m scripts.sop._set_next 01    # 回到循环开始
  python -m scripts.sop._set_next status  # 查看当前状态
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import load_state, set_next, SOP_STEPS, SOP_NAMES


def main():
    if len(sys.argv) < 2:
        print("用法: python -m scripts.sop._set_next <编号|status>")
        print(f"  有效编号: {SOP_STEPS}")
        print("  status: 查看当前状态")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "status":
        state = load_state()
        print("=== SOP 流程状态 ===")
        print(f"  上一个: sop_{state.get('last')}（{SOP_NAMES.get(state.get('last'), '无')}）")
        print(f"  下一个: sop_{state.get('next')}（{SOP_NAMES.get(state.get('next'), '无')}）")
        print(f"  循环轮次: {state.get('cycle', 0)}")
        print(f"  上次执行: {state.get('last_ts', '无')}")
        print(f"  batch_id: {state.get('batch_id', 'p27-full')}")
        return

    ok, msg = set_next(arg)
    if ok:
        print(msg)
        print(f"现在可以执行: python -m scripts.sop.{SOP_NAMES[arg]}")
    else:
        print(msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
