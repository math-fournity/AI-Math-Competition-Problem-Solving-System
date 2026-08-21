#!/usr/bin/env python3
"""acp_v2.py — 观察者/做题者两阶段递归接力驱动器。

用法：python3 acp_v2.py <round_num>
流程：
  1. 重建隔离现场 /tmp/p275-1962-v2/，复制 round1..round{N-1} 的 笔记+thinking+thoughts.jsonl
  2. 组装prompt（轮1用prompt_round1.md；轮N≥2用prompt_roundN.md填充轮次号）
  3. 启动opencode ACP（两步断言：model=ox-alpha / effort=max，fail-fast）
  4. 实时落盘 thoughts.jsonl；完成检测=prompt response或静默30s（pending tool放宽600s）
  5. 归档至 v2run/roundN/（工作笔记/分析笔记/proof/thinking/thoughts/meta）并打印监督摘要
"""
import json
import shutil
import subprocess
import select
import sys
import time
from pathlib import Path

REPO = Path("/Users/user/glm5.2-math-worktree")
V2 = REPO / "Tell分类学研究过程文档/poc_assets/poc_2.7.5/v2"
RUN = REPO / "Tell分类学研究过程文档/poc_assets/poc_2.7.5/v2run"
SKILL = Path("/Users/user/.config/opencode/skills/oc-trajectory/scripts/oc_traj.py")
CWD = Path("/tmp/p275-1962-v2")
MODEL = "openrouter/stealth/ox-alpha"
EFFORT = "max"
SILENT = 300
MAXRT = 120 * 60


def rpc(proc, method, params, rid, timeout=25):
    send(proc, {"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
    dl = time.time() + timeout
    while time.time() < dl:
        m = read_msg(proc, 5)
        if m is None:
            continue
        if m.get("id") == rid and ("result" in m or "error" in m):
            return m
    return {"error": {"code": -1, "message": f"timeout {method}"}}


def send(proc, msg):
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def read_msg(proc, timeout):
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


def assert_config(proc, sid, cid, value, rid, log):
    for method in ("session/set_config_option", "session/set_config"):
        resp = rpc(proc, method, {"sessionId": sid, "configId": cid, "value": value}, rid)
        if "error" in resp:
            msg = str(resp["error"].get("message", ""))[:200]
            if "method" in msg.lower() or "not found" in msg.lower():
                continue
            return False, {"step": cid, "error": msg}
        opts = resp.get("result", {}).get("configOptions", [])
        cur = next((o.get("currentValue") for o in opts if o.get("id") == cid), None)
        log[f"{cid}_echo"] = {"method": method, "configOptions": opts}
        if cur == value:
            return True, opts
        return False, {"step": cid, "error": f"echo mismatch set={value} echo={cur}"}
    return False, {"step": cid, "error": "no recognized method"}


def main():
    n = int(sys.argv[1])
    role = sys.argv[2] if len(sys.argv) > 2 else "auto"
    prev = n - 1
    tag = f"r{n}"
    # ---- 1. 现场准备 ----
    if CWD.exists():
        shutil.rmtree(CWD)
    CWD.mkdir(parents=True)
    rounds_src = RUN / "rounds"
    rounds_dst = CWD / "rounds"
    rounds_dst.mkdir(exist_ok=True)
    for p in sorted(rounds_src.glob("round*")):
        if int(p.name[5:]) < n:
            shutil.copytree(p, rounds_dst / p.name)
    shutil.copy(SKILL, CWD / "oc_traj.py")
    print(f"[stage] 现场={CWD} 历史轮次={[p.name for p in sorted(rounds_dst.iterdir())]}", flush=True)

    # ---- 2. prompt ----
    tplname = {"observer": "prompt_observer.md", "solver": "prompt_solver.md"}.get(
        role, "prompt_round1.md" if n == 1 else "prompt_roundN.md")
    tpl = (V2 / tplname).read_text()
    prompt_text = tpl.replace("{ROUND_NUM}", str(n)).replace("{PREV_NUM}", str(prev))
    OUT = CWD / f"acp_out_{tag}"
    OUT.mkdir(exist_ok=True)
    (OUT / "prompt_sent.txt").write_text(prompt_text)

    # ---- 3. ACP会话 ----
    stderr_log = open(OUT / "server_stderr.log", "wb")
    proc = subprocess.Popen(["opencode", "acp", "--cwd", str(CWD)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=stderr_log, bufsize=0)
    result = {"round": n, "model": MODEL, "effort": EFFORT,
              "launch_assertions": {}}
    resp = rpc(proc, "initialize", {"protocolVersion": 1, "clientCapabilities": {}}, 1)
    result["protocolVersion"] = resp.get("result", {}).get("protocolVersion")
    resp = rpc(proc, "session/new", {"cwd": str(CWD), "mcpServers": []}, 2)
    sid = resp["result"]["sessionId"]
    result["sessionId"] = sid
    ok, info = assert_config(proc, sid, "model", MODEL, 10, result["launch_assertions"])
    if not ok:
        result["launch_assertions"]["FAILED"] = info
        (OUT / "launch_result.json").write_text(json.dumps(result, indent=2))
        print(f"FATAL model: {info}")
        sys.exit(1)
    ok, info = assert_config(proc, sid, "effort", EFFORT, 11, result["launch_assertions"])
    if not ok:
        result["launch_assertions"]["FAILED"] = info
        (OUT / "launch_result.json").write_text(json.dumps(result, indent=2))
        print(f"FATAL effort: {info}")
        sys.exit(1)
    (OUT / "launch_result.json").write_text(json.dumps(result, indent=2))
    print(f"[assert] model✓ effort=max✓ session={sid}", flush=True)

    tf = open(OUT / "thoughts.jsonl", "w")
    mf = open(OUT / "messages.jsonl", "w")
    tools_f = open(OUT / "tools.jsonl", "w")

    def dump(f, obj):
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()

    send(proc, {"jsonrpc": "2.0", "id": 99, "method": "session/prompt",
                "params": {"sessionId": sid,
                           "prompt": [{"type": "text", "text": prompt_text}]}})
    print("[prompt] 已发送", flush=True)
    start = last = time.time()
    counts = {"thought": 0, "message": 0, "tool": 0}
    tools_state = {}
    prompt_response = None
    while True:
        if proc.poll() is not None:
            print("[done] opencode进程已退出", flush=True)
            break
        r, _, _ = select.select([proc.stdout], [], [], 5)
        now = time.time()
        if not r:
            pending = any(s not in ("completed", "error")
                          for s in tools_state.values())
            thr = 600 if pending else SILENT
            if now - last >= thr:
                break
            if now - start >= MAXRT:
                send(proc, {"jsonrpc": "2.0", "method": "session/cancel",
                            "params": {"sessionId": sid}})
                result["cancelled"] = True
                break
            continue
        raw = proc.stdout.readline()
        if not raw:
            break
        last = now
        try:
            msg = json.loads(raw.decode())
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 99 and ("result" in msg or "error" in msg):
            prompt_response = msg
            break
        upd = msg.get("params", {}).get("update", {})
        su = upd.get("sessionUpdate", "")
        ts = round(time.time() - start, 1)
        if su == "agent_thought_chunk":
            dump(tf, {"t": ts, "mid": upd.get("messageId"),
                      "text": upd.get("content", {}).get("text", "")})
            counts["thought"] += 1
        elif su == "agent_message_chunk":
            dump(mf, {"t": ts, "mid": upd.get("messageId"),
                      "text": upd.get("content", {}).get("text", "")})
            counts["message"] += 1
        elif su in ("tool_call", "tool_call_update"):
            tid, st = upd.get("toolCallId"), upd.get("status")
            if tid and st:
                tools_state[tid] = st
            dump(tools_f, {"t": ts, "kind": su, "title": upd.get("title"),
                           "status": st, "toolCallId": tid})
            counts["tool"] += 1
    for f in (tf, mf, tools_f):
        f.close()

    usage = (prompt_response or {}).get("result", {}).get("usage", {})
    proof = (CWD / "proof.md")
    notes = {
        "工作笔记": (CWD / "工作笔记.md").exists(),
        "分析笔记": (CWD / "分析笔记.md").exists(),
    }
    # 截断指纹：outputTokens恰为整上限值即判（message/tool计数不再作为必要条件——
    # 解题者轮可能用工具后仍被截断，R4实证）
    truncated = (usage.get("outputTokens") == 32000)
    result.update({
        "counts": counts, "usage": usage, "notes_present": notes,
        "proof_md": proof.exists(),
        "boxed": proof.exists() and "\\boxed" in proof.read_text(),
        "budget_starved_fingerprint": bool(truncated),
        "duration_sec": round(time.time() - start, 1),
    })
    result["final_status"] = (
        "COMPLETED" if result["boxed"] else
        "BUDGET_STARVED" if truncated else
        "ENDED_NO_PROOF" if not proof.exists() else "PROOF_NO_BOXED")
    (OUT / "launch_result.json").write_text(json.dumps(result, indent=2))

    # ---- 5. 归档 ----
    arch = RUN / "rounds" / f"round{n}"
    arch.mkdir(parents=True, exist_ok=True)
    thinking = "".join(json.loads(l).get("text", "")
                       for l in open(OUT / "thoughts.jsonl"))
    (arch / "thinking.md").write_text(thinking)
    shutil.copy(OUT / "thoughts.jsonl", arch / "thoughts.jsonl")
    shutil.copy(OUT / "launch_result.json", arch / "meta_launch.json")
    for name in ("工作笔记.md", "分析笔记.md", "proof.md"):
        src = CWD / name
        if src.exists():
            shutil.copy(src, arch / name)
    exp = subprocess.run(["opencode", "export", sid], capture_output=True,
                         text=True, timeout=120)
    (arch / "opencode_export_raw.txt").write_text(exp.stdout[-200000:])
    print(json.dumps({k: result[k] for k in
                      ("final_status", "counts", "notes_present", "boxed",
                       "budget_starved_fingerprint")},
                     ensure_ascii=False, indent=2))
    try:
        send(proc, {"jsonrpc": "2.0", "id": 200, "method": "session/close",
                    "params": {"sessionId": sid}})
    except Exception:
        pass
    proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
