#!/usr/bin/env python3
"""continuation_control.py — POC-2.7续传Pipe控制工具

对齐solver_harness的pipe_control.py和错题分析系统的analysis_control.py：
  - start: 一键启动launcher+monitor（tmux session + auto-restart）
  - stop: 一键优雅停止（SIGINT等退出，不kill devin session）
  - stop --force: 强制停止（kill所有session+清空队列）
  - status: 查看状态
  - health: 健康检查
  - set-concurrency: 动态修改并发数

auto-restart机制：
  launcher和monitor都通过bash while循环包裹，退出后5秒自动重启。
  防止8天运行中因Redis断连、未处理异常等导致整个batch停滞。

用法:
  python -m monitoring.continuation_control start --batch-id p27-full --concurrency 1
  python -m monitoring.continuation_control stop
  python -m monitoring.continuation_control stop --force
  python -m monitoring.continuation_control status --batch-id p27-full
  python -m monitoring.continuation_control health --batch-id p27-full
  python -m monitoring.continuation_control set-concurrency --batch-id p27-full --concurrency 20
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# 路径设置
PROJECT_ROOT = Path(__file__).parent.parent  # repo根目录
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from monitoring.shared_logger import get_logger

logger = get_logger("continuation_control")

VENV_PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python3")
if not Path(VENV_PYTHON).exists():
    VENV_PYTHON = sys.executable

# session_registry导入（编号化管理）
from src.session_registry import (
    list_sessions as _list_sessions, clean_session as _clean_session,
    clean_done_sessions as _clean_done_sessions, consistency_check as _consistency_check,
    get_session as _get_session,
)
from src.continuation_db_schema import connect_db as _connect_db

# tmux session命名
LAUNCHER_SESSION = "p27-launcher"
MONITOR_SESSION = "monitor-p27"
WATCHDOG_SESSION = "p27-watchdog"

# launchd plist路径（如果用launchd自动启动watchdog）
WATCHDOG_PLIST = os.path.expanduser("~/Library/LaunchAgents/com.user.continuation-watchdog.plist")


# ============================================================
# 通用工具
# ============================================================

def tmux_running(name: str) -> bool:
    try:
        r = subprocess.run(
            ["tmux", "has-session", "-t", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


def list_p27_sessions():
    """列出所有p27-开头的tmux session（devin cli实例），排除服务session"""
    # 排除服务session——它们不是devin cli实例
    EXCLUDE = {LAUNCHER_SESSION, MONITOR_SESSION, WATCHDOG_SESSION}
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    sessions = []
    for line in result.stdout.strip().split("\n"):
        if line.startswith("p27-"):
            name = line.split(":")[0]
            if name not in EXCLUDE:
                sessions.append(name)
    return sessions


def get_pane_tail(session_name, lines=10):
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout
    except Exception:
        return ""


def stop_watchdog():
    """停止watchdog——必须同时处理tmux session和launchd plist

    核心问题：如果watchdog通过launchd自动启动，只kill tmux session不够——
    launchd会立即重启它。必须先launchctl unload+disable plist，再kill tmux session。

    launchctl unload只是从当前session移除——plist文件还在，下次系统重启或用户登录时
    launchd会自动重新加载。必须launchctl disable来永久禁用，这样即使系统重启也不会加载。

    反过来，如果只unload+disable plist但不kill tmux session，watchdog进程继续运行
    （只是不会被launchd重启）。所以三步都要做。
    """
    # 步骤1：卸载launchd plist（从当前session移除）
    if os.path.exists(WATCHDOG_PLIST):
        subprocess.run(["launchctl", "unload", WATCHDOG_PLIST],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        print(f"  [watchdog] launchd plist已卸载: {WATCHDOG_PLIST}")

        # 步骤2：永久禁用——即使系统重启也不会自动加载
        # service identifier是plist文件名（去掉.plist）
        service_id = os.path.basename(WATCHDOG_PLIST).replace(".plist", "")
        subprocess.run(["launchctl", "disable", f"gui/$(id -u)/{service_id}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        print(f"  [watchdog] launchd服务已永久禁用: {service_id}")

    # 步骤3：kill tmux session（如果存在）
    if tmux_running(WATCHDOG_SESSION):
        subprocess.run(["tmux", "kill-session", "-t", WATCHDOG_SESSION],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        print(f"  [watchdog] tmux session已kill: {WATCHDOG_SESSION}")
    elif not os.path.exists(WATCHDOG_PLIST):
        print(f"  [watchdog] 未运行（无tmux session，无launchd plist）")


# ============================================================
# 服务启停（对齐solver_harness的pipe_control.py）
# ============================================================

def start_service(name: str, script_cmd: str, session_name: str, auto_restart: bool = True):
    """启动一个服务到tmux session

    auto_restart=True: 用bash while循环包裹，服务退出后自动重启（等5秒）。
    """
    if tmux_running(session_name):
        print(f"  [{name}] 已在运行, 跳过")
        return

    if auto_restart:
        full_cmd = (
            f'while true; do {script_cmd} 2>&1; '
            f'echo "[auto-restart] {name}退出, 5秒后重启..."; '
            f'sleep 5; done'
        )
    else:
        full_cmd = script_cmd + " 2>&1"

    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, full_cmd],
        check=False, timeout=10
    )
    print(f"  [{name}] 启动 → tmux:{session_name}" + (" (auto-restart)" if auto_restart else ""))


def stop_service(name: str, session_name: str, graceful: bool = True, timeout: int = 15):
    """停止一个服务

    graceful=True: 发送SIGINT让服务优雅退出（launcher收到后不再启动新run，等running自然完成）
    graceful=False: 直接kill-session（强制停止）
    """
    if not tmux_running(session_name):
        print(f"  [{name}] 未运行")
        return

    if graceful:
        subprocess.run(["tmux", "send-keys", "-t", session_name, "C-c", ""],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        print(f"  [{name}] 发送SIGINT, 等待优雅退出...")

        # launcher的优雅退出可能需要较长时间（等running自然完成）
        # 先等timeout秒，如果还没退出就提示用户
        for i in range(timeout):
            time.sleep(1)
            if not tmux_running(session_name):
                print(f"  [{name}] 已优雅退出 (等待{i+1}s)")
                return

        print(f"  [{name}] 优雅退出超时({timeout}s)")
        print(f"    launcher可能还在等running自然完成——这是正常的")
        print(f"    如需强制停止: python -m monitoring.continuation_control stop --force")
    else:
        subprocess.run(["tmux", "kill-session", "-t", session_name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        print(f"  [{name}] 已强制停止")


# ============================================================
# start
# ============================================================

def cmd_start(args):
    """一键启动续传系统（launcher + monitor，都带auto-restart）"""
    # WP-G：并发数不写默认值——未传参则透传 None，由 launcher 执行
    # "DB 无记录且未传参报错退出"的硬约束（DB 有记录时 launcher 用 DB 值）
    conc_arg = (f"--concurrency {args.concurrency} "
                if args.concurrency is not None else "")
    conc_arg_monitor = (f"--concurrency {args.concurrency} "
                        if args.concurrency is not None else "")
    print(f"=== 启动POC-2.7续传系统 (batch={args.batch_id}, "
          f"concurrency={args.concurrency if args.concurrency is not None else '从DB读取'}) ===\n")

    # 前置检查
    # Redis
    try:
        from src.continuation_redis_queue import ping as redis_ping
        if not redis_ping():
            print("  ❌ Redis连接失败，请先启动Redis容器")
            return
        print("  ✅ Redis连接正常")
    except Exception as e:
        print(f"  ❌ Redis检查失败: {e}")
        return

    # ArangoDB
    try:
        from src.continuation_db_schema import connect_db
        db = connect_db()
        print("  ✅ ArangoDB连接正常")
    except Exception as e:
        print(f"  ❌ ArangoDB连接失败: {e}")
        return

    print()

    # 启动launcher（auto-restart）
    launcher_cmd = (
        f"cd {PROJECT_ROOT} && {VENV_PYTHON} -m src.continuation_launcher "
        f"--batch-id {args.batch_id} "
        f"{conc_arg}"
        f"--max-rounds {args.max_rounds} "
        f"--method {args.method}"
    )
    start_service("launcher", launcher_cmd, LAUNCHER_SESSION, auto_restart=True)

    # 启动Monitor Pipe（auto-restart）
    time.sleep(2)
    monitor_cmd = (
        f"cd {PROJECT_ROOT} && {VENV_PYTHON} -m src.monitor_continuation "
        f"--batch-id {args.batch_id} "
        f"--interval {args.monitor_interval} "
        f"{conc_arg_monitor.rstrip()}".rstrip()
    )
    start_service("monitor", monitor_cmd, MONITOR_SESSION, auto_restart=True)

    print(f"\n所有服务已启动。")
    print(f"  查看状态: python -m monitoring.continuation_control status --batch-id {args.batch_id}")
    print(f"  优雅停止: python -m monitoring.continuation_control stop")
    print(f"  强制停止: python -m monitoring.continuation_control stop --force")


# ============================================================
# stop
# ============================================================

def cmd_stop(args):
    """停止续传系统"""
    print("=== 停止POC-2.7续传系统 ===\n")

    # ★ 第0步：必须先停watchdog——否则它会重启刚停掉的服务
    # 核心问题：watchdog通过launchd自动启动时，只kill服务tmux session不够——
    # watchdog会30秒内重启它们。必须先停watchdog（unload plist + kill session）。
    stop_watchdog()

    if args.force:
        # 强制模式：停服务 + 分类处理devin cli session + 清空队列
        stop_service("launcher", LAUNCHER_SESSION, graceful=False)
        stop_service("monitor", MONITOR_SESSION, graceful=False)

        # ★ 分类处理devin cli session（见specs §A.5）★
        # done状态的可以安全kill（export已落盘）
        # stuck/running状态的不kill（devin cli可能正在写export）
        try:
            db = _connect_db()
            # 清理done的
            result = _clean_done_sessions(db)
            if result["cleaned"] > 0:
                print(f"  清理 {result['cleaned']}个done session（安全，export已落盘）")

            # stuck和running的不kill——提示用户
            stuck_sessions = _list_sessions(db, status="stuck", limit=100)
            running_sessions = _list_sessions(db, status="running", limit=100)
            if stuck_sessions:
                print(f"  ⚠️ {len(stuck_sessions)}个stuck session未清理（需用户授意）")
                for s in stuck_sessions[:5]:
                    print(f"     {s['_key']} ({s['session_name']}) — 清理: continuation_control sessions --clean {s['_key']}")
                if len(stuck_sessions) > 5:
                    print(f"     ... 还有{len(stuck_sessions)-5}个")
            if running_sessions:
                print(f"  ⚠️ {len(running_sessions)}个running session未清理（devin cli可能正在写export）")
                for s in running_sessions[:5]:
                    print(f"     {s['_key']} ({s['session_name']}) — 等DONE.md出现后清理")
                if len(running_sessions) > 5:
                    print(f"     ... 还有{len(running_sessions)-5}个")
        except Exception as e:
            # 如果DB查询失败，回退到旧行为——kill所有p27- session
            print(f"  ⚠️ DB查询失败({e})，回退到旧行为——kill所有p27- session")
            p27_sessions = list_p27_sessions()
            for s in p27_sessions:
                subprocess.run(["tmux", "kill-session", "-t", s],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            print(f"  kill {len(p27_sessions)}个p27- devin session")

        # 清空Redis队列
        try:
            from src.continuation_redis_queue import get_redis, clear_all
            r = get_redis()
            clear_all(r)
            print(f"  Redis队列已清空")
        except Exception as e:
            print(f"  Redis清空失败: {e}")

        print("\n所有服务已强制停止。")
        print("  注意：stuck/running session未kill——等DONE.md后用 sessions --clean 清理")
    else:
        # 优雅模式：发送SIGINT，不kill devin session
        stop_service("launcher", LAUNCHER_SESSION, graceful=True, timeout=15)
        stop_service("monitor", MONITOR_SESSION, graceful=True, timeout=10)

        p27_sessions = list_p27_sessions()
        print(f"\n  p27- devin session: {len(p27_sessions)}个（继续独立运行，不kill）")
        print(f"  launcher收到SIGINT后不再启动新run，等running自然完成")
        print(f"  如需强制停止: python -m monitoring.continuation_control stop --force")


# ============================================================
# status
# ============================================================

def cmd_status(args):
    """查看状态"""
    print("=== POC-2.7续传系统状态 ===\n")

    # 服务状态
    services = [
        ("launcher", LAUNCHER_SESSION),
        ("monitor", MONITOR_SESSION),
        ("watchdog", WATCHDOG_SESSION),
    ]
    for name, sess in services:
        running = tmux_running(sess)
        status = "✅ 运行中" if running else "❌ 未运行"
        print(f"  {name:12s} {status}")
        if running:
            pane = get_pane_tail(sess, lines=3)
            last_line = ""
            for line in pane.split("\n"):
                if line.strip() and "Guide Devin" not in line:
                    last_line = line.strip()[:80]
            if last_line:
                print(f"    └─ {last_line}")

    print()

    # p27- devin session数
    p27_sessions = list_p27_sessions()
    print(f"  p27- devin session: {len(p27_sessions)}个")

    # Redis队列状态
    try:
        from src.continuation_redis_queue import (
            get_redis, pending_count, update_stats, get_stats
        )
        r = get_redis()
        update_stats(r)
        stats = get_stats(r)
        print(f"\n  Redis队列:")
        print(f"    pending:   {stats.get('pending', 0)}")
        print(f"    running:   {stats.get('running', 0)}")
        print(f"    completed: {stats.get('completed', 0)}")
        print(f"    failed:    {stats.get('failed', 0)}")
    except Exception as e:
        print(f"\n  Redis查询失败: {e}")

    # DB进度
    if args.batch_id:
        try:
            from src.continuation_db_schema import connect_db
            from src.continuation_config import CONTINUATION_RUNS_COLLECTION
            db = connect_db()
            aql = (
                f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
                f"FILTER run.batch_id == @bid "
                f"COLLECT status = run.status WITH COUNT INTO c "
                f"SORT c DESC RETURN {{status, count: c}}"
            )
            cursor = db.aql.execute(aql, bind_vars={"bid": args.batch_id}, ttl=60)
            print(f"\n  DB进度 (batch={args.batch_id}):")
            for row in cursor:
                print(f"    {row['status']:20s} {row['count']}")
        except Exception as e:
            print(f"\n  DB查询失败: {e}")


# ============================================================
# health
# ============================================================

def cmd_health(args):
    """健康检查"""
    print("=== POC-2.7续传系统健康检查 ===\n")

    issues = []

    # 1. 服务存活
    launcher_running = tmux_running(LAUNCHER_SESSION)
    monitor_running = tmux_running(MONITOR_SESSION)
    watchdog_running = tmux_running(WATCHDOG_SESSION)
    plist_loaded = os.path.exists(WATCHDOG_PLIST)
    print(f"【1. 服务存活】")
    print(f"  launcher: {'✅' if launcher_running else '❌'}")
    print(f"  monitor:  {'✅' if monitor_running else '❌'}")
    print(f"  watchdog: {'✅' if watchdog_running else '❌'} (launchd plist: {'loaded' if plist_loaded else 'not loaded'})")
    if not launcher_running:
        issues.append("launcher未运行")
    if not monitor_running:
        issues.append("monitor未运行")
    # watchdog状态不作为issue——它可选

    # 2. 并发量
    print(f"\n【2. 并发量】")
    p27_sessions = list_p27_sessions()
    try:
        from src.continuation_redis_queue import get_redis
        from src.continuation_redis_queue import pending_count
        r = get_redis()
        running_count = r.hlen("p27:running") if hasattr(r, 'hlen') else 0
        print(f"  p27- devin session: {len(p27_sessions)}")
        print(f"  Redis running:      {running_count}")
        if abs(len(p27_sessions) - running_count) > 2:
            issues.append(f"session数({len(p27_sessions)})与Redis running({running_count})不一致")
    except Exception as e:
        print(f"  Redis查询失败: {e}")

    # 3. DB进度
    if args.batch_id:
        print(f"\n【3. DB进度 (batch={args.batch_id})】")
        try:
            from src.continuation_db_schema import connect_db
            from src.continuation_config import CONTINUATION_RUNS_COLLECTION
            db = connect_db()
            aql = (
                f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
                f"FILTER run.batch_id == @bid "
                f"COLLECT status = run.status WITH COUNT INTO c "
                f"SORT c DESC RETURN {{status, count: c}}"
            )
            cursor = db.aql.execute(aql, bind_vars={"bid": args.batch_id}, ttl=60)
            total = 0
            for row in cursor:
                print(f"  {row['status']:20s} {row['count']}")
                total += row['count']
            print(f"  {'total':20s} {total}")
        except Exception as e:
            print(f"  DB查询失败: {e}")

    # 4. Monitor Pipe的alert
    print(f"\n【4. Monitor Pipe alert】")
    try:
        from src.continuation_db_schema import connect_db
        from src.continuation_config import MONITOR_ALERTS_COLLECTION
        db = connect_db()
        aql = (
            f"FOR a IN {MONITOR_ALERTS_COLLECTION} "
            f"FILTER a.batch_id == @bid "
            f"FILTER a.status != 'resolved' "
            f"COLLECT severity = a.severity WITH COUNT INTO c "
            f"RETURN {{severity: severity, count: c}}"
        )
        cursor = db.aql.execute(aql, bind_vars={"bid": args.batch_id}, ttl=60)
        has_alerts = False
        for row in cursor:
            print(f"  {row['severity']:10s} {row['count']}")
            has_alerts = True
            if row['severity'] == 'critical':
                issues.append(f"{row['count']}个critical alert")
        if not has_alerts:
            print(f"  无未解决alert ✅")
    except Exception as e:
        print(f"  alert查询失败: {e}")

    # 总结
    print(f"\n{'='*50}")
    if issues:
        print(f"  发现{len(issues)}个问题:")
        for i, issue in enumerate(issues, 1):
            print(f"    {i}. {issue}")
    else:
        print(f"  ✅ 所有检查通过")


# ============================================================
# set-concurrency
# ============================================================

def cmd_set_concurrency(args):
    """动态修改并发数——launcher下次poll时生效"""
    from src.continuation_db_schema import connect_db
    from src.continuation_config import CONTINUATION_BATCHES_COLLECTION

    db = connect_db()
    doc = db.collection(CONTINUATION_BATCHES_COLLECTION).get(args.batch_id)
    if not doc:
        print(f"  ❌ batch {args.batch_id} 不存在")
        return

    old = doc.get("concurrency", "?")
    db.collection(CONTINUATION_BATCHES_COLLECTION).update(
        {"_key": args.batch_id, "concurrency": args.concurrency}
    )
    print(f"  并发数: {old} → {args.concurrency}")
    print(f"  launcher会在下次poll时自动读取新值（通常{args.poll_seconds or 30}秒内生效）")
    print(f"  当前running不会受影响——只影响后续新启动的run")


# ============================================================
# sessions（编号化管理——见specs/p27_session_management_and_polish_spec.md §A.6）
# ============================================================

def cmd_sessions(args):
    """查看/清理/检查session注册表"""
    db = _connect_db()

    if args.consistency_check:
        print("=== Session一致性检查 ===\n")
        cc = _consistency_check(db)
        print(f"注册表中有 {cc['registered_count']} 个session，tmux中有 {cc['tmux_count']} 个session\n")

        if cc["orphaned_in_registry"]:
            print("注册表有但tmux无（已自然退出，需标记cleaned或检查崩溃）：")
            for s in cc["orphaned_in_registry"]:
                status_tag = "done" if s["done_md"] else "⚠️ stuck无DONE.md"
                print(f"  {s['key']} ({s['session_name']}) status={s['status']} {status_tag}")
            print()
        else:
            print("注册表有但tmux无：无\n")

        if cc["unregistered_in_tmux"]:
            print("tmux有但注册表无（孤儿session，需人工检查）：")
            for name in cc["unregistered_in_tmux"]:
                print(f"  {name}")
            print()
        else:
            print("tmux有但注册表无：无\n")

        if not cc["orphaned_in_registry"] and not cc["unregistered_in_tmux"]:
            print("✅ 注册表和tmux一致")
        return

    if args.clean_done:
        print("=== 批量清理done状态的session ===\n")
        result = _clean_done_sessions(db)
        print(f"  清理 {result['cleaned']} 个，失败 {result['failed']} 个")
        for d in result["details"][:10]:
            print(f"    {d}")
        if len(result["details"]) > 10:
            print(f"    ... 还有{len(result['details'])-10}个")
        return

    if args.clean:
        print(f"=== 清理session {args.clean} ===\n")
        s = _get_session(db, args.clean)
        if not s:
            print(f"  ❌ session {args.clean} 不存在")
            return
        print(f"  session: {s['session_name']}")
        print(f"  status: {s['status']}")
        print(f"  done_md: {s.get('done_md', False)}")
        if s["status"] not in ("done", "stuck"):
            print(f"  ❌ 状态为{s['status']}，不能清理（只有done/stuck可清理）")
            return
        if _clean_session(db, args.clean):
            print(f"  ✅ 已清理")
        else:
            print(f"  ❌ 清理失败")
        return

    # 默认：列出session
    print("=== Session注册表 ===\n")
    sessions = _list_sessions(db,
                              batch_id=args.batch_id,
                              status=args.status,
                              session_type=args.type,
                              limit=args.limit or 50)
    if not sessions:
        print("  无session记录")
        return

    print(f"共 {len(sessions)} 个session（按seq降序）：\n")
    print(f"{'key':<16} {'type':<14} {'status':<10} {'done':<5} {'session_name':<50} {'started_at'}")
    print("-" * 120)
    for s in sessions:
        done = "✓" if s.get("done_md") else " "
        name = s["session_name"][:50]
        started = s.get("started_at", "")[:19]
        print(f"{s['_key']:<16} {s['type']:<14} {s['status']:<10} {done:<5} {name:<50} {started}")


# ============================================================
# resolve-alert / mark-ai-review（SOP_03/04/06 操作支撑）
# ============================================================

def cmd_resolve_alert(args):
    """标记 alert 为 resolved——SOP_06 §4 操作支撑。

    用法：
      python -m monitoring.continuation_control resolve-alert <alert_key>
      python -m monitoring.continuation_control resolve-alert --all-critical  # 批量resolve所有critical
    """
    from src.continuation_config import MONITOR_ALERTS_COLLECTION
    from datetime import datetime, timezone

    db = _connect_db()
    col = db.collection(MONITOR_ALERTS_COLLECTION)
    now = datetime.now(timezone.utc).isoformat()

    if args.all_critical:
        # 批量 resolve 所有未处理的 critical alert
        aql = (
            f"FOR a IN {MONITOR_ALERTS_COLLECTION} "
            f"FILTER a.status != 'resolved' "
            f"FILTER a.severity == 'critical' "
            f"RETURN a._key"
        )
        keys = list(db.aql.execute(aql, ttl=60))
        if not keys:
            print("无未处理的 critical alert")
            return
        for k in keys:
            col.update({"_key": k, "status": "resolved", "resolved_at": now})
        print(f"已批量 resolve {len(keys)} 个 critical alert: {keys}")
        return

    if not args.alert_key:
        print("用法: resolve-alert <alert_key> 或 --all-critical")
        return

    doc = col.get(args.alert_key)
    if not doc:
        print(f"⚠️ alert 不存在: {args.alert_key}")
        return
    col.update({"_key": args.alert_key, "status": "resolved", "resolved_at": now})
    print(f"✅ 已 resolve alert: {args.alert_key}（原 severity={doc.get('severity')} type={doc.get('alert_type')}）")


def cmd_mark_ai_review(args):
    """标记 run 的 AI 判断完成+结果——SOP_04 §4 操作支撑。

    用法：
      python -m monitoring.continuation_control mark-ai-review <run_key> --result PASS
      python -m monitoring.continuation_control mark-ai-review <run_key> --result FAIL --note "C2幻觉"
    """
    from src.continuation_config import CONTINUATION_RUNS_COLLECTION

    db = _connect_db()
    col = db.collection(CONTINUATION_RUNS_COLLECTION)

    doc = col.get(args.run_key)
    if not doc:
        print(f"⚠️ run 不存在: {args.run_key}")
        return

    update = {
        "_key": args.run_key,
        "ai_review_done": True,
        "ai_review_result": args.result,
    }
    if args.note:
        update["ai_review_note"] = args.note

    col.update(update)
    print(f"✅ 已标记 {args.run_key}: ai_review_done=True result={args.result}")
    if args.note:
        print(f"   note: {args.note}")


# ============================================================
# main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="POC-2.7续传Pipe控制工具")
    sub = parser.add_subparsers(dest="action")

    # start
    p_start = sub.add_parser("start", help="一键启动launcher+monitor（带auto-restart）")
    p_start.add_argument("--batch-id", required=True, help="批次ID")
    p_start.add_argument("--concurrency", type=int, default=None,
                         help="并发数（不传则 launcher 从 DB batch 读；DB 也无则报错退出）")
    p_start.add_argument("--max-rounds", type=int, default=5, help="最大续传轮次")
    p_start.add_argument("--method", choices=["v1", "v2"], default="v2", help="续传方案")
    p_start.add_argument("--monitor-interval", type=int, default=120, help="Monitor Pipe检查间隔（秒）")
    p_start.set_defaults(func=cmd_start)

    # stop
    p_stop = sub.add_parser("stop", help="停止续传系统")
    p_stop.add_argument("--force", action="store_true", help="强制停止（kill所有session+清空队列）")
    p_stop.set_defaults(func=cmd_stop)

    # status
    p_status = sub.add_parser("status", help="查看状态")
    p_status.add_argument("--batch-id", help="批次ID（显示DB进度）")
    p_status.set_defaults(func=cmd_status)

    # health
    p_health = sub.add_parser("health", help="健康检查")
    p_health.add_argument("--batch-id", help="批次ID")
    p_health.set_defaults(func=cmd_health)

    # set-concurrency
    p_setc = sub.add_parser("set-concurrency", help="动态修改并发数")
    p_setc.add_argument("--batch-id", required=True, help="批次ID")
    p_setc.add_argument("--concurrency", type=int, required=True, help="新并发数")
    p_setc.add_argument("--poll-seconds", type=int, default=15, help="launcher的poll间隔（用于提示生效时间；launcher默认DEFAULT_POLL_SECONDS=15）")
    p_setc.set_defaults(func=cmd_set_concurrency)

    # sessions（编号化管理）
    p_sess = sub.add_parser("sessions", help="查看/清理/检查session注册表")
    p_sess.add_argument("--batch-id", help="按批次过滤")
    p_sess.add_argument("--status", choices=["running", "done", "stuck", "cleaned"], help="按状态过滤")
    p_sess.add_argument("--type", choices=["solve", "handover", "monitor_exec"], help="按类型过滤")
    p_sess.add_argument("--limit", type=int, default=50, help="最多返回多少条")
    p_sess.add_argument("--clean", help="清理特定session（需用户授意，只清理done/stuck状态）")
    p_sess.add_argument("--clean-done", action="store_true", help="批量清理所有done状态的session（安全操作）")
    p_sess.add_argument("--consistency-check", action="store_true", help="注册表 vs tmux一致性检查")
    p_sess.set_defaults(func=cmd_sessions)

    # resolve-alert（SOP_06 §4 操作支撑）
    p_ra = sub.add_parser("resolve-alert", help="标记alert为resolved（SOP_06操作支撑）")
    p_ra.add_argument("alert_key", nargs="?", help="alert的_key")
    p_ra.add_argument("--all-critical", action="store_true", help="批量resolve所有未处理的critical alert")
    p_ra.set_defaults(func=cmd_resolve_alert)

    # mark-ai-review（SOP_04 §4 操作支撑）
    p_mai = sub.add_parser("mark-ai-review", help="标记run的AI判断完成+结果（SOP_04操作支撑）")
    p_mai.add_argument("run_key", help="run的_key")
    p_mai.add_argument("--result", required=True, choices=["PASS", "FAIL"], help="判断结果")
    p_mai.add_argument("--note", help="判断备注（如C2幻觉/C4缺章节）")
    p_mai.set_defaults(func=cmd_mark_ai_review)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
