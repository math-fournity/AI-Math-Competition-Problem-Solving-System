#!/usr/bin/env python3
"""reporter.py — 错题分析系统定时报告

定时从DB和文件读取状态，输出进度报告和告警。
可以独立运行，也可以被launcher内嵌调用。

模仿solver_harness的reporter.py。

用法:
  python -m monitoring.reporter --interval 60
  python -m monitoring.reporter --once        # 只报告一次
  python -m monitoring.reporter --batch-id analysis-1 --interval 30
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from src.config import (
    OUTPUT_BASE, ANALYSIS_TRAJECTORY_BASE,
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    ANALYSIS_RUNS_COLLECTION, ANALYSIS_RESULTS_COLLECTION,
)
from monitoring.shared_logger import get_logger

logger = get_logger("reporter")


def connect_db():
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)


def collect_stats(batch_id=None):
    """收集当前统计"""
    stats = {
        "timestamp": datetime.now().isoformat(),
        "batches": {},
        "db": {},
        "tmux_sessions": 0,
    }

    # 文件系统统计
    if OUTPUT_BASE.exists():
        batches = [d.name for d in OUTPUT_BASE.iterdir() if d.is_dir()]
        if batch_id:
            batches = [b for b in batches if b == batch_id]
        for bid in batches:
            bdir = OUTPUT_BASE / bid
            bstats = {"prepared": 0, "launched": 0, "completed": 0, "failed": 0, "parsed": 0}

            prepared_path = bdir / "prepared.json"
            if prepared_path.exists():
                with open(str(prepared_path)) as f:
                    bstats["prepared"] = len(json.load(f).get("prepared", []))

            launch_path = bdir / "launch_results.json"
            if launch_path.exists():
                with open(str(launch_path)) as f:
                    data = json.load(f)
                bstats["completed"] = len(data.get("completed", []))
                bstats["failed"] = len(data.get("failed", []))
                bstats["launched"] = bstats["completed"] + bstats["failed"]

            collected_path = bdir / "collected_results.json"
            if collected_path.exists():
                with open(str(collected_path)) as f:
                    bstats["parsed"] = json.load(f).get("parsed", 0)

            stats["batches"][bid] = bstats

    # DB统计
    try:
        db = connect_db()
        aql = f"FOR r IN {ANALYSIS_RUNS_COLLECTION} COLLECT status = r.status WITH COUNT INTO c RETURN {{status, count: c}}"
        cursor = db.aql.execute(aql, ttl=60)
        stats["db"]["runs_by_status"] = {row["status"]: row["count"] for row in cursor}

        aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} COLLECT verdict = r.dimension1_verdict WITH COUNT INTO c RETURN {{verdict, count: c}}"
        cursor = db.aql.execute(aql, ttl=60)
        stats["db"]["results_by_verdict"] = {row["verdict"]: row["count"] for row in cursor}
    except Exception as e:
        stats["db"]["error"] = str(e)

    # tmux session计数
    import subprocess
    try:
        result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
        stats["tmux_sessions"] = sum(1 for l in result.stdout.split("\n") if l.startswith("an-"))
    except Exception:
        stats["tmux_sessions"] = 0

    return stats


def format_report(stats):
    """格式化报告"""
    lines = []
    lines.append(f"=== 错题分析系统报告 {stats['timestamp']} ===")
    lines.append(f"tmux sessions: {stats['tmux_sessions']}")
    lines.append("")

    for bid, bstats in sorted(stats["batches"].items()):
        progress = ""
        if bstats["prepared"] > 0:
            pct = bstats["launched"] * 100 // bstats["prepared"]
            progress = f" ({pct}% launched)"
        lines.append(f"批次 {bid}:{progress}")
        lines.append(f"  prepared={bstats['prepared']}, launched={bstats['launched']}, "
                      f"completed={bstats['completed']}, failed={bstats['failed']}, "
                      f"parsed={bstats['parsed']}")

    if stats["db"]:
        lines.append("")
        lines.append("DB:")
        if "runs_by_status" in stats["db"]:
            for s, c in sorted(stats["db"]["runs_by_status"].items(), key=lambda x: -x[1]):
                lines.append(f"  runs.{s}: {c}")
        if "results_by_verdict" in stats["db"]:
            lines.append("  results by verdict:")
            for v, c in sorted(stats["db"]["results_by_verdict"].items(), key=lambda x: -x[1]):
                lines.append(f"    {v}: {c}")
        if "error" in stats["db"]:
            lines.append(f"  ❌ DB错误: {stats['db']['error']}")

    # 告警
    lines.append("")
    alerts = []
    for bid, bstats in stats["batches"].items():
        if bstats["prepared"] > 0 and bstats["launched"] < bstats["prepared"]:
            alerts.append(f"{bid}: {bstats['prepared'] - bstats['launched']}题未启动")
        if bstats["failed"] > bstats["completed"] * 0.3 and bstats["completed"] > 10:
            alerts.append(f"{bid}: 失败率过高 ({bstats['failed']}/{bstats['completed'] + bstats['failed']})")
    if stats["tmux_sessions"] > 50:
        alerts.append(f"tmux session过多: {stats['tmux_sessions']}")

    if alerts:
        lines.append("告警:")
        for a in alerts:
            lines.append(f"  ⚠️ {a}")
    else:
        lines.append("无告警 ✅")

    return "\n".join(lines)


def report_once(batch_id=None):
    """报告一次"""
    stats = collect_stats(batch_id)
    report = format_report(stats)
    print(report)
    logger.info(f"报告生成: tmux={stats['tmux_sessions']}, batches={len(stats['batches'])}")


def report_loop(interval, batch_id=None):
    """循环报告"""
    logger.info(f"启动reporter, interval={interval}s")
    while True:
        try:
            report_once(batch_id)
        except Exception as e:
            logger.error(f"报告生成失败: {e}", exc_info=True)
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="错题分析系统定时报告")
    parser.add_argument("--interval", type=int, default=60, help="报告间隔秒数")
    parser.add_argument("--once", action="store_true", help="只报告一次")
    parser.add_argument("--batch-id", help="指定批次")
    args = parser.parse_args()

    if args.once:
        report_once(args.batch_id)
    else:
        report_loop(args.interval, args.batch_id)


if __name__ == "__main__":
    main()
