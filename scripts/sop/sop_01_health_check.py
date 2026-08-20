"""sop_01_health_check.py — SOP 步骤1：系统健康检查

运行 monitor_check_continuation.sh 获取系统状态 + 所有未处理 alert。
这是 SOP 循环的第一步——获取全貌，为后续步骤（alert分类/AI判断/修复/报告）提供输入。

用法：
  python -m scripts.sop.sop_01_health_check
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import (
    check_order, advance, print_header, print_sop_doc, print_todo_directive,
    load_state,
)

STEP_NUM = "01"


def run_health_check():
    """运行 monitor_check_continuation.sh 获取系统状态"""
    repo_root = Path(__file__).parent.parent.parent
    script = repo_root / "scripts" / "monitor_check_continuation.sh"
    state = load_state()
    batch_id = state.get("batch_id", "p27-full")

    if not script.exists():
        print(f"⚠️ 检查脚本不存在: {script}")
        return

    print("--- 自动化检查结果（monitor_check_continuation.sh）---")
    try:
        result = subprocess.run(
            ["bash", str(script), batch_id],
            capture_output=True, text=True, timeout=120,
            cwd=str(repo_root),
        )
        print(result.stdout)
        if result.stderr:
            print("--- stderr ---")
            print(result.stderr)
    except subprocess.TimeoutExpired:
        print("⚠️ 检查脚本超时（120秒），可能系统状态异常")
    except Exception as e:
        print(f"⚠️ 检查脚本执行失败: {e}")
    print()


def main():
    # 1. 顺序校验
    ok, msg = check_order(STEP_NUM)
    if not ok:
        print(msg)
        sys.exit(1)

    # 2. 打印头部 + SOP 文档
    print_header(STEP_NUM)
    print_sop_doc(STEP_NUM)

    # 3. 执行自身检查逻辑
    run_health_check()

    # 4. 推进状态
    advance(STEP_NUM)

    # 5. 打印 todo 指令
    print_todo_directive(STEP_NUM)


if __name__ == "__main__":
    main()
