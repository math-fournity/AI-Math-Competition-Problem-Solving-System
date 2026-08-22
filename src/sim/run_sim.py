"""run_sim.py — 全流程模拟编排器（sim的入口）

一个命令跑完一个剧本的完整生命周期：
  setup（造批次）→ 真feeder入队 → 真launcher调度 → 等全部run终态
  → 终态断言 → 清场（--keep保留现场）

被测系统（launcher/feeder/门闸/注册表/Redis队列/判定逻辑）100%原代码
真跑——本编排器只做三件事：设置隔离环境、以子进程启动真组件、验收。

隔离环境（四层，与生产可并行）：
  ARANGO_DB=p27sim（独立库）  P27_REDIS_PREFIX=p27sim:（独立键空间）
  SOLVER_BASE/TRAJECTORY_BASE=<repo>/tmp/sim/（独立文件根）
  SIM_MODE=1（launcher的devin命令换成fake_devin）

用法：
  python -m src.sim.run_sim --scenario solve3           # 跑完即清（留DB和文件）
  python -m src.sim.run_sim --scenario solve3 --keep    # 保留现场排查
  python -m src.sim.run_sim --scenario chaos_016 --timeout 600
"""
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def setup_sim_env(extra=None):
    """在当前进程设置隔离环境。必须在import任何src模块之前调用。"""
    env = {
        "SIM_MODE": "1",
        "ARANGO_DB": "p27sim",
        "P27_REDIS_PREFIX": "p27sim:",
        "SOLVER_BASE": str(PROJECT_ROOT / "tmp" / "sim" / "solver"),
        "TRAJECTORY_BASE": str(PROJECT_ROOT / "tmp" / "sim" / "traj"),
    }
    if extra:
        env.update(extra)
    for k, v in env.items():
        os.environ[k] = v
    return env


def wait_all_settled(batch_id, run_keys, timeout):
    """轮询DB等全部run结束本次调度（含非永久window_exhausted）。"""
    from src.continuation_config import CONTINUATION_RUNS_COLLECTION
    from src.continuation_db_schema import connect_db
    db = connect_db()
    runs = db.collection(CONTINUATION_RUNS_COLLECTION)
    deadline = time.time() + timeout
    while time.time() < deadline:
        pending = 0
        for rk in run_keys:
            doc = runs.get(rk) or {}
            if doc.get("final_status") is None and doc.get("status") not in (
                    "window_exhausted", "ai_gave_up", "dead_session",
                    "failed_stall", "failed_timeout", "unknown_state",
                    "launch_error", "rate_limited", "failed_connection"):
                pending += 1
        if pending == 0:
            return True
        time.sleep(3)
    return False


def main():
    ap = argparse.ArgumentParser(description="全流程模拟编排器")
    ap.add_argument("--scenario", required=True, help="剧本名（见src/sim/scenarios.py）")
    ap.add_argument("--runs", type=int, default=None, help="覆盖剧本默认题数")
    ap.add_argument("--timeout", type=int, default=300, help="等终态的超时秒数")
    ap.add_argument("--poll-seconds", type=int, default=2, help="launcher轮询间隔")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--keep", action="store_true", help="保留现场（不teardown）")
    ap.add_argument("--purge-db", action="store_true", help="teardown时连DB一起删")
    ap.add_argument("--purge-files", action="store_true", help="teardown时连文件一起删")
    ap.add_argument("--batch-id", default=None, help="指定batch_id（默认自动生成）")
    args = ap.parse_args()

    # 1. 隔离环境——必须在import src之前
    from src.sim import scenarios as sim_scenarios
    sc = sim_scenarios.get(args.scenario)
    extra = {}
    if sc.get("stall_seconds"):
        pass  # stall通过launcher命令行参数传
    if sc.get("handover_timeout_seconds"):
        extra["HANDOVER_TIMEOUT_SECONDS"] = str(sc["handover_timeout_seconds"])
    env = setup_sim_env(extra)
    # 子进程继承隔离环境
    child_env = os.environ.copy()

    # 延迟import（环境已就位）
    from src.sim.setup import build_batch
    from src.sim.assert_final import run_assertions
    from src.sim.teardown import teardown

    batch_id = args.batch_id or (
        "p27sim-" + args.scenario + "-" + time.strftime("%Y%m%d-%H%M%S"))
    print(f"=== 全流程模拟 ===")
    print(f"  剧本: {args.scenario} — {sc['description']}")
    print(f"  batch: {batch_id}")
    print(f"  隔离: ARANGO_DB={env['ARANGO_DB']} REDIS前缀={env['P27_REDIS_PREFIX']}")

    ok = False          # 是否全部run到达终态
    exit_code = 1       # 断言结果

    # 2. setup造批次
    run_keys = build_batch(batch_id, args.scenario, args.runs)

    launcher_log_dir = PROJECT_ROOT / "tmp" / "sim"
    launcher_log_dir.mkdir(parents=True, exist_ok=True)

    try:
        windows = int(sc.get("windows", 1))
        ok = True
        for window_no in range(1, windows + 1):
            # 3. 真feeder入队
            print(f"\n--- feeder（真代码，窗口{window_no}/{windows}） ---")
            feed = subprocess.run(
                [sys.executable, "-m", "src.continuation_feeder", "--batch-id", batch_id],
                capture_output=True, text=True, timeout=120, env=child_env,
                cwd=str(PROJECT_ROOT))
            print(feed.stdout.strip() or feed.stderr.strip()[:500])

            # 4. 真launcher调度（SIGINT优雅停止）
            launcher_log = launcher_log_dir / f"{batch_id}-w{window_no}-launcher.log"
            print("\n--- launcher（真代码，SIM_MODE=1）---")
            print(f"  日志: {launcher_log}")
            launcher_cmd = [
                sys.executable, "-m", "src.continuation_launcher",
                "--batch-id", batch_id,
                "--concurrency", str(args.concurrency),
                "--round-window-size", str(sc.get("round_window_size", 5)),
                "--poll-seconds", str(args.poll_seconds),
            ]
            if sc.get("stall_seconds"):
                launcher_cmd += ["--stall-seconds", str(sc["stall_seconds"])]
            with open(launcher_log, "w") as lf:
                launcher = subprocess.Popen(
                    launcher_cmd, stdout=lf, stderr=subprocess.STDOUT,
                    env=child_env, cwd=str(PROJECT_ROOT),
                    start_new_session=True)

            # 5. 等全部run结束本次窗口
            print(f"--- 等待窗口收场（timeout={args.timeout}s）---", flush=True)
            window_ok = wait_all_settled(batch_id, run_keys, args.timeout)
            ok = ok and window_ok
            if not window_ok:
                print("❌ 超时：部分run未结束本次窗口。tail launcher日志：")
                tail = launcher_log.read_text().splitlines()[-15:]
                print("\n".join("  " + l for l in tail))

            # 6. 停launcher（SIGINT优雅）+ 等退出
            if launcher.poll() is None:
                launcher.send_signal(signal.SIGINT)
                try:
                    launcher.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    launcher.kill()
                    print("  ⚠️ launcher未在30秒内退出，已kill")

            if window_no < windows:
                # sim显式开启下一窗口：只调用与生产管理脚本相同的纯字段函数；
                # 实际入队仍由下一轮真feeder完成。
                from src.continuation_db_schema import connect_db, update_run
                from src.continuation_config import CONTINUATION_RUNS_COLLECTION
                from src.round_window import resume_window_fields
                db = connect_db()
                runs = db.collection(CONTINUATION_RUNS_COLLECTION)
                for rk in run_keys:
                    doc = runs.get(rk) or {}
                    if doc.get("status") != "window_exhausted":
                        raise RuntimeError(
                            f"{rk}: 中间窗口期望window_exhausted，实际{doc.get('status')}")
                    update_run(db, rk, resume_window_fields(
                        doc, reason=f"sim_window_{window_no + 1}"))
                print(f"  [sim] 已显式开启窗口{window_no + 1}，下一轮feeder将入队")

        # 7. 最终断言
        exit_code = run_assertions(batch_id, run_keys, sc)

    finally:
        # 8. 清场
        if args.keep:
            print(f"\n[run_sim] --keep：现场保留（DB/Redis/文件/tmux未清理）")
            print(f"[run_sim] 手动清场: python -m src.sim.teardown --batch-id {batch_id}")
        else:
            print(f"\n--- teardown ---")
            teardown(batch_id, purge_db=args.purge_db, purge_files=args.purge_files)

    sys.exit(0 if (ok and exit_code == 0) else 1)


if __name__ == "__main__":
    main()
