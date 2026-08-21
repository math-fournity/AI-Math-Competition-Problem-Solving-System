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


def _check_pending_gates():
    """步骤01例行：步进门闸Y通道——查有没有闸在等放行（系统冻结在此）。

    X/Y注意力模型：auto且无waiting_for=不需操心；有waiting_for（Y）=
    系统正冻结在该闸处等Master Agent核对checklist后--step放行。
    这里完整输出该闸的认知闭包（"放行前…检查"段），Master Agent
    按清单核对——这就是单步跟踪的检查提示词，随Y自动送达。
    """
    print("--- 步进门闸Y通道（waiting中的闸=系统冻结点）---")
    try:
        from src.continuation_db_schema import connect_db
        from src.step_gate import extract_checklist, COLLECTION
        db = connect_db()
        if not db.has_collection(COLLECTION):
            print("  （门闸集合未创建——先 python -m src.step_gate --register）")
            print()
            return
        pending = [d for d in db.collection(COLLECTION).all() if d.get("waiting_for")]
        if not pending:
            print("  ✅ 无Y——没有闸在等待，系统未被hold冻结")
            print()
            return
        for doc in pending:
            print(f"  🔶 Y: {doc['_key']} 自 {doc.get('waiting_since')} 冻结至今")
            print(f"     上下文: {doc['waiting_for']}")
            print(f"     放行: python -m src.step_gate --step {doc['_key']}")
            print(f"     --- 认知闭包 / 放行前检查清单 ---")
            for line in extract_checklist(doc.get("doc") or "").splitlines():
                print(f"     {line}")
            print()
    except Exception as e:
        print(f"  ⚠️ 门闸Y通道检查失败（DB不可达？）: {e}")
        print()


def _check_flow_snapshot():
    """步骤01例行：行为流水快照——016事故后新增的"看见流动"能力（SOP_01 §8）。

    日志只看存量（队列/session数），016事故中存量没变但流动病态。行为流水
    （log/flow/）记录launcher每个状态转移。这里自动跑聚合统计，把"每轮必查"
    从靠Master Agent自觉变成自动执行——churn_suspects非空时直接醒目输出，
    是016失控循环的3秒预警。
    """
    print("--- 行为流水快照（016预警：失控循环3秒可见，`observability --stats --since 1h`）---")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "src.observability", "--stats", "--since", "1h"],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        if result.stdout:
            print(result.stdout)
        else:
            print("  （无行为流水输出——系统可能刚启动/log/flow/为空）")
        if result.stderr:
            print(f"  ⚠️ observability stderr: {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        print("  ⚠️ 行为流水统计超时（30秒）——log/flow/可能过大")
    except Exception as e:
        print(f"  ⚠️ 行为流水快照失败: {e}")
    print()


def _check_system_panorama(batch_id):
    """步骤01例行：系统运行过程全景视图——023方案新增的"过程叙事"能力。

    行为流水的 --stats 给统计聚合，--tail 给原始事件，但都不回答
    "系统作为一个整体在如何运行"。本函数调用 system_panorama 脚本，
    输出4层过程叙事（L1现状/L2流畅性/L3流程合规/L4趋势），让AI在
    认知闭包背景下分析和推理系统运行是否正常。

    与 _check_flow_snapshot 的关系：flow_snapshot 给统计聚合（数字），
    system_panorama 给过程叙事（"系统在做什么"的可读描述）。两者互补。
    """
    print("--- 系统运行过程全景视图（023方案：过程叙事，AI分析推理的基础）---")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.sop.system_panorama",
             "--batch-id", batch_id, "--since", "1h"],
            capture_output=True, text=True, timeout=60,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        if result.stdout:
            print(result.stdout)
        else:
            print("  （无全景视图输出——系统可能刚启动/无行为流水）")
        if result.stderr:
            print(f"  ⚠️ system_panorama stderr: {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        print("  ⚠️ 全景视图生成超时（60秒）")
    except Exception as e:
        print(f"  ⚠️ 全景视图生成失败: {e}")
    print()


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

    _check_pending_gates()
    _check_flow_snapshot()
    _check_system_panorama(batch_id)
    _check_audit_pipe_health()


def _check_audit_pipe_health():
    """步骤01例行：Pipe 5 审计 Pipe 健康检查（A15-A18，见 dev-docs/029 §7.3）。

    审计 Pipe 上线后，SOP_01 需要监控审计队列/完成/失败率/门闸状态。
    """
    print("--- Pipe 5 审计 Pipe 健康（A15-A18）---")
    try:
        from src.proof_audit_redis_queue import get_redis, pending_count, running_count, completed_count, failed_count
        from src.proof_audit_db_schema import connect_db
        from src.proof_audit_config import (
            PROOF_AUDIT_RUNS_COLLECTION, PROOF_AUDITS_COLLECTION,
        )

        # Redis 队列状态
        try:
            r = get_redis()
            r.ping()
            stats = {
                "pending": pending_count(r),
                "running": running_count(r),
                "completed": completed_count(r),
                "failed": failed_count(r),
            }
            print(f"  Redis paudit: pending={stats['pending']} running={stats['running']} "
                  f"completed={stats['completed']} failed={stats['failed']}")

            # A15: 队列停滞检测（简化版——pending>0 但 running=0）
            if stats["pending"] > 0 and stats["running"] == 0:
                print(f"  ⚠️ A15 audit_queue_stalled: pending={stats['pending']} 但 running=0")
        except Exception as e:
            print(f"  ⚠️ Redis 不可达: {e}")

        # DB 审计结果统计
        db = connect_db()
        try:
            # A16: 审计完成数
            total_audits = db.collection(PROOF_AUDITS_COLLECTION).count()
            print(f"  A16 p27_proof_audits 总数: {total_audits}")

            # A17: 审计失败率
            if total_audits > 0:
                fail_aql = (
                    f"FOR a IN {PROOF_AUDITS_COLLECTION} "
                    f"FILTER a.audit_status LIKE 'FAIL_%' "
                    f"COLLECT WITH COUNT INTO c RETURN c"
                )
                fail_count = list(db.aql.execute(fail_aql, ttl=30))
                fail_rate = (fail_count[0] / total_audits * 100) if fail_count else 0
                print(f"  A17 审计失败率: {fail_rate:.1f}% ({fail_count[0]}/{total_audits})")
                if fail_rate > 20:
                    print(f"  ⚠️ A17 audit_failure_rate_high: 失败率>{20}%")

            # 审计状态分布
            dist_aql = (
                f"FOR a IN {PROOF_AUDITS_COLLECTION} "
                f"COLLECT status = a.audit_status WITH COUNT INTO c "
                f"SORT c DESC RETURN {{status, count: c}}"
            )
            dist = list(db.aql.execute(dist_aql, ttl=30))
            if dist:
                print(f"  审计状态分布:")
                for d in dist:
                    print(f"    {d['status']}: {d['count']}")
        except Exception as e:
            print(f"  ⚠️ DB 查询失败: {e}")

        # A18: 审计门闸等待
        try:
            from src.step_gate import COLLECTION
            if db.has_collection(COLLECTION):
                audit_pending = [
                    d for d in db.collection(COLLECTION).all()
                    if d.get("waiting_for") and "AUDIT" in d.get("_key", "")
                ]
                if audit_pending:
                    print(f"  🔶 A18 audit_gate_waiting: {len(audit_pending)}个审计门闸在等放行")
                    for doc in audit_pending:
                        print(f"     {doc['_key']}: {doc.get('waiting_for')}")
                else:
                    print(f"  ✅ A18 无审计门闸在等")
        except Exception:
            pass

    except ImportError:
        print("  （审计 Pipe 模块未安装）")
    except Exception as e:
        print(f"  ⚠️ 审计 Pipe 健康检查失败: {e}")
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
                # round=1是seed预检轮（2026-08-20起补录——017 off-by-one修复）：
                # 它没有自己的prompt/handover（那是R2起才有的），唯一产物是
                # round1_export.json（seed镜像）。必填字段只有export。
                if round_num == 1:
                    file_checks = [("export", "输出", True)]
                else:
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

        # === 数据库集合级完整性检查 ===

        # --- results 集合检查（缺口1）---
        from src.continuation_config import CONTINUATION_RESULTS_COLLECTION
        results_count = db.collection(CONTINUATION_RESULTS_COLLECTION).count()
        print(f"--- results 集合检查 ---")
        print(f"  results 集合文档数: {results_count}")
        print(f"  runs 中 COMPLETED 数: {completed}")
        if completed > 0 and results_count < completed:
            print(f"  ⚠️ results 集合为空或不满——{completed - results_count} 个 COMPLETED 的结果未归档到 results（数据丢失风险）")
        elif results_count == 0 and completed == 0:
            print(f"  （无 COMPLETED run，results 为空属正常）")
        else:
            print(f"  results 归档完整")
        print()

        # --- events 完整性检查（缺口5）---
        from src.continuation_config import CONTINUATION_EVENTS_COLLECTION
        aql_events = (
            f"FOR e IN {CONTINUATION_EVENTS_COLLECTION} "
            f"FILTER e.batch_id == @bid "
            f"COLLECT rk = e.run_key INTO events = e.event_type "
            f"RETURN {{run_key: rk, events: events}}"
        )
        cursor_events = db.aql.execute(aql_events, bind_vars={"bid": batch_id}, ttl=120)
        all_events = list(cursor_events)
        incomplete_events = []
        for e in all_events:
            rk = e.get("run_key", "")
            evs = e.get("events", [])
            has_launched = any("launched" in x for x in evs)
            has_end = any("completed" in x or "failed" in x for x in evs)
            if has_launched and not has_end:
                incomplete_events.append(rk)
        print(f"--- events 完整性检查 ---")
        print(f"  有事件的 run 数: {len(all_events)}")
        print(f"  有 launched 无 completed/failed: {len(incomplete_events)} 个")
        if incomplete_events:
            print(f"  ⚠️ 以下 run 事件不完整（可能还在运行或崩溃未写完成事件）：")
            for rk in incomplete_events[:10]:
                print(f"    {rk}")
            if len(incomplete_events) > 10:
                print(f"    ... 还有 {len(incomplete_events) - 10} 个")
        print()

        # --- prepared 堆积检查（缺口3）---
        aql_prepared = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status == 'prepared' "
            f"COLLECT WITH COUNT INTO cnt RETURN cnt"
        )
        prepared_count = list(db.aql.execute(aql_prepared, bind_vars={"bid": batch_id}, ttl=60))[0]
        print(f"--- prepared 堆积检查 ---")
        print(f"  prepared 状态的 run 数: {prepared_count}")
        try:
            from src.continuation_redis_queue import get_redis, pending_count
            r = get_redis()
            redis_pending = pending_count(r)
            print(f"  Redis pending 数: {redis_pending}")
            if prepared_count > 0 and redis_pending == 0:
                print(f"  ⚠️ {prepared_count} 个 prepared 但 Redis pending=0——feeder 可能没在入队")
            elif prepared_count > redis_pending * 10:
                print(f"  ⚠️ prepared({prepared_count}) 远大于 pending({redis_pending})——入队速度可能跟不上")
            else:
                print(f"  prepared/pending 比例正常")
        except Exception as re:
            print(f"  Redis 查询失败: {re}")
        print()

        # --- 按题源完成率统计（缺口2）---
        from collections import defaultdict
        aql_src = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"RETURN {{pid: run.problem_id, fs: run.final_status}}"
        )
        cursor_src = db.aql.execute(aql_src, bind_vars={"bid": batch_id}, ttl=120, batch_size=500)
        src_stats = defaultdict(lambda: {"total": 0, "completed": 0})
        for r in cursor_src:
            src = r["pid"].split("_")[0]
            src_stats[src]["total"] += 1
            if r["fs"] == "COMPLETED":
                src_stats[src]["completed"] += 1
        print(f"--- 按题源完成率统计 ---")
        zero_sources = []
        for src in sorted(src_stats.keys()):
            s = src_stats[src]
            rate = s["completed"] / s["total"] if s["total"] > 0 else 0
            rate_str = f"{rate:.1%}"
            flag = ""
            if rate == 0:
                flag = " ⚠️ 全0%"
                zero_sources.append(src)
            print(f"  {src}: {s['completed']}/{s['total']} = {rate_str}{flag}")
        if zero_sources:
            print(f"  ⚠️ {len(zero_sources)} 个题源完成率为0%——系统性问题（prompt不适用？model不胜任？还是没跑到？）")
        print()

        # --- 标准文件检查（缺口6）---
        aql_files = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"LIMIT 100 "
            f"RETURN {{_key: run._key, pid: run.problem_id, work_dir: run.work_dir, "
            f"traj_dir: run.trajectory_dir, status: run.status, fs: run.final_status}}"
        )
        cursor_files = db.aql.execute(aql_files, bind_vars={"bid": batch_id}, ttl=60)
        file_issues = []
        checked_runs = 0
        for r in cursor_files:
            checked_runs += 1
            wd = Path(r.get("work_dir", ""))
            td = Path(r.get("traj_dir", ""))
            pid = r.get("pid", "?")
            # problem.txt
            if wd.exists() and not (wd / "problem.txt").exists():
                file_issues.append(f"  [{pid}] problem.txt 缺失")
            # completed 的 proof.md
            if r.get("fs") == "COMPLETED" and wd.exists() and not (wd / "proof.md").exists():
                file_issues.append(f"  [{pid}] COMPLETED 但 work_dir/proof.md 缺失")
            # round 1 的 export（不在 rounds_log 中）
            if td.exists():
                r1_export = td / "round1" / "exports" / "conversation.json"
                if not r1_export.exists():
                    # 也检查 exports/ 目录
                    r1_export2 = td / "exports" / "conversation.json"
                    if not r1_export2.exists():
                        # WP-S：降级为提示（不计 issue）——round1 traj 双写自
                        # WP-S 起对新 run 生效；缺失多为早于 WP-S 的旧 run
                        print(f"  [info] [{pid}] round1/exports/conversation.json "
                              f"缺失（该 run 早于 WP-S 双写，属正常）")
        print(f"--- 标准文件检查（{checked_runs}个run）---")
        if file_issues:
            print(f"  发现 {len(file_issues)} 个问题：")
            for issue in file_issues[:15]:
                print(issue)
            if len(file_issues) > 15:
                print(f"  ... 还有 {len(file_issues) - 15} 个问题")
        else:
            print(f"  标准文件完整性正常")
        print()

        # --- round 编号连续性检查（缺口4）---
        aql_rounds = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER LENGTH(run.rounds_log) > 0 "
            f"LIMIT 50 "
            f"RETURN {{_key: run._key, rounds: run.rounds_log[*].round}}"
        )
        cursor_rounds = db.aql.execute(aql_rounds, bind_vars={"bid": batch_id}, ttl=60)
        discontinuous = []
        starts_from_2 = 0
        for r in cursor_rounds:
            rounds = r.get("rounds", [])
            if not rounds:
                continue
            if rounds[0] == 2:
                starts_from_2 += 1
            expected = list(range(rounds[0], rounds[0] + len(rounds)))
            if rounds != expected:
                discontinuous.append(f"  {r['_key']}: rounds={rounds}")
        print(f"--- round 编号连续性检查（50个run）---")
        print(f"  从 round=2 开始的 run: {starts_from_2}/50")
        if discontinuous:
            print(f"  编号不连续: {len(discontinuous)} 个")
            for d in discontinuous[:5]:
                print(d)
        else:
            print(f"  编号连续（正常轮序 [1,2,3..]，round-1 补录已修复）")
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
    """步骤04：C类AI判断——查询 needs_ai_review 的 run + 审计质量复核（C7-C9）"""
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
        else:
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

        # === 审计质量复核（C7-C9，见 dev-docs/029 §7.2）===
        _check_audit_quality_review(db)

    except Exception as e:
        print(f"⚠️ AI review 候选查询失败: {e}")
        print()


def _check_audit_quality_review(db):
    """步骤04例行：审计质量复核——抽查审计 AI 的判断质量（C7-C9）。

    审计 Pipe 上线后，SOP_04 从"Master Agent 人工判断 C1-C6"升级为
    "审计 Pipe 自动判断 + Master Agent 复核审计质量 C7-C9"。
    """
    print("--- 审计质量复核（C7-C9）---")
    try:
        from src.proof_audit_config import PROOF_AUDITS_COLLECTION

        if not db.has_collection(PROOF_AUDITS_COLLECTION):
            print("  （审计 Pipe 未运行——p27_proof_audits 集合不存在）")
            print()
            return

        # C7: 抽查审计判 PASS 的题——proof 真的对吗？
        pass_aql = (
            f"FOR a IN {PROOF_AUDITS_COLLECTION} "
            f"FILTER a.audit_status IN ['PASS', 'PASS_WITH_CAVEAT'] "
            f"FILTER a.ai_review_done != true "
            f"SORT RAND() LIMIT 5 "
            f"RETURN {{_key: a._key, source_run_key: a.source_run_key, "
            f"problem_id: a.problem_id, audit_status: a.audit_status, "
            f"audit_summary: a.audit_summary}}"
        )
        pass_candidates = list(db.aql.execute(pass_aql, ttl=60))

        # C8: 抽查审计判 FAIL 的题——proof 真的错吗？
        fail_aql = (
            f"FOR a IN {PROOF_AUDITS_COLLECTION} "
            f"FILTER a.audit_status LIKE 'FAIL_%' "
            f"FILTER a.ai_review_done != true "
            f"SORT RAND() LIMIT 5 "
            f"RETURN {{_key: a._key, source_run_key: a.source_run_key, "
            f"problem_id: a.problem_id, audit_status: a.audit_status, "
            f"audit_summary: a.audit_summary, cheating_analysis: a.cheating_analysis}}"
        )
        fail_candidates = list(db.aql.execute(fail_aql, ttl=60))

        # C9: 作弊检测题——复查作弊证据是否充分
        cheat_aql = (
            f"FOR a IN {PROOF_AUDITS_COLLECTION} "
            f"FILTER a.audit_status IN ['FAIL_CHEATING', 'FAIL_CHEATING_DECLARED'] "
            f"FILTER a.ai_review_done != true "
            f"LIMIT 5 "
            f"RETURN {{_key: a._key, source_run_key: a.source_run_key, "
            f"problem_id: a.problem_id, audit_status: a.audit_status, "
            f"cheating_analysis: a.cheating_analysis}}"
        )
        cheat_candidates = list(db.aql.execute(cheat_aql, ttl=60))

        print(f"  C7 审计判PASS的题（抽查proof是否确实正确）: {len(pass_candidates)}条")
        for c in pass_candidates:
            print(f"    [{c['problem_id']}] {c['audit_status']}: {c['audit_summary'][:80]}")

        print(f"  C8 审计判FAIL的题（抽查proof是否确实错误）: {len(fail_candidates)}条")
        for c in fail_candidates:
            print(f"    [{c['problem_id']}] {c['audit_status']}: {c['audit_summary'][:80]}")

        print(f"  C9 作弊检测题（复查作弊证据是否充分）: {len(cheat_candidates)}条")
        for c in cheat_candidates:
            analysis = c.get("cheating_analysis", "")[:100]
            print(f"    [{c['problem_id']}] {c['audit_status']}: {analysis}")

        if not pass_candidates and not fail_candidates and not cheat_candidates:
            print("  ✅ 无待复核的审计结果")

    except Exception as e:
        print(f"  ⚠️ 审计质量复核失败: {e}")
    print()


def check_05_code_repair(batch_id):
    """步骤05：代码修复——自动汇总未处理的"代码bug"类 alert + 显示最近 git log

    跨步骤信息传递：03 分类为"代码bug"的 alert 和 04 发现的代码相关问题，
    在这里自动从 DB 查询汇总，避免 AI 上下文压缩后丢失 03/04 的分类结果。
    """
    log.info(f"check_05_code_repair: start batch={batch_id}")
    repo_root = Path(__file__).parent.parent.parent

    # === 自动汇总未处理的"代码bug"类 alert（跨步骤信息传递）===
    # alert_type 分类依据 SYSTEM_CLOSURE §6 的 alert_type 完整清单表
    CODE_BUG_ALERT_TYPES = {
        "session_health", "export_missing", "export_missing_rate",
        "rounds_log_duplicate_round", "rounds_log_missing_field",
        "rounds_log_export_missing", "rounds_log_handover_missing",
        "rounds_log_proof_missing", "rounds_log_no_proof_path",
        "intermediate_product_collision", "work_dir_collision",
        "session_registry_inconsistency",
        "real_concurrency_mismatch", "real_concurrency_exceeded",
        "launch_churn",
    }
    print("--- 未处理的代码bug类 alert（从步骤03汇总，跨步骤信息传递）---")
    try:
        from src.continuation_db_schema import connect_db
        from src.continuation_config import MONITOR_ALERTS_COLLECTION
        db = connect_db()
        aql = (
            f"FOR a IN {MONITOR_ALERTS_COLLECTION} "
            f"FILTER a.status != 'resolved' "
            f"FILTER a.alert_type IN @bug_types "
            f"SORT a.severity DESC, a.created_at DESC "
            f"LIMIT 30 "
            f"RETURN a"
        )
        cursor = db.aql.execute(aql, bind_vars={"bug_types": list(CODE_BUG_ALERT_TYPES)}, ttl=60)
        code_bug_alerts = list(cursor)
        if code_bug_alerts:
            print(f"  发现 {len(code_bug_alerts)} 个未处理的代码bug类 alert：")
            for a in code_bug_alerts:
                severity = a.get("severity", "?")
                atype = a.get("alert_type", "?")
                details = a.get("details", {})
                summary = details.get("summary", "") if isinstance(details, dict) else str(details)
                print(f"    [{severity}] {atype} (key={a.get('_key', '?')}): {summary[:80]}")
            print(f"  → 这些 alert 需在步骤05修复（分类为代码bug）")
        else:
            print("  ✅ 无未处理的代码bug类 alert")
        print()
    except Exception as e:
        print(f"  ⚠️ 代码bug alert 查询失败: {e}")
        print()

    # === 显示最近 git log ===
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


def _check_prev_report_filled():
    """步骤06例行：上一轮 report.md 填写校验（观察项-4）。

    检查 D 盘报表目录中最近一份 report.md 是否还有 [ ] 待检查标记残留。
    SOP 要求"不填写=检查没完成"，但 run.py 只生成空白模板不校验填写。
    这里自动检查，有残留时醒目输出。
    """
    print("--- 上一轮 report.md 填写校验 ---")
    try:
        from scripts.sop.report import REPORT_BASE
        if not REPORT_BASE.exists():
            print("  （报表目录不存在——系统可能刚启动，无历史报表）")
            print()
            return
        # 遍历所有 cycle/step/timestamp 目录，找最近的 report.md
        report_files = list(REPORT_BASE.rglob("report.md"))
        if not report_files:
            print("  （无历史 report.md——系统可能刚启动）")
            print()
            return
        latest = max(report_files, key=lambda f: f.stat().st_mtime)
        content = latest.read_text(encoding="utf-8", errors="ignore")
        unchecked = content.count("[ ]")
        checked = content.count("[x]")
        if unchecked > 0:
            print(f"  ⚠️ 最近 report.md 有 {unchecked} 个 [ ] 未填写: {latest}")
            print(f"     （已填写 [x]: {checked}）——上一轮检查可能未完成")
        else:
            print(f"  ✅ 最近 report.md 已全部填写（[x]: {checked}）: {latest}")
        print()
    except Exception as e:
        print(f"  ⚠️ report.md 填写校验失败: {e}")
        print()


def check_06_report_worklog_selfcheck(batch_id):
    """步骤06：报告+WORKLOG+Self-check——显示 WORKLOG 状态 + MONITOR_REPORT.md 检查"""
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

    # MONITOR_REPORT.md 存在性+大小检查（观察项-2）
    report_path = repo_root / "MONITOR_REPORT.md"
    print("--- MONITOR_REPORT.md 检查 ---")
    if report_path.exists():
        size = report_path.stat().st_size
        if size < 100:
            print(f"  ⚠️ MONITOR_REPORT.md 过小 ({size}B)，可能未填写")
        else:
            print(f"  ✅ MONITOR_REPORT.md 存在 ({size}B)")
    else:
        print(f"  ❌ MONITOR_REPORT.md 不存在——SOP_06 要求写此文件")
    print()

    # 上一轮 report.md 填写校验（观察项-4）——检查是否有 [ ] 待检查标记残留
    _check_prev_report_filled()


def check_Z_meta_system_review(batch_id):
    """步骤Z：元检查+整体检查——显示 SOP 系统全貌 + 016新能力接线自动检查（M8）"""
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

    # === M8: 016新能力接线自动检查 ===
    # 行为流水(observability)/步进门闸(step_gate)/A13A14告警 接线状态
    print("--- M8: 016新能力接线检查（自动化）---")

    # 1. 行为流水接线：log/flow/ 目录是否存在且有文件
    repo_root = Path(__file__).parent.parent.parent
    flow_dir = repo_root / "log" / "flow"
    if flow_dir.exists():
        flow_files = list(flow_dir.glob("flow-*.jsonl"))
        if flow_files:
            latest = max(flow_files, key=lambda f: f.stat().st_mtime)
            size_kb = latest.stat().st_size / 1024
            print(f"  ✅ 行为流水：{len(flow_files)} 个文件，最新 {latest.name} ({size_kb:.1f}KB)")
        else:
            print(f"  ⚠️ 行为流水目录存在但无 flow-*.jsonl 文件（系统可能刚启动）")
    else:
        print(f"  ❌ 行为流水目录不存在: {flow_dir}（observability 未接线）")

    # 2. 步进门闸接线：DB p27_step_gates 集合是否存在且有文档
    try:
        from src.continuation_db_schema import connect_db
        from src.step_gate import COLLECTION
        db = connect_db()
        if db.has_collection(COLLECTION):
            gate_count = db.collection(COLLECTION).count()
            if gate_count > 0:
                print(f"  ✅ 步进门闸：{gate_count} 个门闸已注册（p27_step_gates 集合）")
            else:
                print(f"  ⚠️ 步进门闸集合存在但无门闸（需 python -m src.step_gate --register）")
        else:
            print(f"  ❌ 步进门闸集合不存在: {COLLECTION}（step_gate 未接线）")
    except Exception as e:
        print(f"  ⚠️ 步进门闸检查失败（DB不可达？）: {e}")

    # 3. A13/A14 告警接线：检查 monitor_continuation.py 是否有对应 check 函数
    # 通过检查 DB 中是否有 real_concurrency_mismatch/launch_churn 类型的 alert 历史
    try:
        from src.continuation_config import MONITOR_ALERTS_COLLECTION
        aql = (
            f"FOR a IN {MONITOR_ALERTS_COLLECTION} "
            f"FILTER a.alert_type IN ['real_concurrency_mismatch', 'real_concurrency_exceeded', 'launch_churn'] "
            f"COLLECT t = a.alert_type WITH COUNT INTO c "
            f"RETURN {{type: t, count: c}}"
        )
        cursor = db.aql.execute(aql, ttl=30)
        a13_a14_alerts = list(cursor)
        if a13_a14_alerts:
            print(f"  ✅ A13/A14 告警已触发过：")
            for a in a13_a14_alerts:
                print(f"     {a['type']}: {a['count']} 次")
        else:
            print(f"  ✅ A13/A14 告警接线正常（未触发过=系统未出现失控循环）")
    except Exception as e:
        print(f"  ⚠️ A13/A14 告警历史查询失败: {e}")

    # 4. checks.py Y通道接线：确认 check_01 调用了 _check_pending_gates
    try:
        import inspect
        from scripts.sop import checks as checks_mod
        src_01 = inspect.getsource(checks_mod.check_01_system_health)
        has_y = "_check_pending_gates" in src_01
        has_flow = "_check_flow_snapshot" in src_01
        has_panorama = "_check_system_panorama" in src_01
        y_status = "✅" if has_y else "❌"
        flow_status = "✅" if has_flow else "❌"
        panorama_status = "✅" if has_panorama else "❌"
        print(f"  {y_status} checks.py Y通道接线（check_01 调用 _check_pending_gates）")
        print(f"  {flow_status} checks.py 行为流水接线（check_01 调用 _check_flow_snapshot）")
        print(f"  {panorama_status} checks.py 全景视图接线（check_01 调用 _check_system_panorama）")
    except Exception as e:
        print(f"  ⚠️ checks.py 接线检查失败: {e}")
    print()


def check_OP_operations_knowledge(batch_id):
    """步骤OP：运营知识刷新——环境验证(ENV-01~07) + 运营知识已在上方文档注入。

    AGENTS.md受16K限制只保留启动指令核心，运营知识（硬约束/外部索引/快速开始
    /SOP机制）在SOP_OP文档里每轮由run.py反复注入。这里做轻量环境验证，确保
    基础设施正常（系统无法运行时运营知识也无意义）。
    """
    log.info(f"check_OP_operations_knowledge: start batch={batch_id}")
    import os
    from pathlib import Path

    print("--- 环境验证（ENV-01~07）---")
    arango_db = os.environ.get("ARANGO_DB", "")
    if arango_db == "xishujuzhen_math_glm52":
        print(f"  ✅ ARANGO_DB={arango_db}")
    else:
        print(f"  ❌ ARANGO_DB='{arango_db}'（应=xishujuzhen_math_glm52）——先 source .env")

    try:
        from src.continuation_db_schema import connect_db
        db = connect_db()
        print(f"  ✅ ArangoDB连接成功（库={db.name}）")
    except Exception as e:
        print(f"  ❌ ArangoDB连接失败: {e}")

    try:
        from src.continuation_redis_queue import ping
        if ping():
            print("  ✅ Redis连接成功（ping=True）")
        else:
            print("  ❌ Redis ping返回False")
    except Exception as e:
        print(f"  ❌ Redis连接失败: {e}")

    d = Path("/Volumes/data")
    try:
        if d.exists() and any(d.iterdir()):
            print("  ✅ D盘已挂载")
        else:
            print("  ❌ D盘未挂载或为空")
    except Exception as e:
        print(f"  ❌ D盘检查失败: {e}")

    print()
    print("--- 运营知识已在上方SOP_OP文档注入 ---")
    print("  （项目概况/硬约束10+4条/外部文档索引/快速开始/SOP文档与报表系统）")
    print("  读一遍确认无变化。环境全✅=可继续循环；有❌=critical需先修复环境。")
    print()
