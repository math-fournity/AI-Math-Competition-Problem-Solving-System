"""report.py — SOP检查报表与系统快照生成

每次SOP步骤执行后，生成年月日时间戳目录，包含：
- report.md: 从模板文件复制过来的报表模板（AI填写）
- snapshot.json: 聚合统计（总数/完成数/完成率/按题源分组）
- snapshot_runs.json: 全量per-run数据（problem_id/status/final_status/current_round/...）
- check_output.txt: 脚本输出的原文

报表模板是文件形态的运行期资产，存放在 docs/sop/templates/report_step_{XX}.md。
每次执行SOP步骤时，脚本把对应模板复制到D盘报表目录，AI加载后逐项检查填写。

目录结构（D盘独立目录）：
  {REPORT_BASE}/cycle_{NNN}/step_{XX}/{YYYYMMDD_HHMMSS}/
    report.md           ← 从模板复制，AI填写
    snapshot.json       ← 脚本生成
    snapshot_runs.json  ← 脚本生成
    check_output.txt    ← 脚本输出原文
"""

import json
import os
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import SOP_NAMES
from scripts.sop.sop_log import get_logger

log = get_logger("report")

# 报表根目录——D盘独立目录，通过环境变量配置
_REPORT_BASE = os.environ.get("SOP_REPORT_BASE", "")
if _REPORT_BASE:
    REPORT_BASE = Path(_REPORT_BASE)
else:
    from src.continuation_config import D_TRAJ_DIR
    REPORT_BASE = D_TRAJ_DIR / "p27-sop-reports"

# 报表模板目录——项目运行期资产
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "docs" / "sop" / "templates"


def _get_template_path(step_num):
    """获取对应step的报表模板文件路径"""
    return TEMPLATES_DIR / f"report_step_{step_num}.md"


def generate_snapshot(batch_id, step_num, cycle, timestamp):
    """查询DB生成系统快照——聚合统计 + 全量per-run数据"""
    from src.continuation_db_schema import connect_db
    from src.continuation_config import (
        CONTINUATION_RUNS_COLLECTION,
        CONTINUATION_EVENTS_COLLECTION,
        CONTINUATION_RESULTS_COLLECTION,
        SESSIONS_COLLECTION,
    )

    db = connect_db()

    # === 全量per-run数据 ===
    aql_runs = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"RETURN {{"
        f"  problem_id: run.problem_id, "
        f"  status: run.status, "
        f"  final_status: run.final_status, "
        f"  rounds_count: LENGTH(run.rounds_log), "
        f"  current_round: run.rounds_log[LENGTH(run.rounds_log)-1].round, "
        f"  last_method: run.rounds_log[LENGTH(run.rounds_log)-1].method, "
        f"  last_completed: run.rounds_log[LENGTH(run.rounds_log)-1].completed, "
        f"  last_truncated: run.rounds_log[LENGTH(run.rounds_log)-1].truncated, "
        f"  updated_at: run.updated_at, "
        f"  work_dir: run.work_dir"
        f"}}"
    )
    cursor = db.aql.execute(aql_runs, bind_vars={"bid": batch_id}, ttl=120, batch_size=500)
    runs_data = list(cursor)

    # === 聚合统计 ===
    total = len(runs_data)
    status_counts = defaultdict(int)
    final_status_counts = defaultdict(int)
    source_stats = defaultdict(lambda: {"total": 0, "completed": 0})
    for r in runs_data:
        status_counts[r.get("status", "unknown")] += 1
        fs = r.get("final_status") or "None"
        final_status_counts[fs] += 1
        src = r["problem_id"].split("_")[0]
        source_stats[src]["total"] += 1
        if r.get("final_status") == "COMPLETED":
            source_stats[src]["completed"] += 1

    results_count = db.collection(CONTINUATION_RESULTS_COLLECTION).count()
    events_count = db.collection(CONTINUATION_EVENTS_COLLECTION).count()
    sessions_count = db.collection(SESSIONS_COLLECTION).count() - 1

    completed = final_status_counts.get("COMPLETED", 0)
    completion_rate = completed / total if total > 0 else 0

    by_source = {}
    for src in sorted(source_stats.keys()):
        s = source_stats[src]
        by_source[src] = {
            "total": s["total"],
            "completed": s["completed"],
            "rate": round(s["completed"] / s["total"], 4) if s["total"] > 0 else 0,
        }

    snapshot = {
        "batch_id": batch_id,
        "timestamp": timestamp,
        "cycle": cycle,
        "step": step_num,
        "step_name": SOP_NAMES.get(step_num, "?"),
        "aggregate": {
            "total_runs": total,
            "status_counts": dict(status_counts),
            "final_status_counts": dict(final_status_counts),
            "completed": completed,
            "completion_rate": round(completion_rate, 4),
            "results_collection_count": results_count,
            "events_total": events_count,
            "sessions_total": sessions_count,
        },
        "by_source": by_source,
    }
    return snapshot, runs_data


def generate_report(step_num, batch_id, cycle, check_output):
    """生成报表和快照的主函数

    在D盘创建目录结构，写入4个文件：
    - report.md: 从模板文件复制（AI填写）
    - check_output.txt: 脚本输出原文
    - snapshot.json: 聚合统计
    - snapshot_runs.json: 全量per-run数据
    """
    timestamp_dt = datetime.now(timezone.utc)
    timestamp = timestamp_dt.isoformat()
    timestamp_dir = timestamp_dt.strftime("%Y%m%d_%H%M%S")

    step_dir_name = f"step_{step_num}"
    report_dir = REPORT_BASE / f"cycle_{cycle:03d}" / step_dir_name / timestamp_dir
    report_dir.mkdir(parents=True, exist_ok=True)

    # 1. 保存脚本输出原文
    (report_dir / "check_output.txt").write_text(check_output, encoding="utf-8")

    # 2. 生成快照
    try:
        snapshot, runs_data = generate_snapshot(batch_id, step_num, cycle, timestamp)
        (report_dir / "snapshot.json").write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "snapshot_runs.json").write_text(
            json.dumps(runs_data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info(f"generate_report: snapshot written, {len(runs_data)} runs")
    except Exception as e:
        log.error(f"generate_report: snapshot failed: {e}", exc_info=True)

    # 3. 从模板文件复制report.md
    template_path = _get_template_path(step_num)
    report_path = report_dir / "report.md"
    if template_path.exists():
        shutil.copy2(template_path, report_path)
        log.info(f"generate_report: template copied from {template_path}")
    else:
        log.warning(f"generate_report: template not found at {template_path}, creating placeholder")
        report_path.write_text(
            f"# SOP检查报表 — step_{step_num}\n\n"
            f"⚠️ 模板文件不存在: {template_path}\n"
            f"请手动创建模板文件。\n", encoding="utf-8")

    print(f"\n--- 报表已生成 ---")
    print(f"  目录: {report_dir}")
    print(f"  文件: report.md（从模板复制，AI必须填写）, snapshot.json, snapshot_runs.json, check_output.txt")
    print(f"  ⚠️ 请用 read 工具加载 {report_path}")
    print(f"  ⚠️ 按模板中的检查方法逐项检查，填写检查项清单和发现/操作部分")
    print(f"  ⚠️ 填写后用 edit 工具写回同一文件")
    print()
    return report_dir


class Tee:
    """同时输出到多个流——用于捕获stdout的同时在终端显示"""
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            s.write(data)
    def flush(self):
        for s in self.streams:
            s.flush()
