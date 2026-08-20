"""report.py — SOP检查报表与系统快照生成

每次SOP步骤执行后，生成年月日时间戳目录，包含：
- snapshot.json: 聚合统计（总数/完成数/完成率/按题源分组/问题计数）
- snapshot_runs.json: 全量per-run数据（problem_id/status/final_status/current_round/...）
- check_output.txt: 脚本输出的原文
- report.md: AI填写的报表模板（checklist打勾+发现+操作）

目录结构（D盘独立目录）：
  {REPORT_BASE}/cycle_{NNN}/step_{XX}/{YYYYMMDD_HHMMSS}/
    report.md
    snapshot.json
    snapshot_runs.json
    check_output.txt
"""

import io
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.sop.sop_state import SOP_NAMES
from scripts.sop.sop_log import get_logger

log = get_logger("report")

# 报表根目录——D盘独立目录，通过环境变量配置
import os
_REPORT_BASE = os.environ.get("SOP_REPORT_BASE", "")
if _REPORT_BASE:
    REPORT_BASE = Path(_REPORT_BASE)
else:
    from src.continuation_config import D_TRAJ_DIR
    REPORT_BASE = D_TRAJ_DIR / "p27-sop-reports"


# === 各步骤的检查项清单（报表模板用）===

# 每个检查项：(编号, 检查项名称, 类型[自动化/AI判断], 通过标准)
STEP_CHECKLIST = {
    "01": [
        ("1", "Monitor Pipe pane输出", "自动化", "最近3轮监控输出正常"),
        ("2", "alerts集合", "自动化", "无未处理critical alert"),
        ("3", "进程状态", "自动化", "launcher/monitor/watchdog 3个进程存活"),
        ("4", "进度", "自动化", "pending在减少/completed在增加"),
        ("5", "续传质量汇总", "自动化", "proof统计正常"),
        ("6", "通过率判定", "自动化", "通过率达标"),
        ("7", "系统健康", "自动化", "DB/Redis/Disk正常"),
        ("8", "运行时健康检查10维度", "自动化", "A-J 10维度无⚠️"),
        ("SESS", "Session注册表深度检查", "AI判断", "SESS-01~12逐项通过"),
        ("ENV", "环境检查", "AI判断", "ENV-01~07逐项通过"),
    ],
    "02": [
        ("F1", "rounds_log 6个路径字段文件存在性", "自动化", "所有必需字段文件存在"),
        ("F2", "文件大小检查", "自动化", "无<100字节文件"),
        ("F3", "export JSON格式", "自动化", "所有export是有效JSON"),
        ("F4", "proof.md内容质量", "自动化", "proof.md不<50字符"),
        ("F5", "HANDOVER.md内容质量", "自动化", "HANDOVER.md不<200字符"),
        ("F6", "prompt内容质量", "自动化", "prompt不<100字符"),
        ("Q1", "proof.md质量统计(RUN-05)", "自动化", "存在率和boxed率正常"),
        ("Q2", "results集合检查", "自动化", "results数>=COMPLETED数"),
        ("Q3", "events完整性检查", "自动化", "无有launched无completed/failed"),
        ("Q4", "prepared堆积检查", "自动化", "prepared数和pending数比例正常"),
        ("Q5", "按题源完成率统计", "自动化", "无题源完成率全0%"),
        ("Q6", "标准文件检查", "自动化", "problem.txt/proof.md/round1 export存在"),
        ("Q7", "round编号连续性", "自动化", "round编号连续"),
        ("2a", "DB记录vs文件一致性", "AI判断", "COMPLETED的proof_path存在/running的tmux在跑"),
        ("2b", "Redis队列vs DB status", "AI判断", "prepared数和pending数接近"),
        ("2c", "Session注册表完整性", "AI判断", "running session的export_path父目录存在"),
        ("2d", "事件流完整性确认", "AI判断", "有launched无end的run确认是running"),
        ("2e", "跨题目模式分析", "AI判断", "0%题源原因诊断+失败模式分布"),
    ],
    "03": [
        ("A", "未处理alert列表", "自动化", "查询最多50条未处理alert"),
        ("T1", "alert分类(A/B/C类)", "AI判断", "逐个分类并记录"),
        ("T2", "需要立即处理的alert", "AI判断", "critical alert已处理"),
        ("T3", "alert标记resolved", "AI判断", "已处理alert标记为fixed"),
    ],
    "04": [
        ("C0", "待AI判断条目列表", "自动化", "查询needs_ai_review=True的run"),
        ("C1", "proof数学正确性", "AI判断", "答案正确且证明逻辑完整"),
        ("C2", "proof幻觉检查", "AI判断", "无编造定理/引用/计算"),
        ("C3", "答案泄漏检查", "AI判断", "答案通过推导得到"),
        ("C4", "HANDOVER质量", "AI判断", "准确总结上一轮/无遗漏/无编造"),
        ("C5", "续传方向", "AI判断", "在上一轮基础上继续"),
        ("C6", "export语义检查", "AI判断", "thinking真的在解这道题"),
    ],
    "05": [
        ("R0", "最近git提交", "自动化", "最近5条commit"),
        ("R1", "汇总需要修复的问题", "AI判断", "从步骤01-04汇总问题"),
        ("R2", "逐个修复", "AI判断", "读代码→定位根因→修复→验证"),
        ("R3", "修复后确认", "AI判断", "py_compile通过+不会立即复发"),
    ],
    "06": [
        ("W1", "WORKLOG.md状态", "自动化", "WORKLOG存在且在续写"),
        ("S1", "export完整性", "AI判断", "自己conversation.json存在且>1KB"),
        ("S2", "DONE.md写入", "AI判断", "退出前确认echo命令正确"),
        ("S3", "REPORT完整性", "AI判断", "包含检查/判断/修复/未修复四部分"),
        ("S4", "session注册", "AI判断", "自己session在p27_sessions中"),
        ("S5", "py_compile通过", "AI判断", "修复代码后无语法错误"),
        ("S6", "git commit成功", "AI判断", "修复后commit成功"),
        ("S7", "未修改第二级规范", "AI判断", "git diff不包含架构级规范"),
        ("S8", "git add规范", "AI判断", "只add具体路径"),
        ("S9", "只修本轮发现的问题", "AI判断", "无重构/改架构/顺便修"),
        ("S10", "未spawn subagent", "AI判断", "无run_subagent调用"),
        ("S11", "未push代码", "AI判断", "无git push"),
        ("S12", "C类判断有依据", "AI判断", "每个判断有读了文件的记录"),
        ("S13", "未陷入重复修复", "AI判断", "同一问题无连续3轮修"),
        ("S14", "同一alert未反复出现", "AI判断", "同一alert_type无最近5轮反复"),
        ("S15", "第一级文档同步", "AI判断", "改了代码就改了对应文档"),
        ("S16", "第二级规范建议记录", "AI判断", "涉及第二级规范有记录"),
        ("S17", "同步清单完整性", "AI判断", "该改的都改了"),
    ],
    "Z": [
        ("M1", "步骤01元检查", "AI判断", "8项输出是否够用"),
        ("M2", "步骤02元检查", "AI判断", "全量检查是否有效/7字段是否完整"),
        ("M3", "步骤03元检查", "AI判断", "alert类型清单是否需要更新"),
        ("M4", "步骤04元检查", "AI判断", "C1-C6检查项是否全面"),
        ("M5", "步骤05元检查", "AI判断", "修复约束是否合理"),
        ("M6", "步骤06元检查", "AI判断", "S1-S17是否有效"),
        ("Z1", "6步划分是否合理", "AI判断", "无太重或太轻的步骤"),
        ("Z2", "步骤顺序是否需要调整", "AI判断", "顺序合理"),
        ("Z3", "_state.json机制是否可靠", "AI判断", "状态文件无不一致"),
        ("Z4", "SOP与目标系统适配度", "AI判断", "循环节奏匹配"),
        ("Z5", "AGENTS.md SOP说明是否准确", "AI判断", "说明准确"),
        ("Z6", "checklist需求覆盖度", "AI判断", "14门类都有对应检查"),
        ("Z7", "方向性判断", "AI判断", "策略有效性+系统产出价值+系统性问题诊断"),
    ],
}


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

    # results集合
    results_count = db.collection(CONTINUATION_RESULTS_COLLECTION).count()
    # events总数
    events_count = db.collection(CONTINUATION_EVENTS_COLLECTION).count()
    # sessions总数（排除counter文档）
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


def generate_report_template(step_num, batch_id, cycle, timestamp, snapshot):
    """生成report.md报表模板"""
    step_name = SOP_NAMES.get(step_num, "?")
    checklist = STEP_CHECKLIST.get(step_num, [])

    lines = []
    lines.append(f"# SOP检查报表 — cycle_{cycle:03d} / step_{step_num}")
    lines.append("")
    lines.append(f"> **检查时间**: {timestamp}")
    lines.append(f"> **batch_id**: {batch_id}")
    lines.append(f"> **步骤**: {step_num} — {step_name}")
    lines.append(f"> **快照文件**: snapshot.json, snapshot_runs.json")
    lines.append(f"> **脚本输出**: check_output.txt")
    lines.append("")

    # 系统快照摘要（从snapshot.json自动填充）
    if snapshot:
        agg = snapshot.get("aggregate", {})
        lines.append("## 系统快照摘要")
        lines.append("")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|---|---|")
        lines.append(f"| 总run数 | {agg.get('total_runs', '?')} |")
        lines.append(f"| COMPLETED | {agg.get('completed', '?')} |")
        lines.append(f"| 完成率 | {agg.get('completion_rate', '?')} |")
        lines.append(f"| results集合 | {agg.get('results_collection_count', '?')} |")
        lines.append(f"| events总数 | {agg.get('events_total', '?')} |")
        lines.append(f"| sessions总数 | {agg.get('sessions_total', '?')} |")
        lines.append("")
        # 按题源完成率
        by_src = snapshot.get("by_source", {})
        if by_src:
            lines.append("### 按题源完成率")
            lines.append("")
            lines.append("| 题源 | 总数 | 完成 | 完成率 |")
            lines.append("|---|---|---|---|")
            for src, s in sorted(by_src.items()):
                rate = f"{s['rate']:.1%}"
                lines.append(f"| {src} | {s['total']} | {s['completed']} | {rate} |")
            lines.append("")

    # 检查项清单
    lines.append("## 检查项清单")
    lines.append("")
    lines.append("填写说明：`[x]` 通过 · `[!]` 有问题 · `[ ]` 待检查 · `[-]` 不适用")
    lines.append("")
    lines.append("| 编号 | 检查项 | 类型 | 结果 | 详情 |")
    lines.append("|---|---|---|---|---|")
    for num, name, check_type, criteria in checklist:
        lines.append(f"| {num} | {name} | {check_type} | [ ] | （填写发现） |")
    lines.append("")

    # 发现的问题
    lines.append("## 发现的问题")
    lines.append("")
    lines.append("### Critical")
    lines.append("（填写critical级别的问题，或写「无」）")
    lines.append("")
    lines.append("### Warning")
    lines.append("（填写warning级别的问题，或写「无」）")
    lines.append("")
    lines.append("### Info")
    lines.append("（填写info级别的问题，或写「无」）")
    lines.append("")

    # 执行的操作
    lines.append("## 执行的操作")
    lines.append("")
    lines.append("（填写本轮做了什么修复/重启/重跑等操作，或写「无操作」）")
    lines.append("")

    # 未修复的问题及原因
    lines.append("## 未修复的问题及原因")
    lines.append("")
    lines.append("（填写哪些问题没修，为什么，或写「无」）")
    lines.append("")

    # 下一轮建议
    lines.append("## 下一轮建议")
    lines.append("")
    lines.append("（填写下一轮需要关注什么，或写「无」）")
    lines.append("")

    return "\n".join(lines)


def generate_report(step_num, batch_id, cycle, check_output):
    """生成报表和快照的主函数

    在D盘创建目录结构，写入4个文件：
    - check_output.txt: 脚本输出原文
    - snapshot.json: 聚合统计
    - snapshot_runs.json: 全量per-run数据
    - report.md: AI填写的报表模板
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
    snapshot = None
    runs_data = None
    try:
        snapshot, runs_data = generate_snapshot(batch_id, step_num, cycle, timestamp)
        (report_dir / "snapshot.json").write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "snapshot_runs.json").write_text(
            json.dumps(runs_data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info(f"generate_report: snapshot written, {len(runs_data)} runs")
    except Exception as e:
        log.error(f"generate_report: snapshot failed: {e}", exc_info=True)

    # 3. 生成报表模板
    report_md = generate_report_template(step_num, batch_id, cycle, timestamp, snapshot)
    report_path = report_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")

    print(f"\n--- 报表已生成 ---")
    print(f"  目录: {report_dir}")
    print(f"  文件: report.md（AI必须填写）, snapshot.json, snapshot_runs.json, check_output.txt")
    print(f"  ⚠️ 请用 read 工具加载 {report_path}，填写检查项清单和发现/操作部分")
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
