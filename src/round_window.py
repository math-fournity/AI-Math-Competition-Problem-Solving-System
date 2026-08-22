"""Round 调度窗口的纯领域逻辑。

Round 编号描述一道题的长期研究历史；窗口只限制本次调度默认处理多少个
数学 Round。窗口用完不是题目终态，未来可从下一绝对 Round 继续。

本模块不连接 DB/Redis、不设置 Gate。调用方负责把返回字段与 rounds_log
在同一次 DB update 中持久化，并通过现有 feeder/launch/kill Gate 执行动作。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


RUN_STATUS_WINDOW_EXHAUSTED = "window_exhausted"
WINDOW_STATUS_PENDING = "pending"
WINDOW_STATUS_ACTIVE = "active"
WINDOW_STATUS_EXHAUSTED = "exhausted"
WINDOW_STATUS_PAUSED = "paused"
WINDOW_STATUS_COMPLETED = "completed"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def next_absolute_round(run_doc: dict[str, Any]) -> int:
    """返回下一绝对 Round 编号。

    新数据应连续且不重复；历史数据曾有[2,2,3]等缺陷，故不能用len+1。
    取最大合法编号+1既保持新不变量，也避免恢复时覆盖已有Round资产。
    """
    nums = []
    for entry in run_doc.get("rounds_log") or []:
        try:
            value = int(entry.get("round"))
        except (AttributeError, TypeError, ValueError):
            continue
        if value > 0:
            nums.append(value)
    return max(nums, default=0) + 1


def ensure_active_window(
    run_doc: dict[str, Any], window_size: int, now: str | None = None,
) -> tuple[dict[str, int], dict[str, Any]]:
    """取得当前活跃窗口；没有时返回开启新窗口所需的 DB 更新字段。

    活跃窗口的 size 在窗口中途保持稳定。launcher 重启时即使命令行参数改变，
    也继续使用已持久化 size；新参数只作用于下一个窗口。
    """
    if window_size <= 0:
        raise ValueError("round_window_size 必须是正整数")

    if run_doc.get("round_window_status") == WINDOW_STATUS_ACTIVE:
        start = int(run_doc.get("round_window_start_round") or next_absolute_round(run_doc))
        size = int(run_doc.get("round_window_size") or window_size)
        used = int(run_doc.get("round_window_rounds_used") or 0)
        window_id = int(run_doc.get("round_window_id") or 1)
        repair = {}
        normalized = {
            "round_window_id": window_id,
            "round_window_start_round": start,
            "round_window_size": size,
            "round_window_rounds_used": used,
            "continuation_eligible": True,
        }
        for key, value in normalized.items():
            if run_doc.get(key) is None:
                repair[key] = value
        return {
            "id": window_id,
            "start_round": start,
            "size": size,
            "used": used,
        }, repair

    window_id = int(run_doc.get("round_window_id") or 0) + 1
    start = next_absolute_round(run_doc)
    started_at = now or utc_now()
    state = {"id": window_id, "start_round": start, "size": window_size, "used": 0}
    update = {
        "round_window_id": window_id,
        "round_window_status": WINDOW_STATUS_ACTIVE,
        "round_window_start_round": start,
        "round_window_size": window_size,
        "round_window_rounds_used": 0,
        "round_window_started_at": started_at,
        "round_window_ended_at": None,
        "round_window_end_reason": None,
        "continuation_eligible": True,
    }
    return state, update


def record_round_consumption(
    run_doc: dict[str, Any], round_num: int, *, consumed: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """记录一个尝试是否消耗当前数学 Round 窗口额度。

    基础设施失败可以有独立绝对 Round/资产，但 consumed=False，不浪费本次
    数学工作额度。返回值二：DB窗口字段更新、应写入rounds_log的窗口元数据。
    """
    if run_doc.get("round_window_status") != WINDOW_STATUS_ACTIVE:
        raise ValueError("记录 Round 前必须有 active 调度窗口")

    used = int(run_doc.get("round_window_rounds_used") or 0)
    if consumed:
        used += 1
    update = {"round_window_rounds_used": used}
    metadata = {
        "round_window_id": int(run_doc.get("round_window_id") or 1),
        "round_window_consumed": bool(consumed),
    }
    return update, metadata


def has_window_capacity(run_doc: dict[str, Any]) -> bool:
    """当前窗口是否还能开始新的数学 Round。"""
    if run_doc.get("round_window_status") != WINDOW_STATUS_ACTIVE:
        return False
    size = int(run_doc.get("round_window_size") or 0)
    used = int(run_doc.get("round_window_rounds_used") or 0)
    return size > 0 and used < size


def exhaust_window_fields(
    run_doc: dict[str, Any], *, end_round: int, reason: str,
    now: str | None = None,
) -> dict[str, Any]:
    """生成窗口结束字段；不会把题目写成永久 final_status。"""
    ended_at = now or utc_now()
    history = list(run_doc.get("round_window_history") or [])
    window_id = int(run_doc.get("round_window_id") or 1)
    if not history or history[-1].get("window_id") != window_id:
        history.append({
            "window_id": window_id,
            "start_round": run_doc.get("round_window_start_round"),
            "end_round": end_round,
            "size": run_doc.get("round_window_size"),
            "rounds_used": int(run_doc.get("round_window_rounds_used") or 0),
            "status": WINDOW_STATUS_EXHAUSTED,
            "reason": reason,
            "started_at": run_doc.get("round_window_started_at"),
            "ended_at": ended_at,
        })
    return {
        "status": RUN_STATUS_WINDOW_EXHAUSTED,
        "final_status": None,
        "round_window_status": WINDOW_STATUS_EXHAUSTED,
        "round_window_ended_at": ended_at,
        "round_window_end_reason": reason,
        "round_window_history": history,
        "continuation_eligible": True,
        "next_round": end_round + 1,
        "updated_at": ended_at,
    }


def pause_window_fields(
    run_doc: dict[str, Any], *, end_round: int, reason: str,
    now: str | None = None,
) -> dict[str, Any]:
    """AI放弃等非自动续传结果：暂停当前窗口，但保留未来继续资格。"""
    ended_at = now or utc_now()
    return {
        "round_window_status": WINDOW_STATUS_PAUSED,
        "round_window_ended_at": ended_at,
        "round_window_end_reason": reason,
        "continuation_eligible": True,
        "next_round": end_round + 1,
        "updated_at": ended_at,
    }


def resume_window_fields(
    run_doc: dict[str, Any], *, reason: str, now: str | None = None,
) -> dict[str, Any]:
    """显式开启“可进入下一窗口”的准备态；不直接入 Redis。

    实际入队继续走现有 feeder 的 GATE-FEED-ENQUEUE。历史 final_status 被
    复制到 legacy_final_status 后清空，避免丢失旧 TRUNCATED_AT_MAX 证据。
    """
    if run_doc.get("final_status") == "COMPLETED":
        raise ValueError("已正确完成的题不能作为未解题恢复")
    if not reason.strip():
        raise ValueError("恢复新窗口必须提供 reason")

    resumed_at = now or utc_now()
    update: dict[str, Any] = {
        "status": "prepared",
        "final_status": None,
        "round_window_status": WINDOW_STATUS_PENDING,
        "round_window_start_round": None,
        "round_window_size": None,
        "round_window_rounds_used": 0,
        "round_window_started_at": None,
        "round_window_ended_at": None,
        "round_window_end_reason": None,
        "continuation_eligible": True,
        "next_round": next_absolute_round(run_doc),
        "ended_at": None,
        "resumed_at": resumed_at,
        "resume_reason": reason.strip(),
        "updated_at": resumed_at,
    }
    old_final = run_doc.get("final_status")
    if old_final:
        update["legacy_final_status"] = old_final
    return update
