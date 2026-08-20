"""dry_run.py — SOP 循环完整性验证（dry-run）

模拟跑完完整的 7 步 SOP 循环，验证：
  1. 每一步的 SOP 文档都能被读取
  2. 顺序校验机制正常工作
  3. 状态推进正确（01→02→03→04→05→06→Z→01）
  4. cycle 计数正确（Z 完成后 +1）
  5. 顺序错误时正确拒绝
  6. _set_next 跳步功能正常
  7. 日志写入正常

dry-run 不执行真正的检查逻辑（不连 DB、不运行 monitor_check_continuation.sh），
只验证流程机制本身。

用法：
  python -m scripts.sop.dry_run
"""

import json
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import (
    STATE_FILE, SOP_STEPS, SOP_NAMES, SOP_DOCS,
    load_state, save_state, check_order, advance, set_next,
    get_sop_doc_path, get_next_step_num,
)
from scripts.sop.sop_log import get_logger, get_log_dir_info

log = get_logger("dry_run")


def backup_state():
    """备份当前 state，dry-run 结束后恢复"""
    if STATE_FILE.exists():
        backup = STATE_FILE.read_text()
        log.info(f"backup_state: backed up current state")
        return backup
    return None


def restore_state(backup):
    """恢复 state"""
    if backup is not None:
        STATE_FILE.write_text(backup)
        log.info(f"restore_state: restored original state")
    else:
        # 原来不存在，删除 dry-run 创建的
        reset_state()
        log.info(f"restore_state: reset to initial (original didn't exist)")


def reset_state():
    """重置到初始状态"""
    state = {"last": None, "next": "01", "cycle": 0, "last_ts": None, "batch_id": "p27-full"}
    save_state(state)
    log.info(f"reset_state: {state}")


def test_doc_exists():
    """测试1：每个步骤的 SOP 文档都存在"""
    print("\n=== 测试1：SOP 文档存在性 ===")
    all_exist = True
    for step in SOP_STEPS:
        doc_name = SOP_DOCS[step]
        doc_path = get_sop_doc_path(step)
        exists = doc_path.exists()
        status = "✅" if exists else "❌"
        print(f"  {status} 步骤{step} ({SOP_NAMES[step]}): {doc_name} {'存在' if exists else '不存在!'}")
        if not exists:
            all_exist = False
            log.error(f"test_doc_exists: MISSING {doc_path}")
        else:
            log.info(f"test_doc_exists: OK {doc_name}")
    return all_exist


def test_sequential_flow():
    """测试2：顺序执行 01→02→03→04→05→06→Z，验证状态推进"""
    print("\n=== 测试2：顺序执行 7 步 ===")
    reset_state()
    results = []

    for step in SOP_STEPS:
        state_before = load_state()
        ok, msg = check_order(step)
        if not ok:
            print(f"  ❌ 步骤{step}: 顺序校验失败 — {msg}")
            log.error(f"test_sequential_flow: order check failed at step={step}")
            results.append(False)
            break

        # 读取 SOP 文档（验证可读）
        doc_path = get_sop_doc_path(step)
        content = doc_path.read_text(encoding="utf-8")
        doc_len = len(content)
        log.info(f"test_sequential_flow: step={step} doc read OK ({doc_len} chars)")

        # 推进状态
        advance(step)
        state_after = load_state()

        expected_next = get_next_step_num(step)
        actual_next = state_after["next"]
        next_ok = (actual_next == expected_next)

        cycle_info = ""
        if step == "Z":
            cycle_info = f" cycle={state_after['cycle']}"
            if state_after["cycle"] != 1:
                print(f"  ❌ 步骤Z: cycle 应该是 1 但实际是 {state_after['cycle']}")
                log.error(f"test_sequential_flow: cycle mismatch at Z: {state_after['cycle']}")
                results.append(False)
                break

        status = "✅" if next_ok else "❌"
        print(f"  {status} 步骤{step} ({SOP_NAMES[step]}): next={actual_next} (期望={expected_next}){cycle_info}")
        log.info(f"test_sequential_flow: step={step} next={actual_next} expected={expected_next} ok={next_ok}")
        results.append(next_ok)

    return all(results)


def test_order_violation():
    """测试3：顺序违规——执行 01 后直接执行 03，应该被拒绝"""
    print("\n=== 测试3：顺序违规检测 ===")
    reset_state()

    # 执行 01
    ok, _ = check_order("01")
    if not ok:
        print(f"  ❌ 步骤01 应该通过但失败了")
        log.error("test_order_violation: step 01 should pass but failed")
        return False
    advance("01")

    # 尝试执行 03（应该被拒绝，因为 next=02）
    ok, msg = check_order("03")
    if ok:
        print(f"  ❌ 步骤03 应该被拒绝但通过了")
        log.error("test_order_violation: step 03 should be rejected but passed")
        return False
    else:
        print(f"  ✅ 步骤03 被正确拒绝（期望 next=02，尝试 03）")
        log.info("test_order_violation: step 03 correctly rejected")
        return True


def test_set_next():
    """测试4：_set_next 强制跳步"""
    print("\n=== 测试4：_set_next 强制跳步 ===")
    reset_state()

    # 执行 01
    ok, _ = check_order("01")
    advance("01")
    state = load_state()
    assert state["next"] == "02", f"next should be 02 but is {state['next']}"

    # 强制设定 next=05
    ok, msg = set_next("05")
    if not ok:
        print(f"  ❌ set_next('05') 失败: {msg}")
        log.error("test_set_next: set_next('05') failed")
        return False

    state = load_state()
    if state["next"] != "05":
        print(f"  ❌ set_next 后 next 应该是 05 但实际是 {state['next']}")
        log.error(f"test_set_next: next={state['next']} expected=05")
        return False

    # 验证 05 能通过顺序校验
    ok, _ = check_order("05")
    if not ok:
        print(f"  ❌ set_next('05') 后 check_order('05') 应该通过但失败了")
        log.error("test_set_next: check_order('05') failed after set_next")
        return False

    print(f"  ✅ set_next('05') 成功，check_order('05') 通过")
    log.info("test_set_next: set_next('05') and check_order('05') both passed")
    return True


def test_invalid_step():
    """测试5：无效步骤编号"""
    print("\n=== 测试5：无效步骤编号 ===")
    ok, msg = set_next("99")
    if ok:
        print(f"  ❌ set_next('99') 应该失败但成功了")
        log.error("test_set_next: set_next('99') should fail but succeeded")
        return False
    else:
        print(f"  ✅ set_next('99') 被正确拒绝")
        log.info("test_set_next: set_next('99') correctly rejected")
        return True


def test_logging():
    """测试6：日志写入"""
    print("\n=== 测试6：日志写入 ===")
    log.info("test_logging: writing test log message")
    info = get_log_dir_info()
    print(f"  日志目录: {info['dir']}")
    print(f"  文件数: {info['file_count']}")
    print(f"  总大小: {info['total_size_mb']} MB")
    print(f"  上限: {info['max_files']} 文件 / {info['max_size_mb']} MB")

    if info["file_count"] > 0:
        print(f"  ✅ 日志文件已生成")
        log.info("test_logging: log files exist, test passed")
        return True
    else:
        print(f"  ❌ 没有日志文件")
        log.error("test_logging: no log files found")
        return False


def main():
    print("=" * 60)
    print("SOP 循环完整性验证（dry-run）")
    print("=" * 60)
    log.info("dry_run: START")

    # 备份当前 state
    backup = backup_state()

    all_passed = True

    tests = [
        ("文档存在性", test_doc_exists),
        ("顺序执行7步", test_sequential_flow),
        ("顺序违规检测", test_order_violation),
        ("强制跳步", test_set_next),
        ("无效步骤编号", test_invalid_step),
        ("日志写入", test_logging),
    ]

    for name, test_fn in tests:
        try:
            result = test_fn()
            if not result:
                all_passed = False
        except Exception as e:
            print(f"  ❌ 测试异常: {e}")
            log.error(f"dry_run: test '{name}' raised exception: {e}", exc_info=True)
            all_passed = False

    # 恢复 state
    restore_state(backup)

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ 全部测试通过——SOP 循环完整性验证成功")
        log.info("dry_run: ALL TESTS PASSED")
    else:
        print("❌ 有测试失败——需要修复")
        log.error("dry_run: SOME TESTS FAILED")
    print("=" * 60)


if __name__ == "__main__":
    main()
