"""sop_state.py — SOP 流程状态管理模块

读写 _state.json，提供顺序校验。单脚本 run.py 共用此模块。

循环结构（7步）：
  01  系统存活+进度+Session
  02  数据完整性
  03  alert分类
  04  C类AI判断
  05  代码修复
  06  报告+WORKLOG+Self-check
  Z   元检查+整体检查
  → 回到 01（新的一轮循环）

状态文件：scripts/sop/_state.json
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from scripts.sop.sop_log import get_logger

STATE_FILE = Path(__file__).parent / "_state.json"

log = get_logger("state")

# SOP 步骤定义——顺序即循环顺序
SOP_STEPS = ["01", "02", "03", "04", "05", "06", "Z"]

# 编号→步骤名称映射（用于显示）
SOP_NAMES = {
    "01": "系统存活+进度+Session",
    "02": "数据完整性",
    "03": "alert分类",
    "04": "C类AI判断",
    "05": "代码修复",
    "06": "报告+WORKLOG+Self-check",
    "Z": "元检查+整体检查",
}

# 编号→SOP文档名映射
SOP_DOCS = {
    "01": "SOP_01_system_health.md",
    "02": "SOP_02_data_integrity.md",
    "03": "SOP_03_alert_triage.md",
    "04": "SOP_04_ai_judgment.md",
    "05": "SOP_05_code_repair.md",
    "06": "SOP_06_report_worklog_selfcheck.md",
    "Z": "SOP_Z_meta_system_review.md",
}


def load_state():
    with open(STATE_FILE) as f:
        state = json.load(f)
    log.debug(f"load_state: {state}")
    return state


def save_state(state):
    log.info(f"save_state: last={state.get('last')} next={state.get('next')} cycle={state.get('cycle')}")
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_sop_doc_path(step_num):
    docs_dir = Path(__file__).parent.parent.parent / "docs" / "sop"
    return docs_dir / SOP_DOCS[step_num]


def get_sop_doc_content(step_num):
    path = get_sop_doc_path(step_num)
    if not path.exists():
        return f"⚠️ SOP 文档不存在: {path}"
    return path.read_text(encoding="utf-8")


# 系统级认知闭包（L0）——每次SOP执行前置注入，让AI时刻知道系统应怎样工作
SYSTEM_CLOSURE_DOC = "SYSTEM_CLOSURE.md"


def get_system_closure_path():
    docs_dir = Path(__file__).parent.parent.parent / "docs" / "sop"
    return docs_dir / SYSTEM_CLOSURE_DOC


def get_system_closure_content():
    path = get_system_closure_path()
    if not path.exists():
        return f"⚠️ 系统级认知闭包不存在: {path}"
    return path.read_text(encoding="utf-8")


def get_next_step_num(current_step):
    idx = SOP_STEPS.index(current_step)
    next_idx = (idx + 1) % len(SOP_STEPS)
    return SOP_STEPS[next_idx]


def check_order(step_num):
    state = load_state()
    expected = state["next"]
    if expected == step_num:
        log.info(f"check_order PASS: step={step_num} (expected={expected})")
        return True, None
    last = state.get("last", "（无）")
    last_name = SOP_NAMES.get(last, "（无）")
    expected_name = SOP_NAMES.get(expected, "（无）")
    your_name = SOP_NAMES.get(step_num, "（未知）")
    msg = (
        f"⚠️ 顺序错误：你试图执行步骤 {step_num}（{your_name}），\n"
        f"   但下一个应该执行的是步骤 {expected}（{expected_name}）。\n"
        f"   上一个执行的是步骤 {last}（{last_name}）。\n\n"
        f"   如果你确定要执行步骤 {step_num}，请先运行：\n"
        f"   python -m scripts.sop._set_next {step_num}\n"
        f"   然后再执行本脚本。"
    )
    log.warning(f"check_order FAIL: step={step_num} expected={expected} last={last}")
    return False, msg


def advance(step_num):
    state = load_state()
    state["last"] = step_num
    state["next"] = get_next_step_num(step_num)
    if step_num == "Z":
        state["cycle"] = state.get("cycle", 0) + 1
        log.info(f"advance: step={step_num} → cycle {state['cycle']} completed, next={state['next']}")
    else:
        log.info(f"advance: step={step_num} → next={state['next']}")
    state["last_ts"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    return state


def set_next(step_num):
    if step_num not in SOP_STEPS:
        log.warning(f"set_next: invalid step={step_num}")
        return False, f"无效步骤编号: {step_num}，有效值: {SOP_STEPS}"
    state = load_state()
    state["next"] = step_num
    log.info(f"set_next: forcing next={step_num} ({SOP_NAMES[step_num]})")
    save_state(state)
    return True, f"已设定下一步为步骤 {step_num}（{SOP_NAMES[step_num]}）"


def print_header(step_num):
    state = load_state()
    cycle = state.get("cycle", 0)
    last_ts = state.get("last_ts", "（首次执行）")
    batch_id = state.get("batch_id", "p27-full")
    doc_name = SOP_DOCS[step_num]
    step_name = SOP_NAMES[step_num]
    next_step = get_next_step_num(step_num)
    next_name = SOP_NAMES[next_step]

    print(f"=== SOP_{step_num}: {step_name} ===")
    print(f"（轮次: 第{cycle + 1}轮 | 上次执行: {last_ts} | batch: {batch_id}）")
    print(f"（SOP文档: docs/sop/{doc_name}）")
    print(f"（下一步: 步骤 {next_step}（{next_name}））")
    print()


def print_system_closure():
    """每次SOP执行前置注入系统级认知闭包（L0）——让AI时刻知道系统应怎样工作。
    系统级知识（架构/数据流/生命周期/判定框架）全在这里，各步骤SOP(L1)只补充
    该步骤特有增量，不重复系统级内容。"""
    print("--- 系统级认知闭包（L0，每次注入）---")
    print(get_system_closure_content())
    print("--- 系统级认知闭包结束 ---")
    print()


def print_sop_doc(step_num):
    print("--- SOP 文档内容 ---")
    print(get_sop_doc_content(step_num))
    print("--- SOP 文档内容结束 ---")
    print()


def print_todo_directive(step_num):
    next_step = get_next_step_num(step_num)
    next_name = SOP_NAMES[next_step]
    print("--- 下一步指令 ---")
    print(f"请用 todo_write 建立本轮 todo list。")
    print(f"todo list 的最后一项必须是：")
    print(f"  执行下一个脚本: python -m scripts.sop.run")
    print()
    print(f"完成所有 todo 后，最后一项会自动触发下一阶段（步骤 {next_step}: {next_name}）。")
    if step_num == "Z":
        print(f"注意：这是循环的最后一步，下一阶段是新一轮循环的开始。")
    print()
