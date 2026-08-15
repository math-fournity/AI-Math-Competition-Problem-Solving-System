"""analysis_launcher.py — 并发启动组件

并发启动devin cli实例，每个实例分析一道题。
模仿solver_harness的launch_attempt设计，但简化：
  - 无MITM（分析任务不需要token级截获）
  - 无problem.txt（AGENTS.md中已包含所有内容）
  - 用--export导出conversation.json
  - 用tmux capture-pane检测### ANALYSIS COMPLETE

用法：
  python -m src.analysis_launcher --batch-id analysis-1 --concurrency 10
  python -m src.analysis_launcher --status --batch-id analysis-1
  python -m src.analysis_launcher --stop --batch-id analysis-1
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import (
    ANALYSIS_SOLVER_BASE, ANALYSIS_TRAJECTORY_BASE, OUTPUT_BASE,
    DEVIN_MODEL, DEVIN_PERMISSION_MODE, DEVIN_PROMPT,
    DEFAULT_CONCURRENCY, DEFAULT_MAX_RUNTIME_SECONDS, DEFAULT_STALL_SECONDS,
    DEFAULT_POLL_SECONDS, ANALYSIS_COMPLETE_MARKER, XML_BLOCK_END,
)
from src.db_schema import connect_db, ensure_schema, insert_event, update_run


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def tmux_session_name(analysis_exp_id):
    """生成tmux session名（不超过50字符）"""
    # tmux session名不能含点号
    name = analysis_exp_id.replace(".", "-")
    if len(name) > 48:
        name = name[:48]
    return f"an-{name}"


def tmux_running(session_name):
    """检查tmux session是否在运行"""
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def tmux_pane_text(session_name, lines=500):
    """获取tmux pane内容"""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout
    except Exception:
        return ""


def tmux_pane_is_empty(session_name):
    """检查tmux pane是否空白（devin cli已退出）"""
    text = tmux_pane_text(session_name, lines=50)
    # 去掉空行和ANSI转义
    lines = [l.strip() for l in text.split("\n") if l.strip() and not l.startswith("\x1b[")]
    return len(lines) < 3


def launch_one(analysis_exp_id, work_dir):
    """启动一个devin cli实例
    
    Args:
        analysis_exp_id: 分析实验ID
        work_dir: 工作目录路径
    
    Returns:
        tmux_session_name
    """
    session_name = tmux_session_name(analysis_exp_id)
    traj_dir = ANALYSIS_TRAJECTORY_BASE / analysis_exp_id
    traj_dir.mkdir(parents=True, exist_ok=True)
    (traj_dir / "exports").mkdir(exist_ok=True)
    (traj_dir / "tmux").mkdir(exist_ok=True)

    export_path = traj_dir / "exports" / "conversation.json"
    tmux_log_path = traj_dir / "tmux" / "tmux_pipe.log"

    # devin cli命令
    devin_cmd = (
        f"devin --permission-mode {DEVIN_PERMISSION_MODE} "
        f"--respect-workspace-trust false "
        f"--model {DEVIN_MODEL} "
        f"--export {export_path} "
        f"-- '{DEVIN_PROMPT}'"
    )

    full_cmd = f"cd {work_dir} && {devin_cmd} 2>&1 | tee {tmux_log_path}"

    # 启动tmux session
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, full_cmd],
        capture_output=True, timeout=10,
    )

    return session_name


def launch_batch(batch_id, concurrency=DEFAULT_CONCURRENCY,
                 max_runtime=DEFAULT_MAX_RUNTIME_SECONDS,
                 stall_seconds=DEFAULT_STALL_SECONDS,
                 poll_seconds=DEFAULT_POLL_SECONDS):
    """并发启动一个批次的分析"""
    print(f"=== 启动分析批次 batch={batch_id} concurrency={concurrency} ===")

    # 加载prepared列表
    prepared_path = OUTPUT_BASE / batch_id / "prepared.json"
    if not prepared_path.exists():
        print(f"ERROR: prepared.json not found at {prepared_path}")
        print("请先运行 data_collector")
        return

    with open(str(prepared_path)) as f:
        prepared_data = json.load(f)
    prepared = prepared_data["prepared"]
    print(f"  待分析: {len(prepared)}")

    db = connect_db()
    ensure_schema(db)

    # 状态跟踪
    running = {}  # {analysis_exp_id: {session_name, work_dir, started_at, last_activity}}
    completed = []
    failed = []
    pending = list(prepared)

    print(f"  开始并发启动（concurrency={concurrency}）...")

    while pending or running:
        # 启动新的（填满并发槽）
        while pending and len(running) < concurrency:
            item = pending.pop(0)
            analysis_exp_id = item["analysis_exp_id"]
            work_dir = item["work_dir"]

            print(f"  [launch] {item['problem_id']}")
            session_name = launch_one(analysis_exp_id, work_dir)

            running[analysis_exp_id] = {
                "session_name": session_name,
                "work_dir": work_dir,
                "problem_id": item["problem_id"],
                "started_at": time.time(),
                "last_activity": time.time(),
                "last_pane_hash": "",
            }

            # 更新DB
            try:
                update_run(db, _run_key(item["problem_id"], batch_id), {
                    "status": "running",
                    "tmux_session": session_name,
                    "started_at": utc_now(),
                })
            except Exception:
                pass

            insert_event(db, batch_id, "analysis_launched", {
                "problem_id": item["problem_id"],
                "analysis_exp_id": analysis_exp_id,
                "tmux_session": session_name,
            })

            time.sleep(2)  # 避免同时启动太多

        # 检查运行中的
        to_remove = []
        for analysis_exp_id, info in running.items():
            session_name = info["session_name"]
            pane_text = tmux_pane_text(session_name)

            # 检测完成标记
            # 注意：ANALYSIS COMPLETE可能出现在prompt中（因为prompt包含"结尾输出 ### ANALYSIS COMPLETE"）
            # 只检测pane最后部分（agent输出区域），不检测prompt区域
            # agent输出在prompt之后——取pane最后200行，且去掉prompt行
            pane_lines = pane_text.split("\n")
            # 找最后一个prompt行（以❭开头或包含"请按AGENTS.md"）
            last_prompt_idx = -1
            for j, line in enumerate(pane_lines):
                if "请按AGENTS.md" in line or "❭" in line:
                    last_prompt_idx = j
            agent_output = "\n".join(pane_lines[last_prompt_idx+1:]) if last_prompt_idx >= 0 else pane_text
            # 完成标记：XML结束标签 或 ANALYSIS COMPLETE 或 "分析完成"
            is_complete = (
                XML_BLOCK_END in agent_output
                or ANALYSIS_COMPLETE_MARKER in agent_output
                or "分析完成" in agent_output
            )
            if is_complete:
                print(f"  [done] {info['problem_id']} — analysis complete")
                completed.append({
                    "problem_id": info["problem_id"],
                    "analysis_exp_id": analysis_exp_id,
                    "session_name": session_name,
                })
                to_remove.append(analysis_exp_id)
                # kill tmux session
                subprocess.run(["tmux", "kill-session", "-t", session_name],
                               capture_output=True, timeout=5)
                # 更新DB
                try:
                    update_run(db, _run_key(info["problem_id"], batch_id), {
                        "status": "completed",
                        "ended_at": utc_now(),
                    })
                except Exception:
                    pass
                continue

            # 检测stall/timeout
            elapsed = time.time() - info["started_at"]
            pane_hash = hash(pane_text[-500:])  # 只看最后500字符
            if pane_hash != info["last_pane_hash"]:
                info["last_pane_hash"] = pane_hash
                info["last_activity"] = time.time()
            idle = time.time() - info["last_activity"]

            is_running = tmux_running(session_name)

            if not is_running:
                # tmux session已结束（devin cli退出）
                print(f"  [done] {info['problem_id']} — session ended")
                completed.append({
                    "problem_id": info["problem_id"],
                    "analysis_exp_id": analysis_exp_id,
                    "session_name": session_name,
                })
                to_remove.append(analysis_exp_id)
                try:
                    update_run(db, _run_key(info["problem_id"], batch_id), {
                        "status": "completed",
                        "ended_at": utc_now(),
                    })
                except Exception:
                    pass
                continue

            if elapsed > max_runtime:
                print(f"  [timeout] {info['problem_id']} — {int(elapsed)}s")
                failed.append({
                    "problem_id": info["problem_id"],
                    "analysis_exp_id": analysis_exp_id,
                    "reason": "timeout",
                })
                to_remove.append(analysis_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name],
                               capture_output=True, timeout=5)
                try:
                    update_run(db, _run_key(info["problem_id"], batch_id), {
                        "status": "failed_timeout",
                        "ended_at": utc_now(),
                        "end_reason": "max_runtime_exceeded",
                    })
                except Exception:
                    pass
                continue

            if idle > stall_seconds:
                print(f"  [stall] {info['problem_id']} — idle {int(idle)}s")
                failed.append({
                    "problem_id": info["problem_id"],
                    "analysis_exp_id": analysis_exp_id,
                    "reason": "stall",
                })
                to_remove.append(analysis_exp_id)
                subprocess.run(["tmux", "kill-session", "-t", session_name],
                               capture_output=True, timeout=5)
                try:
                    update_run(db, _run_key(info["problem_id"], batch_id), {
                        "status": "failed_stall",
                        "ended_at": utc_now(),
                        "end_reason": "stall_detected",
                    })
                except Exception:
                    pass
                continue

        for key in to_remove:
            running.pop(key, None)

        # 状态报告
        if pending or running:
            print(f"  [status] running={len(running)} pending={len(pending)} "
                  f"completed={len(completed)} failed={len(failed)}")
            time.sleep(poll_seconds)

    print(f"\n=== 批次完成 ===")
    print(f"  completed: {len(completed)}")
    print(f"  failed: {len(failed)}")

    # 保存结果
    results_path = OUTPUT_BASE / batch_id / "launch_results.json"
    with open(str(results_path), "w") as f:
        json.dump({"completed": completed, "failed": failed}, f, ensure_ascii=False, indent=2)
    print(f"  结果保存到: {results_path}")


def status_batch(batch_id):
    """查看批次状态"""
    prepared_path = OUTPUT_BASE / batch_id / "prepared.json"
    results_path = OUTPUT_BASE / batch_id / "launch_results.json"

    prepared_count = 0
    if prepared_path.exists():
        with open(str(prepared_path)) as f:
            prepared_count = len(json.load(f)["prepared"])

    completed_count = 0
    failed_count = 0
    if results_path.exists():
        with open(str(results_path)) as f:
            results = json.load(f)
            completed_count = len(results["completed"])
            failed_count = len(results["failed"])

    # 检查运行中的tmux sessions
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    an_sessions = [l for l in result.stdout.split("\n") if l.startswith("an-")]

    print(f"批次: {batch_id}")
    print(f"  prepared: {prepared_count}")
    print(f"  completed: {completed_count}")
    print(f"  failed: {failed_count}")
    print(f"  running tmux sessions: {len(an_sessions)}")
    for s in an_sessions:
        print(f"    {s}")


def stop_batch(batch_id):
    """停止批次中所有运行中的tmux session"""
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    an_sessions = [l.split(":")[0] for l in result.stdout.split("\n") if l.startswith("an-")]
    for s in an_sessions:
        subprocess.run(["tmux", "kill-session", "-t", s], capture_output=True, timeout=5)
        print(f"  killed: {s}")
    print(f"  已停止 {len(an_sessions)} 个session")


def _run_key(problem_id, batch_id):
    """生成DB key"""
    return f"{problem_id.replace('_', '-')}-{batch_id}"


def main():
    parser = argparse.ArgumentParser(description="并发启动分析devin cli")
    parser.add_argument("--batch-id", required=True, help="批次ID")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="并发数")
    parser.add_argument("--max-runtime", type=int, default=DEFAULT_MAX_RUNTIME_SECONDS, help="最大运行时间（秒）")
    parser.add_argument("--stall-seconds", type=int, default=DEFAULT_STALL_SECONDS, help="stall判定时间（秒）")
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS, help="轮询间隔（秒）")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--stop", action="store_true", help="停止所有")
    args = parser.parse_args()

    if args.status:
        status_batch(args.batch_id)
    elif args.stop:
        stop_batch(args.batch_id)
    else:
        launch_batch(
            args.batch_id,
            concurrency=args.concurrency,
            max_runtime=args.max_runtime,
            stall_seconds=args.stall_seconds,
            poll_seconds=args.poll_seconds,
        )


if __name__ == "__main__":
    main()
