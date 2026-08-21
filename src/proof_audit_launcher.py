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
    AUDIT_MAX_RUNTIME_SECONDS,
    AUDIT_STALL_SECONDS, AUDIT_POLL_SECONDS,
    AUDIT_COMPLETE_MARKER, AUDIT_TMUX_PREFIX,
    GATE_AUDIT_LAUNCH, GATE_AUDIT_KILL_SESSION,
)
from src.continuation_config import CONTINUATION_BATCHES_COLLECTION
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
# WP-I 共享检测模块（WP-J 消费）
from src.devin_cli_failure_detection import (
    RATE_LIMIT_PATTERNS, CONNECTION_PATTERNS, TOKEN_LIMIT_PATTERNS,
    match_patterns, check_ai_gave_up, classify_failure,
)

logger = get_logger("proof_audit_launcher")

# rate_limit 全局暂停时间戳（WP-J，照抄续传 rate_limit_paused_until 模式）
audit_rate_paused_until = 0

# kill 策略两类（WP-J 设计决策，单测断言用）：
#   rate_limited / failed_connection —— 不 kill：devin 可能自恢复（对齐续传
#     "标记不kill"哲学），session 留观；rate_limited 另触发全局暂停 20 分钟
#   ai_gave_up / failed_token_limit —— kill：模型不会再产出有效结果
KILL_POLICY = {
    "rate_limited": False,
    "failed_connection": False,
    "ai_gave_up": True,
    "failed_token_limit": True,
}


def tail_file(path, nbytes=5120):
    """读文件末尾 n 字节（errors=ignore）——pane scrollback 会滚走早期错误，
    pipe log 尾部是更稳的错误模式数据源。路径不存在返回空串。"""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            return f.read().decode(errors="ignore")
    except Exception:
        return ""


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
    """【门闸: GATE-AUDIT-LAUNCH】启动一个审计 devin cli。

    这个函数做什么：
    - 用 tmux 启动一个 devin -p 子进程跑审计 prompt（proof.txt 为输入）；
    - 建立 tmux 日志管道（pipe-pane 实时落盘）；
    - 返回 session_name。

    为什么追踪这个动作：
    - 启动即消耗 GLM-5.2 API 配额、创建 session；
    - 审计是选题池的准入门槛——审计通过=进入选题池，审计失败=排除；
    - 028 教训：DB 有 proof_text ≠ 文件在——启动前必须直接验证输入实物。

    放行前 Master Agent 应检查并论证：
    【检查项】（每项含查法+正常值）
    1. proof.txt 存在且非空，且与 DB 一致 → 查法：ls work_dir/proof.txt && wc -c > 0，
       且前 200 字符与 DB audit_run.proof_text 抽样一致。正常值=一致。
       （028 教训：DB 有文本≠文件在——直接检查两者）
    2. AGENTS.md 模板渲染正确 → 查法：grep -c "{problem_text}" work_dir/AGENTS.md
       等占位符应为 0（未替换 = 模板 bug，审计 AI 会收到骨架）
    3. 并发未超限 → 查法：redis-cli HLEN paudit:running < 并发数；并发数来源 =
       p27_continuation_batches.{batch_id}.concurrency（WP-G 后无写死默认）
    4. 该 audit_run 无活跃 session → 查法：tmux list-sessions |
       grep <audit_run_key 后 30 字符> 应无结果

    【论证依据——放行/不放行判定】
    放行/不放行：1✓+2✓+3✓+4✓ 全过则放行。理由：审计输入真实存在且与 DB 一致、
       模板正确、并发受控、无重复启动——启动不会白耗配额也不会重复审计。
    不可放行：1✗（proof.txt 缺失或与 DB 不一致）→ 028 重现（审计无输入或审的是
       旧文本）；2✗（占位符未替换）→ 审计 AI 收到模板骨架，产出必然 PARSE_ERROR；
       3✗ → 并发失控（rate limit 风险）；4✗ → 重复启动浪费配额且状态互相污染。

    系统正常运行表现：paudit:pending 持续下降 + running ≤ 并发数 + 每个审计约
    3-10 分钟完成；异常时：pending 不降（launcher 没 dequeue——先查 launcher 进程
    是否存活）/ 审计秒退（devin 启动失败——capture-pane 查报错）→ 交 SOP_07 处理。
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
    """【门闸: GATE-AUDIT-KILL-SESSION】kill 该审计的 tmux session（不可逆清理）。

    这个函数做什么：
    - kill 该审计的 tmux session——devin cli 退出后 session 因命令尾部的
      sleep 999999 设计仍存活，kill 是正常清理动作（非杀死工作中的进程）。

    为什么追踪这个动作：
    - kill 直接终止 tmux 会话不可逆；
    - E1 语义澄清：DONE.md 存在 = devin cli 已退出，**≠ 审计成功**——审计成败
      要看 p27_proof_audits.audit_status（result_collector 解析 export 后写入）。

    放行前 Master Agent 应检查并论证：
    【检查项】（每项含查法+正常值）
    1. **completed 的真实语义提醒**：DONE.md 存在只证明 devin cli 已退出，
       ≠ 审计成功——审计成败查 p27_proof_audits.audit_status
    2. 完成标记存在 → 查法：ls exports/DONE.md 存在；或 grep export 文件含
       "### PROOF AUDIT COMPLETE"。正常值=任一存在
    3. session 确属该 audit_run → 查法：session 名 = "paudit-" +
       audit_run_key 后 30 字符（映射规则）。正常值=名字匹配
    4. kill 前 export 已落盘非空 → 查法：stat -f%z export 路径 > 1000。
       正常值=有实质内容

    【论证依据——放行/不放行判定】
    放行/不放行：2✓+3✓+4✓ 全过则放行（检查项 1 是语义提醒非放行条件）。
    理由：devin 已退出、session 归属正确、产出已落盘——清理不丢结果。
    不可放行：无 DONE.md 且 reason 非 dead_session → 违反"绝不 kill 无 DONE.md
    session"铁律；export 空 → 审计产出未落盘就 kill = 结果丢失。

    系统正常运行表现：completed 后 kill 干净、tmux 无 paudit- 残留 session；
    异常时：paudit session 堆积 = 孤儿（launcher 死了无人 kill）→ SOP_07 孤儿
    对账发现后人工清理（每个先验证 DONE.md 再 kill）。
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


# （WP-J）原死代码检测函数已整体删除——031 B5：定义后从未被调用；
# 无活动检测按 034/036 裁定不做（审计任务短，max_runtime 兜底 + SOP 巡检足够）。


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


def detect_terminal_verdict(detect_text):
    """审计终态判定辅助（WP-J，模块级便于单测）。

    输入：pane 文本 + pipe log 尾部的合并文本。
    返回 verdict 或 None。检测顺序（先环境性，续传同序）：
      rate_limited → failed_connection → failed_token_limit → ai_gave_up
    """
    for name, patterns in (("rate_limited", RATE_LIMIT_PATTERNS),
                           ("failed_connection", CONNECTION_PATTERNS),
                           ("failed_token_limit", TOKEN_LIMIT_PATTERNS)):
        if match_patterns(detect_text, patterns):
            return name
    if check_ai_gave_up(detect_text):
        return "ai_gave_up"
    return None


def launch_batch(batch_id, concurrency=None,
                 max_runtime=AUDIT_MAX_RUNTIME_SECONDS,
                 stall_seconds=AUDIT_STALL_SECONDS,
                 poll_seconds=AUDIT_POLL_SECONDS):
    """并发启动审计批次"""
    print(f"=== 启动审计批次 batch={batch_id} ===")
    log_event(logger, "info", "audit_batch_start", batch_id=batch_id)

    # 优雅停止注册（WP-H，graceful-shutdown.md §6 清单第 2 步）
    register_shutdown("proof_audit_launcher")

    db = connect_db()
    ensure_schema(db)

    # 并发数治理（WP-G，AGENTS.md 硬约束落地）：DB batch 记录是唯一权威。
    # 审计批次与续传批次同集合（p27_continuation_batches）——set-concurrency
    # 命令直接可用。DB 有则不覆盖；显式传参则初始化 DB；两者皆无则报错退出。
    batches = db.collection(CONTINUATION_BATCHES_COLLECTION)
    existing_batch = batches.get(batch_id)
    if existing_batch and "concurrency" in existing_batch:
        concurrency = existing_batch["concurrency"]
        print(f"  并发数: {concurrency}（从 DB batch 记录读取）")
    elif concurrency is not None:
        print(f"  并发数: {concurrency}（命令行显式传入，初始化 DB batch 记录）")
    else:
        print("并发数未设置：DB batch 记录无 concurrency 字段且未传 --concurrency。"
              "请先 python -m monitoring.continuation_control set-concurrency "
              f"--batch-id {batch_id} --concurrency N")
        log_event(logger, "error", "concurrency_not_set", batch_id=batch_id)
        return

    # 初始化/刷新批次记录（get-or-create——审计批次此前不在该集合）
    now = utc_now()
    try:
        if existing_batch:
            batches.update({"_key": batch_id, "status": "auditing",
                            "concurrency": concurrency, "updated_at": now})
        else:
            batches.insert({"_key": batch_id, "batch_id": batch_id,
                            "status": "auditing", "concurrency": concurrency,
                            "created_at": now, "updated_at": now})
            log_event(logger, "info", "audit_batch_record_created",
                      batch_id=batch_id, concurrency=concurrency)
    except Exception as e:
        # 批次记录写失败不阻塞启动（并发数已定），但留痕
        log_event(logger, "warning", "batch_record_update_failed",
                  batch_id=batch_id, error=str(e))

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

        # 动态并发（WP-G）——从DB读取batch.concurrency，支持运行中通过set-concurrency调整
        try:
            batch_doc = batches.get(batch_id)
            if batch_doc and "concurrency" in batch_doc:
                db_concurrency = batch_doc["concurrency"]
                if db_concurrency != concurrency:
                    print(f"  [concurrency] 并发数调整: {concurrency} → {db_concurrency}（从DB读取）")
                    log_event(logger, "info", "concurrency_adjusted",
                              batch_id=batch_id, old=concurrency, new=db_concurrency)
                    concurrency = db_concurrency
        except Exception:
            # DB读取失败时保持当前concurrency，不让DB故障导致launcher崩溃
            pass

        # rate_limit 全局暂停检查（WP-J，照抄续传 rate_limit_paused_until 模式）
        now_ts = time.time()
        if audit_rate_paused_until > now_ts:
            remaining = int(audit_rate_paused_until - now_ts)
            if remaining % 60 == 0:
                print(f"  [rate_limit_pause] 等待 rate limit 恢复，剩余 {remaining}s...")
            time.sleep(poll_seconds)
            continue
        elif audit_rate_paused_until > 0:
            print(f"  [rate_limit_pause] 恢复运行")
            audit_rate_paused_until = 0

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

        # 补充并发——从 pending 取出填到并发数（优雅停止/限流暂停模式下跳过）
        while (not should_stop() and audit_rate_paused_until <= time.time()
               and current_running < concurrency and current_pending > 0):
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

            # 加入 running（WP-J：tmux_pipe_path 供错误模式检测读尾部）
            add_running(r, audit_run_key, {
                "session_name": session_name,
                "work_dir": str(work_dir),
                "export_path": export_path,
                "tmux_pipe_path": str(Path(export_path).parent.parent / "tmux" / "tmux_pipe.log"),
                "started_at": time.time(),
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

            # 错误模式检测（WP-J）——在 session 还活着时做（pane 是活 session 的）。
            # 数据源：pane 300 行 + pipe log 尾部 5KB 合并（早期错误可能滚出 scrollback）。
            # 检测顺序：rate_limit → connection → token_limit（先环境性，续传同序）
            #           → ai_gave_up。命中即按 KILL_POLICY 两类处置。
            pane_text = tmux_pane_text(session_name, lines=300)
            detect_text = pane_text + tail_file(meta.get("tmux_pipe_path", ""), 5120)
            verdict = detect_terminal_verdict(detect_text)

            if verdict:
                failure_category = classify_failure(verdict)
                add_failed(r, {"audit_run_key": audit_run_key, "reason": verdict})
                update_audit_run(db, audit_run_key, {
                    "status": "failed",
                    "error_message": verdict,
                    "failure_category": failure_category,
                    "ended_at": utc_now(),
                })
                remove_running(r, audit_run_key)
                log_event(logger, "warning", "audit_terminal_state",
                          audit_run_key=audit_run_key, verdict=verdict,
                          failure_category=failure_category)

                if KILL_POLICY.get(verdict, True):
                    # ai_gave_up / failed_token_limit：模型不会再产出——kill（过门闸）
                    audit_kill_session(session_name, audit_run_key, reason=verdict)
                    print(f"  [{verdict}] {audit_run_key} 已 kill 并标记失败"
                          f"（category={failure_category}）")
                else:
                    # rate_limited / failed_connection：不 kill，session 留观
                    # （devin 可能自恢复；对齐续传"标记不kill"哲学）
                    print(f"  [{verdict}] {audit_run_key} 标记失败，session 留观不 kill"
                          f"（category={failure_category}）")

                if verdict == "rate_limited":
                    # rate_limit 全局暂停 20 分钟（照抄续传模式）
                    pause_until = time.time() + 1200
                    if pause_until > audit_rate_paused_until:
                        audit_rate_paused_until = pause_until
                        print(f"  [rate_limit_pause] 暂停 20 分钟...")

                failed_count += 1
                continue

            # 检查 session 消失
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

            # 检查超时（WP-J 语义修正：这是总时长超时，旧命名名不副实已废弃）
            if time.time() - started_at > max_runtime:
                audit_kill_session(session_name, audit_run_key, reason="max_runtime_exceeded")
                remove_running(r, audit_run_key)
                add_failed(r, {
                    "audit_run_key": audit_run_key,
                    "reason": "max_runtime_exceeded",
                })
                update_audit_run(db, audit_run_key, {
                    "status": "failed",
                    "error_message": "max_runtime_exceeded",
                    "failure_category": classify_failure("max_runtime_exceeded"),
                    "ended_at": utc_now(),
                })
                log_event(logger, "warning", "audit_terminal_state",
                          audit_run_key=audit_run_key, verdict="max_runtime_exceeded",
                          failure_category=classify_failure("max_runtime_exceeded"))
                failed_count += 1
                print(f"  [fail-timeout] {audit_run_key}（超过 max_runtime={max_runtime}s）")

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
    parser.add_argument("--concurrency", type=int, default=None,
                        help="并发数（不传则用 DB batch 记录；两者皆无则报错退出）")
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
