"""continuation_launcher.py — POC-2.7续传Pipe并发启动组件

复用analysis_launcher.py的架构模式（stall/rate_limit/zombie检测），
适配POC-2.7的多轮续传逻辑。

核心差异（vs analysis_launcher）：
  1. 多轮续传——每道题最多max_rounds轮，每轮检测截断/完成
  2. v2方案双pipe——每轮先Pipe A生成HANDOVER.md，再Pipe B解题
  3. 完成判定——proof.md存在且有boxed答案（不是XML标记）
  4. 更长timeout——续传单轮可能thinking spin很久（30分钟 vs 分析5分钟）

用法：
  python -m src.continuation_launcher --batch-id p27-full --concurrency 1 --max-rounds 5 --method v2
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
    SESSIONS_COLLECTION,
    TMUX_PREFIX, PROJECT_ROOT, SIM_MODE, HANDOVER_TIMEOUT_SECONDS,
)
from src.continuation_db_schema import (
    connect_db, ensure_schema, update_run, update_batch, insert_event, make_verdict,
    insert_result,
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
    update_stats, get_stats, clear_all, pending_count, RUNNING_KEY,
)
from monitoring.shared_logger import get_logger, log_event
from monitoring.graceful_shutdown import register_shutdown, should_stop
from src.observability import log_flow
from src.step_gate import gated, sync_registry_to_db

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


@gated(resource="file")
def remove_old_proof(work_dir, round_num, started_at=None):
    """【门闸: GATE-REMOVE-OLD-PROOF】删除旧proof.md——新一轮开始前的产物清场。

    为什么追踪这个动作：
    - proof.md是"整题完成"的唯一凭证（有\\boxed即COMPLETED）。上一轮残留的
      proof.md会被本轮误判为完成（016事故P0-2根因），所以启动新一轮前必须删；
    - 但删除文件本身不可逆——删错了就丢失解题成果证据。

    放行前Master Agent应检查并论证：
    【检查项】（每项含查法+正常值）
    1. 要删的确实是旧proof → 查法：stat work_dir/proof.md的mtime < started_at
    2. 上轮proof已归档 → 查法：ls work_dir/round*_proof.md（归档优先于删除）
    3. 无运行中session在写proof → 查法：find_active_session(db,run_key,pid)返回None

    【论证依据——放行/不放行判定】
    可放行：1✓(mtime<started_at)+3✓(无session写proof)。理由：删的是上轮残留proof，
       删除不丢失本轮成果也不破坏正在写入的proof——旧产物清场正确(016 P0-2)
    不可放行：mtime≥started_at→这是本轮刚写的proof，删=丢失解题成果；
       有运行session→可能正写proof，删=破坏

    调用点：三处（v2 handover回退分支 / v2 handover完成启动solve / v1直接启动），
    全部在launch_batch主循环"启动新一轮"之前。
    """
    proof = Path(work_dir) / PROOF_FILE_NAME
    if not proof.exists():
        return
    if started_at is not None and proof.stat().st_mtime >= started_at:
        # 新proof（本轮写的）——不删，让完成判定处理它
        return
    proof.unlink()
    logger.info(f"[{work_dir}] 清理旧proof.md（启动R{round_num}前）")


def find_active_session(db, run_key, pid):
    """016事故P0-1修复：查注册表中该run的活跃session（tmux还活着的）。

    防抖用——launcher重启后内存dict（running/handover_pending）清空，若孤儿
    devin cli session还在跑，重复启动同题会产生并发超限+产物互踩。
    只认tmux还活着的session（死了的已无devin cli在跑，不构成重复启动风险）。

    注意：注册表run_key字段写入不一致——launch_solve写完整run_key（如
    p27-full-amo_bench_00000006），start_handover写problem_id（如
    amo_bench_00000006），两种都匹配（该不一致本身是P2遗留缺陷）。

    返回活跃session_name，无则返回None。
    """
    try:
        aql = (
            f"FOR s IN {SESSIONS_COLLECTION} "
            f"FILTER s.run_key == @rk OR s.run_key == @pid "
            f"FILTER s.status IN ['running', 'stuck'] "
            f"RETURN {{session_name: s.session_name}}"
        )
        cursor = db.aql.execute(aql, bind_vars={"rk": run_key, "pid": pid}, ttl=30)
        for row in cursor:
            name = row.get("session_name", "")
            if name and tmux_running(name):
                return name
    except Exception as e:
        # 查询失败不阻塞启动——防抖是兜底，不是硬依赖
        logger.warning(f"find_active_session查询失败(忽略): {e}")
    return None


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


def is_truncated(export_path, since_ts=None):
    """检测export是否被截断

    016事故P0-2修复：增加since_ts（本轮启动时间戳）参数做产物归属校验——
    文件mtime早于since_ts说明是历史残留旧产物（比如8月18日手工跑的），
    不能用来判定本轮结果，直接视为"无有效export"。
    """
    if not os.path.exists(export_path):
        return False, "no export file"
    if since_ts is not None and os.path.getmtime(export_path) < since_ts:
        return False, f"stale export (mtime早于本轮启动: {export_path})"
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


def is_completed(export_path, work_dir, since_ts=None):
    """检测export是否已完成——proof.md存在且有boxed答案

    016事故P0-2修复：增加since_ts（本轮启动时间戳）参数做产物归属校验——
    export和proof.md的mtime都必须晚于since_ts，否则是历史残留旧产物，
    不能判定为本轮完成（旧proof.md残留曾导致误判）。
    """
    # 检查export的agent step是否有message/tool_call输出
    if os.path.exists(export_path):
        # 产物归属校验——旧残留export不算本轮产物
        if since_ts is not None and os.path.getmtime(export_path) < since_ts:
            return False, "stale export (mtime早于本轮启动)"
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
                    # 产物归属校验——旧残留proof.md不算本轮产物
                    if since_ts is not None and proof_path.stat().st_mtime < since_ts:
                        return False, "stale proof.md (mtime早于本轮启动)"
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
    handover_timeout = HANDOVER_TIMEOUT_SECONDS
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


@gated
def start_handover(export_path, pid, round_num, problem_text, work_dir, model=DEVIN_MODEL,
                   db=None, batch_id=None, run_key=None):
    """【门闸: GATE-START-HANDOVER】启动HANDOVER.md生成(Pipe A) devin cli。

    这个函数做什么：
    - 跑conversation_mapper.py生成上一轮对话的面包屑地图（.md）；
    - 构造Pipe A的prompt（写HANDOVER.md的任务说明）；
    - 用tmux启动devin -p子进程，异步生成round{N}_HANDOVER.md，立即返回。

    为什么追踪这个动作：
    - 它消耗API配额并占并发槽（handover_pending与running合计不超concurrency）；
    - 016事故中上千个handover session全部从这里产生——旧HANDOVER.md被
      check_handover秒判成功，导致"启动→秒判→重入队→再启动"死循环。

    放行前Master Agent应检查并论证：
    【检查项】（每项含查法+正常值）
    1. prev_export非历史残留 → 查法：stat prev_export的mtime属于应引用的那一轮
    2. 面包屑地图已生成 → 查法：ls map_path存在且非空
    3. 无活跃handover session → 查法：find_active_session(db,run_key,pid)返回None
    4. round_num正确 → 查法：DB run的current_round+1 == round_num

    【论证依据——放行/不放行判定】
    可放行：1✓+2✓+3✓+4✓。理由：Pipe A输入(prev_export+map)正确非残留、无重复
       handover、round编号正确——启动不会产生016"秒判→重入队→再启动"循环
    不可放行：1✗(prev_export残留)→016根因重现；3✗(有活跃handover)→重复启动=失控循环

    返回handover信息dict（含session_name/session_key和路径），或None（启动失败时）。
    主循环通过check_handover()检查是否完成。

    如果传了db，使用编号化管理（allocate_seq + create_session_record）。
    run_key用于行为流水（observability）——不传则fallback用pid。
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
    if SIM_MODE:
        # 全流程模拟（dev-docs/017）：Pipe A的devin替换为剧本演员。
        # mapper（Step 1）仍是真代码真跑——被测的面包屑地图生成逻辑不变。
        cmd = [
            sys.executable, "-m", "src.sim.fake_devin",
            "--role", "handover",
            "--run-key", run_key or pid,
            "--round", str(round_num),
            "--work-dir", str(work_dir),
            "--handover-out", str(handover_path),
        ]
        tmux_cmd = f"PYTHONPATH={PROJECT_ROOT} " + " ".join(cmd)
    else:
        cmd = [
            "devin", "-p",
            "--prompt-file", str(prompt_file),
            "--model", model,
            "--respect-workspace-trust", "false",
            "--permission-mode", DEVIN_PERMISSION_MODE,
            "--export", str(handover_export),
        ]
        tmux_cmd = " ".join(cmd)
    log_event(logger, "info", "devin_cli_launch", problem_id=pid, round=round_num, session_type="handover", model=model, permission_mode=DEVIN_PERMISSION_MODE, batch_id=batch_id or "p27-full")
    log_flow("launch_handover", run_key=run_key or pid, pid=pid, round=round_num,
             session_name=tmux_sess, model=model, batch_id=batch_id or "p27-full")
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", tmux_sess,
         f"cd {work_dir} && {tmux_cmd}"],
        capture_output=True, timeout=10,
    )

    log_event(logger, "info", "handover_started", problem_id=pid, round=round_num, session_name=tmux_sess, session_key=session_key, batch_id=batch_id or "p27-full")
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

    # 016事故P0-2修复：产物归属校验——HANDOVER.md必须晚于本轮handover启动时间。
    # 旧残留的HANDOVER.md（比如上一轮或历史手工运行的）会让这里秒判成功，
    # 配合"devin cli启动即失败退出→tmux session消失"形成3秒失控循环。
    if handover_path.stat().st_mtime < hinfo["started_at"]:
        print(f"  [{pid}] HANDOVER.md是旧残留(mtime早于本轮启动)，视为失败")
        return ""  # 失败，需回退v1

    handover_size = handover_path.stat().st_size
    if handover_size < 500:
        print(f"  [{pid}] Pipe A生成的HANDOVER.md太小({handover_size}c)，可能不完整")
        return ""  # 失败，需回退v1

    return str(handover_path)  # 成功


# =============================================================================
# 启动单个devin cli（Pipe B解题）
# =============================================================================

@gated
def launch_solve(run_key, work_dir, prompt_file, export_path, round_num, pid,
                 db=None, batch_id=None):
    """【门闸: GATE-LAUNCH-SOLVE】启动解题(Pipe B) devin cli——系统最重的动作。

    这个函数做什么：
    - 用tmux启动一个devin -p子进程跑续传解题prompt；
    - 分配全局session编号（allocate_seq），创建注册表记录（p27_sessions）；
    - 清理上一轮的DONE.md标记；建立tmux日志管道。

    为什么追踪这个动作：
    - 启动即消耗GLM-5.2 API配额、创建session、随后主循环会把run标记为
      running（DB+Redis）——这是系统里最重的状态改变；
    - 016事故的失控循环就是"启动"这个动作被高频触发（18分钟上千次），
      Master Agent当时既看不见也拦不住。

    放行前Master Agent应检查并论证：
    【检查项】（每项含查法+正常值）
    1. work_dir存在且属于该run → 查法：ls work_dir + DB run记录的work_dir字段比对
    2. 该run无活跃session → 查法：find_active_session(db,run_key,pid)返回None
    3. 并发槽空闲 → 查法：len(running)+len(handover_pending)<concurrency
    4. prompt内容合理 → 查法：head prompt_file，确认题目文本+上轮reasoning/HANDOVER

    【论证依据——放行/不放行判定】
    可放行：1✓+2✓+3✓+4✓。理由：系统最重动作的所有前置条件满足——产物归属正确、
       无重复启动(016 P0-1)、并发不超限(016根因)、输入完整。启动不会产生失控循环
    不可放行：2✗(有活跃session)→重复启动=016失控循环直接原因；
       3✗(并发满)→超并发=016"设1跑6"直接原因；4✗(prompt空)→devin立即失败=浪费配额

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

    if SIM_MODE:
        # 全流程模拟（dev-docs/017）：devin命令替换为剧本演员fake_devin。
        # 命令结构与生产完全一致（--export + echo $? > DONE.md + sleep），
        # 差别只是tmux里跑的是python脚本而非devin cli。下游一切（判定/
        # 防抖/注册表/门闸）面对的都是真文件真session。
        devin_cmd = (
            f"PYTHONPATH={PROJECT_ROOT} {sys.executable} -m src.sim.fake_devin "
            f"--role solve --run-key {run_key} --round {round_num} "
            f"--work-dir {work_dir} --export {export_path}; "
            f"echo $? > {done_marker}; "
            f"sleep 999999"
        )
    else:
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
    log_event(logger, "info", "devin_cli_launch", problem_id=pid, round=round_num, session_type="solve", model=DEVIN_MODEL, permission_mode=DEVIN_PERMISSION_MODE, batch_id=batch_id or "p27-full")
    log_flow("launch_solve", run_key=run_key, pid=pid, round=round_num,
             session_name=session_name, model=DEVIN_MODEL,
             batch_id=batch_id or "p27-full")

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

    log_event(logger, "info", "session_created", problem_id=pid, round=round_num, session_type="solve", session_name=session_name, session_key=session_key, batch_id=batch_id or "p27-full")
    return session_name, session_key


# ============================================================
# 门闸化的小动作函数——原先是主循环里的内联代码块（016后提取）
# 每个函数名=日志标志（grep直达），docstring=自包含文档（进DB注册表）
# ============================================================

@gated(resource="redis")
def requeue_skip(r, run_key, pid, priority, source, session_name=""):
    """【门闸: GATE-REQUEUE-SKIP】防抖拦截后的低优先级重入队（priority=9999）。

    触发场景（source字段区分）：
    - source=memory：该run已在launcher内存dict（running/handover_pending）
      ——同一进程内防重复启动；
    - source=orphan：注册表查到该run有活跃孤儿session（launcher重启后
      内存丢失，但tmux里旧session还活着）。

    为什么追踪这个动作：
    - 频繁触发此闸=系统有结构性问题（孤儿堆积/防抖误伤/队列里只剩
      被跳过的题）；
    - 016事故后加的requeued_keys守卫保证同一轮poll不会无限跳过——
      再取到已跳过的key就break等下一轮。

    放行前Master Agent应检查并论证：
    【检查项】（每项含查法+正常值）
    1. source=orphan时session真在tmux → 查法：tmux has-session -t <session_name>
    2. 该题非误伤 → 查法：observability --run-key看该run历史，判断是否真孤儿
    3. score=9999在队尾 → 查法：ZRANGE p27:pending 0 -1 WITHSCORES查该key的score

    【论证依据——放行/不放行判定】
    可放行：1✓(orphan时session真在tmux)+3✓(score=9999队尾)。理由：防抖拦截合理
       (真孤儿/真重复)，重入队低优先级排队尾不抢队首——不产生016"跳过→重取→再跳过"死循环
    不可放行：2✗(被误伤)→正常题被当孤儿跳过=系统有bug；
       3✗(score被feeder重置回0)→016 P0-3根因重现(NX失效)
    """
    enqueue_pending(r, run_key, priority=9999)


@gated(resource="file")
def overwrite_round1_seed(work_dir, seed_export, run_key, pid):
    """【门闸: GATE-OVERWRITE-ROUND1-SEED】用seed_export覆盖round1_export.json。

    这个动作做什么：
    round1_export.json的语义是"原始失败export的镜像"。每个run第一次被
    取出时，从seed_export（DB里存的原始路径）拷贝一份到work_dir。

    为什么追踪这个动作：
    - 016事故根因之一：work_dir里残留8月18日手工跑的旧round1_export.json，
      被当成有效产物参与截断/完成判定。总是覆盖=旧产物清场（P0-2修复）；
    - 覆盖本身无损（原件在seed_export路径），但若seed_export路径失效，
      旧文件会残留——这正是hold此闸时要检查的。

    放行前Master Agent应检查并论证：
    【检查项】（每项含查法+正常值）
    1. seed_export存在且非空 → 查法：ls -la seed_export路径
    2. 本轮首次取件 → 查法：DB run的current_round==1
    3. 旧round1_export是历史残留 → 查法：stat round1_export.json的mtime是今天以前

    【论证依据——放行/不放行判定】
    可放行：1✓(seed存在)+2✓(首次取件)。理由：用正确seed覆盖=旧产物清场(016 P0-2)，
       round1_export恢复正确镜像，后续截断/完成判定基于正确产物
    不可放行：1✗(seed不存在)→代码会shutil.copy(空路径)崩溃；
       2✗(非首次取件)→不该覆盖(可能已有正确round1)
    """
    import shutil
    round1_export = Path(work_dir) / "round1_export.json"
    if seed_export and Path(seed_export).exists():
        shutil.copy(seed_export, round1_export)
    elif not round1_export.exists():
        shutil.copy(seed_export, round1_export)
    return round1_export


@gated(resource="tmux")
def kill_session(session_name, run_key, pid, reason):
    """【门闸: GATE-KILL-SESSION】kill一个解题session的tmux（不可逆）。

    触发场景（reason字段区分）：
    - reason=completed：run完成，证明已归档，正常清理；
    - reason=truncated：round截断转入下一轮，旧session让位；
    - reason=dead_session：devin cli退出但无proof，判定死亡后清理。

    为什么追踪这个动作：
    - kill直接终止tmux里的devin cli进程，不可逆；
    - 项目铁律"绝不kill无DONE.md的session"管的就是这里——dead_session
      分支是唯一例外（DONE.md已出现但无proof）。

    放行前Master Agent应检查并论证：
    【检查项】（每项含查法+正常值）
    1. reason=completed/truncated时成果已落地 → 查法：ls DONE.md存在 + export文件mtime属于本轮
    2. reason=dead_session时判定成立 → 查法：observability --run-key看judge事件reason
    3. session_name匹配注册表 → 查法：DB p27_sessions查该session_name的run_key一致

    【论证依据——放行/不放行判定】
    可放行：(1✓或2✓)+3✓。理由：kill的是已完成(成果已归档)或已死(devin已退出无proof)的session，
       且确认是正确session——不违反铁律"绝不kill无DONE.md的session"(dead_session是唯一例外:DONE.md已出现但无proof)
    不可放行：1✗(无DONE.md)且非dead_session→违反铁律；3✗(session_name不匹配)→误杀风险
    """
    tmux_kill(session_name)


@gated(resource="redis")
def requeue_truncated(r, run_key, pid, round_num):
    """【门闸: GATE-REQUEUE-TRUNCATED】截断round的低优先级重入队（多轮续传核心流转）。

    这个动作做什么：
    round{N}被判定截断（thinking超长被切断），把run以priority=round_num
    重新入pending队列，等launcher再取出启动round{N+1}。

    为什么追踪这个动作：
    - 这是多轮续传的引擎，也是016事故循环的引擎——判定出错+feeder重置
      优先级时，"截断→重入队→再启动"变成失控循环；
    - 重入队前run被标回prepared、rounds_log已append——放行前这些都是
      可查的。

    放行前Master Agent应检查并论证：
    【检查项】（每项含查法+正常值）
    1. 截断判据完整 → 查法：observability --run-key看judge事件的comp≥24000+rc>1000+msg=0
    2. rounds_log+export正确 → 查法：DB run的rounds_log最后一条round==round_num且export路径存在
    3. 未到max → 查法：round_num < DB batch的max_rounds(默认5)
    4. score未被feeder重置 → 查法：ZRANGE p27:pending查该key的score==round_num(非0)

    【论证依据——放行/不放行判定】
    可放行：1✓+2✓+3✓+4✓。理由：多轮续传正常流转——截断判定有据、轮次记录完整、
       未到上限、优先级正确排队尾。重入队后该题等下一轮启动，不产生016循环
    不可放行：1✗(截断判据不完整)→016核心根因(误判截断→失控)；3✗(到max)→应走TRUNCATED_AT_MAX不重入队；
       4✗(score被重置回0)→016 P0-3根因重现(NX失效)
    """
    enqueue_pending(r, run_key, priority=round_num)


@gated(resource="db")
def finalize_run_completed(db, r, run_key, pid, round_num, done_reason,
                           elapsed, archived_proof, export_path, info, batch_id):
    """【门闸: GATE-FINALIZE-RUN-COMPLETED】写整题终态COMPLETED（几乎不可逆）。

    这个动作做什么：
    proof.md有\\boxed且devin cli已退出——把run标记为completed/
    final_status=COMPLETED，写rounds_log终条目，从running移除，
    入completed队列，写DB事件。

    为什么追踪这个动作：
    - COMPLETED是整题终态，直接影响通过率统计和POC-2.5选题；
    - 写入后只有人工改DB才能翻案。误判完成=该题永远失去续传机会。

    放行前Master Agent应检查并论证：
    【检查项】（每项含查法+正常值）
    1. proof有boxed且是本轮产出 → 查法：grep boxed proof.md + stat mtime>started_at
    2. export已落盘 → 查法：ls export文件存在且mtime属于本轮
    3. rounds_log齐全 → 查法：DB run的rounds_log每条都有export/prompt/proof路径
    4. 抽样题C类PASS → 查法：DB run的ai_review_result(抽样题时SOP_04已查)

    【论证依据——放行/不放行判定】
    可放行：1✓+2✓+3✓+(抽样题时4✓)。理由：整题终态写入前置全满足——proof是本轮产出
       非残留(016 P0-2)、export完整可审计、轮次记录完整、(抽样题)数学正确性已抽查。
       写COMPLETED后该题正确进入选题池
    不可放行：1✗(proof旧残留/mtime早于本轮)→016 P0-2根因(旧proof误判完成)，
       误判COMPLETED=该题永远失去续传机会；4✗(抽样题C类FAIL)→数学错误/幻觉，不可判完成
    """
    completed_list = []
    archived_proof = Path(archived_proof)
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
        "proof_path": str(archived_proof),
        "ended_at": utc_now(),
        "updated_at": utc_now(),
        "verdict": make_verdict("completed", f"round{round_num}_proof_complete"),
    })
    # 018事故加固：proof文本入库（continuation_results）。此前只存路径——
    # 文件是单点，盘上丢失即永久丢失（018实证：124份proof不可恢复）。
    # 入库后DB自身成为proof的第二份存档，选题/复核不再依赖盘上文件。
    try:
        insert_result(db, {
            "run_key": run_key,
            "batch_id": batch_id,
            "final_status": "COMPLETED",
            "round": round_num,
            "proof_text": archived_proof.read_text(errors="replace")[:100000],
            "proof_path": str(archived_proof),
            "export_path": str(export_path),
            "elapsed": elapsed,
            "done_reason": done_reason,
            "created_at": utc_now(),
        })
    except Exception as e:
        logger.warning(f"proof入库失败(不影响完成判定): {e}")
    remove_running(r, run_key)
    add_completed(r, {"run_key": run_key, "final_status": "COMPLETED"})
    update_stats(r)
    insert_event(db, batch_id, "continuation_completed", {
        "pid": pid, "round": round_num, "elapsed": elapsed,
    }, run_key=run_key)
    return completed_list


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
    log_event(logger, "info", "batch_start", batch_id=batch_id, concurrency=concurrency, method=method, max_rounds=max_rounds)
    log_flow("batch_start", run_key=None, batch_id=batch_id, concurrency=concurrency,
             method=method, max_rounds=max_rounds)
    # 步进门闸：把@gated装饰器收集的门闸目录同步到DB（Master Agent可见）
    try:
        sync_registry_to_db()
    except Exception as e:
        logger.warning(f"step_gate注册表同步失败(继续运行): {e}")
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
    # 注意：不覆盖DB中已有的concurrency——动态并发要求set-concurrency设置的值
    # 在launcher重启后仍然生效。如果DB已有concurrency则用DB的，否则用启动参数初始化。
    existing_batch = db.collection(CONTINUATION_BATCHES_COLLECTION).get(batch_id)
    if existing_batch and "concurrency" in existing_batch:
        concurrency = existing_batch["concurrency"]
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
        # 退出条件（017-sim发现：原条件漏了handover_pending——批次最后一题走v2
        # 路径时handover还在生成中，running空+队列空会导致launcher提前退出，
        # 把题晾在handover_pending里。生产因队列常年有垫底题未暴露）
        if not running and not handover_pending and pending_count(r) == 0:
            break

        # 优雅退出检查——收到SIGTERM/SIGINT后不再启动新run，等running自然完成
        if should_stop():
            if not running and not handover_pending:
                print(f"  [graceful_shutdown] running/handover已全部完成，launcher退出")
                log_flow("graceful_stop", run_key=None, batch_id=batch_id,
                         reason="running+handover全空，launcher退出")
                break
            else:
                print(f"  [graceful_shutdown] 不再启动新run，等待{len(running)}个running"
                      f"+{len(handover_pending)}个handover自然完成...")
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

        # 动态并发——从DB读取batch.concurrency，支持运行中通过set-concurrency调整
        # concurrency参数是启动时的初始值，主循环中每轮从DB刷新
        try:
            batch_doc = db.collection(CONTINUATION_BATCHES_COLLECTION).get(batch_id)
            if batch_doc and "concurrency" in batch_doc:
                db_concurrency = batch_doc["concurrency"]
                if db_concurrency != concurrency:
                    print(f"  [concurrency] 并发数调整: {concurrency} → {db_concurrency}（从DB读取）")
                    concurrency = db_concurrency
        except Exception as e:
            # DB读取失败时保持当前concurrency，不让DB故障导致launcher崩溃
            pass

        # === 检查handover_pending中的run——handover生成完成后启动解题 ===
        handover_done = []
        for h_run_key, hinfo in list(handover_pending.items()):
            result = check_handover(hinfo["hinfo"], hinfo["pid"])
            if result is None:
                # 还在运行——检查超时
                if time.time() - hinfo["hinfo"]["started_at"] > HANDOVER_TIMEOUT_SECONDS:
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

            # 清理旧round的proof.md（门闸GATE-REMOVE-OLD-PROOF）
            remove_old_proof(work_dir, round_num,
                             gate_ctx={"run_key": run_key, "pid": pid, "round": round_num})

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
            log_event(logger, "info", "launch_solve", problem_id=pid, round=round_num, method=method, handover_ok=round_handover_success, batch_id=batch_id)
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
        # 016勘误补丁：requeued_keys防死循环——被防抖跳过重入队(9999)的题如果
        # 是pending里唯一/最低分的，zpopmin会立刻再取回它，同一轮poll内无限跳过。
        # 再取到已重入队过的key时直接break，等下一轮poll（孤儿session可能已结束）。
        requeued_keys = set()
        while not should_stop() and len(running) + len(handover_pending) < concurrency and pending_count(r) > 0:
            items = dequeue_pending(r, count=1)
            if not items:
                break
            run_key, priority = items[0]
            if run_key in requeued_keys:
                enqueue_pending(r, run_key, priority=9999)
                break
            log_flow("dequeue", run_key=run_key, priority=priority)

            run_doc = db.collection(CONTINUATION_RUNS_COLLECTION).get(run_key)
            if not run_doc:
                logger.warning(f"DB中找不到run_key={run_key}, 跳过")
                continue

            pid = run_doc.get("problem_id", run_key)

            # === 016事故P0-1修复：同run_key防抖（拦住失控循环的最后一道闸） ===
            # 检查1：内存dict——该题是否已被本进程跟踪（防同进程重复启动）
            if run_key in running or run_key in handover_pending:
                print(f"  [skip_duplicate] {pid} 已在内存跟踪中(running/handover_pending)，低优先级重入队")
                log_event(logger, "warning", "duplicate_launch_blocked",
                          problem_id=pid, run_key=run_key, source="memory", batch_id=batch_id)
                log_flow("skip_duplicate", run_key=run_key, pid=pid, source="memory",
                         priority=priority)
                requeued_keys.add(run_key)
                requeue_skip(r, run_key, pid, priority, source="memory",
                             gate_ctx={"run_key": run_key, "pid": pid, "source": "memory"})
                continue
            # 检查2：注册表——该题是否有活跃孤儿session（防launcher重启后重复启动）
            active_session = find_active_session(db, run_key, pid)
            if active_session:
                print(f"  [skip_orphan] {pid} 有活跃孤儿session {active_session}，低优先级重入队等其结束")
                log_event(logger, "warning", "orphan_session_detected",
                          problem_id=pid, run_key=run_key,
                          session_name=active_session, batch_id=batch_id)
                log_flow("skip_orphan", run_key=run_key, pid=pid,
                         session_name=active_session, priority=priority)
                requeued_keys.add(run_key)
                requeue_skip(r, run_key, pid, priority, source="orphan",
                             session_name=active_session,
                             gate_ctx={"run_key": run_key, "pid": pid,
                                       "source": "orphan", "session_name": active_session})
                continue

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
                # 017-sim补：TRUNCATED_AT_MAX也是整题终态，必须进行为流水黑匣子
                log_flow("run_completed", run_key=run_key, pid=pid,
                         round=current_round, final_status="TRUNCATED_AT_MAX",
                         batch_id=batch_id)
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
                # 门闸GATE-OVERWRITE-ROUND1-SEED：总是从seed_export覆盖拷贝。
                # 残留的旧round1_export.json（历史手工运行产物，如8月18日的）内容
                # 未必是本题的原始失败export，用它判定round1截断/完成会误判。
                # round1_export的语义就是seed_export的镜像，覆盖无损（原件在seed_export路径）。
                round1_export = overwrite_round1_seed(
                    work_dir, seed_export, run_key, pid,
                    gate_ctx={"run_key": run_key, "pid": pid, "round": 1})

                trunc, trunc_reason = is_truncated(str(round1_export))
                # 016事故P0-2：产物归属校验——残留的旧proof.md（mtime早于刚拷贝的
                # round1_export）不能判定round1已完成
                comp, comp_reason = is_completed(
                    str(round1_export), work_dir,
                    since_ts=round1_export.stat().st_mtime,
                )
                log_flow("judge", run_key=run_key, pid=pid, round=1,
                         outcome="round1_precheck",
                         reason=f"trunc={trunc}({trunc_reason}), comp={comp}({comp_reason})")
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

                # 017-sim实证修复：补录round-1的rounds_log条目。current_round =
                # len(rounds_log)+1 假设每轮都有条目——原代码round1（seed重判）
                # 不补录，导致R2截断后current_round仍=2，round 2被重跑一次
                # （sim solve3实证rounds_log=[2,2,3]，多耗一次handover+solve）。
                # 补录后轮序为[1,2,3...]，round 1的历史在DB中完整可见。
                update_run(db, run_key, {
                    "rounds_log": existing_rounds + [
                        make_round_log_entry(1, str(round1_export), trunc, False,
                                             f"round1_precheck: {trunc_reason}", None)],
                })

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
                    db=db, batch_id=batch_id, run_key=run_key,
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

                    # 门闸GATE-REMOVE-OLD-PROOF：清理旧proof防误判完成
                    remove_old_proof(work_dir, round_num,
                                     gate_ctx={"run_key": run_key, "pid": pid, "round": round_num})

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

                # 门闸GATE-REMOVE-OLD-PROOF：清理旧proof防误判完成
                remove_old_proof(work_dir, round_num,
                                 gate_ctx={"run_key": run_key, "pid": pid, "round": round_num})

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
            # 016事故P0-2：产物归属校验——只认本轮启动后写的proof.md，
            # 旧残留proof.md（mtime早于info["started_at"]）不作为完成证据
            proof_path = Path(work_dir) / PROOF_FILE_NAME
            if proof_path.exists():
                if proof_path.stat().st_mtime >= info["started_at"]:
                    proof_text = proof_path.read_text()
                    if re.search(PROOF_COMPLETE_MARKER, proof_text):
                        proof_found = True
                        done_reason = f"proof.md有boxed ({len(proof_text)}c)"
                else:
                    print(f"  [{pid}] 忽略旧残留proof.md (mtime早于本轮启动)")
                    log_event(logger, "warning", "stale_proof_ignored",
                              problem_id=pid, round=round_num, batch_id=batch_id)
                    log_flow("judge", run_key=run_key, pid=pid, round=round_num,
                             outcome="stale_proof_ignored", reason="mtime早于本轮启动")

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
                    # 016事故P0-2：since_ts校验——旧残留export不算本轮产物
                    comp, comp_reason = is_completed(export_path, work_dir,
                                                     since_ts=info["started_at"])
                    if comp:
                        is_done = True
                        done_reason = f"session ended: {comp_reason}"
                        proof_found = PROOF_FILE_NAME in comp_reason
                        log_flow("judge", run_key=run_key, pid=pid, round=round_num,
                                 outcome="completed_by_export", reason=comp_reason)
                    else:
                        # 017-sim实证修复（P0）：截断判定必须先于dead判定。原结构下
                        # is_truncated只在is_done（需proof或完成）之后才被咨询——
                        # devin退出+无proof+截断态export时dead分支抢占，截断→重入队
                        # 的多轮续传引擎不可达，真实截断全部被误判为dead_session。
                        # 生产实证：deepmath_103k_00004712被判dead，其export重判
                        # rc=70632c/msg=0/comp=25000是教科书式截断。
                        trunc, trunc_reason = is_truncated(
                            export_path, since_ts=info["started_at"])
                        if trunc:
                            is_done = True
                            done_reason = f"truncated: {trunc_reason}"
                        else:
                            # 既非完成也非截断——真正的dead_session
                            elapsed_sec = int(time.time() - info["started_at"])
                            print(f"  [dead_session] {pid} R{round_num} ({elapsed_sec}s)")
                            log_event(logger, "warning", "dead_session", problem_id=pid, round=round_num, elapsed=elapsed_sec, batch_id=batch_id)
                            log_flow("judge", run_key=run_key, pid=pid, round=round_num,
                                     outcome="dead_session", reason=f"devin退出无proof, elapsed={elapsed_sec}s")
                            log_flow("run_failed", run_key=run_key, pid=pid,
                                     round=round_num, reason="dead_session")
                            failed.append({"pid": pid, "round": round_num, "reason": "dead_session"})
                            to_remove.append(run_key)
                            kill_session(session_name, run_key, pid, reason="dead_session",
                                         gate_ctx={"run_key": run_key, "pid": pid,
                                                   "reason": "dead_session", "elapsed": elapsed_sec})
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
                log_event(logger, "info", "round_done", problem_id=pid, round=round_num, reason=done_reason, elapsed=elapsed, batch_id=batch_id)

                # 检查这一轮是否真的完成（有proof.md）还是需要继续续传
                if proof_found:
                    # 真正完成——devin cli已自然退出，export已写入
                    # proof.md已在上面devin_exited分支中归档

                    archived_proof = Path(work_dir) / f"round{round_num}_proof.md"
                    completed.append({"pid": pid, "round": round_num, "proof": str(archived_proof)})
                    to_remove.append(run_key)
                    # 门闸GATE-KILL-SESSION（reason=completed：证明已归档，正常清理）
                    kill_session(session_name, run_key, pid, reason="completed",
                                 gate_ctx={"run_key": run_key, "pid": pid,
                                           "reason": "completed", "round": round_num})

                    # 门闸GATE-FINALIZE-RUN-COMPLETED：写整题终态COMPLETED
                    log_flow("round_done", run_key=run_key, pid=pid, round=round_num,
                             outcome="completed", reason=done_reason, elapsed=elapsed)
                    finalize_run_completed(
                        db, r, run_key, pid, round_num, done_reason, elapsed,
                        archived_proof, export_path, info, batch_id,
                        gate_ctx={"run_key": run_key, "pid": pid,
                                  "round": round_num, "reason": done_reason})
                    log_flow("run_completed", run_key=run_key, pid=pid,
                             round=round_num, final_status="COMPLETED")
                else:
                    # 有输出但无proof.md——检查是否截断
                    # 016事故P0-2：since_ts校验——旧残留export不算本轮产物
                    trunc, trunc_reason = is_truncated(export_path,
                                                       since_ts=info["started_at"])
                    if trunc and round_num < max_rounds:
                        # 截断——需要继续续传，重新入队
                        print(f"  [truncated] {pid} R{round_num} — {trunc_reason}, 将继续R{round_num+1}")
                        log_event(logger, "info", "truncated", problem_id=pid, round=round_num, reason=trunc_reason, next_round=round_num+1, batch_id=batch_id)
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
                        kill_session(session_name, run_key, pid, reason="truncated",
                                     gate_ctx={"run_key": run_key, "pid": pid,
                                               "reason": "truncated", "round": round_num})
                        remove_running(r, run_key)
                        # 重新入队（低优先级，避免阻塞新题）——门闸GATE-REQUEUE-TRUNCATED
                        requeue_truncated(r, run_key, pid, round_num,
                                          gate_ctx={"run_key": run_key, "pid": pid,
                                                    "round": round_num, "reason": trunc_reason})
                        log_flow("judge", run_key=run_key, pid=pid, round=round_num,
                                 outcome="truncated", reason=trunc_reason)
                        log_flow("requeue", run_key=run_key, pid=pid,
                                 priority=round_num, reason=f"truncated_r{round_num}")
                        update_stats(r)
                        insert_event(db, batch_id, "continuation_truncated", {
                            "pid": pid, "round": round_num, "reason": trunc_reason,
                        }, run_key=run_key)
                    elif trunc and round_num >= max_rounds:
                        # 截断且已达最大轮次——TRUNCATED_AT_MAX
                        print(f"  [truncated_max] {pid} R{round_num} — 达到max_rounds={max_rounds}")
                        log_event(logger, "info", "truncated_max", problem_id=pid, round=round_num, max_rounds=max_rounds, batch_id=batch_id)
                        log_flow("judge", run_key=run_key, pid=pid, round=round_num,
                                 outcome="truncated_at_max", reason=f"达到max_rounds={max_rounds}")
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
                        kill_session(session_name, run_key, pid, reason="truncated_at_max",
                                     gate_ctx={"run_key": run_key, "pid": pid,
                                               "reason": "truncated_at_max", "round": round_num})
                        remove_running(r, run_key)
                        add_completed(r, {"run_key": run_key, "final_status": "TRUNCATED_AT_MAX"})
                        update_stats(r)
                        insert_event(db, batch_id, "continuation_truncated_at_max", {
                            "pid": pid, "round": round_num, "reason": trunc_reason,
                        }, run_key=run_key)
                        # 017-sim补：TRUNCATED_AT_MAX终态进行为流水黑匣子
                        log_flow("run_completed", run_key=run_key, pid=pid,
                                 round=round_num, final_status="TRUNCATED_AT_MAX",
                                 batch_id=batch_id)
                    else:
                        # 既没截断也没完成——异常状态
                        log_event(logger, "warning", "unknown_status", problem_id=pid, round=round_num, batch_id=batch_id)
                        print(f"  [unknown] {pid} R{round_num} — 既没截断也没完成")
                        failed.append({"pid": pid, "round": round_num, "reason": "unknown_state"})
                        to_remove.append(run_key)
                        kill_session(session_name, run_key, pid, reason="unknown_state",
                                     gate_ctx={"run_key": run_key, "pid": pid,
                                               "reason": "unknown_state", "round": round_num})
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
                        log_flow("run_failed", run_key=run_key, pid=pid,
                                 round=round_num, reason="unknown_state",
                                 batch_id=batch_id)
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
                log_event(logger, "warning", "infra_failure", problem_id=pid, round=round_num, error=detected_error, elapsed=elapsed_sec, batch_id=batch_id)
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
                log_flow("run_failed", run_key=run_key, pid=pid,
                         round=round_num, reason=detected_error,
                         batch_id=batch_id)
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
                log_event(logger, "warning", "timeout", problem_id=pid, round=round_num, elapsed=elapsed_sec, batch_id=batch_id)
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
                log_flow("run_failed", run_key=run_key, pid=pid,
                         round=round_num, reason="timeout",
                         batch_id=batch_id)
                insert_event(db, batch_id, "continuation_failed", {
                    "pid": pid, "round": round_num, "reason": "timeout",
                    "elapsed": elapsed_sec,
                }, run_key=run_key)
                continue

            if idle > stall_seconds:
                idle_sec = int(idle)
                print(f"  [stall] {pid} R{round_num} — idle {idle_sec}s")
                log_event(logger, "warning", "stall", problem_id=pid, round=round_num, idle=idle_sec, batch_id=batch_id)
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
                log_flow("run_failed", run_key=run_key, pid=pid,
                         round=round_num, reason="stall",
                         batch_id=batch_id)
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
            running_count = r.hlen(RUNNING_KEY)
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
