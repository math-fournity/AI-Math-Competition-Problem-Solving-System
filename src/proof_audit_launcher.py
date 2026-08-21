"""proof_audit_launcher.py — Pipe 5 审计 Pipe 并发引擎

并发启动 devin cli 审计 proof.md。复用续传 launcher 的 tmux 架构和
stall/rate_limit/zombie 检测模式，但简化为单轮（审计不需要多轮续传）。

门闸（@gated）：
  GATE-AUDIT-LAUNCH       — 启动审计 devin cli（resource=action）
  GATE-AUDIT-KILL-SESSION — kill 审计 session（resource=tmux）

用法：
  python -m src.proof_audit_launcher --batch-id paudit-p27-full --concurrency 5
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.proof_audit_config import (
    PROJECT_ROOT, AUDIT_SOLVER_BASE, AUDIT_TRAJECTORY_BASE,
    DEVIN_MODEL, DEVIN_PERMISSION_MODE,
    PROOF_AUDIT_RUNS_COLLECTION,
    AUDIT_DEFAULT_CONCURRENCY, AUDIT_MAX_RUNTIME_SECONDS,
    AUDIT_STALL_SECONDS, AUDIT_POLL_SECONDS,
    AUDIT_COMPLETE_MARKER, AUDIT_TMUX_PREFIX,
    GATE_AUDIT_LAUNCH, GATE_AUDIT_KILL_SESSION,
)
from src.proof_audit_db_schema import (
    connect_db, ensure_schema, get_audit_run, update_audit_run,
)
from src.proof_audit_redis_queue import (
    get_redis, enqueue_pending, dequeue_pending,
    add_running, get_running, get_all_running, remove_running,
    add_completed, add_failed, pending_count, running_count,
)
from src.step_gate import gated
from monitoring.shared_logger import get_logger, log_event
from monitoring.graceful_shutdown import register_shutdown, should_stop
from src.observability import log_flow
from src.proof_audit_result_collector import collect_one, collect_results

logger = get_logger("proof_audit_launcher")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def tmux_session_name(audit_run_key):
    """生成 tmux session 名——paudit-{audit_run_key后30字符}"""
    short = audit_run_key[-30:] if len(audit_run_key) > 30 else audit_run_key
    return f"{AUDIT_TMUX_PREFIX}-{short}"


def tmux_running(session_name):
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def tmux_kill(session_name):
    try:
        subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def tmux_pane_text(session_name, lines=500):
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout
    except Exception:
        return ""


def prepare_audit_work_dir(audit_run_key, problem_text, standard_answer, proof_text):
    """准备审计 work_dir——写 AGENTS.md（渲染模板）+ input 文件"""
    work_dir = AUDIT_SOLVER_BASE / audit_run_key
    work_dir.mkdir(parents=True, exist_ok=True)

    # 渲染审计 AGENTS.md 模板
    template_path = PROJECT_ROOT / "templates" / "proof_audit_agents_md.md"
    template = template_path.read_text()

    # 用 replace 替换占位符（不用 .format() 因为模板中有 LaTeX 大括号会被误解析）
    agents_md = template.replace("{problem_id}", audit_run_key.replace("paudit-", ""))
    agents_md = agents_md.replace("{problem_text}", problem_text or "（题目文本缺失）")
    agents_md = agents_md.replace("{standard_answer}", standard_answer or "（标准答案缺失）")
    agents_md = agents_md.replace("{proof_text}", proof_text or "（proof文本缺失）")
    agents_md = agents_md.replace("{solver_trajectory_summary}", "（暂未提供解题AI的工具调用记录）")

    agents_md_path = work_dir / "AGENTS.md"
    agents_md_path.write_text(agents_md)

    # 也写一份 proof.txt 供审计 AI 直接读
    (work_dir / "proof.txt").write_text(proof_text or "")

    return work_dir, agents_md_path


@gated
def audit_launch(audit_run_key, work_dir, prompt_file, export_path, db=None, batch_id=None):
    """【门闸: GATE-AUDIT-LAUNCH】启动审计 devin cli。

    这个函数做什么：
    - 用 tmux 启动一个 devin -p 子进程跑审计 prompt；
    - 建立 tmux 日志管道；
    - 返回 session_name。

    为什么追踪这个动作：
    - 启动即消耗 GLM-5.2 API 配额、创建 session；
    - 审计是选题池的准入门槛——审计通过=进入选题池，审计失败=排除。

    放行前 Master Agent 应检查：
    1. 待审计的 proof.md 存在且非空 → 查法：ls work_dir/proof.txt + wc -c > 0
    2. 审计 work_dir 已准备好（AGENTS.md + proof.txt） → 查法：ls work_dir
    3. 审计并发未超限 → 查法：paudit:running 的 hlen < concurrency
    """
    session_name = tmux_session_name(audit_run_key)
    tmux_kill(session_name)  # 清理同名 session

    traj_dir = Path(export_path).parent.parent
    tmux_log_path = traj_dir / "tmux" / "tmux.log"
    tmux_pipe_path = traj_dir / "tmux" / "tmux_pipe.log"
    tmux_log_path.parent.mkdir(parents=True, exist_ok=True)

    # DONE.md 标记文件
    done_marker = Path(export_path).parent / "DONE.md"
    if done_marker.exists():
        done_marker.unlink()

    devin_cmd = (
        f"devin -p "
        f"--prompt-file {prompt_file} "
        f"--model {DEVIN_MODEL} "
        f"--respect-workspace-trust false "
        f"--permission-mode {DEVIN_PERMISSION_MODE} "
        f"--export {export_path}; "
        f"echo $? > {done_marker}; "
        f"sleep 999999"
    )

    log_event(logger, "info", "devin_cli_launch",
              audit_run_key=audit_run_key, session_type="audit",
              model=DEVIN_MODEL, permission_mode=DEVIN_PERMISSION_MODE,
              batch_id=batch_id or "")

    full_cmd = f"cd {work_dir} && {devin_cmd} 2>&1 | tee {tmux_log_path}"
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, full_cmd],
        capture_output=True, timeout=10,
    )
    subprocess.run(
        ["tmux", "pipe-pane", "-t", session_name, f"cat >> {tmux_pipe_path}"],
        capture_output=True, timeout=5,
    )

    return session_name


@gated(resource="tmux")
def audit_kill_session(session_name, audit_run_key, reason="completed"):
    """【门闸: GATE-AUDIT-KILL-SESSION】kill 审计 session 的 tmux（不可逆）。

    为什么追踪这个动作：
    - kill 是不可逆动作——kill 后审计 devin cli 进程终止；
    - 误 kill 会导致审计中断、结果丢失。

    放行前 Master Agent 应检查：
    1. 审计已完成 → 查法：DONE.md 存在 或 ### PROOF AUDIT COMPLETE 在 export 中
    2. 审计 export 已落盘 → 查法：ls export 文件存在
    3. reason=completed/stall/dead 时审计结果已提取 → 查法：p27_proof_audits 有记录
    """
    tmux_kill(session_name)
    log_event(logger, "info", "audit_kill_session",
              audit_run_key=audit_run_key, session_name=session_name, reason=reason)


def check_audit_complete(export_path, session_name):
    """检查审计是否完成——DONE.md 存在 或 export 中有 ### PROOF AUDIT COMPLETE"""
    done_marker = Path(export_path).parent / "DONE.md"
    if done_marker.exists():
        return True

    # 检查 export 文件中是否有完成标记
    if Path(export_path).exists():
        try:
            with open(export_path) as f:
                content = f.read()
            if AUDIT_COMPLETE_MARKER in content:
                return True
        except Exception:
            pass

    # 检查 tmux pane 文本
    pane_text = tmux_pane_text(session_name, lines=200)
    if AUDIT_COMPLETE_MARKER in pane_text:
        return True

    return False


def detect_stall(session_name, stall_since):
    """检测审计是否 stall——tmux pane 无新活动超过 stall_seconds"""
    if stall_since is None:
        return None
    elapsed = time.time() - stall_since
    if elapsed > AUDIT_STALL_SECONDS:
        return True
    return False


def _final_collect(batch_id):
    """兜底收集（WP-H 三条退出路径统一收尾）：正常情况下收尾即收集已入库，
    这里抓漏网（如崩溃恢复后残留的 completed）。失败不阻塞退出——收集可重试，
    崩溃不可接受。"""
    try:
        n = collect_results(batch_id)
        print(f"  [final-collect] 兜底收集: {n} 条")
    except Exception as e:
        log_event(logger, "warning", "final_collect_failed",
                  batch_id=batch_id, error=str(e))
        print(f"  [final-collect] 失败（不阻塞退出）: {e}")


def launch_batch(batch_id, concurrency=AUDIT_DEFAULT_CONCURRENCY,
                 max_runtime=AUDIT_MAX_RUNTIME_SECONDS,
                 stall_seconds=AUDIT_STALL_SECONDS,
                 poll_seconds=AUDIT_POLL_SECONDS):
    """并发启动审计批次"""
    print(f"=== 启动审计批次 batch={batch_id} concurrency={concurrency} ===")
    log_event(logger, "info", "audit_batch_start",
              batch_id=batch_id, concurrency=concurrency)

    # 优雅停止注册（WP-H，graceful-shutdown.md §6 清单第 2 步）
    register_shutdown("proof_audit_launcher")

    db = connect_db()
    ensure_schema(db)

    # 连接 Redis
    try:
        r = get_redis()
        r.ping()
        print("  Redis: 连接成功")
    except Exception as e:
        print(f"  Redis: 连接失败({e})")
        return

    pending_in_redis = pending_count(r)
    if pending_in_redis == 0:
        print(f"  paudit:pending 为空——请先运行 proof_audit_collector")
        return
    print(f"  paudit:pending: {pending_in_redis}")

    start_time = time.time()
    launched = 0
    completed_count = 0
    failed_count = 0

    # 主循环
    while True:
        # 检查 pending 和 running 是否都空了
        current_pending = pending_count(r)
        current_running = running_count(r)
        if current_pending == 0 and current_running == 0:
            print(f"\n=== 审计批次完成 ===")
            print(f"  launched: {launched}")
            print(f"  completed: {completed_count}")
            print(f"  failed: {failed_count}")
            _final_collect(batch_id)  # WP-H：自然完成路径也统一收尾
            break

        # 检查超时
        if time.time() - start_time > max_runtime * 10:  # 整体超时（批次级）
            print(f"\n=== 审计批次超时 ===")
            print(f"  launched: {launched}")
            print(f"  completed: {completed_count}")
            print(f"  failed: {failed_count}")
            _final_collect(batch_id)  # WP-H：超时退出路径同样收尾（033 P3-b）
            break

        # 优雅退出检查（WP-H）——收到 SIGTERM/SIGINT 后不再启动新审计
        if should_stop():
            if current_running == 0:
                print(f"\n=== 优雅停止：running 已全部完成，launcher 退出 ===")
                log_flow("graceful_stop", run_key=None, batch_id=batch_id,
                         launched=launched, completed=completed_count,
                         failed=failed_count)
                print(f"  launched: {launched}")
                print(f"  completed: {completed_count}")
                print(f"  failed: {failed_count}")
                _final_collect(batch_id)
                break
            print(f"  [graceful_shutdown] 不再启动新审计，"
                  f"等待{current_running}个running自然完成...")

        # 补充并发——从 pending 取出填到并发数（优雅停止模式下跳过）
        while not should_stop() and current_running < concurrency and current_pending > 0:
            items = dequeue_pending(r, count=1)
            if not items:
                break
            audit_run_key, _ = items[0]

            # 从 DB 获取审计 run 信息
            audit_run = get_audit_run(db, audit_run_key)
            if not audit_run:
                print(f"  [skip] {audit_run_key}: DB 中无记录")
                add_failed(r, {"audit_run_key": audit_run_key, "reason": "DB无记录"})
                failed_count += 1
                current_pending = pending_count(r)
                continue

            # 准备 work_dir
            problem_text = audit_run.get("problem_text", "")
            standard_answer = audit_run.get("standard_answer", "")
            proof_text = audit_run.get("proof_text", "")

            if not proof_text:
                print(f"  [skip] {audit_run_key}: 无 proof_text")
                add_failed(r, {"audit_run_key": audit_run_key, "reason": "无proof_text"})
                update_audit_run(db, audit_run_key, {
                    "status": "failed",
                    "error_message": "无proof_text",
                    "ended_at": utc_now(),
                })
                failed_count += 1
                current_pending = pending_count(r)
                continue

            work_dir, prompt_file = prepare_audit_work_dir(
                audit_run_key, problem_text, standard_answer, proof_text)
            export_path = audit_run.get("export_path", "")

            # 启动审计 devin cli（门闸 GATE-AUDIT-LAUNCH）
            session_name = audit_launch(
                audit_run_key, work_dir, prompt_file, export_path,
                db=db, batch_id=batch_id)

            # 加入 running
            add_running(r, audit_run_key, {
                "session_name": session_name,
                "work_dir": str(work_dir),
                "export_path": export_path,
                "started_at": time.time(),
                "stall_since": None,
            })

            # 更新 DB
            update_audit_run(db, audit_run_key, {
                "status": "running",
                "started_at": utc_now(),
                "work_dir": str(work_dir),
            })

            launched += 1
            print(f"  [launch] {audit_run_key} → {session_name}")
            current_running = running_count(r)
            current_pending = pending_count(r)
            time.sleep(2)  # 启动间隔

        # 检查 running 中的审计是否完成
        all_running = get_all_running(r)
        for audit_run_key, meta in list(all_running.items()):
            session_name = meta.get("session_name", "")
            export_path = meta.get("export_path", "")
            started_at = meta.get("started_at", time.time())

            # 检查完成
            if check_audit_complete(export_path, session_name):
                # 审计完成——kill session（门闸 GATE-AUDIT-KILL-SESSION）
                audit_kill_session(session_name, audit_run_key, reason="completed")

                # 移出 running，加入 completed
                remove_running(r, audit_run_key)
                add_completed(r, {
                    "audit_run_key": audit_run_key,
                    "export_path": export_path,
                    "completed_at": utc_now(),
                })

                # 更新 DB
                update_audit_run(db, audit_run_key, {
                    "status": "completed",
                    "ended_at": utc_now(),
                })

                # 收尾即收集（WP-H，030 需求1第二层）：判定完成立即入库
                try:
                    result = collect_one(db, get_audit_run(db, audit_run_key))
                    print(f"  [collect] {audit_run_key}: {result}")
                except Exception as e:
                    log_event(logger, "warning", "collect_one_failed",
                              audit_run_key=audit_run_key, error=str(e))
                    print(f"  [collect] {audit_run_key}: 失败(不阻塞) {e}")

                completed_count += 1
                print(f"  [done] {audit_run_key}")
                continue

            # 检查 stall
            if not tmux_running(session_name):
                # session 已消失——可能是 devin cli 正常退出但 DONE.md 没写
                # 检查 export 是否有完成标记
                if Path(export_path).exists():
                    # 有 export——视为完成
                    audit_kill_session(session_name, audit_run_key, reason="dead_done")
                    remove_running(r, audit_run_key)
                    add_completed(r, {
                        "audit_run_key": audit_run_key,
                        "export_path": export_path,
                        "completed_at": utc_now(),
                    })
                    update_audit_run(db, audit_run_key, {
                        "status": "completed",
                        "ended_at": utc_now(),
                    })

                    # 收尾即收集（WP-H）：dead_done 分支同样立即入库
                    try:
                        result = collect_one(db, get_audit_run(db, audit_run_key))
                        print(f"  [collect] {audit_run_key}: {result}")
                    except Exception as e:
                        log_event(logger, "warning", "collect_one_failed",
                                  audit_run_key=audit_run_key, error=str(e))
                        print(f"  [collect] {audit_run_key}: 失败(不阻塞) {e}")

                    completed_count += 1
                    print(f"  [done-dead] {audit_run_key}")
                else:
                    # 无 export——失败
                    remove_running(r, audit_run_key)
                    add_failed(r, {
                        "audit_run_key": audit_run_key,
                        "reason": "dead_session_no_export",
                    })
                    update_audit_run(db, audit_run_key, {
                        "status": "failed",
                        "error_message": "dead_session_no_export",
                        "ended_at": utc_now(),
                    })
                    failed_count += 1
                    print(f"  [fail-dead] {audit_run_key}")
                continue

            # 检查超时
            if time.time() - started_at > max_runtime:
                audit_kill_session(session_name, audit_run_key, reason="stall")
                remove_running(r, audit_run_key)
                add_failed(r, {
                    "audit_run_key": audit_run_key,
                    "reason": "stall_timeout",
                })
                update_audit_run(db, audit_run_key, {
                    "status": "failed",
                    "error_message": "stall_timeout",
                    "ended_at": utc_now(),
                })
                failed_count += 1
                print(f"  [fail-stall] {audit_run_key}")

        # 等待下一轮轮询
        time.sleep(poll_seconds)

    log_event(logger, "info", "audit_batch_done",
              batch_id=batch_id, launched=launched,
              completed=completed_count, failed=failed_count)


def stop_audit_batch(batch_id, force=False):
    """停止审计批次——优雅停止（默认）或强制 kill（WP-H 任务3，模仿 continuation_launcher.stop_batch）

    优雅停止（force=False，默认）：
      - 向 launcher 进程发送 SIGINT，launcher 收到后不再启动新审计
      - 已在运行的 devin cli session 继续自然完成（收尾即收集照常生效）
      - Redis 队列不清空（恢复时可继续）

    强制停止（force=True）：
      - kill 所有 paudit- tmux session（包括正在运行的 devin cli）
      - 清空 paudit: Redis 队列
    """
    print(f"=== 停止审计批次: {batch_id} (mode: {'force' if force else 'graceful'}) ===")

    if force:
        # 强制模式：kill 所有 paudit- session + 清空队列
        result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
        paudit_sessions = [l.split(":")[0] for l in result.stdout.split("\n")
                           if l.startswith(f"{AUDIT_TMUX_PREFIX}-")]
        for s in paudit_sessions:
            subprocess.run(["tmux", "kill-session", "-t", s], capture_output=True, timeout=5)
            print(f"  killed: {s}")
        print(f"  共kill {len(paudit_sessions)}个session")

        r = get_redis()
        from src.proof_audit_redis_queue import (
            PENDING_KEY, RUNNING_KEY, COMPLETED_KEY, FAILED_KEY, STATS_KEY,
        )
        for key in (PENDING_KEY, RUNNING_KEY, COMPLETED_KEY, FAILED_KEY, STATS_KEY):
            r.delete(key)
        print(f"  paudit: Redis 队列已清空")
    else:
        # 优雅模式：向 launcher 发送 SIGINT，不 kill devin session
        launcher_pids = subprocess.run(
            ["pgrep", "-f", f"proof_audit_launcher.*{batch_id}"],
            capture_output=True, text=True
        ).stdout.strip().split("\n")
        launcher_pids = [p for p in launcher_pids if p]

        if not launcher_pids:
            print(f"  [WARNING] launcher进程未找到，可能已退出")
            print(f"  如需强制停止所有session: python -m scripts.run_proof_audit_pipeline --batch-id {batch_id} --stop --force")
            return

        for pid in launcher_pids:
            try:
                os.kill(int(pid), 2)  # SIGINT=2
                print(f"  向launcher PID={pid}发送SIGINT")
            except Exception as e:
                print(f"  向PID={pid}发送SIGINT失败: {e}")

        try:
            r = get_redis()
            n = running_count(r)
            print(f"  当前running: {n}个（等待自然完成，收尾即收集照常）")
        except Exception:
            pass

        print(f"")
        print(f"  ★ 等所有running完成后，launcher自动退出（退出前兜底收集）")
        print(f"  ★ 如需立即强制停止（kill所有devin session）:")
        print(f"    python -m scripts.run_proof_audit_pipeline --batch-id {batch_id} --stop --force")


def main():
    parser = argparse.ArgumentParser(description="Pipe 5 审计并发引擎")
    parser.add_argument("--batch-id", required=True, help="审计批次ID")
    parser.add_argument("--concurrency", type=int, default=AUDIT_DEFAULT_CONCURRENCY,
                        help=f"并发数（默认{AUDIT_DEFAULT_CONCURRENCY}）")
    parser.add_argument("--max-runtime", type=int, default=AUDIT_MAX_RUNTIME_SECONDS,
                        help=f"单轮最大运行时间秒（默认{AUDIT_MAX_RUNTIME_SECONDS}）")
    parser.add_argument("--poll-seconds", type=int, default=AUDIT_POLL_SECONDS,
                        help=f"轮询间隔秒（默认{AUDIT_POLL_SECONDS}）")
    args = parser.parse_args()

    launch_batch(
        batch_id=args.batch_id,
        concurrency=args.concurrency,
        max_runtime=args.max_runtime,
        poll_seconds=args.poll_seconds,
    )


if __name__ == "__main__":
    main()
