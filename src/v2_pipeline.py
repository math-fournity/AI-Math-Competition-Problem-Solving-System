#!/usr/bin/env python3
"""v2_pipeline.py — 观察者/解题者递归消化链解题管线（053 技术说明书实现）

一道题的完整 v2 接力：
  round1: 解题者（仅题目 → 工作笔记 + proof）
  round2: 观察者（前轮档案 → 分析笔记）
  round3: 解题者（分析笔记 → 继续推进）
  ...交替直到 COMPLETED 或本次Round调度窗口结束；未解题可从下一Round继续

用法（模块导入）：
    from src.v2_pipeline import solve_problem
    result = solve_problem(problem_text, output_dir=Path("/tmp/v2run"))

用法（命令行单题）：
    python -m src.v2_pipeline --problem-file problem.txt --output-dir /tmp/v2test
"""
import argparse
import json
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).parent.parent
TEMPLATES = REPO / "templates" / "v2"
OC_TRAJ_NAME = "oc_traj.py"

MODEL = "openrouter/stealth/ox-alpha"
EFFORT = "max"
SILENCE_THRESHOLD = 300
TOOL_PENDING_GRACE = 600
MAX_SESSION_SECONDS = 120 * 60
OUTPUT_CAP = 32000


# ═══ JSON-RPC 基础 ═══════════════════════════════════

def _send(proc, msg):
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def _read_msg(proc, timeout=5):
    r, _, _ = select.select([proc.stdout], [], [], timeout)
    if not r:
        return None
    line = proc.stdout.readline()
    if not line:
        return None
    try:
        return json.loads(line.decode())
    except json.JSONDecodeError:
        return None


def _rpc(proc, method, params, rid, timeout=25):
    _send(proc, {"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = _read_msg(proc, 5)
        if msg is None:
            continue
        if msg.get("id") == rid and ("result" in msg or "error" in msg):
            return msg
    return {"error": {"code": -1, "message": f"timeout: {method}"}}


# ═══ 铁律 15 断言链 ═════════════════════════════════

def assert_config(proc, sid, config_id, value, rid):
    """设模型/强度并断言回显。双方法名兼容探测。返回 (ok: bool, echo_info)。"""
    for method in ("session/set_config_option", "session/set_config"):
        resp = _rpc(proc, method,
                    {"sessionId": sid, "configId": config_id, "value": value}, rid)
        if "error" in resp:
            msg = str(resp["error"].get("message", ""))
            if "method" in msg.lower() or "not found" in msg.lower():
                continue
            return False, {"config": config_id, "error": msg}
        opts = resp.get("result", {}).get("configOptions", [])
        cur = next((o.get("currentValue") for o in opts if o.get("id") == config_id), None)
        if cur == value:
            return True, {config_id: cur}
        return False, {"config": config_id, "expected": value, "echo": cur}
    return False, {"config": config_id, "error": "双方法均不可用"}


# ═══ 单轮会话 ═══════════════════════════════════════

def run_round(round_num, role, prompt_text, work_dir):
    """运行一轮 ACP 会话（观察者或解题者）。返回 result dict。

    work_dir 是本轮的隔离工作区——AI 在这里读写文件、产出笔记和 proof。
    """
    out_dir = work_dir / f".acp_out_r{round_num}"
    out_dir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        ["opencode", "acp", "--cwd", str(work_dir)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, bufsize=0)

    # initialize
    resp = _rpc(proc, "initialize",
                {"protocolVersion": 1, "clientCapabilities": {}}, 1)
    protocol_version = resp.get("result", {}).get("protocolVersion")

    # session/new
    resp = _rpc(proc, "session/new",
                {"cwd": str(work_dir), "mcpServers": []}, 2)
    sid = resp.get("result", {}).get("sessionId")

    # 铁律 15：model 断言
    ok_m, echo_m = assert_config(proc, sid, "model", MODEL, 10)
    assert ok_m, f"[r{round_num}] 铁律15 model 未接受: {echo_m}"
    # effort 断言
    ok_e, echo_e = assert_config(proc, sid, "effort", EFFORT, 11)
    assert ok_e, f"[r{round_num}] 铁律15 effort 未接受: {echo_e}"

    print(f"  [r{round_num}·{role}] session={sid[:20]}… model✓ effort={EFFORT}✓",
          flush=True)

    # 打开三路 jsonl 落盘（实时 flush——进程崩溃不丢）
    tf = open(out_dir / "thoughts.jsonl", "w")
    mf = open(out_dir / "messages.jsonl", "w")
    tl = open(out_dir / "tools.jsonl", "w")

    def dump(f, obj):
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()

    # 发 prompt
    t0 = time.time()
    _send(proc, {"jsonrpc": "2.0", "id": 99, "method": "session/prompt",
                 "params": {"sessionId": sid,
                            "prompt": [{"type": "text", "text": prompt_text}]}})

    # 通知循环
    counts = {"thought": 0, "message": 0, "tool": 0}
    tools_state = {}
    thought_parts = []
    message_parts = []
    last_signal = time.time()
    prompt_response = None

    while True:
        # 进程退出检测
        if proc.poll() is not None:
            break

        # select 等待数据（5s 超时用于检查静默/超时）
        r, _, _ = select.select([proc.stdout], [], [], 5)
        now = time.time()
        elapsed_total = now - t0

        if not r:
            # 无数据——检查静默/超时
            pending_tool = any(s not in ("completed", "error")
                               for s in tools_state.values())
            threshold = TOOL_PENDING_GRACE if pending_tool else SILENCE_THRESHOLD

            if now - last_signal >= threshold:
                reason = (f"静默 {threshold}s"
                          + ("（工具执行中放宽后仍超时）" if pending_tool else ""))
                print(f"  [r{round_num}] {reason}，判定结束", flush=True)
                break

            if elapsed_total >= MAX_SESSION_SECONDS:
                _send(proc, {"jsonrpc": "2.0", "method": "session/cancel",
                             "params": {"sessionId": sid}})
                print(f"  [r{round_num}] 总时长 {MAX_SESSION_SECONDS}s 兜底 cancel",
                      flush=True)
                break
            continue

        # 有数据——读取并解析
        raw = proc.stdout.readline()
        if not raw:
            break
        last_signal = time.time()
        try:
            msg = json.loads(raw.decode())
        except json.JSONDecodeError:
            continue

        # prompt response 到达 = 正常完成
        if msg.get("id") == 99 and ("result" in msg or "error" in msg):
            prompt_response = msg
            break

        # 权限自动批准
        if msg.get("method") == "session/request_permission" and "id" in msg:
            opts = msg.get("params", {}).get("options", [])
            pick = next((o["optionId"] for o in opts
                         if o.get("kind") == "allow_once"),
                        opts[0]["optionId"] if opts else "allow_once")
            resp_msg = {"jsonrpc": "2.0", "id": msg["id"],
                        "result": {"outcome": {"outcome": "selected",
                                               "optionId": pick}}}
            proc.stdin.write((json.dumps(resp_msg) + "\n").encode())
            proc.stdin.flush()
            continue

        # session/update 通知分类采集
        upd = msg.get("params", {}).get("update", {})
        su = upd.get("sessionUpdate", "")
        elapsed = round(now - t0, 1)

        if su == "agent_thought_chunk":
            text = (upd.get("content") or {}).get("text") or ""
            dump(tf, {"t": elapsed, "mid": upd.get("messageId"), "text": text})
            thought_parts.append(text)
            counts["thought"] += 1
        elif su == "agent_message_chunk":
            text = (upd.get("content") or {}).get("text") or ""
            dump(mf, {"t": elapsed, "mid": upd.get("messageId"), "text": text})
            message_parts.append(text)
            counts["message"] += 1
        elif su in ("tool_call", "tool_call_update"):
            tid, st = upd.get("toolCallId"), upd.get("status")
            if tid:
                tools_state[tid] = st
            dump(tl, {"t": elapsed, "kind": su, "title": upd.get("title"),
                      "status": st})
            counts["tool"] += 1

    duration = round(time.time() - t0, 1)

    # 关闭文件
    for f in (tf, mf, tl):
        f.close()

    # usage 与终态判定
    usage = {}
    if prompt_response:
        usage = (prompt_response.get("result") or {}).get("usage") or {}

    output_tokens = usage.get("outputTokens", 0)
    proof_path = work_dir / "proof.md"
    has_proof = proof_path.exists()
    has_boxed = has_proof and "\\boxed" in proof_path.read_text(errors="ignore")

    # BUDGET_STARVED 指纹（053 §3.2）：outputTokens 恰为整数上限值
    budget_starved = (
        output_tokens > 0
        and output_tokens % 1000 == 0  # 整数千值暗示上限截断
        and output_tokens >= OUTPUT_CAP * 0.9
    )

    if has_boxed:
        final_status = "COMPLETED"
    elif budget_starved:
        final_status = "BUDGET_STARVED"
    elif not has_proof:
        final_status = "ENDED_NO_PROOF"
    else:
        final_status = "PROOF_NO_BOXED"

    result = {
        "round": round_num, "role": role,
        "sessionId": sid, "protocolVersion": protocol_version,
        "counts": counts,
        "thought_chars": len("".join(thought_parts)),
        "message_chars": len("".join(message_parts)),
        "outputTokens": output_tokens,
        "stopReason": (prompt_response or {}).get("result", {}).get("stopReason"),
        "final_status": final_status,
        "budget_starved": budget_starved,
        "has_proof": has_proof, "has_boxed": has_boxed,
        "duration_sec": duration,
    }

    # 写 meta
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(result, ensure_ascii=False, indent=1))

    # 归档 thinking 到 problem_dir
    arch = work_dir / f"rounds" / f"round{round_num}"
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "thinking.md").write_text("".join(thought_parts))
    shutil.copy(out_dir / "thoughts.jsonl", arch / "thoughts.jsonl")
    shutil.copy(meta_path, arch / "meta.json")

    # 关闭子进程
    try:
        _send(proc, {"jsonrpc": "2.0", "method": "session/close",
                     "params": {"sessionId": sid}})
    except Exception:
        pass
    time.sleep(0.5)
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

    print(f"  [r{round_num}·{role}] {final_status} | "
          f"think={result['thought_chars']}c msg={result['message_chars']}c "
          f"outTok={output_tokens} | {duration:.0f}s", flush=True)
    return result


# 修复：_send 在权限响应中需要 proc 引用——用闭包包装
class _SessionPopen:
    """轻量包装让 _send 可访问 proc。"""
    pass


# ═══ 递归接力编排 ═══════════════════════════════════

def load_template(name):
    return (TEMPLATES / name).read_text()


def _next_archived_round(output_dir):
    """从归档目录确定下一绝对Round；跨调度窗口不重置。"""
    rounds_dir = Path(output_dir) / "rounds"
    nums = []
    if rounds_dir.exists():
        for path in rounds_dir.glob("round*"):
            try:
                nums.append(int(path.name.removeprefix("round")))
            except ValueError:
                continue
    return max(nums, default=0) + 1


def solve_problem(problem_text, output_dir, round_window_size=10):
    """运行一个 v2 调度窗口；未完成时保留资产供未来窗口继续。

    返回 dict：{status, rounds_completed, total_time_sec, proof_path, rounds: [...]}
    """
    if round_window_size <= 0:
        raise ValueError("round_window_size 必须是正整数")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    oc_traj_src = Path.home() / ".config/opencode/skills/oc-trajectory/scripts/oc_traj.py"

    rounds_results = []
    start = time.time()
    start_round = _next_archived_round(output_dir)

    for n in range(start_round, start_round + round_window_size):
        # 角色判定
        if n == 1:
            role = "solver_initial"
        elif n % 2 == 0:
            role = "observer"
        else:
            role = "solver"

        # 选模板 + 填充
        if n == 1:
            tpl_name = "prompt_round1.md"
            prompt = (load_template(tpl_name)
                      .replace("{PROBLEM}", problem_text))
        elif role == "observer":
            tpl_name = "prompt_observer.md"
            prev = n - 1
            prompt = (load_template(tpl_name)
                      .replace("{ROUND_NUM}", str(n))
                      .replace("{PREV_NUM}", str(prev))
                      .replace("{OC_TRAJ_PATH}", str(oc_traj_src)))
        else:
            tpl_name = "prompt_solver.md"
            prompt = (load_template(tpl_name)
                      .replace("{ROUND_NUM}", str(n))
                      .replace("{OC_TRAJ_PATH}", str(oc_traj_src)))

        # 每轮使用隔离工作区（复制历史轮次目录进去）
        round_work = output_dir / f".work_r{n}"
        if round_work.exists():
            shutil.rmtree(round_work)
        round_work.mkdir(parents=True)
        # 复制历史轮次供观察者引用
        hist_src = output_dir / "rounds"
        if hist_src.exists():
            shutil.copytree(hist_src, round_work / "rounds", dirs_exist_ok=True)
        # 复制 oc_traj 工具
        if oc_traj_src.exists():
            shutil.copy(oc_traj_src, round_work / OC_TRAJ_NAME)
        # 复制最新分析笔记到根（解题者轮的输入）
        latest_notes = output_dir / "rounds" / f"round{n-1}" / "分析笔记.md"
        if n >= 3 and latest_notes.exists():
            shutil.copy(latest_notes, round_work / "分析笔记.md")

        # 运行本轮
        print(f"\n{'='*50}", flush=True)
        print(f"Round {n} · {role} · round_window_size={round_window_size}", flush=True)
        print(f"{'='*50}", flush=True)

        result = run_round(n, role, prompt, round_work)

        # 归档产物到 problem 目录
        for fname in ("工作笔记.md", "分析笔记.md", "proof.md"):
            src_f = round_work / fname
            if src_f.exists():
                dest = output_dir / "rounds" / f"round{n}" / fname
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src_f, dest)

        rounds_results.append(result)

        # 终态判定
        status = result["final_status"]
        if status == "COMPLETED":
            proof_src = round_work / "proof.md"
            final_proof = output_dir / "proof.md"
            shutil.copy(proof_src, final_proof)
            break
        elif status == "ENDED_NO_PROOF":
            # 连续 ENDED_NO_PROOF 不重试同角色——切角色可能解决
            pass

    total_time = round(time.time() - start, 0)
    final_status = rounds_results[-1]["final_status"] if rounds_results else "UNKNOWN"
    completed = any(r.get("has_boxed") for r in rounds_results)

    summary = {
        "problem_chars": len(problem_text),
        "window_start_round": start_round,
        "window_rounds": len(rounds_results),
        "total_rounds": start_round - 1 + len(rounds_results),
        "next_round": start_round + len(rounds_results),
        "total_time_sec": total_time,
        "final_status": final_status,
        "completed": completed,
        "window_exhausted": not completed,
        "continuation_eligible": not completed,
        "rounds": rounds_results,
    }

    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1))

    print(f"\n{'='*50}")
    print(f"本次窗口结束: {final_status} | 绝对R{start_round}-R"
          f"{summary['next_round'] - 1} | {total_time:.0f}s | "
          f"completed={summary['completed']} | "
          f"continuation_eligible={summary['continuation_eligible']}")
    print(f"{'='*50}", flush=True)

    return summary


# ═══ CLI 入口 ═══════════════════════════════════════

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="v2 递归消化链单题管线")
    ap.add_argument("--problem-file", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--round-window-size", "--max-rounds",
                    dest="round_window_size", type=int, default=10,
                    help="本次调度窗口Round数；--max-rounds为兼容别名")
    args = ap.parse_args()

    problem = Path(args.problem_file).read_text()
    result = solve_problem(problem, args.output_dir, args.round_window_size)
    sys.exit(0 if result.get("completed") else 1)
