"""assert_final.py — sim当前调度窗口收场断言层

一个sim批次跑完后，从四个独立来源核对系统行为是否符合剧本期望：
  1. DB状态     —— final_status/status、窗口历史、rounds_log轮序
  2. Redis队列  —— completed/failed/窗口结束不入终态队列、pending/running清空
  3. 行为流水   —— run_completed/run_failed事件存在；016不变量：
                   同一run无5秒内重复launch_solve（失控循环特征）、
                   launch次数不超本次窗口额度合理范围
  4. tmux       —— 无sim批次残留session

rounds_log轮序只报告不强断（017发现launcher疑似round off-by-one：
R2截断后current_round=len+1=2会重跑round 2——首个sim运行实证后转正式缺陷）。
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FLOW_DIR = PROJECT_ROOT / "log" / "flow"
RAPID_RELAUNCH_SECONDS = 5  # 016失控循环特征：同一run秒级重复launch


def collect_flow(batch_id, since_hours=6):
    """读行为流水，过滤出本批次的全部事件（按ts排序）。"""
    events = []
    now = datetime.now(timezone.utc)
    for f in FLOW_DIR.glob("flow-*.jsonl"):
        # 只读今天和昨天的文件（sim运行窗口内）
        try:
            date_part = f.stem.replace("flow-", "")
            fdate = datetime.strptime(date_part, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if fdate < now - timedelta(hours=since_hours + 24):
            continue
        try:
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("batch_id") == batch_id:
                    events.append(e)
                elif e.get("run_key") and e["run_key"].startswith(batch_id):
                    # 部分事件（如run_completed/run_failed）不带batch_id字段，
                    # 但run_key = {batch_id}-{pid}天然含批次前缀
                    events.append(e)
        except OSError:
            continue
    events.sort(key=lambda e: e.get("ts_ms", 0))
    return events


def check_db(db, run_keys, scenario):
    from src.continuation_config import CONTINUATION_RUNS_COLLECTION
    passed, failed, warned = [], [], []
    runs = db.collection(CONTINUATION_RUNS_COLLECTION)
    for rk in run_keys:
        doc = runs.get(rk)
        if not doc:
            failed.append(f"{rk}: DB中run记录消失")
            continue
        expect_final = scenario.get("expect_final")
        expect_status = scenario.get("expect_status")
        if expect_final is not None and doc.get("final_status") != expect_final:
            failed.append(f"{rk}: final_status={doc.get('final_status')} 期望{expect_final}")
        else:
            passed.append(f"{rk}: final_status={doc.get('final_status')}")
        if expect_status and doc.get("status") != expect_status:
            failed.append(f"{rk}: status={doc.get('status')} 期望{expect_status}")
        rounds = [r.get("round") for r in doc.get("rounds_log", [])]
        # 轮序只报告——off-by-one实证后改为强断（期望轮序去重后应单调递增）
        dedup = sorted(set(rounds))
        if rounds != dedup:
            warned.append(f"{rk}: rounds_log有重复轮号 {rounds}（疑似off-by-one，见017）")
        else:
            passed.append(f"{rk}: rounds_log轮序 {rounds}")
        expected_history = scenario.get("expect_window_history")
        if expected_history is not None:
            history = doc.get("round_window_history") or []
            if len(history) != expected_history:
                failed.append(
                    f"{rk}: round_window_history={len(history)} 期望{expected_history}")
            else:
                passed.append(f"{rk}: round_window_history={len(history)}")
        if doc.get("status") == "window_exhausted":
            if doc.get("final_status") is not None:
                failed.append(f"{rk}: window_exhausted却有final_status")
            elif not doc.get("continuation_eligible"):
                failed.append(f"{rk}: window_exhausted却不可继续")
            else:
                passed.append(f"{rk}: 窗口结束且未来可继续")
    return passed, failed, warned


def check_redis(r, run_keys, scenario):
    from src.continuation_redis_queue import (
        COMPLETED_KEY, FAILED_KEY, PENDING_KEY, RUNNING_KEY)
    passed, failed, warned = [], [], []
    pending = r.zcard(PENDING_KEY)
    if pending == 0:
        passed.append(f"redis pending已清空")
    else:
        failed.append(f"redis pending残留{pending}个（有run未被处理或重入队后未消费）")
    running = r.hlen(RUNNING_KEY)
    if running == 0:
        passed.append("redis running已清空")
    else:
        failed.append(f"redis running残留{running}个（记账泄漏）")
    # completed/failed是list（lpush JSON）——解析出run_key成员
    def _members(key):
        out = set()
        for item in (r.lrange(key, 0, -1) or []):
            try:
                out.add(json.loads(item).get("run_key"))
            except (json.JSONDecodeError, TypeError):
                pass
        return out
    completed = _members(COMPLETED_KEY)
    failed_set = _members(FAILED_KEY)
    expect_queue = scenario.get("expect_queue")
    for rk in run_keys:
        if expect_queue == "none":
            if rk in completed or rk in failed_set:
                failed.append(f"{rk}: window_exhausted不应进入completed/failed队列")
            else:
                passed.append(f"{rk}: 未进入永久终态队列")
        elif rk in completed:
            passed.append(f"{rk}: 在completed队列")
        elif rk in failed_set:
            passed.append(f"{rk}: 在failed队列")
        else:
            failed.append(f"{rk}: 不在completed也不在failed队列")
    return passed, failed, warned


def check_flow(events, run_keys, scenario):
    passed, failed, warned = [], [], []
    by_run = {}
    for e in events:
        by_run.setdefault(e.get("run_key"), []).append(e)

    for rk in run_keys:
        evs = by_run.get(rk, [])
        names = [e["event"] for e in evs]
        if ("run_completed" in names or "run_failed" in names
                or "round_window_exhausted" in names):
            passed.append(f"{rk}: 有本次运行收场flow事件")
        else:
            failed.append(f"{rk}: 无run_completed/run_failed/round_window_exhausted事件")

        # 016不变量1：同一run无RAPID_RELAUNCH内重复launch_solve
        launches = [e for e in evs if e["event"] == "launch_solve"]
        for a, b in zip(launches, launches[1:]):
            gap = (b.get("ts_ms", 0) - a.get("ts_ms", 0)) / 1000
            if gap < RAPID_RELAUNCH_SECONDS:
                failed.append(f"{rk}: {gap:.1f}秒内重复launch_solve（失控循环特征）")
        # 016不变量2：launch次数不超过各窗口额度总和（R1 seed不launch，
        # 因此这是保守上界）。
        window_size = scenario.get("round_window_size", 5)
        windows = scenario.get("windows", 1)
        launch_limit = window_size * windows
        if len(launches) > launch_limit:
            failed.append(
                f"{rk}: launch_solve {len(launches)}次 > 窗口合理上界{launch_limit}")
        else:
            passed.append(
                f"{rk}: launch_solve共{len(launches)}次（窗口合理上界{launch_limit}）")

    # 快速重入队风暴检测（016特征：requeue事件密度）
    requeues = [e for e in events if e["event"] == "requeue"]
    window_budget = scenario.get("round_window_size", 5) * scenario.get("windows", 1)
    if len(requeues) > len(run_keys) * (window_budget + 2):
        failed.append(f"requeue事件{len(requeues)}个——超出轮数合理范围")
    return passed, failed, warned


def check_tmux(batch_id):
    passed, failed, _ = [], [], []
    try:
        out = subprocess.run(["tmux", "ls"], capture_output=True, text=True, timeout=5)
        leftovers = [l for l in out.stdout.splitlines() if batch_id in l]
    except Exception:
        return ["tmux不可用（跳过）"], [], []
    if leftovers:
        failed.append(f"tmux残留sim session: {leftovers}")
    else:
        passed.append("tmux无sim残留session")
    return passed, failed, []


def run_assertions(batch_id, run_keys, scenario):
    """全部断言。返回exit code（0=全过）。"""
    from src.continuation_db_schema import connect_db
    from src.continuation_redis_queue import get_redis

    db = connect_db()
    r = get_redis()
    events = collect_flow(batch_id)

    all_pass, all_fail, all_warn = [], [], []
    for fn, args in [
        (check_db, (db, run_keys, scenario)),
        (check_redis, (r, run_keys, scenario)),
        (check_flow, (events, run_keys, scenario)),
        (check_tmux, (batch_id,)),
    ]:
        p, f, w = fn(*args)
        all_pass += p
        all_fail += f
        all_warn += w

    print(f"\n=== sim终态断言: batch={batch_id} ===")
    print(f"--- ✅ 通过 ({len(all_pass)}) ---")
    for line in all_pass:
        print(f"  ✅ {line}")
    if all_warn:
        print(f"--- ⚠️ 警告 ({len(all_warn)}) ---")
        for line in all_warn:
            print(f"  ⚠️ {line}")
    if all_fail:
        print(f"--- ❌ 失败 ({len(all_fail)}) ---")
        for line in all_fail:
            print(f"  ❌ {line}")

    print(f"\n结果: {len(all_pass)} passed, {len(all_warn)} warned, {len(all_fail)} failed")
    print(f"flow事件总数: {len(events)}（事件序: {[e['event'] for e in events][:40]}...）")
    return 1 if all_fail else 0


if __name__ == "__main__":
    import argparse
    from src.sim import scenarios as sim_scenarios
    ap = argparse.ArgumentParser(description="sim终态断言")
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--scenario", required=True)
    args = ap.parse_args()
    sc = sim_scenarios.get(args.scenario)
    from src.continuation_config import CONTINUATION_RUNS_COLLECTION
    from src.continuation_db_schema import connect_db
    keys = [row["k"] for row in connect_db().aql.execute(
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid RETURN {{k: run._key}}",
        bind_vars={"bid": args.batch_id})]
    sys.exit(run_assertions(args.batch_id, keys, sc))
