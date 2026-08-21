#!/usr/bin/env python3
"""test_wp_s_partial_archive.py — WP-S 项1 单测：remove_old_proof 删前归档 partial proof

修复内容（资产保留铁律的代码兑现）：
  旧实现 unlink() 直删——无 boxed 的部分证明（AI 推到哪里断掉的物证）从不归档。
  新实现：非空旧 proof 删前先 copy2 为 round{N}_proof_partial.md。

断言覆盖（验收要求）：
  partial 生成 + 原文件删除 + 无 boxed 也归档 + 幂等 + 新proof保护分支 + 空文件边界

用法：
  python scripts/test_wp_s_partial_archive.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.continuation_launcher import remove_old_proof

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


def make_proof(work_dir, content, mtime_offset=None):
    p = Path(work_dir) / "proof.md"
    p.write_text(content)
    if mtime_offset is not None:
        t = time.time() + mtime_offset
        os.utime(p, (t, t))
    return p


def case1_partial_archived(tmp):
    """旧 proof（mtime < started_at，无 boxed 非空）→ 归档+删除"""
    wd = tmp / "c1"
    wd.mkdir()
    content = "## Partial proof\n\nWe have shown that f(x) = x^2 - 4x + 3 has roots 1 and 3.\n"
    p = make_proof(wd, content, mtime_offset=-600)
    started_at = time.time()

    remove_old_proof(str(wd), round_num=2, started_at=started_at)

    check("原 proof.md 已删除", not p.exists())
    partial = wd / "round2_proof_partial.md"
    check("partial 已生成", partial.exists())
    check("partial 内容一致（无 boxed 也归档）",
          partial.exists() and partial.read_text() == content,
          f"content={partial.read_text()[:50]!r}")


def case2_idempotent(tmp):
    """再次调用（proof 已不存在）→ 幂等，无异常"""
    wd = tmp / "c2"
    wd.mkdir()
    # 空目录直接调
    try:
        remove_old_proof(str(wd), round_num=3, started_at=time.time())
        check("幂等：无 proof 时静默返回", True)
    except Exception as e:
        check("幂等：无 proof 时静默返回", False, str(e))


def case3_new_proof_protected(tmp):
    """本轮刚写的 proof（mtime >= started_at）→ 不删也不归档"""
    wd = tmp / "c3"
    wd.mkdir()
    content = "\\boxed{42}"
    p = make_proof(wd, content, mtime_offset=+60)  # 未来 mtime = 本轮新写的
    started_at = time.time()

    remove_old_proof(str(wd), round_num=4, started_at=started_at)

    check("新 proof 未被删除", p.exists())
    partial = wd / "round4_proof_partial.md"
    check("新 proof 未被误归档", not partial.exists())


def case4_empty_proof_deleted_no_archive(tmp):
    """空旧 proof → 删除但不产生 partial（零字节无保留价值）"""
    wd = tmp / "c4"
    wd.mkdir()
    p = make_proof(wd, "", mtime_offset=-600)
    started_at = time.time()

    remove_old_proof(str(wd), round_num=5, started_at=started_at)

    check("空旧 proof 已删除", not p.exists())
    check("空 proof 不产生 partial", not (wd / "round5_proof_partial.md").exists())


def main():
    import tempfile
    print("=" * 60)
    print("WP-S 项1 单测：remove_old_proof 删前归档 partial proof")
    print("=" * 60)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        case1_partial_archived(tmp)
        case2_idempotent(tmp)
        case3_new_proof_protected(tmp)
        case4_empty_proof_deleted_no_archive(tmp)
    print("\n" + "=" * 60)
    print(f"结果: {PASS} PASS / {FAIL} FAIL")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
