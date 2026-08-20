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
from scripts.sop.sop_log import get_logger

log = get_logger("checks")


def check_01_system_health(batch_id):
    """步骤01：系统存活+进度+Session——运行 monitor_check_continuation.sh"""
    log.info(f"check_01_system_health: start batch={batch_id}")
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
    """步骤02：数据完整性——全量检查所有 run 的每轮输入/输出文件"""
    log.info(f"check_02_data_integrity: start batch={batch_id}")
    try:
        from src.continuation_db_schema import connect_db
        from src.continuation_config import CONTINUATION_RUNS_COLLECTION
        db = connect_db()

        # 全量检查所有有 rounds_log 的 run（最多200个）
        aql = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER LENGTH(run.rounds_log) > 0 "
            f"SORT run.updated_at DESC "
            f"LIMIT 200 "
            f"RETURN {{_key: run._key, problem_id: run.problem_id, "
            f"status: run.status, final_status: run.final_status, "
            f"work_dir: run.work_dir, rounds_log: run.rounds_log}}"
        )
        cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=120)
        runs = list(cursor)

        print(f"--- 数据完整性检查（{len(runs)}个run，最多200个）---")
        if not runs:
            print("（无有 rounds_log 的 run）")
            print()
            return

        issues = []
        checked_files = 0
        for run in runs:
            pid = run.get("problem_id", "?")
            rounds_log = run.get("rounds_log", [])

            for i, entry in enumerate(rounds_log):
                round_num = entry.get("round", i + 1)

                # 每轮的输入/输出文件
                file_checks = [
                    ("export", "输出", True),
                    ("prompt_path", "输入", True),
                    ("proof_path", "输出", False),
                    ("handover_path", "输入", False),
                    ("map_path", "输入", False),
                    ("prev_export", "输入", False),
                ]

                for field, io_type, required in file_checks:
                    val = entry.get(field)
                    if not val or val == "":
                        if required:
                            issues.append(f"  [{pid} R{round_num}] {io_type}字段 {field} 为空")
                        continue

                    path = Path(val)
                    checked_files += 1

                    if not path.exists():
                        issues.append(f"  [{pid} R{round_num}] {io_type} {field} 文件不存在: {val}")
                        continue

                    size = path.stat().st_size
                    if size < 100:
                        issues.append(f"  [{pid} R{round_num}] {io_type} {field} 文件过小: {size}字节")
                        continue

                    # export 是有效JSON
                    if field == "export":
                        try:
                            with open(path, encoding="utf-8", errors="ignore") as f:
                                head = f.read(4096)
                            if not head.strip().startswith(("{", "[")):
                                issues.append(f"  [{pid} R{round_num}] 输出 export 不是JSON格式")
                        except Exception:
                            issues.append(f"  [{pid} R{round_num}] 输出 export 读取失败")

                    # proof.md 有内容
                    if field == "proof_path":
                        try:
                            c = path.read_text(encoding="utf-8", errors="ignore")
                            if len(c.strip()) < 50:
                                issues.append(f"  [{pid} R{round_num}] 输出 proof.md 内容过短: {len(c)}字符")
                        except Exception:
                            pass

                    # HANDOVER.md 有内容
                    if field == "handover_path":
                        try:
                            c = path.read_text(encoding="utf-8", errors="ignore")
                            if len(c.strip()) < 200:
                                issues.append(f"  [{pid} R{round_num}] 输入 HANDOVER.md 内容过短: {len(c)}字符")
                        except Exception:
                            pass

                    # prompt 有内容
                    if field == "prompt_path":
                        try:
                            c = path.read_text(encoding="utf-8", errors="ignore")
                            if len(c.strip()) < 100:
                                issues.append(f"  [{pid} R{round_num}] 输入 prompt 内容过短: {len(c)}字符")
                        except Exception:
                            pass

        print(f"  检查了 {len(runs)} 个 run 的 {checked_files} 个文件")
        if issues:
            print(f"  发现 {len(issues)} 个问题：")
            for issue in issues[:30]:
                print(issue)
            if len(issues) > 30:
                print(f"  ... 还有 {len(issues) - 30} 个问题")
        else:
            print(f"  所有检查的文件完整性正常")
        print()

        # === proof.md 质量统计（RUN-05 需求点）===
        # 全量统计：COMPLETED 数 / proof.md 存在数 / 有 boxed 数
        aql_all = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"RETURN {{final_status: run.final_status, work_dir: run.work_dir, "
            f"proof_path: (run.rounds_log[LENGTH(run.rounds_log)-1].proof_path)}}"
        )
        cursor_all = db.aql.execute(aql_all, bind_vars={"bid": batch_id}, ttl=120)
        all_runs = list(cursor_all)

        total = len(all_runs)
        completed = sum(1 for r in all_runs if r.get("final_status") == "COMPLETED")
        proof_exists = 0
        proof_has_boxed = 0
        for r in all_runs:
            proof_path = r.get("proof_path", "")
            if not proof_path:
                # proof_path 不在 rounds_log 最后一条，尝试 work_dir/proof.md
                work_dir = r.get("work_dir", "")
                if work_dir:
                    proof_path = str(Path(work_dir) / "proof.md")
            if proof_path and Path(proof_path).exists():
                proof_exists += 1
                try:
                    content = Path(proof_path).read_text(encoding="utf-8", errors="ignore")
                    if "\\boxed" in content:
                        proof_has_boxed += 1
                except Exception:
                    pass

        print(f"\n--- proof.md 质量统计（RUN-05）---")
        print(f"  总 run 数: {total}")
        print(f"  COMPLETED: {completed} ({completed}/{total} = {completed/total:.1%})" if total else "  COMPLETED: 0")
        print(f"  proof.md 存在: {proof_exists}")
        print(f"  proof.md 有 boxed: {proof_has_boxed}")
        if completed > 0:
            print(f"  存在率（proof_exists/COMPLETED）: {proof_exists}/{completed} = {proof_exists/completed:.1%}")
        if proof_exists > 0:
            print(f"  boxed 率（has_boxed/proof_exists）: {proof_has_boxed}/{proof_exists} = {proof_has_boxed/proof_exists:.1%}")
        if completed > 0 and proof_exists < completed:
            print(f"  ⚠️ {completed - proof_exists} 个 COMPLETED 的 run 缺少 proof.md（数据丢失风险）")
        if proof_exists > 0 and proof_has_boxed < proof_exists:
            print(f"  ⚠️ {proof_exists - proof_has_boxed} 个 proof.md 没有 boxed 答案（未完成的证明）")
        print()

    except Exception as e:
        print(f"⚠️ 数据完整性检查失败: {e}")
        print()


def check_03_alert_triage(batch_id):
    """步骤03：alert分类——查询未处理 alert"""
    log.info(f"check_03_alert_triage: start batch={batch_id}")
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
    log.info(f"check_04_ai_judgment: start batch={batch_id}")
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
    log.info(f"check_05_code_repair: start batch={batch_id}")
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
    log.info(f"check_06_report_worklog_selfcheck: start batch={batch_id}")
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
    log.info(f"check_Z_meta_system_review: start batch={batch_id}")
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
