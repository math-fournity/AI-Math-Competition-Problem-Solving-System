"""checks.py — SOP 各步骤的自动化检查逻辑

每个函数对应一个 SOP 步骤的"脚本能做的自动化部分"。
AI 判断部分不在这些函数中——那些在 SOP 文档指引下由 Master Agent 自己做。

函数命名：check_XX_YYY() 对应步骤 XX
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def check_01_system_health(batch_id):
    """步骤01：系统存活+进度+Session——运行 monitor_check_continuation.sh"""
    repo_root = Path(__file__).parent.parent.parent
    script = repo_root / "scripts" / "monitor_check_continuation.sh"

    if not script.exists():
        print(f"⚠️ 检查脚本不存在: {script}")
        return

    print("--- 自动化检查结果（monitor_check_continuation.sh）---")
    try:
        result = subprocess.run(
            ["bash", str(script), batch_id],
            capture_output=True, text=True, timeout=120,
            cwd=str(repo_root),
        )
        print(result.stdout)
        if result.stderr:
            print("--- stderr ---")
            print(result.stderr[:2000])
    except subprocess.TimeoutExpired:
        print("⚠️ 检查脚本超时（120秒），可能系统状态异常")
    except Exception as e:
        print(f"⚠️ 检查脚本执行失败: {e}")
    print()


def check_02_data_integrity(batch_id):
    """步骤02：数据完整性——抽查 run 的产出文件存在性 + rounds_log 字段完整性"""
    try:
        from src.continuation_db_schema import connect_db
        from src.continuation_config import CONTINUATION_RUNS_COLLECTION
        db = connect_db()

        # 抽查最近10个有 rounds_log 的 run
        aql = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER LENGTH(run.rounds_log) > 0 "
            f"SORT run.updated_at DESC "
            f"LIMIT 10 "
            f"RETURN {{_key: run._key, problem_id: run.problem_id, "
            f"status: run.status, final_status: run.final_status, "
            f"work_dir: run.work_dir, rounds_log: run.rounds_log}}"
        )
        cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
        runs = list(cursor)

        print(f"--- 数据完整性抽查（{len(runs)}个run）---")
        if not runs:
            print("（无有 rounds_log 的 run）")
            print()
            return

        issues = []
        for run in runs:
            pid = run.get("problem_id", "?")
            work_dir = run.get("work_dir", "")
            rounds_log = run.get("rounds_log", [])

            for i, entry in enumerate(rounds_log):
                round_num = entry.get("round", i + 1)

                # 检查 rounds_log 的7个路径字段
                path_fields = ["export", "handover_path", "map_path",
                               "prompt_path", "prev_export", "proof_path"]
                for field in path_fields:
                    val = entry.get(field)
                    if val and val != "":
                        if not Path(val).exists():
                            issues.append(f"  [{pid} R{round_num}] {field} 文件不存在: {val}")

                # 检查 export 文件是否可读（不是空文件或损坏JSON）
                export_path = entry.get("export", "")
                if export_path and Path(export_path).exists():
                    size = Path(export_path).stat().st_size
                    if size < 100:
                        issues.append(f"  [{pid} R{round_num}] export 文件过小: {size}字节")

        if issues:
            print(f"发现 {len(issues)} 个数据完整性问题：")
            for issue in issues[:20]:
                print(issue)
            if len(issues) > 20:
                print(f"  ... 还有 {len(issues) - 20} 个问题")
        else:
            print("抽查的10个run的数据完整性正常")
        print()

    except Exception as e:
        print(f"⚠️ 数据完整性检查失败: {e}")
        print()


def check_03_alert_triage(batch_id):
    """步骤03：alert分类——查询未处理 alert"""
    try:
        from src.continuation_db_schema import connect_db
        db = connect_db()
        aql = (
            "FOR a IN p27_monitor_alerts "
            "FILTER a.status != 'resolved' "
            "SORT a.created_at DESC "
            "LIMIT 50 "
            "RETURN a"
        )
        cursor = db.aql.execute(aql, ttl=60)
        alerts = list(cursor)

        print(f"--- 未处理 alert（{len(alerts)}个）---")
        if not alerts:
            print("（无未处理 alert）")
            print()
            return

        for a in alerts:
            severity = a.get("severity", "unknown")
            alert_type = a.get("alert_type", "unknown")
            details = a.get("details", {})
            summary = details.get("summary", "") if isinstance(details, dict) else str(details)
            print(f"  [{severity}] {alert_type} (key={a.get('_key', '?')})")
            if summary:
                print(f"    摘要: {summary}")
        print()
    except Exception as e:
        print(f"⚠️ alert查询失败: {e}")
        print()


def check_04_ai_judgment(batch_id):
    """步骤04：C类AI判断——查询 needs_ai_review 的 run"""
    try:
        from src.continuation_db_schema import connect_db
        from src.continuation_config import CONTINUATION_RUNS_COLLECTION
        db = connect_db()
        aql = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.needs_ai_review == true "
            f"FILTER run.ai_review_done != true "
            f"LIMIT 10 "
            f"RETURN {{_key: run._key, problem_id: run.problem_id, "
            f"rounds_log: run.rounds_log, work_dir: run.work_dir}}"
        )
        cursor = db.aql.execute(aql, ttl=60)
        candidates = list(cursor)

        print(f"--- 待 AI 判断的条目（{len(candidates)}个）---")
        if not candidates:
            print("（无待 AI 判断的条目）")
            print()
            return

        for c in candidates:
            pid = c.get("problem_id", "?")
            work_dir = c.get("work_dir", "")
            rounds_log = c.get("rounds_log", [])
            print(f"  [{pid}] work_dir={work_dir}")
            if rounds_log:
                last = rounds_log[-1] if isinstance(rounds_log, list) else {}
                for field in ["proof_path", "handover_path", "export"]:
                    val = last.get(field, "（无）")
                    print(f"    {field}: {val}")
            print()
    except Exception as e:
        print(f"⚠️ AI review 候选查询失败: {e}")
        print()


def check_05_code_repair(batch_id):
    """步骤05：代码修复——显示最近 git log"""
    repo_root = Path(__file__).parent.parent.parent
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True, text=True, timeout=10,
            cwd=str(repo_root),
        )
        print("--- 最近 5 个 commit ---")
        print(result.stdout)
    except Exception as e:
        print(f"⚠️ git log 失败: {e}")
    print()


def check_06_report_worklog_selfcheck(batch_id):
    """步骤06：报告+WORKLOG+Self-check——显示 WORKLOG 状态"""
    repo_root = Path(__file__).parent.parent.parent
    worklog = repo_root / "WORKLOG.md"
    print("--- WORKLOG.md 状态 ---")
    print(f"路径: {worklog}")
    if worklog.exists():
        size = worklog.stat().st_size
        print(f"大小: {size} 字节（已存在，续写）")
    else:
        print("（不存在，需创建）")
    print()


def check_Z_meta_system_review(batch_id):
    """步骤Z：元检查+整体检查——显示 SOP 系统全貌"""
    from scripts.sop.sop_state import load_state, SOP_STEPS, SOP_NAMES
    state = load_state()
    cycle = state.get("cycle", 0)
    print("--- SOP 系统全貌 ---")
    print(f"循环轮次: 第{cycle + 1}轮（即将完成）")
    print(f"步骤总数: {len(SOP_STEPS)}")
    print()
    print("当前循环结构：")
    for step in SOP_STEPS:
        name = SOP_NAMES[step]
        print(f"  {step:4s} {name}")
    print()
    print("SOP 文档目录：docs/sop/")
    print("SOP 脚本目录：scripts/sop/")
    print("状态文件：scripts/sop/_state.json")
    print()
