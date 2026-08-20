"""system_panorama.py — 系统运行过程全景视图（023方案）

设计动机：行为流水（observability）记录了完整的系统运行过程，但现有查看工具
给的是统计聚合（--stats）或原始事件流（--tail），不是"过程叙事"。AI 在 SOP 中
需要的是"系统作为一个整体在如何运行"的可读描述，才能做"分析和推理"。

4层全景视图：
  L1 现状：系统现在在做什么（活跃管线+阶段+进展）
  L2 流畅性：运行过程是否顺畅（速率时间线+卡顿/循环检测）
  L3 流程合规：管线流程是否符合设计（事件序列完整性+门闸通过）
  L4 趋势：运行趋势是什么（完成/失败时间序列+失败模式变化）

数据来源：行为流水（log/flow/，复用 observability.read_flow）+ 门闸流水
（同上，gate_*事件）+ DB 状态。不新增任何记录层。

用法：
  python -m scripts.sop.system_panorama --batch-id p27-full           # 默认1h
  python -m scripts.sop.system_panorama --batch-id p27-full --since 2h
  python -m scripts.sop.system_panorama --batch-id p27-full --layer L1  # 只输出L1
"""
import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.observability import read_flow, _parse_since, _now  # noqa: E402


# ============================================================
# 设计流程的事件序列模式（L3流程合规校验依据）
# ============================================================
# launcher 主循环的正常事件序列：
#   dequeue → [skip_duplicate|skip_orphan|launch_solve|launch_handover]
#             → judge → [requeue|round_done|run_completed|run_failed]
# 每条管线（run_key）的事件序列应符合此模式。
DESIGN_FLOW_AFTER_DEQUEUE = {
    "skip_duplicate", "skip_orphan", "launch_solve", "launch_handover",
}
DESIGN_FLOW_AFTER_JUDGE = {
    "requeue", "round_done", "run_completed", "run_failed",
}
# round1_precheck 是 judge 的一种 outcome，不需要单独的 requeue/done 跟随
# （后面跟的是 launch_handover 开始续传轮，不是 requeue/done）
# stale_proof_ignored 也是终态判定，不需要后续
JUDGE_OUTCOMES_TERMINAL = {
    "completed_by_export", "dead_session", "stale_proof_ignored",
    "round1_precheck",  # seed预检轮判定，后跟launch_handover开始续传轮
}


def _fmt_ts(ts_str):
    """ISO时间戳 → HH:MM 简短格式"""
    try:
        return datetime.fromisoformat(ts_str).strftime("%H:%M")
    except (ValueError, TypeError):
        return "??:??"


def _fmt_duration(seconds):
    """秒 → 人类可读时长"""
    if seconds < 60:
        return f"{int(seconds)}秒"
    if seconds < 3600:
        return f"{int(seconds / 60)}分钟"
    return f"{seconds / 3600:.1f}小时"


# ============================================================
# L1 现状：系统现在在做什么
# ============================================================

def render_l1(entries, since_dt, batch_id):
    """L1 现状：活跃管线清单 + 队列状态 + 并发槽占用"""
    print("--- L1 现状：系统现在在做什么 ---")

    if not entries:
        print("  （窗口内无行为流水——系统可能刚启动或未运行）")
        print()
        return

    now = _now()

    # 按 run_key 聚合事件，重建每条管线的事件序列
    per_run = defaultdict(list)
    batch_events = []
    for e in entries:
        rk = e.get("run_key")
        if rk:
            per_run[rk].append(e)
        else:
            batch_events.append(e)

    # 找出"活跃"管线：最近有 launch_solve/launch_handover 且无后续 run_completed/run_failed
    active_pipelines = []
    completed_in_window = []
    for rk, evs in per_run.items():
        if not evs:
            continue
        evs_sorted = sorted(evs, key=lambda x: x.get("ts_ms", 0))
        last_event = evs_sorted[-1]
        last_event_type = last_event.get("event", "")
        last_ts = last_event.get("ts", "")

        # 判断是否活跃：最后事件是 launch/judge/dequeue 但不是终态
        is_terminal = last_event_type in ("run_completed", "run_failed", "graceful_stop")
        if is_terminal:
            completed_in_window.append((rk, evs_sorted, last_event))
        else:
            active_pipelines.append((rk, evs_sorted, last_event))

    # 输出活跃管线
    if active_pipelines:
        print(f"  活跃管线（{len(active_pipelines)}条，最后事件非终态）：")
        for rk, evs_sorted, last_event in sorted(
            active_pipelines, key=lambda x: x[2].get("ts_ms", 0), reverse=True
        )[:10]:  # 最多显示10条
            last_type = last_event.get("event", "?")
            last_ts = _fmt_ts(last_event.get("ts", ""))
            pid = last_event.get("pid", "?")
            round_num = last_event.get("round", "?")

            # 重建管线轨迹摘要
            trajectory = []
            for e in evs_sorted:
                et = e.get("event", "?")
                if et == "launch_solve":
                    trajectory.append(f"R{e.get('round', '?')}solve")
                elif et == "launch_handover":
                    trajectory.append(f"R{e.get('round', '?')}handover")
                elif et == "judge":
                    outcome = e.get("outcome", "?")
                    trajectory.append(f"judge({outcome})")
                elif et == "requeue":
                    trajectory.append("requeue")
                elif et == "dequeue":
                    trajectory.append("dequeue")
                elif et.startswith("skip_"):
                    trajectory.append(et.replace("skip_", "skip(") + ")")
                elif et == "round_done":
                    trajectory.append("round_done")

            # 计算最后事件距今多久
            try:
                last_dt = datetime.fromisoformat(last_event.get("ts", ""))
                elapsed = (now - last_dt).total_seconds()
                elapsed_str = f"距今{_fmt_duration(elapsed)}"
            except (ValueError, TypeError):
                elapsed_str = ""

            print(f"    {rk}:")
            print(f"      pid={pid} round={round_num} 最后事件={last_type}@{last_ts} ({elapsed_str})")
            if trajectory:
                traj_str = " → ".join(trajectory[-6:])  # 最后6个事件
                print(f"      轨迹: {traj_str}")
        if len(active_pipelines) > 10:
            print(f"    ...（还有{len(active_pipelines) - 10}条活跃管线未显示）")
    else:
        print("  活跃管线：无（窗口内无活跃管线）")

    # 输出窗口内完成的管线
    if completed_in_window:
        print(f"  窗口内完成/失败的管线（{len(completed_in_window)}条）：")
        for rk, evs_sorted, last_event in completed_in_window[:5]:
            last_type = last_event.get("event", "?")
            final_status = last_event.get("final_status", last_event.get("reason", "?"))
            last_ts = _fmt_ts(last_event.get("ts", ""))
            print(f"    {rk}: {last_type}({final_status}) @{last_ts}")
        if len(completed_in_window) > 5:
            print(f"    ...（还有{len(completed_in_window) - 5}条未显示）")

    # 队列状态 + 并发槽（从DB读，失败则跳过）
    try:
        from src.continuation_db_schema import connect_db
        from src.continuation_config import (
            CONTINUATION_RUNS_COLLECTION, CONTINUATION_BATCHES_COLLECTION,
        )
        from src.continuation_redis_queue import get_redis, pending_count
        db = connect_db()

        # prepared 数
        aql_prepared = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status == 'prepared' "
            f"COLLECT WITH COUNT INTO c RETURN c"
        )
        cursor = db.aql.execute(aql_prepared, bind_vars={"bid": batch_id}, ttl=60)
        prepared = list(cursor)[0] if cursor.batch else 0

        # running 数
        aql_running = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status == 'running' "
            f"COLLECT WITH COUNT INTO c RETURN c"
        )
        cursor = db.aql.execute(aql_running, bind_vars={"bid": batch_id}, ttl=60)
        running = list(cursor)[0] if cursor.batch else 0

        # concurrency
        batch_doc = db.collection(CONTINUATION_BATCHES_COLLECTION).get(batch_id)
        concurrency = batch_doc.get("concurrency", "?") if batch_doc else "?"

        # Redis pending
        try:
            r = get_redis()
            redis_pending = pending_count(r)
        except Exception:
            redis_pending = "?"

        print(f"  队列状态：prepared={prepared}（DB） | pending={redis_pending}（Redis）")
        print(f"  并发槽占用：running={running}/{concurrency}（{running}个槽被占用）")
    except Exception as e:
        print(f"  队列/并发状态：DB读取失败（{e}），跳过")

    print()


# ============================================================
# L2 流畅性：运行过程是否顺畅
# ============================================================

def render_l2(entries, since_dt):
    """L2 流畅性：事件速率时间线 + 卡顿检测 + 循环检测"""
    print("--- L2 流畅性：运行过程是否顺畅 ---")

    if not entries:
        print("  （窗口内无行为流水）")
        print()
        return

    now = _now()
    window_seconds = max(1, (now - since_dt).total_seconds())

    # 按时间段分桶（每10分钟一段）
    bucket_seconds = 600  # 10分钟
    num_buckets = max(1, int(window_seconds / bucket_seconds))
    # 限制桶数避免过多
    if num_buckets > 12:
        bucket_seconds = int(window_seconds / 12)
        num_buckets = 12

    buckets = defaultdict(lambda: Counter())
    for e in entries:
        try:
            e_dt = datetime.fromisoformat(e["ts"])
        except (KeyError, ValueError):
            continue
        offset = (e_dt - since_dt).total_seconds()
        bucket_idx = min(int(offset / bucket_seconds), num_buckets - 1)
        buckets[bucket_idx][e.get("event", "?")] += 1

    # 输出速率时间线
    print(f"  事件速率时间线（每{_fmt_duration(bucket_seconds)}一段）：")
    for i in range(num_buckets):
        bucket_start = since_dt + timedelta(seconds=i * bucket_seconds)
        bucket_end = bucket_start + timedelta(seconds=bucket_seconds)
        counts = buckets.get(i, Counter())
        total = sum(counts.values())
        dequeue = counts.get("dequeue", 0)
        launch = counts.get("launch_solve", 0) + counts.get("launch_handover", 0)
        judge = counts.get("judge", 0)
        done = counts.get("run_completed", 0) + counts.get("run_failed", 0)
        requeue = counts.get("requeue", 0)

        if total == 0:
            print(f"    {_fmt_ts(bucket_start.isoformat())}-{_fmt_ts(bucket_end.isoformat())}: "
                  f"无事件（停滞？）")
        else:
            print(f"    {_fmt_ts(bucket_start.isoformat())}-{_fmt_ts(bucket_end.isoformat())}: "
                  f"dequeue={dequeue} launch={launch} judge={judge} done={done} requeue={requeue}")

    # 卡顿检测：只检测"有事件但无judge"的连续段（系统在跑但无判定输出=卡顿）
    # "无事件"段=系统未运行，不算卡顿
    stall_segments = 0
    max_stall = 0
    current_stall = 0
    for i in range(num_buckets):
        counts = buckets.get(i, Counter())
        total_in_bucket = sum(counts.values())
        has_judge = counts.get("judge", 0) > 0
        if not has_judge and total_in_bucket > 0:
            # 有事件但无judge=卡顿
            current_stall += 1
            max_stall = max(max_stall, current_stall)
        elif has_judge:
            if current_stall > 0:
                stall_segments += 1
            current_stall = 0
        # 无事件段=系统未运行，重置卡顿计数（不累加）
        else:
            if current_stall > 0:
                stall_segments += 1
            current_stall = 0

    if max_stall > 0:
        stall_minutes = max_stall * bucket_seconds / 60
        print(f"  卡顿检测：最长连续{int(stall_minutes)}分钟有事件但无judge"
              f"（{stall_segments}个卡顿段，不含系统未运行时段）")
        if stall_minutes > 30:
            print(f"    ⚠️ 卡顿超过30分钟——系统可能停滞（rate_limit? launcher挂?）")
    else:
        print(f"  卡顿检测：无（系统运行时段每段都有judge事件）")

    # 循环检测：churn_suspects 可读化
    per_run_launch = Counter()
    hour_ago = now - timedelta(hours=1)
    for e in entries:
        if e.get("event") in ("launch_solve", "launch_handover"):
            rk = e.get("run_key")
            if rk:
                try:
                    e_dt = datetime.fromisoformat(e["ts"])
                    if e_dt >= hour_ago:
                        per_run_launch[rk] += 1
                except (ValueError, KeyError):
                    pass

    churn_suspects = {rk: n for rk, n in per_run_launch.items() if n >= 5}
    if churn_suspects:
        print(f"  ⚠️ 失控循环嫌疑（1小时内启动≥5次）：")
        for rk, n in sorted(churn_suspects.items(), key=lambda x: -x[1])[:5]:
            print(f"    {rk}: 启动{n}次——其他题可能在等待，此题在反复启动")
    else:
        max_launch = max(per_run_launch.values()) if per_run_launch else 0
        print(f"  循环检测：无失控嫌疑（1小时内最多启动{max_launch}次/题，阈值5）")

    print()


# ============================================================
# L3 流程合规：管线流程是否符合设计
# ============================================================

def render_l3(entries, since_dt):
    """L3 流程合规：事件序列完整性 + 门闸通过情况"""
    print("--- L3 流程合规：管线流程是否符合设计 ---")

    if not entries:
        print("  （窗口内无行为流水）")
        print()
        return

    # 门闸事件统计
    gate_pass = Counter()
    gate_waiting = []
    gate_release = []
    for e in entries:
        if e.get("event") == "gate_pass":
            gid = e.get("gate_id", "?")
            gate_pass[gid] += 1
        elif e.get("event") == "gate_waiting":
            gate_waiting.append(e)
        elif e.get("event") == "gate_release":
            gate_release.append(e)

    # 门闸通过统计
    if gate_pass:
        print(f"  门闸通过统计（窗口内{sum(gate_pass.values())}次auto通过）：")
        for gid, n in sorted(gate_pass.items()):
            print(f"    {gid}: {n}次")
    else:
        print(f"  门闸通过统计：无gate_pass事件（门闸全auto或系统未触发门闸动作）")

    # 门闸冻结
    if gate_waiting:
        print(f"  ⚠️ 门闸冻结（{len(gate_waiting)}条gate_waiting事件）：")
        # 取最近的waiting
        recent_waiting = sorted(gate_waiting, key=lambda x: x.get("ts_ms", 0), reverse=True)[:3]
        for e in recent_waiting:
            gid = e.get("gate_id", "?")
            ts = _fmt_ts(e.get("ts", ""))
            waited = e.get("waited_seconds", "?")
            print(f"    {gid} @{ts} 已等待{waited}秒")
    else:
        print(f"  门闸冻结：无（所有门闸auto模式，无waiting）")

    if gate_release:
        print(f"  门闸放行（{len(gate_release)}次）：")
        for e in gate_release[-3:]:  # 最近3次
            gid = e.get("gate_id", "?")
            reason = e.get("reason", "(无理由)")
            print(f"    {gid}: {reason}")

    # 事件序列完整性校验
    # 只校验核心业务事件，忽略辅助事件（gate_pass/gate_done/enqueue等）
    CORE_EVENTS = {
        "dequeue", "skip_duplicate", "skip_orphan",
        "launch_solve", "launch_handover",
        "judge", "requeue", "round_done",
        "run_completed", "run_failed",
    }

    per_run = defaultdict(list)
    for e in entries:
        rk = e.get("run_key")
        if rk and e.get("event") in CORE_EVENTS:
            per_run[rk].append(e)

    print(f"  事件序列完整性校验（{len(per_run)}条管线，只看核心业务事件）：")

    valid_sequences = 0
    anomalies = []
    incomplete = 0

    for rk, evs in per_run.items():
        evs_sorted = sorted(evs, key=lambda x: x.get("ts_ms", 0))
        events_seq = [e.get("event", "?") for e in evs_sorted]

        has_anomaly = False
        anomaly_desc = []

        for i, et in enumerate(events_seq):
            # launch 前应有 dequeue 或 requeue
            if et in ("launch_solve", "launch_handover"):
                recent = events_seq[max(0, i - 3):i]
                if "dequeue" not in recent and "requeue" not in recent:
                    # handover 可能从 handover_pending 转来（前一轮 round_done 后）
                    if et == "launch_solve" and "round_done" not in recent:
                        has_anomaly = True
                        anomaly_desc.append("launch_solve无前置dequeue/requeue/round_done")

            # judge 后应有后续（除非outcome是terminal类）
            if et == "judge":
                outcome = evs_sorted[i].get("outcome", "")
                if outcome in JUDGE_OUTCOMES_TERMINAL:
                    continue
                following = events_seq[i + 1:i + 3]
                if not any(f in DESIGN_FLOW_AFTER_JUDGE for f in following):
                    if i == len(events_seq) - 1:
                        incomplete += 1
                    else:
                        has_anomaly = True
                        anomaly_desc.append("judge后无requeue/done事件")

            # 终态后不应再有核心事件
            if et in ("run_completed", "run_failed"):
                if i < len(events_seq) - 1:
                    has_anomaly = True
                    anomaly_desc.append(f"终态后仍有事件: {events_seq[i + 1:]}")

        if has_anomaly:
            anomalies.append((rk, anomaly_desc, events_seq))
        else:
            valid_sequences += 1

    print(f"    ✅ 完整序列：{valid_sequences}条")
    print(f"    ⏳ 进行中（judge后无后续，可能还在跑）：{incomplete}条")
    if anomalies:
        print(f"    ❌ 异常序列：{len(anomalies)}条")
        for rk, desc, seq in anomalies[:3]:
            print(f"      {rk}: {desc}")
            print(f"        序列: {' → '.join(seq[:10])}")
        if len(anomalies) > 3:
            print(f"      ...（还有{len(anomalies) - 3}条异常未显示）")
    else:
        print(f"    ❌ 异常序列：0条")

    print()


# ============================================================
# L4 趋势：运行趋势是什么
# ============================================================

def render_l4(entries, since_dt):
    """L4 趋势：完成/失败时间序列 + 失败模式分布变化 + 判定结果分布变化"""
    print("--- L4 趋势：运行趋势是什么 ---")

    if not entries:
        print("  （窗口内无行为流水）")
        print()
        return

    now = _now()
    window_seconds = max(1, (now - since_dt).total_seconds())

    # 按时间段分桶（每30分钟一段，最多6段）
    bucket_seconds = 1800  # 30分钟
    num_buckets = max(1, int(window_seconds / bucket_seconds))
    if num_buckets > 6:
        bucket_seconds = int(window_seconds / 6)
        num_buckets = 6

    completed_buckets = defaultdict(int)
    failed_buckets = defaultdict(int)
    judge_outcome_buckets = defaultdict(Counter)
    failed_reason_buckets = defaultdict(Counter)

    for e in entries:
        try:
            e_dt = datetime.fromisoformat(e["ts"])
        except (KeyError, ValueError):
            continue
        offset = (e_dt - since_dt).total_seconds()
        bucket_idx = min(int(offset / bucket_seconds), num_buckets - 1)
        et = e.get("event", "?")
        if et == "run_completed":
            completed_buckets[bucket_idx] += 1
        elif et == "run_failed":
            failed_buckets[bucket_idx] += 1
            reason = e.get("reason", "?")
            failed_reason_buckets[bucket_idx][reason] += 1
        elif et == "judge":
            outcome = e.get("outcome", "?")
            judge_outcome_buckets[bucket_idx][outcome] += 1

    # 完成/失败时间序列
    print(f"  完成/失败时间序列（每{_fmt_duration(bucket_seconds)}一段）：")
    prev_completed = None
    prev_failed = None
    for i in range(num_buckets):
        bucket_start = since_dt + timedelta(seconds=i * bucket_seconds)
        c = completed_buckets.get(i, 0)
        f = failed_buckets.get(i, 0)

        # 趋势箭头
        c_trend = ""
        f_trend = ""
        if prev_completed is not None:
            if c > prev_completed:
                c_trend = " ↑"
            elif c < prev_completed:
                c_trend = " ↓"
        if prev_failed is not None:
            if f > prev_failed:
                f_trend = " ↑"
            elif f < prev_failed:
                f_trend = " ↓"

        print(f"    {_fmt_ts(bucket_start.isoformat())}: completed={c}{c_trend} failed={f}{f_trend}")
        prev_completed = c
        prev_failed = f

    # 失败模式分布变化
    all_reasons = set()
    for reasons in failed_reason_buckets.values():
        all_reasons.update(reasons.keys())

    if all_reasons:
        print(f"  失败模式分布变化：")
        for i in range(num_buckets):
            bucket_start = since_dt + timedelta(seconds=i * bucket_seconds)
            reasons = failed_reason_buckets.get(i, Counter())
            if reasons:
                reasons_str = ", ".join(f"{r}={n}" for r, n in reasons.most_common())
                print(f"    {_fmt_ts(bucket_start.isoformat())}: {reasons_str}")
            else:
                print(f"    {_fmt_ts(bucket_start.isoformat())}: 无失败")

    # 判定结果分布变化
    all_outcomes = set()
    for outcomes in judge_outcome_buckets.values():
        all_outcomes.update(outcomes.keys())

    if all_outcomes:
        print(f"  判定结果分布变化：")
        for i in range(num_buckets):
            bucket_start = since_dt + timedelta(seconds=i * bucket_seconds)
            outcomes = judge_outcome_buckets.get(i, Counter())
            if outcomes:
                outcomes_str = ", ".join(f"{o}={n}" for o, n in outcomes.most_common())
                print(f"    {_fmt_ts(bucket_start.isoformat())}: {outcomes_str}")
            else:
                print(f"    {_fmt_ts(bucket_start.isoformat())}: 无判定")

    # 趋势总结
    total_completed = sum(completed_buckets.values())
    total_failed = sum(failed_buckets.values())
    first_half_completed = sum(completed_buckets.get(i, 0) for i in range(num_buckets // 2))
    second_half_completed = sum(
        completed_buckets.get(i, 0) for i in range(num_buckets // 2, num_buckets)
    )

    print(f"  趋势总结：")
    print(f"    窗口内完成{total_completed}题，失败{total_failed}题")
    if num_buckets >= 2:
        if second_half_completed > first_half_completed:
            print(f"    → 完成速率在上升（前半{first_half_completed}→后半{second_half_completed}）")
        elif second_half_completed < first_half_completed:
            print(f"    → 完成速率在下降（前半{first_half_completed}→后半{second_half_completed}）")
        else:
            print(f"    → 完成速率稳定（前半{first_half_completed}→后半{second_half_completed}）")

    print()


# ============================================================
# 主入口
# ============================================================

def generate_panorama(batch_id, since_str="1h", layer=None):
    """生成全景视图并输出到stdout"""
    since_dt = _parse_since(since_str)
    if since_dt is None:
        since_dt = _now() - timedelta(hours=1)

    entries = read_flow(since=since_dt)

    now = _now()
    window_str = since_str or "全部"

    print(f"=== 系统运行过程全景视图 ===")
    print(f"窗口：过去 {window_str} | 生成时间：{now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
          f" | batch: {batch_id} | 事件数: {len(entries)}")
    print()

    if layer is None or layer.upper() == "L1":
        render_l1(entries, since_dt, batch_id)
    if layer is None or layer.upper() == "L2":
        render_l2(entries, since_dt)
    if layer is None or layer.upper() == "L3":
        render_l3(entries, since_dt)
    if layer is None or layer.upper() == "L4":
        render_l4(entries, since_dt)

    if layer is None:
        print("=== 全景视图结束 ===")
        print("AI分析指引：在认知闭包背景下阅读以上4层，分析和推理系统运行是否正常。")
        print("L1现状——系统在做什么？L2流畅性——节奏正常吗？"
              "L3流程合规——流程按设计走吗？L4趋势——在变好还是变差？")


def _main():
    ap = argparse.ArgumentParser(description="系统运行过程全景视图（023方案）")
    ap.add_argument("--batch-id", default="p27-full", help="批次ID（默认p27-full）")
    ap.add_argument("--since", default="1h", help="时间窗口，如 30m/1h/2d（默认1h）")
    ap.add_argument("--layer", choices=["L1", "L2", "L3", "L4"],
                    help="只输出某层（默认全部）")
    args = ap.parse_args()

    generate_panorama(args.batch_id, args.since, args.layer)


if __name__ == "__main__":
    _main()
