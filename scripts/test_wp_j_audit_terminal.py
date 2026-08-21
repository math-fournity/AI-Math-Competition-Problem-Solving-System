#!/usr/bin/env python3
"""test_wp_j_audit_terminal.py — WP-J 审计终态检测单测

覆盖：
  1. detect_terminal_verdict 五类场景（rate_limited/failed_connection/
     failed_token_limit/ai_gave_up/正常无判定）——用仿真审计 pane 文本
  2. KILL_POLICY 映射表断言（rate_limited/connection 不 kill；gave_up/token kill）
  3. classify_failure 对五 verdict 的分类
  4. tail_file 辅助函数
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.proof_audit_launcher import (
    KILL_POLICY, detect_terminal_verdict, tail_file,
)
from src.devin_cli_failure_detection import classify_failure

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


def test_five_scenarios():
    print("\n=== 测试 1：五类场景判定 ===")
    scenarios = [
        # (期望verdict, 仿真审计 pane 文本)
        ("rate_limited",
         "Running audit step 3...\nError: rate limit exceeded, retry after 60s\nPlease wait"),
        ("failed_connection",
         "Connecting to API...\nECONNREFUSED 127.0.0.1:443\nretrying"),
        ("failed_token_limit",
         "Analysis part 2...\nError: maximum context length reached\ncannot continue"),
        ("ai_gave_up",
         "After careful analysis...\n### I CANNOT SOLVE THIS\nsorry"),
        (None,
         "Reading proof.txt...\nThe injective tensor product preserves injectivity when...\n"
         "### PROOF AUDIT COMPLETE\n<proof_audit><audit_status>PASS</audit_status>"),
    ]
    for expect, text in scenarios:
        got = detect_terminal_verdict(text)
        check(f"{expect!r}", got == expect, f"got={got!r}")


def test_kill_policy():
    print("\n=== 测试 2：KILL_POLICY 映射 ===")
    for verdict, should_kill, why in [
        ("rate_limited", False, "可能自恢复——留观"),
        ("failed_connection", False, "可能自恢复——留观"),
        ("ai_gave_up", True, "模型不会再产出"),
        ("failed_token_limit", True, "模型不会再产出"),
    ]:
        check(f"{verdict} → kill={should_kill}（{why}）",
              KILL_POLICY.get(verdict) == should_kill)


def test_classify():
    print("\n=== 测试 3：classify_failure 分类 ===")
    for v in ["rate_limited", "failed_connection"]:
        check(f"{v} → infra", classify_failure(v) == "infra")
    for v in ["ai_gave_up", "failed_token_limit", "max_runtime_exceeded"]:
        check(f"{v} → model", classify_failure(v) == "model")


def test_tail_file():
    print("\n=== 测试 4：tail_file 辅助 ===")
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
        f.write("A" * 6000 + "TAIL_MARKER")
        path = f.name
    tail = tail_file(path, 5120)
    check("尾部 5120 字节读取", len(tail) == 5120 and tail.endswith("TAIL_MARKER"))
    check("不存在的路径返回空串", tail_file("/nonexistent/x.log") == "")


def main():
    print("=" * 60)
    print("WP-J 审计终态检测单测")
    print("=" * 60)
    test_five_scenarios()
    test_kill_policy()
    test_classify()
    test_tail_file()
    print("\n" + "=" * 60)
    print(f"结果: {PASS} PASS / {FAIL} FAIL")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
