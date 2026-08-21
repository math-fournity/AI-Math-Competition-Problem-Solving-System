#!/usr/bin/env python3
"""test_wp_k_ai_gave_up.py — WP-K 单测：ai_gave_up 检测函数与分类语义

分支级逻辑依赖主循环难以单测——正确性由三层保证（任务书§任务3）：
  ①模式函数单测（本文件）②分支与 dead_session 同构照抄（代码评审）③sim 无回归
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.devin_cli_failure_detection import check_ai_gave_up, classify_failure

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def main():
    print("=" * 60)
    print("WP-K ai_gave_up 检测单测")
    print("=" * 60)

    print("\n=== 放弃场景正例（仿真 pane 文本）===")
    positives = [
        "After exhaustive attempts...\n### I CANNOT SOLVE THIS",
        "I cannot solve this equation with elementary methods.",
        "抱歉，这道题我无法解决。",
    ]
    for t in positives:
        hit = check_ai_gave_up(t)
        check(f"命中: {t[:40]!r}…", hit is not None)

    print("\n=== 负例（正常解题/截断文本不得误报）===")
    negatives = [
        "The proof is complete. \\boxed{42}",  # 正常完成
        "",  # session 已死 capture-pane 失败的空串（WP-K 设计：回落 dead_session）
    ]
    for t in negatives:
        hit = check_ai_gave_up(t)
        check(f"不命中: {t[:40]!r}", hit is None)

    print("\n=== 分类语义（本 WP 的全部意义）===")
    check("ai_gave_up 分类 = model（不可重试）", classify_failure("ai_gave_up") == "model")
    check("对照 dead_session 分类 = infra（可重试——误判后果所在）",
          classify_failure("dead_session") == "infra")

    print("\n" + "=" * 60)
    print(f"结果: {PASS} PASS / {FAIL} FAIL")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
