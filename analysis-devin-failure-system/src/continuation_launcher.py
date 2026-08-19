"""continuation_launcher.py — POC-2.7续传Pipe并发启动组件

复用analysis_launcher.py的架构模式（stall/rate_limit/zombie检测），
适配POC-2.7的多轮续传逻辑。

核心差异（vs analysis_launcher）：
  1. 多轮续传——每道题最多max_rounds轮，每轮检测截断/完成
  2. v2方案双pipe——每轮先Pipe A生成HANDOVER.md，再Pipe B解题
  3. 完成判定——proof.md存在且有boxed答案（不是XML标记）
  4. 更长timeout——续传单轮可能thinking spin很久（30分钟 vs 分析5分钟）

用法：
  python -m src.continuation_launcher --batch-id p27-full --concurrency 5 --max-rounds 5 --method v2
  python -m src.continuation_launcher --status --batch-id p27-full
  python -m src.continuation_launcher --stop --batch-id p27-full
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
from src.continuation_config import (
    CONTINUATION_SOLVER_BASE, CONTINUATION_TRAJECTORY_BASE,
    D_TRAJ_DIR, MAPPER_SCRIPT, CONTINUE_SPEC,
    DEVIN_MODEL, DEVIN_PERMISSION_MODE,
    DEFAULT_CONCURRENCY, DEFAULT_MAX_RUNTIME_SECONDS,
    DEFAULT_STALL_SECONDS, DEFAULT_POLL_SECONDS, DEFAULT_MAX_ROUNDS,
    TRUNC_COMP_TOKENS_MIN, PROOF_COMPLETE_MARKER, PROOF_FILE_NAME,
    RATE_LIMIT_PATTERNS, CONNECTION_PATTERNS,
    INFRA_FAILURES, MAX_RETRIES,
    CONTINUATION_RUNS_COLLECTION, CONTINUATION_BATCHES_COLLECTION,
    TMUX_PREFIX,
)
from src.continuation_db_schema import (
    connect_db, ensure_schema, update_run, update_batch, insert_event, make_verdict,
)
from src.session_registry import (
    allocate_seq, create_session_record, make_session_name as _make_session_name,
    update_session_status as _update_session_status,
    get_session as _get_session, mark_stuck as _mark_stuck,
    check_done_md as _check_done_md,
)
from src.continuation_redis_queue import (
    get_redis, enqueue_pending, dequeue_pending,
    add_running, remove_running, add_completed, add_failed,
    update_stats, get_stats, clear_all, pending_count,
)
from monitoring.shared_logger import get_logger
from monitoring.graceful_shutdown import register_shutdown, should_stop

logger = get_logger("continuation_launcher")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def classify_failure(failure_type: str) -> str:
    """区分基础设施失败和模型能力失败

    基础设施失败（infra）——可重试：rate_limited/failed_connection/launch_error/dead_session
    模型能力失败（model）——不可重试，是数据：failed_timeout/failed_stall/failed_no_proof/truncated_at_max

    参考：xishujuzhen/solver_harness/pipe/retry_infrastructure.py
    """
    if failure_type in INFRA_FAILURES:
        return "infra"
    return "model"


# =============================================================================
# tmux操作（复用analysis_launcher的模式）
# =============================================================================

def tmux_session_name(run_key, round_num, is_handover=False, seq=None):
    """生成tmux session名

    如果传了seq（编号化管理），生成编号格式：
      p27-s{seq:04d}-solve-{short}-r{round}  或
      p27-s{seq:04d}-handover-{short}-r{round}

    如果没传seq（向后兼容），用旧格式：
      p27-{short}-r{round}[-h]
    """
    short = run_key[-40:] if len(run_key) > 40 else run_key
    if seq is not None:
        # 编号化管理格式
        session_type = "handover" if is_handover else "solve"
        suffix = f"{short}-r{round_num}"
        return f"p27-s{seq:04d}-{session_type}-{suffix}"
    else:
        # 旧格式（向后兼容）
        suffix = "-h" if is_handover else ""
        return f"{TMUX_PREFIX}-{short}-r{round_num}{suffix}"


def tmux_running(session_name):
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True, timeout=5,
    )
    return result.returncode == 0


def tmux_pane_text(session_name, lines=500):
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout
    except Exception:
        return ""


def tmux_kill(session_name):
    subprocess.run(["tmux", "kill-session", "-t", session_name],
                   capture_output=True, timeout=5)


# =============================================================================
# 截断检测与reasoning提取（复用batch_continue_948.py的逻辑）
# =============================================================================

def make_round_log_entry(round_num, export_path, truncated, completed, reason,
                         info, archived_proof_path=None):
    """构造rounds_log的一条完整记录——包含所有中间产物路径

    确保每轮的所有中间产物路径都存入DB，不会被后续round覆盖。
    """
    entry = {
        "round": round_num,
        "export": export_path,
        "truncated": truncated,
        "completed": completed,
        "reason": reason,
    }
    # 从running dict的round_metadata中补充中间产物路径
    metadata = info.get("round_metadata", {}) if info else {}
    if metadata:
        entry["method"] = metadata.get("method", "")
        entry["handover_success"] = metadata.get("handover_success", False)
        entry["handover_path"] = metadata.get("handover_path", "")
        entry["map_path"] = metadata.get("map_path", "")
        entry["prompt_path"] = metadata.get("prompt_path", "")
        entry["prev_export"] = metadata.get("prev_export", "")
    # 归档的proof路径（每轮独立，不会被覆盖）
    if archived_proof_path:
        entry["proof_path"] = archived_proof_path
    return entry


def is_truncated(export_path):
    """检测export是否被截断"""
    if not os.path.exists(export_path):
        return False, "no export file"
    with open(export_path) as f:
        d = json.load(f)
    steps = [s for s in d.get("steps", []) if s.get("source") == "agent"]
    if not steps:
        return False, "no agent step"
    last = steps[-1]
    rc = len(last.get("reasoning_content", "") or "")
    msg = len(last.get("message", "") or "")
    tc = len(last.get("tool_calls", []) or [])
    comp = (last.get("metrics", {}) or {}).get("completion_tokens", 0)
    if rc > 1000 and msg == 0 and tc == 0 and comp >= TRUNC_COMP_TOKENS_MIN:
        return True, f"rc={rc}c, msg=0, tc=0, comp={comp}"
    if msg > 0 or tc > 0:
        return False, f"completed: rc={rc}c, msg={msg}c, tc={tc}, comp={comp}"
    return False, f"unknown: rc={rc}c, msg={msg}c, tc={tc}, comp={comp}"


def is_completed(export_path, work_dir):
    """检测export是否已完成——proof.md存在且有boxed答案"""
    # 检查export的agent step是否有message/tool_call输出
    if os.path.exists(export_path):
        with open(export_path) as f:
            d = json.load(f)
        steps = [s for s in d.get("steps", []) if s.get("source") == "agent"]
        if steps:
            last = steps[-1]
            msg = len(last.get("message", "") or "")
            tc = len(last.get("tool_calls", []) or [])
            if msg > 0 or tc > 0:
                # 有输出——必须检查proof.md存在且有boxed答案
                proof_path = Path(work_dir) / PROOF_FILE_NAME
                if proof_path.exists():
                    proof_text = proof_path.read_text()
                    if re.search(PROOF_COMPLETE_MARKER, proof_text):
                        return True, f"proof.md有boxed答案 ({len(proof_text)}c)"
                    return False, f"proof.md存在但无boxed ({len(proof_text)}c)"
                # 有message输出但无proof.md——不能判定为completed，需要继续续传
                return False, "有message输出但无proof.md"
    return False, "no working output"


def extract_reasoning(export_path):
    """从export提取所有agent step的reasoning_content"""
    if not os.path.exists(export_path):
        return ""
    with open(export_path) as f:
        d = json.load(f)
    parts = []
    for s in d.get("steps", []):
        if s.get("source") == "agent":
            rc = str(s.get("reasoning_content", "") or "")
            if rc:
                parts.append(rc)
    return "\n\n".join(parts)


# =============================================================================
# prompt构造（复用batch_continue_948.py的模板）
# =============================================================================

HANDOVER_PROMPT_TEMPLATE = """你的任务：为{pid}的round{round_num} conversation.json编写HANDOVER.md交接文档。

## 背景

这道题的round{round_num}思考过程被截断了，需要编写交接文档供下一轮AI继续。

## 你需要读取的文件

1. **面包屑地图**：{map_path}
2. **conversation.json**：{export_path}
3. **续传规范文档**：{spec_path}
4. **题目文本**：
{problem_text}

## 工作流程

1. 先读取面包屑地图，了解conversation.json的整体结构
2. 读取续传规范文档，了解HANDOVER.md的8个章节要求
3. 按地图的面包屑，逐个agent step处理
4. 按HANDOVER.md的8个章节整理提取的内容
5. 将HANDOVER.md写入：{handover_path}

## HANDOVER.md的8个章节（参考续传规范文档）

1. **题目**：完整的数学题目
2. **当前状态**：已完成/截断/错误
3. **已确认的结论**：AI在thinking中得出的数学结论
4. **已排除的方向**：AI尝试过但失败的方向
5. **关键文献/参考**：AI引用的文献或定理
6. **已有的中间产物**：AI创建的文件、计算结果
7. **当前卡在哪里**：如果是截断，AI在思考什么时被截断
8. **下一步建议**：如何继续

## 重要约束

- **不要编造内容**——所有内容必须来自conversation.json
- **保留数学公式**——LaTeX格式保留
- **标注来源**：每个结论标注来自哪个step
- **包含工具调用结果**：exec的observation必须包含在HANDOVER.md中
"""


CONTINUE_PROMPT_TEMPLATE = """{original_problem}

=== 你之前的思考过程（Round {prev_round}，被截断）===

你已经在上一轮中开始了这道题的思考，但因为输出长度限制，思考过程被截断了。
以下是你之前的完整思考过程，请仔细阅读，在此基础上**继续**思考并完成解答（不要从头开始）：

{previous_reasoning}

=== 请继续思考并完成解答 ===

要求：
1. **在之前的思考基础上继续**，不要重复已经做过的分析
2. 给出完整的解答过程
3. 最终答案用 \\boxed{{答案}} 格式给出
4. 数学公式用LaTeX
5. 把证明写到proof.md文件中，不要在对话里输出完整证明
"""


INITIAL_PROMPT_TEMPLATE = """{original_problem}

请解答上面的数学题。

要求：
1. 给出完整的解答过程
2. 最终答案用 \\boxed{{答案}} 格式给出
3. 数学公式用LaTeX
4. 把证明写到proof.md文件中，不要在对话里输出完整证明
"""


def build_continue_prompt(original_problem, previous_reasoning, prev_round):
    return CONTINUE_PROMPT_TEMPLATE.format(
        original_problem=original_problem,
        previous_reasoning=previous_reasoning,
        prev_round=prev_round,
    )


def build_v2_continue_prompt(original_problem, handover_path, prev_round):
    """v2方案：用HANDOVER.md作为续传prompt"""
    handover_content = Path(handover_path).read_text()
    return f"""{original_problem}

=== 你之前的探索历程（Round 1-{prev_round}，交接文档）===

你已经在之前的{prev_round}轮中开始了这道题的探索。以下是前一轮AI编写的交接文档，
总结了之前的思考过程、已确认的结论、已排除的方向和当前卡点。请仔细阅读，在此基础上**继续**完成解答。

{handover_content}

=== 请继续思考并完成解答 ===

根据交接文档中的"下一步建议"，继续完成这道题的解答。

要求：
1. **在之前的探索基础上继续**，不要重复已经做过的分析
2. 给出完整的解答过程
3. 最终答案用 \\boxed{{答案}} 格式给出
4. 数学公式用LaTeX
5. 把证明写到proof.md文件中，不要在对话里输出完整证明
"""


# =============================================================================
# v2方案Pipe A：生成HANDOVER.md
# =============================================================================

def generate_handover(export_path, pid, round_num, problem_text, work_dir, model=DEVIN_MODEL):
    """v2方案Pipe A：生成面包屑地图 + 用devin -p编写HANDOVER.md（同步版本，保留兼容）

    返回HANDOVER.md的路径，或None（失败时）。
    """
    hinfo = start_handover(export_path, pid, round_num, problem_text, work_dir, model)
    if hinfo is None:
        return None
    # 同步等待完成
    handover_timeout = 600
    start_time = time.time()
    while time.time() - start_time < handover_timeout:
        result = check_handover(hinfo, pid)
        if result is not None:
            return result
        time.sleep(10)
    # 超时
    tmux_kill(hinfo["session_name"])
    print(f"  [{pid}] Pipe A超时({handover_timeout}s)，强制kill")
    return None


def start_handover(export_path, pid, round_num, problem_text, work_dir, model=DEVIN_MODEL,
                   db=None, batch_id=None):
    """v2方案Pipe A的异步启动——生成面包屑地图 + 启动devin cli，立即返回

    返回handover信息dict（含session_name/session_key和路径），或None（启动失败时）。
    主循环通过check_handover()检查是否完成。

    如果传了db，使用编号化管理（allocate_seq + create_session_record）。
    """
    export_path = str(export_path)
    work_dir = Path(work_dir)

    map_path = work_dir / f"round{round_num}_conversation_map.md"
    handover_path = work_dir / f"round{round_num}_HANDOVER.md"
    handover_run_dir = work_dir / f"round{round_num}_handover_run"
    handover_run_dir.mkdir(parents=True, exist_ok=True)
    handover_export = handover_run_dir / "conversation.json"

    # Step 1: 生成面包屑地图
    if not MAPPER_SCRIPT.exists():
        print(f"  [{pid}] 错误：conversation_mapper.py不存在: {MAPPER_SCRIPT}")
        return None

    mapper_cmd = [sys.executable, str(MAPPER_SCRIPT), export_path, "-o", str(map_path)]
    result = subprocess.run(mapper_cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"  [{pid}] 地图生成失败: {result.stderr[:200]}")
        return None

    if not map_path.exists():
        print(f"  [{pid}] 地图文件未生成: {map_path}")
        return None

    # Step 2: 构造Pipe A的prompt
    prompt_text = HANDOVER_PROMPT_TEMPLATE.format(
        pid=pid,
        round_num=round_num,
        map_path=map_path,
        export_path=export_path,
        spec_path=CONTINUE_SPEC,
        problem_text=problem_text[:2000],
        handover_path=handover_path,
    )

    prompt_file = work_dir / f"round{round_num}_handover_prompt.txt"
    prompt_file.write_text(prompt_text)

    # Step 3: 分配seq + 创建注册表记录（编号化管理）
    session_key = None
    if db is not None:
        seq = allocate_seq(db)
        short = pid[-40:] if len(pid) > 40 else pid
        tmux_sess = _make_session_name(seq, "handover", f"{short}-r{round_num}")
        session_key = f"p27-s{seq:04d}"
        tmux_kill(tmux_sess)  # 清理同名session（正常不会撞名，因为seq唯一）
        create_session_record(db, seq, tmux_sess, "handover",
                              batch_id or "p27-full",
                              run_key=pid, round=round_num,
                              export_path=str(handover_export),
                              work_dir=str(work_dir))
    else:
        # 向后兼容——旧格式
        tmux_sess = tmux_session_name(pid, round_num, is_handover=True)
        tmux_kill(tmux_sess)

    # Step 4: 启动devin -p编写HANDOVER.md（不等完成，立即返回）
    cmd = [
        "devin", "-p",
        "--prompt-file", str(prompt_file),
        "--model", model,
        "--respect-workspace-trust", "false",
        "--permission-mode", DEVIN_PERMISSION_MODE,
        "--export", str(handover_export),
    ]
    tmux_cmd = " ".join(cmd)
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", tmux_sess,
         f"cd {work_dir} && {tmux_cmd}"],
        capture_output=True, timeout=10,
    )

    return {
        "session_name": tmux_sess,
        "session_key": session_key,  # 编号化管理的key（如p27-s0042）
        "handover_path": handover_path,
        "map_path": map_path,
        "prompt_file": prompt_file,
        "started_at": time.time(),
    }


def check_handover(hinfo, pid):
    """检查handover devin cli是否完成

    返回handover_path字符串（成功）、""字符串（失败，需回退v1）或None（还在运行中）。
    """
    sess = hinfo["session_name"]
    handover_path = hinfo["handover_path"]

    if tmux_running(sess):
        return None  # 还在运行

    # devin cli已退出——检查结果
    if not handover_path.exists():
        print(f"  [{pid}] Pipe A完成但HANDOVER.md未生成")
        return ""  # 失败，需回退v1

    handover_size = handover_path.stat().st_size
    if handover_size < 500:
        print(f"  [{pid}] Pipe A生成的HANDOVER.md太小({handover_size}c)，可能不完整")
        return ""  # 失败，需回退v1

    return str(handover_path)  # 成功


# =============================================================================
# 启动单个devin cli（Pipe B解题）
# =============================================================================

def launch_solve(run_key, work_dir, prompt_file, export_path, round_num, pid,
                 db=None, batch_id=None):
    """启动一个devin cli续传实例（Pipe B解题）

    如果传了db，使用编号化管理（allocate_seq + create_session_record）。
    返回 (session_name, session_key) 元组——session_key在编号化管理时为"p27-s{seq}"，
    向后兼容时为None。
    """
    # 分配seq + 创建注册表记录（编号化管理）
    session_key = None
    if db is not None:
        seq = allocate_seq(db)
        short = run_key[-40:] if len(run_key) > 40 else run_key
        session_name = _make_session_name(seq, "solve", f"{short}-r{round_num}")
        session_key = f"p27-s{seq:04d}"
        tmux_kill(session_name)  # 清理同名session（正常不会撞名）
    else:
        session_name = tmux_session_name(run_key, round_num)
        tmux_kill(session_name)

    traj_dir = Path(export_path).parent.parent
    tmux_log_path = traj_dir / "tmux" / "tmux.log"
    tmux_pipe_path = traj_dir / "tmux" / "tmux_pipe.log"
    tmux_log_path.parent.mkdir(parents=True, exist_ok=True)

    # DONE.md标记文件——devin cli退出后写入exit code，launcher通过文件存在性检测退出
    done_marker = Path(export_path).parent / "DONE.md"
    if done_marker.exists():
        done_marker.unlink()  # 清理上一轮的DONE.md

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

    full_cmd = f"cd {work_dir} && {devin_cmd} 2>&1 | tee {tmux_log_path}"
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, full_cmd],
        capture_output=True, timeout=10,
    )
    subprocess.run(
        ["tmux", "pipe-pane", "-t", session_name, f"cat >> {tmux_pipe_path}"],
        capture_output=True, timeout=5,
    )

    # 创建注册表记录
    if db is not None and session_key:
        create_session_record(db, seq, session_name, "solve",
                              batch_id or "p27-full",
                              run_key=run_key, round=round_num,
                              export_path=str(export_path),
                              work_dir=str(work_dir),
                              tmux_log_path=str(tmux_log_path))

    return session_name, session_key


# =============================================================================
# 并发批量续传（核心——复用analysis_launcher的stall/rate_limit/zombie模式）
# =============================================================================

def launch_batch(batch_id, concurrency=DEFAULT_CONCURRENCY,
                 max_rounds=DEFAULT_MAX_ROUNDS,
                 max_runtime=DEFAULT_MAX_RUNTIME_SECONDS,
                 stall_seconds=DEFAULT_STALL_SECONDS,
                 poll_seconds=DEFAULT_POLL_SECONDS,
                 method="v2"):
    """并发启动续传批次。

    复用analysis_launcher.py的架构：
      - Redis队列调度（dequeue_pending取题）
      - 动态并发（从DB读取batch.concurrency）
      - stall检测（pane_hash变化+idle时间）
      - rate_limit检测（RATE_LIMIT_PATTERNS匹配+自动暂停）
      - zombie session清理（完成后kill-session）
      - dead_session检测（session退出但无完成标记）

    新增：多轮续传逻辑（每道题最多max_rounds轮）
    """
    logger.info(f"启动续传批次 batch={batch_id} concurrency={concurrency} method={method}")
    print(f"=== 启动续传批次 batch={batch_id} concurrency={concurrency} method={method} ===")

    # 注册优雅退出——SIGTERM/SIGINT只设flag，不kill devin session
    register_shutdown("continuation_launcher")

    db = connect_db()
    ensure_schema(db)

    # 连接Redis
    try:
        r = get_redis()
        r.ping()
    except Exception as e:
        print(f"  Redis连接失败: {e}")
        return

    # 更新batch状态
    update_batch(db, batch_id, {
        "status": "launching",
        "updated_at": utc_now(),
        "concurrency": concurrency,
        "method": method,
        "max_rounds": max_rounds,
    })

    pending_in_redis = pending_count(r)
    if pending_in_redis == 0:
        # 检查DB中是否有prepared的题
        aql = (
            f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
            f"FILTER run.batch_id == @bid "
            f"FILTER run.status IN ['prepared', 'pending_retry'] "
            f"COLLECT WITH COUNT INTO c RETURN c"
        )
        cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
        db_pending = list(cursor)[0] if cursor.batch else 0
        if db_pending > 0:
            print(f"  Redis pending为空, 但DB中有{db_pending}个待续传run")
            print(f"  请先运行feeder: python -m src.continuation_feeder --batch-id {batch_id}")
            return
        else:
            print(f"  无待续传任务")
            return

    print(f"  Redis pending: {pending_in_redis}个任务待启动")

    # 状态跟踪
    running = {}  # {run_key: {session_name, work_dir, pid, round_num, ...}}——解题devin cli
    handover_pending = {}  # {run_key: {hinfo, pid, work_dir, ...}}——handover生成中，占并发槽（与running合计不超过concurrency）
    completed = []
    failed = []
    rate_limit_paused_until = 0

    print(f"  开始并发续传（concurrency={concurrency}, max_rounds={max_rounds}, method={method}）...")

    while True:
        # 退出条件
        if not running and pending_count(r) == 0:
            break

        # 优雅退出检查——收到SIGTERM/SIGINT后不再启动新run，等running自然完成
        if should_stop():
            if not running:
                print(f"  [graceful_shutdown] running已全部完成，launcher退出")
                break
            else:
                print(f"  [graceful_shutdown] 不再启动新run，等待{len(running)}个running自然完成...")
                # 继续轮询running状态，但不dequeue新任务
                time.sleep(poll_seconds)
                # 跳过下面的"启动新的"部分，只做running状态检查
                # （fall through到running状态检查逻辑）
        # rate_limit暂停检查
        now_ts = time.time()
        if rate_limit_paused_until > now_ts:
            remaining = int(rate_limit_paused_until - now_ts)
            if remaining % 60 == 0:
                print(f"  [rate_limit_pause] 等待rate limit恢复，剩余{remaining}s...")
            time.sleep(poll_seconds)
            continue
        elif rate_limit_paused_until > 0 and rate_limit_paused_until <= now_ts:
            print(f"  [rate_limit_pause] 恢复运行")
            rate_limit_paused_until = 0

        # 并发数写死为5——不从DB动态读取，避免外部修改导致并发失控
        # concurrency参数已在函数入口固定，此处不再动态调整

        # === 检查handover_pending中的run——handover生成完成后启动解题 ===
        handover_done = []
        for h_run_key, hinfo in list(handover_pending.items()):
            result = check_handover(hinfo["hinfo"], hinfo["pid"])
            if result is None:
                # 还在运行——检查超时
                if time.time() - hinfo["hinfo"]["started_at"] > 600:
                    print(f"  [handover_timeout] {hinfo['pid']} R{hinfo['round_num']}")
                    tmux_kill(hinfo["hinfo"]["session_name"])
                    result = ""  # 视为失败，回退v1
                else:
                    continue

            # handover完成（成功或失败）——构造prompt并启动解题
            pid = hinfo["pid"]
            work_dir = hinfo["work_dir"]
            problem_text = hinfo["problem_text"]
            round_num = hinfo["round_num"]
            prev_export = hinfo["prev_export"]
            existing_rounds = hinfo["existing_rounds"]
            run_doc = hinfo["run_doc"]

            round_handover_path = ""
            round_handover_success = False
            if result:  # 成功——v2方案
                round_handover_path = result
                round_handover_success = True
                prompt_text = build_v2_continue_prompt(problem_text, result, round_num - 1)
            else:  # 失败——回退v1
                if round_num == 2:
                    prev_rc = extract_reasoning(prev_export)
                else:
                    prev_rc = "\n\n".join(
                        extract_reasoning(r.get("export", ""))
                        for r in existing_rounds if r.get("export")
                    )
                prompt_text = build_continue_prompt(problem_text, prev_rc, round_num - 1)

            # 写prompt文件
            prompt_file = Path(work_dir) / f"round{round_num}_prompt.txt"
            prompt_file.write_text(prompt_text)

            # 清理旧round的proof.md
            old_proof = Path(work_dir) / PROOF_FILE_NAME
            if old_proof.exists():
                old_proof.unlink()
                logger.info(f"[{pid}] 清理旧proof.md（启动R{round_num}前）")

            # 准备export路径
            round_traj_dir = CONTINUATION_TRAJECTORY_BASE / h_run_key / f"round{round_num}"
            round_traj_dir.mkdir(parents=True, exist_ok=True)
            (round_traj_dir / "exports").mkdir(exist_ok=True)
            (round_traj_dir / "tmux").mkdir(exist_ok=True)
            export_path = round_traj_dir / "exports" / "conversation.json"

            round_metadata = {
                "method": method,
                "handover_success": round_handover_success,
                "handover_path": round_handover_path,
                "map_path": str(Path(work_dir) / f"round{round_num - 1}_conversation_map.md") if round_handover_success else "",
                "prompt_path": str(prompt_file),
                "prev_export": prev_export,
            }

            # 启动解题devin cli
            print(f"  [launch] {pid} R{round_num} ({method}, handover={'ok' if round_handover_success else 'v1_fallback'})")
            session_name, session_key = launch_solve(h_run_key, work_dir, prompt_file, export_path, round_num, pid,
                                                      db=db, batch_id=batch_id)

            now_ts = time.time()
            now_iso = utc_now()
            running[h_run_key] = {
                "session_name": session_name,
                "session_key": session_key,
                "work_dir": work_dir,
                "pid": pid,
                "round_num": round_num,
                "export_path": str(export_path),
                "started_at": now_ts,
                "started_at_iso": now_iso,
                "last_activity": now_ts,
                "last_pane_hash": "",
                "round_metadata": round_metadata,
            }

            update_run(db, h_run_key, {
                "status": "running",
                "tmux_session": session_name,
                "current_round": round_num,
                "updated_at": now_iso,
                "verdict": make_verdict("running", f"round{round_num}_launched"),
            })
            add_running(r, h_run_key, {
                "pid": pid,
                "round_num": round_num,
                "tmux_session": session_name,
                "started_at": now_ts,
            })
            update_stats(r)

            insert_event(db, batch_id, "continuation_launched", {
                "pid": pid,
                "round_num": round_num,
                "method": method,
                "handover_success": round_handover_success,
                "session_name": session_name,
            }, run_key=h_run_key)

            handover_done.append(h_run_key)

        for h_run_key in handover_done:
            del handover_pending[h_run_key]

        # 启动新的（填满并发槽）——优雅退出模式下跳过
        # handover_pending占并发槽——handover生成中的题+解题中的题总数不超过concurrency
        while not should_stop() and len(running) + len(handover_pending) < concurrency and pending_count(r) > 0:
            items = dequeue_pending(r, count=1)
            if not items:
                break
            run_key, priority = items[0]

            run_doc = db.collection(CONTINUATION_RUNS_COLLECTION).get(run_key)
            if not run_doc:
                logger.warning(f"DB中找不到run_key={run_key}, 跳过")
                continue

            pid = run_doc.get("problem_id", run_key)
            work_dir = run_doc.get("work_dir", "")
            problem_text = run_doc.get("problem_text", "")
            seed_export = run_doc.get("seed_export", "")
            existing_rounds = run_doc.get("rounds_log", [])
            current_round = len(existing_rounds) + 1

            if current_round > max_rounds:
                update_run(db, run_key, {
                    "status": "completed",
                    "final_status": "TRUNCATED_AT_MAX",
                    "updated_at": utc_now(),
                    "verdict": make_verdict("truncated_at_max", "max_rounds_reached"),
                })
                add_completed(r, {"run_key": run_key, "final_status": "TRUNCATED_AT_MAX"})
                update_stats(r)
                continue

            if not work_dir or not Path(work_dir).exists():
                logger.error(f"work_dir不存在: {work_dir}")
                add_failed(r, {"run_key": run_key, "reason": "launch_error"})
                update_run(db, run_key, {
                    "status": "launch_error",
                    "updated_at": utc_now(),
                    "verdict": make_verdict("failed", "work_dir_not_found", "high", True),
                })
                update_stats(r)
                continue

            # 确定本轮的seed export和prev_export
            if current_round == 1:
                round1_export = Path(work_dir) / "round1_export.json"
                if not round1_export.exists():
                    import shutil
                    shutil.copy(seed_export, round1_export)

                trunc, trunc_reason = is_truncated(str(round1_export))
                comp, comp_reason = is_completed(str(round1_export), work_dir)
                if comp and not trunc:
                    update_run(db, run_key, {
                        "status": "completed",
                        "final_status": "COMPLETED",
                        "updated_at": utc_now(),
                        "verdict": make_verdict("completed", "round1_already_complete"),
                    })
                    add_completed(r, {"run_key": run_key, "final_status": "COMPLETED"})
                    update_stats(r)
                    continue

                round_num = 2
                prev_export = str(round1_export)
            else:
                prev_round_info = existing_rounds[-1]
                prev_export = prev_round_info.get("export", "")
                round_num = current_round

            # v2方案：异步启动handover生成（不阻塞主循环）
            if method == "v2":
                print(f"  [handover_start] {pid} R{round_num} (生成round{round_num-1}的HANDOVER.md)")
                hinfo = start_handover(
                    prev_export, pid, round_num - 1, problem_text, Path(work_dir),
                    db=db, batch_id=batch_id,
                )
                if hinfo is None:
                    # start_handover失败（地图生成失败等）——直接用v1
                    print(f"  [handover_fail] {pid} R{round_num} (start_handover失败，回退v1)")
                    if round_num == 2:
                        prev_rc = extract_reasoning(prev_export)
                    else:
                        prev_rc = "\n\n".join(
                            extract_reasoning(r.get("export", ""))
                            for r in existing_rounds if r.get("export")
                        )
                    prompt_text = build_continue_prompt(problem_text, prev_rc, round_num - 1)
                    prompt_file = Path(work_dir) / f"round{round_num}_prompt.txt"
                    prompt_file.write_text(prompt_text)

                    old_proof = Path(work_dir) / PROOF_FILE_NAME
                    if old_proof.exists():
                        old_proof.unlink()

                    round_traj_dir = CONTINUATION_TRAJECTORY_BASE / run_key / f"round{round_num}"
                    round_traj_dir.mkdir(parents=True, exist_ok=True)
                    (round_traj_dir / "exports").mkdir(exist_ok=True)
                    (round_traj_dir / "tmux").mkdir(exist_ok=True)
                    export_path = round_traj_dir / "exports" / "conversation.json"

                    round_metadata = {
                        "method": method, "handover_success": False, "handover_path": "",
                        "map_path": "", "prompt_path": str(prompt_file), "prev_export": prev_export,
                    }
                    print(f"  [launch] {pid} R{round_num} (v1_fallback)")
                    session_name, session_key = launch_solve(run_key, work_dir, prompt_file, export_path, round_num, pid,
                                                              db=db, batch_id=batch_id)
                    now_ts = time.time()
                    now_iso = utc_now()
                    running[run_key] = {
                        "session_name": session_name, "session_key": session_key,
                        "work_dir": work_dir, "pid": pid,
                        "round_num": round_num, "export_path": str(export_path),
                        "started_at": now_ts, "started_at_iso": now_iso,
                        "last_activity": now_ts, "last_pane_hash": "",
                        "round_metadata": round_metadata,
                    }
                    update_run(db, run_key, {
                        "status": "running", "tmux_session": session_name,
                        "current_round": round_num, "updated_at": now_iso,
                        "verdict": make_verdict("running", f"round{round_num}_launched"),
                    })
                    add_running(r, run_key, {
                        "pid": pid, "round_num": round_num,
                        "tmux_session": session_name, "started_at": now_ts,
                    })
                    update_stats(r)
                    insert_event(db, batch_id, "continuation_launched", {
                        "pid": pid, "round_num": round_num, "method": method,
                        "handover_success": False, "session_name": session_name,
                    }, run_key=run_key)
                    time.sleep(3)
                    continue

                # handover生成已启动——放入handover_pending，占并发槽（与running合计不超过concurrency）
                handover_pending[run_key] = {
                    "hinfo": hinfo,
                    "pid": pid,
                    "work_dir": work_dir,
                    "problem_text": problem_text,
                    "round_num": round_num,
                    "prev_export": prev_export,
                    "existing_rounds": existing_rounds,
                    "run_doc": run_doc,
                }
                # 3秒间隔——避免rate limit
                time.sleep(3)
            else:
                # v1方案——直接构造prompt并启动解题
                if round_num == 2:
                    prev_rc = extract_reasoning(prev_export)
                else:
                    prev_rc = "\n\n".join(
                        extract_reasoning(r.get("export", ""))
                        for r in existing_rounds if r.get("export")
                    )
                prompt_text = build_continue_prompt(problem_text, prev_rc, round_num - 1)
                prompt_file = Path(work_dir) / f"round{round_num}_prompt.txt"
                prompt_file.write_text(prompt_text)

                old_proof = Path(work_dir) / PROOF_FILE_NAME
                if old_proof.exists():
                    old_proof.unlink()

                round_traj_dir = CONTINUATION_TRAJECTORY_BASE / run_key / f"round{round_num}"
                round_traj_dir.mkdir(parents=True, exist_ok=True)
                (round_traj_dir / "exports").mkdir(exist_ok=True)
                (round_traj_dir / "tmux").mkdir(exist_ok=True)
                export_path = round_traj_dir / "exports" / "conversation.json"

                round_metadata = {
                    "method": method, "handover_success": False, "handover_path": "",
                    "map_path": "", "prompt_path": str(prompt_file), "prev_export": prev_export,
                }
                print(f"  [launch] {pid} R{round_num} (v1)")
                session_name, session_key = launch_solve(run_key, work_dir, prompt_file, export_path, round_num, pid,
                                                          db=db, batch_id=batch_id)
                now_ts = time.time()
                now_iso = utc_now()
                running[run_key] = {
                    "session_name": session_name, "session_key": session_key,
                    "work_dir": work_dir, "pid": pid,
                    "round_num": round_num, "export_path": str(export_path),
                    "started_at": now_ts, "started_at_iso": now_iso,
                    "last_activity": now_ts, "last_pane_hash": "",
                    "round_metadata": round_metadata,
                }
                update_run(db, run_key, {
                    "status": "running", "tmux_session": session_name,
                    "current_round": round_num, "updated_at": now_iso,
                    "verdict": make_verdict("running", f"round{round_num}_launched"),
                })
                add_running(r, run_key, {
                    "pid": pid, "round_num": round_num,
                    "tmux_session": session_name, "started_at": now_ts,
                })
                update_stats(r)
                insert_event(db, batch_id, "continuation_launched", {
                    "pid": pid, "round_num": round_num, "method": method,
                    "handover_success": False, "session_name": session_name,
                }, run_key=run_key)
                time.sleep(3)

        # 检查运行中的
        to_remove = []
        for run_key, info in running.items():
            session_name = info["session_name"]
            pid = info["pid"]
            round_num = info["round_num"]
            export_path = info["export_path"]
            work_dir = info["work_dir"]

            pane_text = tmux_pane_text(session_name)

            # 检测完成——必须等devin cli自然退出后才处理
            # proof.md只记录结果，不触发kill——等devin cli退出后export才写入
            is_done = False
            done_reason = ""
            proof_found = False

            # 预检proof.md（只记录，不触发完成）
            proof_path = Path(work_dir) / PROOF_FILE_NAME
            if proof_path.exists():
                proof_text = proof_path.read_text()
                if re.search(PROOF_COMPLETE_MARKER, proof_text):
                    proof_found = True
                    done_reason = f"proof.md有boxed ({len(proof_text)}c)"

            # 检查devin cli退出——只有退出后才处理完成/失败
            # 方式1: tmux session消失
            # 方式2: DONE.md文件存在（devin cli退出后echo $? > DONE.md）
            done_marker = Path(export_path).parent / "DONE.md"
            devin_exited = done_marker.exists()
            if not tmux_running(session_name) or devin_exited:
                # devin cli已退出——export已写入，现在可以安全处理
                if proof_found:
                    is_done = True
                    # 归档proof.md为round{N}_proof.md——防止后续round覆盖
                    archived_proof = Path(work_dir) / f"round{round_num}_proof.md"
                    import shutil
                    shutil.copy2(proof_path, archived_proof)
                    logger.info(f"[{pid}] proof.md已归档为round{round_num}_proof.md")
                else:
                    # devin cli退出但无proof.md——检查export判定完成/失败
                    comp, comp_reason = is_completed(export_path, work_dir)
                    if comp:
                        is_done = True
                        done_reason = f"session ended: {comp_reason}"
                        proof_found = PROOF_FILE_NAME in comp_reason
                    else:
                        # dead_session
                        elapsed_sec = int(time.time() - info["started_at"])
                        print(f"  [dead_session] {pid} R{round_num} ({elapsed_sec}s)")
                        failed.append({"pid": pid, "round": round_num, "reason": "dead_session"})
                        to_remove.append(run_key)
                        tmux_kill(session_name)
                        # 记录到rounds_log
                        run_doc = db.collection(CONTINUATION_RUNS_COLLECTION).get(run_key)
                        rounds_log = run_doc.get("rounds_log", []) if run_doc else []
                        rounds_log.append(make_round_log_entry(
                            round_num, export_path, False, False, f"dead_session({elapsed_sec}s)", info,
                        ))
                        update_run(db, run_key, {
                            "status": "dead_session",
                            "rounds_log": rounds_log,
                            "updated_at": utc_now(),
                            "verdict": make_verdict("dead_session", "dead_session"),
                            "failure_category": classify_failure("dead_session"),
                            "retry_eligible": True,
                        })
                        remove_running(r, run_key)
                        add_failed(r, {"run_key": run_key, "reason": "dead_session"})
                        update_stats(r)
                        insert_event(db, batch_id, "continuation_failed", {
                            "pid": pid, "round": round_num, "reason": "dead_session",
                            "elapsed": elapsed_sec,
                        }, run_key=run_key)
                        continue

            if is_done:
                elapsed = int(time.time() - info["started_at"])
                print(f"  [done] {pid} R{round_num} — {done_reason} ({elapsed}s)")

                # 检查这一轮是否真的完成（有proof.md）还是需要继续续传
                if proof_found:
                    # 真正完成——devin cli已自然退出，export已写入
                    # proof.md已在上面devin_exited分支中归档

                    archived_proof = Path(work_dir) / f"round{round_num}_proof.md"
                    completed.append({"pid": pid, "round": round_num, "proof": str(archived_proof)})
                    to_remove.append(run_key)
                    tmux_kill(session_name)

                    # 更新rounds_log——包含完整中间产物路径
                    run_doc = db.collection(CONTINUATION_RUNS_COLLECTION).get(run_key)
                    rounds_log = run_doc.get("rounds_log", []) if run_doc else []
                    rounds_log.append(make_round_log_entry(
                        round_num, export_path, False, True, done_reason,
                        info, archived_proof_path=str(archived_proof),
                    ))

                    update_run(db, run_key, {
                        "status": "completed",
                        "final_status": "COMPLETED",
                        "rounds_log": rounds_log,
                        "proof_path": str(archived_proof),  # 指向归档路径，不会被覆盖
                        "ended_at": utc_now(),
                        "updated_at": utc_now(),
                        "verdict": make_verdict("completed", f"round{round_num}_proof_complete"),
                    })
                    remove_running(r, run_key)
                    add_completed(r, {"run_key": run_key, "final_status": "COMPLETED"})
                    update_stats(r)
                    insert_event(db, batch_id, "continuation_completed", {
                        "pid": pid, "round": round_num, "elapsed": elapsed,
                    }, run_key=run_key)
                else:
                    # 有输出但无proof.md——检查是否截断
                    trunc, trunc_reason = is_truncated(export_path)
                    if trunc and round_num < max_rounds:
                        # 截断——需要继续续传，重新入队
                        print(f"  [truncated] {pid} R{round_num} — {trunc_reason}, 将继续R{round_num+1}")
                        run_doc = db.collection(CONTINUATION_RUNS_COLLECTION).get(run_key)
                        rounds_log = run_doc.get("rounds_log", []) if run_doc else []
                        rounds_log.append(make_round_log_entry(
                            round_num, export_path, True, False, trunc_reason, info,
                        ))
                        update_run(db, run_key, {
                            "status": "prepared",  # 重新标记为prepared，等下一轮
                            "rounds_log": rounds_log,
                            "updated_at": utc_now(),
                        })
                        to_remove.append(run_key)
                        tmux_kill(session_name)
                        remove_running(r, run_key)
                        # 重新入队（低优先级，避免阻塞新题）
                        enqueue_pending(r, run_key, priority=round_num)
                        update_stats(r)
                        insert_event(db, batch_id, "continuation_truncated", {
                            "pid": pid, "round": round_num, "reason": trunc_reason,
                        }, run_key=run_key)
                    elif trunc and round_num >= max_rounds:
                        # 截断且已达最大轮次——TRUNCATED_AT_MAX
                        print(f"  [truncated_max] {pid} R{round_num} — 达到max_rounds={max_rounds}")
                        run_doc = db.collection(CONTINUATION_RUNS_COLLECTION).get(run_key)
                        rounds_log = run_doc.get("rounds_log", []) if run_doc else []
                        rounds_log.append(make_round_log_entry(
                            round_num, export_path, True, False, trunc_reason, info,
                        ))
                        update_run(db, run_key, {
                            "status": "completed",
                            "final_status": "TRUNCATED_AT_MAX",
                            "rounds_log": rounds_log,
                            "ended_at": utc_now(),
                            "updated_at": utc_now(),
                            "verdict": make_verdict("truncated_at_max", "max_rounds_reached"),
                        })
                        to_remove.append(run_key)
                        tmux_kill(session_name)
                        remove_running(r, run_key)
                        add_completed(r, {"run_key": run_key, "final_status": "TRUNCATED_AT_MAX"})
                        update_stats(r)
                        insert_event(db, batch_id, "continuation_truncated_at_max", {
                            "pid": pid, "round": round_num, "reason": trunc_reason,
                        }, run_key=run_key)
                    else:
                        # 既没截断也没完成——异常状态
                        print(f"  [unknown] {pid} R{round_num} — 既没截断也没完成")
                        failed.append({"pid": pid, "round": round_num, "reason": "unknown_state"})
                        to_remove.append(run_key)
                        tmux_kill(session_name)
                        run_doc = db.collection(CONTINUATION_RUNS_COLLECTION).get(run_key)
                        rounds_log = run_doc.get("rounds_log", []) if run_doc else []
                        rounds_log.append(make_round_log_entry(
                            round_num, export_path, False, False, "unknown_state", info,
                        ))
                        update_run(db, run_key, {
                            "status": "unknown_state",
                            "rounds_log": rounds_log,
                            "updated_at": utc_now(),
                            "verdict": make_verdict("unknown_state", "unknown_state"),
                        })
                        remove_running(r, run_key)
                        add_failed(r, {"run_key": run_key, "reason": "unknown_state"})
                        update_stats(r)
                        insert_event(db, batch_id, "continuation_failed", {
                            "pid": pid, "round": round_num, "reason": "unknown_state",
                        }, run_key=run_key)
                continue

            # === rate_limit检测（复用analysis_launcher的逻辑）===
            detect_lower = pane_text.lower()
            detected_error = None
            for p in RATE_LIMIT_PATTERNS:
                if p.lower() in detect_lower:
                    detected_error = "rate_limited"
                    break
            if not detected_error:
                for p in CONNECTION_PATTERNS:
                    if p.lower() in detect_lower:
                        detected_error = "failed_connection"
                        break

            if detected_error:
                elapsed_sec = int(time.time() - info["started_at"])
                print(f"  [{detected_error}] {pid} R{round_num} — {elapsed_sec}s")
                failed.append({"pid": pid, "round": round_num, "reason": detected_error})
                to_remove.append(run_key)
                # ★ 不kill——标记stuck，devin cli可能还在写export ★
                # 只有done状态的session才安全kill（见specs §A.5）
                session_key = info.get("session_key")
                if session_key:
                    _mark_stuck(db, session_key, f"{detected_error}({elapsed_sec}s)")
                    print(f"  [stuck] {session_key} 标记stuck，不kill（等DONE.md或用户授意）")
                # 不调用tmux_kill——session留在tmux里继续跑

                if detected_error == "rate_limited":
                    # rate_limit自动暂停20分钟
                    pause_until = time.time() + 1200
                    if pause_until > rate_limit_paused_until:
                        rate_limit_paused_until = pause_until
                        print(f"  [rate_limit_pause] 暂停20分钟...")

                # 记录到rounds_log
                run_doc = db.collection(CONTINUATION_RUNS_COLLECTION).get(run_key)
                rounds_log = run_doc.get("rounds_log", []) if run_doc else []
                rounds_log.append(make_round_log_entry(
                    round_num, export_path, False, False, f"{detected_error}({elapsed_sec}s)", info,
                ))
                update_run(db, run_key, {
                    "status": detected_error,
                    "rounds_log": rounds_log,
                    "updated_at": utc_now(),
                    "verdict": make_verdict(detected_error, detected_error),
                    "failure_category": classify_failure(detected_error),
                    "retry_eligible": classify_failure(detected_error) == "infra",
                })
                remove_running(r, run_key)
                add_failed(r, {"run_key": run_key, "reason": detected_error})
                update_stats(r)
                insert_event(db, batch_id, "infra_failure", {
                    "pid": pid, "round": round_num,
                    "failure_type": detected_error, "elapsed": elapsed_sec,
                    "failure_category": classify_failure(detected_error),
                }, run_key=run_key)
                continue

            # === stall/timeout检测（复用analysis_launcher的逻辑）===
            elapsed = time.time() - info["started_at"]
            pane_hash = hash(pane_text[-500:])
            if pane_hash != info["last_pane_hash"]:
                info["last_pane_hash"] = pane_hash
                info["last_activity"] = time.time()
            idle = time.time() - info["last_activity"]

            if elapsed > max_runtime:
                elapsed_sec = int(elapsed)
                print(f"  [timeout] {pid} R{round_num} — {elapsed_sec}s")
                failed.append({"pid": pid, "round": round_num, "reason": "timeout"})
                to_remove.append(run_key)
                # ★ 不kill——标记stuck，devin cli可能还在写export ★
                session_key = info.get("session_key")
                if session_key:
                    _mark_stuck(db, session_key, f"timeout({elapsed_sec}s)")
                    print(f"  [stuck] {session_key} 标记stuck，不kill（等DONE.md或用户授意）")
                # 不调用tmux_kill
                run_doc = db.collection(CONTINUATION_RUNS_COLLECTION).get(run_key)
                rounds_log = run_doc.get("rounds_log", []) if run_doc else []
                rounds_log.append(make_round_log_entry(
                    round_num, export_path, False, False, f"timeout({elapsed_sec}s)", info,
                ))
                update_run(db, run_key, {
                    "status": "failed_timeout",
                    "rounds_log": rounds_log,
                    "updated_at": utc_now(),
                    "verdict": make_verdict("failed_timeout", "max_runtime_exceeded"),
                    "failure_category": classify_failure("failed_timeout"),
                    "retry_eligible": False,
                })
                remove_running(r, run_key)
                add_failed(r, {"run_key": run_key, "reason": "timeout"})
                update_stats(r)
                insert_event(db, batch_id, "continuation_failed", {
                    "pid": pid, "round": round_num, "reason": "timeout",
                    "elapsed": elapsed_sec,
                }, run_key=run_key)
                continue

            if idle > stall_seconds:
                idle_sec = int(idle)
                print(f"  [stall] {pid} R{round_num} — idle {idle_sec}s")
                failed.append({"pid": pid, "round": round_num, "reason": "stall"})
                to_remove.append(run_key)
                # ★ 不kill——标记stuck，devin cli可能还在写export ★
                session_key = info.get("session_key")
                if session_key:
                    _mark_stuck(db, session_key, f"stall(idle {idle_sec}s)")
                    print(f"  [stuck] {session_key} 标记stuck，不kill（等DONE.md或用户授意）")
                # 不调用tmux_kill
                run_doc = db.collection(CONTINUATION_RUNS_COLLECTION).get(run_key)
                rounds_log = run_doc.get("rounds_log", []) if run_doc else []
                rounds_log.append(make_round_log_entry(
                    round_num, export_path, False, False, f"stall(idle {idle_sec}s)", info,
                ))
                update_run(db, run_key, {
                    "status": "failed_stall",
                    "rounds_log": rounds_log,
                    "updated_at": utc_now(),
                    "verdict": make_verdict("failed_stall", "stall_detected"),
                    "failure_category": classify_failure("failed_stall"),
                    "retry_eligible": False,
                })
                remove_running(r, run_key)
                add_failed(r, {"run_key": run_key, "reason": "stall"})
                update_stats(r)
                insert_event(db, batch_id, "continuation_failed", {
                    "pid": pid, "round": round_num, "reason": "stall",
                    "idle": idle_sec,
                }, run_key=run_key)
                continue

        for key in to_remove:
            running.pop(key, None)

        # 状态报告
        redis_pending = pending_count(r)
        if running or redis_pending > 0:
            print(f"  [status] running={len(running)} pending={redis_pending} "
                  f"completed={len(completed)} failed={len(failed)}")
            stats = get_stats(r)
            print(f"  [redis] pending={stats.get('pending',0)} running={stats.get('running',0)} "
                  f"completed={stats.get('completed',0)} failed={stats.get('failed',0)}")
            time.sleep(poll_seconds)

    # 批次完成
    print(f"\n=== 批次完成 ===")
    print(f"  completed: {len(completed)}")
    print(f"  failed: {len(failed)}")

    # 更新batch记录
    from collections import Counter
    status_counts = Counter()
    for c in completed:
        status_counts["completed"] += 1
    for f in failed:
        status_counts[f["reason"]] += 1

    update_batch(db, batch_id, {
        "status": "completed",
        "completed_count": len(completed),
        "failed_count": len(failed),
        "status_counts": dict(status_counts),
        "ended_at": utc_now(),
    })

    logger.info(f"续传批次完成 batch={batch_id}: completed={len(completed)}, failed={len(failed)}")


# =============================================================================
# 状态检查和停止
# =============================================================================

def status_batch(batch_id):
    """检查批次状态"""
    db = connect_db()
    r = get_redis()

    print(f"=== 续传批次状态: {batch_id} ===")

    # Redis队列
    stats = get_stats(r)
    print(f"  Redis: pending={stats.get('pending',0)} running={stats.get('running',0)} "
          f"completed={stats.get('completed',0)} failed={stats.get('failed',0)}")

    # DB状态分布
    aql = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"COLLECT status = run.status WITH COUNT INTO c "
        f"SORT c DESC RETURN {{status, count: c}}"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=60)
    print(f"  DB状态分布:")
    for row in cursor:
        print(f"    {row['status']:25s} {row['count']:>4}")

    # final_status分布
    aql2 = (
        f"FOR run IN {CONTINUATION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.final_status != null "
        f"COLLECT fs = run.final_status WITH COUNT INTO c "
        f"SORT c DESC RETURN {{final_status: fs, count: c}}"
    )
    cursor2 = db.aql.execute(aql2, bind_vars={"bid": batch_id}, ttl=60)
    final_counts = list(cursor2)
    if final_counts:
        total = sum(r["count"] for r in final_counts)
        print(f"  最终状态分布（total={total}）:")
        for row in final_counts:
            pct = row["count"] / total * 100 if total else 0
            print(f"    {row['final_status']:25s} {row['count']:>4} ({pct:.0f}%)")

    # 运行中的tmux session
    result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
    p27_sessions = [l for l in result.stdout.split("\n") if l.startswith(f"{TMUX_PREFIX}-")]
    print(f"  运行中的{TMUX_PREFIX} tmux session: {len(p27_sessions)}")


def stop_batch(batch_id, force=False):
    """停止批次——优雅停止（默认）或强制kill

    优雅停止（force=False，默认）：
      - 向launcher进程发送SIGINT，launcher收到后不再启动新run
      - 已在运行的devin cli session继续自然完成
      - Redis队列不清空（恢复时可继续）

    强制停止（force=True）：
      - kill所有p27- tmux session（包括正在运行的devin cli）
      - 清空Redis队列
    """
    print(f"=== 停止续传批次: {batch_id} (mode: {'force' if force else 'graceful'}) ===")

    if force:
        # 强制模式：kill所有session+清空队列
        result = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
        p27_sessions = [l.split(":")[0] for l in result.stdout.split("\n")
                        if l.startswith(f"{TMUX_PREFIX}-")]
        for s in p27_sessions:
            subprocess.run(["tmux", "kill-session", "-t", s], capture_output=True, timeout=5)
            print(f"  killed: {s}")
        print(f"  共kill {len(p27_sessions)}个session")

        r = get_redis()
        clear_all(r)
        print(f"  Redis队列已清空")
    else:
        # 优雅模式：向launcher发送SIGINT，不kill devin session
        launcher_pids = subprocess.run(
            ["pgrep", "-f", f"continuation_launcher.*{batch_id}"],
            capture_output=True, text=True
        ).stdout.strip().split("\n")
        launcher_pids = [p for p in launcher_pids if p]

        if not launcher_pids:
            print(f"  [WARNING] launcher进程未找到，可能已退出")
            print(f"  如需强制停止所有session: python -m src.continuation_launcher --batch-id {batch_id} --stop --force")
            return

        for pid in launcher_pids:
            try:
                import os as _os
                _os.kill(int(pid), 2)  # SIGINT=2
                print(f"  向launcher PID={pid}发送SIGINT")
            except Exception as e:
                print(f"  向PID={pid}发送SIGINT失败: {e}")

        print(f"  launcher收到SIGINT后不再启动新run，等待running自然完成")
        print(f"  已在运行的devin cli session继续独立运行（不kill）")

        # 检查当前running数
        try:
            r = get_redis()
            running_count = r.hlen(f"{REDIS_PREFIX}:running") if hasattr(r, 'hlen') else 0
            print(f"  当前running: {running_count}个（等待自然完成）")
        except Exception:
            pass

        print(f"")
        print(f"  ★ 等所有running完成后，launcher自动退出")
        print(f"  ★ 如需立即强制停止（kill所有devin session）:")
        print(f"    python -m src.continuation_launcher --batch-id {batch_id} --stop --force")


def main():
    parser = argparse.ArgumentParser(description="POC-2.7续传Pipe启动")
    parser.add_argument("--batch-id", required=True, help="批次ID")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    parser.add_argument("--method", choices=["v1", "v2"], default="v2")
    parser.add_argument("--max-runtime", type=int, default=DEFAULT_MAX_RUNTIME_SECONDS)
    parser.add_argument("--stall-seconds", type=int, default=DEFAULT_STALL_SECONDS)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--stop", action="store_true", help="优雅停止（不kill devin session）")
    parser.add_argument("--force", action="store_true", help="强制停止（kill所有session+清空队列）")
    args = parser.parse_args()

    if args.status:
        status_batch(args.batch_id)
        return

    if args.stop:
        stop_batch(args.batch_id, force=args.force)
        return

    launch_batch(
        args.batch_id,
        concurrency=args.concurrency,
        max_rounds=args.max_rounds,
        max_runtime=args.max_runtime,
        stall_seconds=args.stall_seconds,
        poll_seconds=args.poll_seconds,
        method=args.method,
    )


if __name__ == "__main__":
    main()
