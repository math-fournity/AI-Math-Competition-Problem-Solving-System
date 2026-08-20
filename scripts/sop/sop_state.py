"""sop_state.py — SOP 流程状态管理模块

读写 _state.json，提供顺序校验。所有 SOP 脚本共用此模块。

状态文件：scripts/sop/_state.json
结构：
  {
    "last": "01",       # 上一个执行的脚本编号
    "next": "02",       # 下一个应该执行的脚本编号
    "cycle": 3,         # 当前是第几轮循环（sop_01→05 完成为一轮）
    "last_ts": "...",   # 上次执行时间（ISO格式）
    "batch_id": "p27-full"  # 当前监控的批次
  }
"""

import json
from pathlib import Path
from datetime import datetime, timezone

STATE_FILE = Path(__file__).parent / "_state.json"

# SOP 步骤定义——顺序即循环顺序
SOP_STEPS = ["01", "02", "03", "04", "05"]

# 编号→脚本名映射
SOP_SCRIPTS = {
    "01": "sop_01_health_check",
    "02": "sop_02_alert_triage",
    "03": "sop_03_ai_judgment",
    "04": "sop_04_code_repair",
    "05": "sop_05_report_worklog",
}

# 编号→SOP文档名映射
SOP_DOCS = {
    "01": "SOP_01_health_check.md",
    "02": "SOP_02_alert_triage.md",
    "03": "SOP_03_ai_judgment.md",
    "04": "SOP_04_code_repair.md",
    "05": "SOP_05_report_worklog.md",
}


def load_state():
    """读取状态文件"""
    with open(STATE_FILE) as f:
        return json.load(f)


def save_state(state):
    """写入状态文件"""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_next_step():
    """获取下一个应该执行的步骤编号"""
    return load_state()["next"]


def get_sop_doc_path(step_num):
    """获取 SOP 文档路径"""
    docs_dir = Path(__file__).parent.parent.parent / "docs" / "sop"
    return docs_dir / SOP_DOCS[step_num]


def get_sop_doc_content(step_num):
    """读取 SOP 文档内容"""
    path = get_sop_doc_path(step_num)
    if not path.exists():
        return f"⚠️ SOP 文档不存在: {path}"
    return path.read_text(encoding="utf-8")


def get_next_step_num(current_step):
    """获取循环中的下一个步骤编号（05→01 回到开始）"""
    idx = SOP_STEPS.index(current_step)
    next_idx = (idx + 1) % len(SOP_STEPS)
    return SOP_STEPS[next_idx]


def check_order(step_num):
    """校验执行顺序。返回 (ok, message)。

    如果 state["next"] == step_num，校验通过。
    否则返回错误信息，告知上一个和下一个应该是什么。
    """
    state = load_state()
    expected = state["next"]
    if expected == step_num:
        return True, None
    last = state.get("last", "（无）")
    last_script = SOP_SCRIPTS.get(last, "（无）")
    expected_script = SOP_SCRIPTS.get(expected, "（无）")
    your_script = SOP_SCRIPTS.get(step_num, "（未知）")
    msg = (
        f"⚠️ 顺序错误：你试图执行 sop_{step_num}（{your_script}），\n"
        f"   但下一个应该执行的是 sop_{expected}（{expected_script}）。\n"
        f"   上一个执行的是 sop_{last}（{last_script}）。\n\n"
        f"   如果你确定要执行 sop_{step_num}，请先运行：\n"
        f"   python -m scripts.sop._set_next {step_num}\n"
        f"   然后再执行本脚本。"
    )
    return False, msg


def advance(step_num):
    """执行完成后推进状态——更新 last/next/cycle/last_ts。

    如果 step_num == "05"（最后一步），cycle + 1，next 回到 "01"。
    """
    state = load_state()
    state["last"] = step_num
    state["next"] = get_next_step_num(step_num)
    if step_num == "05":
        state["cycle"] = state.get("cycle", 0) + 1
    state["last_ts"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    return state


def set_next(step_num):
    """强制设定下一步"""
    if step_num not in SOP_STEPS:
        return False, f"无效步骤编号: {step_num}，有效值: {SOP_STEPS}"
    state = load_state()
    state["next"] = step_num
    save_state(state)
    return True, f"已设定下一步为 sop_{step_num}（{SOP_SCRIPTS[step_num]}）"


def print_header(step_num):
    """打印脚本头部信息"""
    state = load_state()
    cycle = state.get("cycle", 0)
    last_ts = state.get("last_ts", "（首次执行）")
    batch_id = state.get("batch_id", "p27-full")
    script_name = SOP_SCRIPTS[step_num]
    doc_name = SOP_DOCS[step_num]
    next_step = get_next_step_num(step_num)
    next_script = SOP_SCRIPTS[next_step]

    print(f"=== SOP_{step_num}: {script_name} ===")
    print(f"（轮次: 第{cycle + 1}轮 | 上次执行: {last_ts} | batch: {batch_id}）")
    print(f"（SOP文档: docs/sop/{doc_name}）")
    print(f"（下一步: sop_{next_step}（{next_script}））")
    print()


def print_sop_doc(step_num):
    """打印 SOP 文档内容"""
    print("--- SOP 文档内容 ---")
    print(get_sop_doc_content(step_num))
    print("--- SOP 文档内容结束 ---")
    print()


def print_todo_directive(step_num):
    """打印 todo_write 指令——最后一项是执行下一个脚本"""
    next_step = get_next_step_num(step_num)
    next_script = SOP_SCRIPTS[next_step]
    print("--- 下一步指令 ---")
    print(f"请用 todo_write 建立本轮 todo list。")
    print(f"todo list 的最后一项必须是：")
    print(f"  执行下一个脚本: python -m scripts.sop.{next_script}")
    print()
    print(f"完成所有 todo 后，最后一项会自动触发下一阶段（sop_{next_step}）。")
    if step_num == "05":
        print(f"注意：这是循环的最后一步，下一阶段 sop_01 是新的一轮循环。")
    print()
