#!/usr/bin/env python3
"""runtime_health_check.py — 错题分析系统运行时健康检查

系统运行时检查并发安全性、资源泄漏、DB-Redis一致性、网络健康等。
analysis_control.py health检查基础设施健康，本脚本检查运行时动态健康。

模仿solver_harness的concurrency_safety_check.py（10个维度A-J）。

检查维度：
  A. Redis操作原子性——dequeue+add_running间隙的丢题风险
  B. DB-Redis一致性——DB running数 vs Redis running数，孤儿记录
  C. 重复run检测——同一problem_id被多个run同时running
  D. 并发上限实际验证——设定并发 vs Redis running vs tmux session数
  E. devin进程数 vs 并发数——僵尸devin进程堆积
  F. 网络连接健康度——API可达性、HTTP错误率、rate limit
  G. devin异常退出率——dead_session占比、completed率、趋势
  H. 落盘完整性——completed的run是否有tmux_pipe.log和AGENTS.md
  I. 批次进度健康——pending是否堆积、failed率是否过高
  J. 日志健康——最近日志中是否有大量错误

用法:
  cd analysis-devin-failure-system
  python -m monitoring.runtime_health_check
  python -m monitoring.runtime_health_check --batch-id <id>
"""
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from src.config import (
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    ANALYSIS_TRAJECTORY_BASE, ANALYSIS_SOLVER_BASE, OUTPUT_BASE,
    INFRA_FAILURES, MODEL_FAILURES,
)
from src.db_schema import (
    ANALYSIS_RUNS_COLLECTION, ANALYSIS_BATCHES_COLLECTION,
    ANALYSIS_EVENTS_COLLECTION, ANALYSIS_RESULTS_COLLECTION,
)
from monitoring.redis_queue import (
    get_redis, get_all_running, running_count, pending_count,
    completed_count, failed_count, get_stats, ping,
)
from monitoring.shared_logger import get_logger, LOG_BASE

logger = get_logger("health_check")

TRAJ = ANALYSIS_TRAJECTORY_BASE
LOG_DIR = LOG_BASE


def connect_db():
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)


def check_a_redis_atomicity(r):
    """A. Redis操作原子性——检查dequeue+add_running间隙的丢题风险"""
    print("【A. Redis操作原子性】")
    running = get_all_running(r)
    no_run_key = sum(1 for v in running.values() if not v.get("run_key"))
    print(f"  running中run_key为空: {no_run_key}", "❌" if no_run_key else "✅")
    if no_run_key:
        print("  (dequeue→add_running间隙crash会丢题，已知风险，recover_from_crash兜底)")
    return no_run_key


def check_b_db_redis_consistency(db, r):
    """B. DB-Redis一致性——DB running数 vs Redis running数"""
    print("【B. DB-Redis一致性】")
    redis_running = r.hlen("analysis:running")
    redis_running_keys = set(r.hkeys("analysis:running"))

    db_running = list(db.aql.execute(
        f"FOR r IN {ANALYSIS_RUNS_COLLECTION} "
        f"FILTER r.status == 'running' OR r.status == 'launching' "
        f"RETURN r._key"
    ))
    db_running_set = set(db_running)

    print(f"  Redis running: {redis_running}")
    print(f"  DB running:    {len(db_running)}")

    redis_not_db = redis_running_keys - db_running_set
    db_not_redis = db_running_set - redis_running_keys

    print(f"  Redis有DB无: {len(redis_not_db)}", "⚠️" if redis_not_db else "✅", "(launcher正在写DB)")
    print(f"  DB有Redis无(孤儿): {len(db_not_redis)}", "❌" if db_not_redis else "✅")
    if db_not_redis:
        print(f"    孤儿示例: {list(db_not_redis)[:3]}")
    return len(db_not_redis)


def check_c_duplicate_run(r):
    """C. 重复run检测——同一problem_id被多个run同时running"""
    print("【C. 重复run检测】")
    running = get_all_running(r)
    pids = [v.get("problem_id", "") for v in running.values()]
    dupes = {k: v for k, v in Counter(pids).items() if v > 1}
    print(f"  running中run数: {len(pids)}")
    print(f"  唯一problem_id数: {len(set(pids))}")
    print(f"  重复problem_id: {len(dupes)}", "❌" if dupes else "✅")
    if dupes:
        for pid, cnt in dupes.items():
            print(f"    {pid}: {cnt}次")
    return len(dupes)


def check_d_concurrency_limit(db, r):
    """D. 并发上限实际验证——设定并发 vs Redis running vs tmux session数"""
    print("【D. 并发上限实际验证】")
    # 从DB读取最近批次的concurrency
    batch = list(db.aql.execute(
        f"FOR b IN {ANALYSIS_BATCHES_COLLECTION} "
        f"FILTER b.status == 'launching' OR b.status == 'launched' "
        f"SORT b.updated_at DESC LIMIT 1 RETURN b"
    ))
    conc = int(batch[0].get("concurrency", 0)) if batch else 0
    redis_running = r.hlen("analysis:running")

    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True)
    an_sessions = [l for l in result.stdout.split("\n") if l.startswith("an-")]

    print(f"  设定并发:        {conc}")
    print(f"  Redis running:   {redis_running}")
    print(f"  an- tmux sessions: {len(an_sessions)}")

    over_limit = redis_running > conc + 5 if conc else False
    print(f"  running超并发:   {'❌' if over_limit else '✅'} (允许+5)")
    return 1 if over_limit else 0


def check_e_devin_process_count():
    """E. devin进程数 vs 并发数——僵尸devin进程堆积"""
    print("【E. devin进程数 vs 并发数】")
    result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
    devin_procs = [line for line in result.stdout.split("\n")
                   if "devin" in line and "grep" not in line
                   and "runtime_health" not in line and "health_check" not in line]
    node_procs = [p for p in devin_procs if "node" in p]

    print(f"  devin相关进程: {len(devin_procs)}")
    print(f"  其中node进程:  {len(node_procs)}")
    return len(devin_procs)


def check_f_network_health(r):
    """F. 网络连接健康度——API可达性、TCP连接数、HTTP错误率、rate limit"""
    print("【F. 网络连接健康度】")
    issues = 0

    # 1. 从running的devin进程提取TCP连接
    ps_result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
    devin_pids = [line.split()[1] for line in ps_result.stdout.split("\n")
                  if "devin" in line and "grep" not in line
                  and "runtime_health" not in line and "health_check" not in line
                  and line.strip()]

    established_conns = 0
    for pid in devin_pids:
        try:
            lsof = subprocess.run(
                ["lsof", "-i", "-a", "-p", pid],
                capture_output=True, text=True, timeout=5
            )
            established_conns += sum(1 for line in lsof.stdout.split("\n") if "ESTABLISHED" in line)
        except Exception:
            pass

    conc = r.hlen("analysis:running")
    expected_conns = conc * 2
    print(f"  devin进程TCP连接数: {established_conns} (共{len(devin_pids)}个进程)")
    print(f"  预期连接数: ~{expected_conns} (并发{conc}×2)")
    if conc > 0:
        if established_conns < conc * 0.5:
            print(f"  ❌ TCP连接数远低于并发数，网络可能断连")
            issues += 1
        elif established_conns < conc:
            print(f"  ⚠️ TCP连接数低于并发数")
        else:
            print(f"  ✅ TCP连接数正常")

    # 2. 从launcher日志统计最近网络错误
    launcher_log = LOG_DIR / "launcher.log"
    network_errors = 0
    rate_limits = 0
    if launcher_log.exists():
        log_text = launcher_log.read_text(errors="ignore")
        recent_lines = log_text.split("\n")[-500:]
        network_patterns = [
            "connection error", "econnrefused", "econnreset", "socket hang up",
            "fetch failed", "network error", "network request failed", "etimedout",
        ]
        rate_limit_patterns = ["rate limit", "429", "too many requests"]
        for line in recent_lines:
            line_lower = line.lower()
            if any(p in line_lower for p in network_patterns):
                network_errors += 1
            if any(p in line_lower for p in rate_limit_patterns):
                rate_limits += 1

    print(f"  launcher最近500行中网络错误: {network_errors}",
          "❌" if network_errors > 5 else ("⚠️" if network_errors > 0 else "✅"))
    print(f"  launcher最近500行中rate limit: {rate_limits}",
          "❌" if rate_limits > 5 else ("⚠️" if rate_limits > 0 else "✅"))
    if network_errors > 5:
        issues += 1

    # 3. 从failed队列统计网络相关失败
    failed = r.lrange("analysis:failed", 0, -1)
    network_failed = 0
    for item in failed:
        data = json.loads(item)
        if data.get("reason", "") in INFRA_FAILURES or data.get("failure_type") == "infra":
            network_failed += 1

    network_rate = network_failed / len(failed) * 100 if failed else 0
    print(f"  failed队列中基础设施失败: {network_failed}/{len(failed)} ({network_rate:.1f}%)")
    if network_rate > 50:
        print(f"  ❌ 基础设施失败率>{network_rate:.0f}%，API不稳定")
        issues += 1
    elif network_rate > 20:
        print(f"  ⚠️ 基础设施失败率{network_rate:.0f}%，需关注")
    else:
        print(f"  ✅ 基础设施失败率低")

    return issues


def check_g_devin_exit_health(db, r):
    """G. devin异常退出率——dead_session占比、completed率、趋势"""
    print("【G. devin异常退出率】")
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    thirty_min_ago = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M")
    now_str = now.strftime("%Y-%m-%dT%H:%M")

    recent = list(db.aql.execute(
        f"FOR r IN {ANALYSIS_RUNS_COLLECTION} "
        f"FILTER r.ended_at != null "
        f"FILTER r.ended_at >= @start "
        f"FILTER r.ended_at <= @end "
        f"COLLECT status = r.status WITH COUNT INTO c "
        f"SORT c DESC RETURN {{status, count: c}}",
        bind_vars={"start": thirty_min_ago, "end": now_str}
    ))

    total = sum(s["count"] for s in recent)
    if total == 0:
        print(f"  最近30分钟无终态产出（launcher可能还在运行中）")
        return 0

    status_map = {s["status"]: s["count"] for s in recent}
    completed = status_map.get("completed", 0)
    dead = status_map.get("dead_session", 0)
    rate_limited = status_map.get("rate_limited", 0)
    failed_conn = status_map.get("failed_connection", 0)
    timeout = status_map.get("failed_timeout", 0)
    stall = status_map.get("failed_stall", 0)

    completed_rate = completed / total * 100
    dead_rate = dead / total * 100
    infra_rate = (dead + rate_limited + failed_conn) / total * 100

    print(f"  最近30分钟总产出: {total}题")
    print(f"  completed:        {completed} ({completed_rate:.1f}%)")
    print(f"  dead_session:     {dead} ({dead_rate:.1f}%)")
    print(f"  rate_limited:     {rate_limited} ({rate_limited/total*100:.1f}%)")
    print(f"  failed_connection: {failed_conn} ({failed_conn/total*100:.1f}%)")
    print(f"  failed_timeout:   {timeout} ({timeout/total*100:.1f}%)")
    print(f"  failed_stall:     {stall} ({stall/total*100:.1f}%)")

    issues = 0
    if infra_rate > 30:
        print(f"  ❌ 基础设施失败率{infra_rate:.0f}%>30%，API不稳定")
        issues += 1
    elif infra_rate > 10:
        print(f"  ⚠️ 基础设施失败率{infra_rate:.0f}%，需关注")
    else:
        print(f"  ✅ 基础设施失败率{infra_rate:.0f}%正常")

    if completed_rate < 30 and total > 10:
        print(f"  ❌ completed率{completed_rate:.0f}%<30%，系统产出质量低")
        issues += 1
    elif completed_rate < 50 and total > 10:
        print(f"  ⚠️ completed率{completed_rate:.0f}%，偏低")
    else:
        print(f"  ✅ completed率{completed_rate:.0f}%健康")

    return issues


def check_h_landing_completeness(db):
    """H. 落盘完整性——completed的run是否有tmux_pipe.log和AGENTS.md"""
    print("【H. 落盘完整性】")
    runs = list(db.aql.execute(
        f"FOR r IN {ANALYSIS_RUNS_COLLECTION} "
        f"FILTER r.status == 'completed' "
        f"LIMIT 100 RETURN r"
    ))

    if not runs:
        print("  无completed记录")
        return 0

    missing_pipe = 0
    missing_agents = 0
    missing_traj = 0
    for r in runs:
        exp_id = r.get("analysis_exp_id", "")
        traj_dir = TRAJ / exp_id
        if not traj_dir.exists():
            missing_traj += 1
            continue
        pipe_path = traj_dir / "tmux" / "tmux_pipe.log"
        if not pipe_path.exists() or pipe_path.stat().st_size < 100:
            missing_pipe += 1
        # 检查AGENTS.md
        paths = r.get("paths", {})
        agents_path = paths.get("agents_md_path", "")
        if agents_path and not Path(agents_path).exists():
            missing_agents += 1

    print(f"  检查{len(runs)}个completed记录:")
    print(f"  缺trajectory目录: {missing_traj}", "❌" if missing_traj else "✅")
    print(f"  缺tmux_pipe.log:  {missing_pipe}", "❌" if missing_pipe else "✅")
    print(f"  缺AGENTS.md:      {missing_agents}", "❌" if missing_agents else "✅")
    return missing_traj + missing_pipe + missing_agents


def check_i_batch_progress(db, r):
    """I. 批次进度健康——pending是否堆积、failed率是否过高"""
    print("【I. 批次进度健康】")
    stats = get_stats(r)
    pending = int(stats.get("pending", 0))
    running = int(stats.get("running", 0))
    completed = int(stats.get("completed", 0))
    failed = int(stats.get("failed", 0))

    total = completed + failed
    failed_rate = failed / total * 100 if total > 0 else 0

    print(f"  Redis队列: pending={pending} running={running} completed={completed} failed={failed}")
    print(f"  failed率: {failed_rate:.1f}%")

    issues = 0
    if pending > 1000:
        print(f"  ⚠️ pending堆积({pending})，launcher可能卡住或并发太低")
        issues += 1
    if failed_rate > 50 and total > 10:
        print(f"  ❌ failed率{failed_rate:.0f}%>50%，系统异常")
        issues += 1
    elif failed_rate > 30 and total > 10:
        print(f"  ⚠️ failed率{failed_rate:.0f}%，偏高")
    else:
        print(f"  ✅ failed率正常")

    # 检查各批次状态
    batches = list(db.aql.execute(
        f"FOR b IN {ANALYSIS_BATCHES_COLLECTION} "
        f"FILTER b.status == 'launching' "
        f"RETURN {{_key: b._key, concurrency: b.concurrency, completed: b.completed_count, failed: b.failed_count}}"
    ))
    for b in batches:
        print(f"  批次 {b['_key']}: concurrency={b.get('concurrency',0)} "
              f"completed={b.get('completed',0)} failed={b.get('failed',0)}")

    return issues


def check_j_log_health():
    """J. 日志健康——最近日志中是否有大量错误"""
    print("【J. 日志健康】")
    issues = 0
    for log_name in ["launcher.log", "result_collector.log", "data_collector.log"]:
        log_path = LOG_DIR / log_name
        if not log_path.exists():
            continue
        lines = log_path.read_text(errors="ignore").strip().split("\n")
        recent = lines[-100:]
        errors = sum(1 for l in recent if "ERROR" in l or "CRITICAL" in l)
        warnings = sum(1 for l in recent if "WARNING" in l)
        print(f"  {log_name}: 最近100行中 errors={errors} warnings={warnings}",
              "❌" if errors > 10 else ("⚠️" if errors > 0 else "✅"))
        if errors > 10:
            issues += 1
    return issues


def main():
    import argparse
    parser = argparse.ArgumentParser(description="运行时健康检查")
    parser.add_argument("--batch-id", help="指定批次")
    args = parser.parse_args()

    print("=" * 70)
    print("错题分析系统运行时健康检查")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    if not ping():
        print("❌ Redis连接失败，无法进行运行时检查")
        sys.exit(1)

    r = get_redis()
    db = connect_db()

    all_issues = []

    all_issues.append(("A", check_a_redis_atomicity(r)))
    print()
    all_issues.append(("B", check_b_db_redis_consistency(db, r)))
    print()
    all_issues.append(("C", check_c_duplicate_run(r)))
    print()
    all_issues.append(("D", check_d_concurrency_limit(db, r)))
    print()
    devin_count = check_e_devin_process_count()
    conc = r.hlen("analysis:running")
    if conc > 0:
        expected_devin = conc * 2
        zombie_devin = max(0, devin_count - expected_devin - 10)
        if zombie_devin > 0:
            print(f"  僵尸devin进程: ~{zombie_devin}个 ❌")
            all_issues.append(("E", zombie_devin))
        else:
            print(f"  僵尸devin进程: 0 ✅")
    else:
        print(f"  并发=0，跳过僵尸进程检查（当前{devin_count}个devin进程是其他session的）")
    print()
    all_issues.append(("F", check_f_network_health(r)))
    print()
    all_issues.append(("G", check_g_devin_exit_health(db, r)))
    print()
    all_issues.append(("H", check_h_landing_completeness(db)))
    print()
    all_issues.append(("I", check_i_batch_progress(db, r)))
    print()
    all_issues.append(("J", check_j_log_health()))

    # 总结
    print()
    print("=" * 70)
    real_issues = [(k, v) for k, v in all_issues if v and v != 0]
    if real_issues:
        print(f"判定: ⚠️ 有 {len(real_issues)} 个问题需要关注:")
        for k, v in real_issues:
            print(f"  - [{k}] {v}")
    else:
        print("判定: ✅ 全部通过")
    print("=" * 70)


if __name__ == "__main__":
    main()
