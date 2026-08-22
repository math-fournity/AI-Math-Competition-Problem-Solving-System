#!/usr/bin/env python3
"""WP-01 Round窗口纯逻辑回归测试（无DB/Redis/文件写入）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.round_window import (
    RUN_STATUS_WINDOW_EXHAUSTED,
    WINDOW_STATUS_ACTIVE,
    WINDOW_STATUS_EXHAUSTED,
    WINDOW_STATUS_PENDING,
    ensure_active_window,
    exhaust_window_fields,
    has_window_capacity,
    next_absolute_round,
    pause_window_fields,
    record_round_consumption,
    resume_window_fields,
)
from scripts.manage_continuation_windows import is_default_eligible


def merge(doc, update):
    out = dict(doc)
    out.update(update)
    return out


def test_two_windows_keep_absolute_rounds():
    doc = {"rounds_log": [], "status": "prepared", "final_status": None}
    state, update = ensure_active_window(doc, 2, now="t1")
    assert state == {"id": 1, "start_round": 1, "size": 2, "used": 0}
    doc = merge(doc, update)

    for n in (1, 2):
        win_update, meta = record_round_consumption(doc, n, consumed=True)
        entry = {"round": n, **meta}
        doc = merge(doc, win_update)
        doc["rounds_log"] = [*doc["rounds_log"], entry]
    assert not has_window_capacity(doc)

    doc = merge(doc, exhaust_window_fields(doc, end_round=2, reason="quota", now="t2"))
    assert doc["status"] == RUN_STATUS_WINDOW_EXHAUSTED
    assert doc["final_status"] is None
    assert doc["next_round"] == 3
    assert doc["round_window_history"][0]["rounds_used"] == 2

    doc = merge(doc, resume_window_fields(doc, reason="继续研究", now="t3"))
    assert doc["status"] == "prepared"
    assert doc["round_window_status"] == WINDOW_STATUS_PENDING
    assert next_absolute_round(doc) == 3

    state, update = ensure_active_window(doc, 2, now="t4")
    assert state["id"] == 2
    assert state["start_round"] == 3
    doc = merge(doc, update)
    assert doc["round_window_status"] == WINDOW_STATUS_ACTIVE


def test_infra_attempt_does_not_consume_math_quota():
    doc = {"rounds_log": []}
    _, update = ensure_active_window(doc, 1, now="t1")
    doc = merge(doc, update)
    win_update, meta = record_round_consumption(doc, 1, consumed=False)
    doc = merge(doc, win_update)
    doc["rounds_log"] = [{"round": 1, **meta}]
    assert doc["round_window_rounds_used"] == 0
    assert has_window_capacity(doc)


def test_ai_gave_up_is_resumable():
    doc = {"rounds_log": [{"round": 1}], "round_window_status": WINDOW_STATUS_ACTIVE}
    paused = pause_window_fields(doc, end_round=1, reason="ai_gave_up", now="t2")
    doc = merge(doc, paused)
    assert doc["continuation_eligible"] is True
    assert doc["next_round"] == 2
    resumed = resume_window_fields(doc, reason="换模型继续", now="t3")
    assert resumed["status"] == "prepared"


def test_legacy_truncated_preserved_on_resume():
    doc = {
        "rounds_log": [{"round": 1}, {"round": 2}],
        "status": "completed",
        "final_status": "TRUNCATED_AT_MAX",
    }
    update = resume_window_fields(doc, reason="迁移旧窗口终态", now="t")
    assert update["legacy_final_status"] == "TRUNCATED_AT_MAX"
    assert update["final_status"] is None
    assert update["next_round"] == 3


def test_completed_cannot_resume():
    doc = {"rounds_log": [], "final_status": "COMPLETED"}
    try:
        resume_window_fields(doc, reason="不应允许")
    except ValueError:
        pass
    else:
        raise AssertionError("COMPLETED run unexpectedly resumable")


def test_invalid_window_size():
    try:
        ensure_active_window({"rounds_log": []}, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("zero window size unexpectedly accepted")


def test_active_window_repairs_missing_persisted_fields():
    doc = {"round_window_status": WINDOW_STATUS_ACTIVE, "rounds_log": [{"round": 3}]}
    state, update = ensure_active_window(doc, 2, now="unused")
    assert state == {"id": 1, "start_round": 4, "size": 2, "used": 0}
    assert update["round_window_start_round"] == 4
    assert update["round_window_size"] == 2
    assert update["continuation_eligible"] is True


def test_default_resume_candidate_filter():
    assert is_default_eligible({"status": "window_exhausted"})
    assert is_default_eligible({"status": "ai_gave_up"})
    assert is_default_eligible({"final_status": "TRUNCATED_AT_MAX"})
    assert is_default_eligible({"status": "dead_session", "continuation_eligible": True})
    assert not is_default_eligible({"status": "dead_session", "final_status": None})
    assert not is_default_eligible({"status": "running", "continuation_eligible": True})


def test_next_round_uses_historical_max_not_length():
    doc = {"rounds_log": [{"round": 2}, {"round": 2}, {"round": 5}]}
    assert next_absolute_round(doc) == 6


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")


if __name__ == "__main__":
    main()
