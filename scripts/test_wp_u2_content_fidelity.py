#!/usr/bin/env python3
"""test_wp_u2_content_fidelity.py — WP-U2 内容完整性三路对比实验

三路同题独立运行，对比 thinking/message 的量级与判定链可组装性：
  --mode p_export     A 路：devin -p --export（glm-5-2，现状基准）
  --mode devin_acp    B 路：Devin ACP（glm-5-2，同模型跨模式受控对照）
  --mode opencode_acp C 路：OpenCode ACP（ox-alpha，目标管线）——含铁律15前置断言
  --mode analyze      组装器+指标对比+C路原生export对照（不调 API）

配额纪律：三路各 1 题 1 次；失败重跑最多 1 次并记录原因。

本脚本自身是长命令——必须放 tmux 里跑（长命令铁律），进度看 jsonl 增长。
"""
import argparse
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).parent.parent
WORK = REPO / "tmp" / "wp_u2"
TARGET_MODEL = "openrouter/stealth/ox-alpha"


def ts():
    return datetime.now(timezone.utc).isoformat()


class AcpClient:
    """最小 ACP 客户端（U1 骨架 + 权限自动批准 + 全通知落盘）"""

    def __init__(self, backend, log_path):
        self.backend = backend
        self.log_path = str(log_path)
        self.proc = None
        self.msg_id = 0
        self.session_id = None
        self.responses = {}
        self.lock = threading.Lock()
        self.running = False
        self.last_msg_ts = time.time()

    def _next_id(self):
        self.msg_id += 1
        return self.msg_id

    def _log(self, direction, msg):
        entry = {"ts": ts(), "dir": direction, "msg": msg}
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.last_msg_ts = time.time()
        with self.lock:
            if "id" in msg and ("result" in msg or "error" in msg):
                self.responses[msg["id"]] = msg.get("result", msg.get("error"))

    def _send(self, method, params=None):
        self.msg_id += 1
        msg = {"jsonrpc": "2.0", "method": method, "id": self.msg_id}
        if params:
            msg["params"] = params
        self._log("→", msg)
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        return msg["id"]

    def _reader_loop(self):
        while self.running:
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"  [non-JSON] {line[:150]}", flush=True)
                continue
            self._log("←", msg)
            if msg.get("method") == "session/request_permission" and "id" in msg:
                opts = msg.get("params", {}).get("options", [])
                pick = next((o["optionId"] for o in opts if o.get("kind") == "allow_once"),
                            (opts[0]["optionId"] if opts else "allow_once"))
                resp = {"jsonrpc": "2.0", "id": msg["id"],
                        "result": {"outcome": {"outcome": "selected", "optionId": pick}}}
                self._log("→", resp)
                self.proc.stdin.write(json.dumps(resp) + "\n")
                self.proc.stdin.flush()

    def start(self, cwd):
        cmd = ["devin", "acp", "--model", "glm-5-2"] if self.backend == "devin" \
            else ["opencode", "acp", "--cwd", cwd]
        print(f"[{ts()[11:19]}] 启动: {' '.join(cmd)}", flush=True)
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
        self.running = True
        threading.Thread(target=self._reader_loop, daemon=True).start()

    def wait_response(self, rid, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if rid in self.responses:
                    return self.responses[rid]
            time.sleep(1)
        return None

    def wait_silence(self, quiet_seconds, max_wait):
        deadline = time.time() + max_wait
        while time.time() < deadline:
            if time.time() - self.last_msg_ts >= quiet_seconds:
                return True
            time.sleep(2)
        return False

    def stop(self, try_close):
        if try_close and self.session_id:
            try:
                self._send("session/close", {"sessionId": self.session_id})
                time.sleep(1)
            except Exception:
                pass
        self.running = False
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


# === A 路：devin -p --export ===

def run_p_export(problem_file):
    work = WORK
    prompt_file = work / "a_prompt.txt"
    export_path = work / "a_export.json"
    prompt_text = Path(problem_file).read_text()
    prompt_file.write_text(prompt_text)

    cmd = ["devin", "-p",
           "--prompt-file", str(prompt_file),
           "--model", "glm-5-2",
           "--respect-workspace-trust", "false",
           "--permission-mode", "dangerous",
           "--export", str(export_path)]
    print(f"[A路] 启动 devin -p（同步等待完成，数学题可能 10-30 分钟）", flush=True)
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - t0
    ok = export_path.exists() and export_path.stat().st_size > 1000
    print(f"[A路] 完成：耗时 {elapsed:.0f}s，exit={result.returncode}，"
          f"export={'✅ ' + str(export_path.stat().st_size) + 'B' if ok else '❌ 缺失'}")
    return 0 if ok else 1


# === B/C 路：ACP ===

def run_acp(backend, problem_file):
    work = WORK
    tag = "b" if backend == "devin" else "c"
    log = work / f"{tag}_acp.jsonl"
    if log.exists():
        log.unlink()
    problem = Path(problem_file).read_text()
    cwd = str(work / f"{tag}_cwd")
    Path(cwd).mkdir(parents=True, exist_ok=True)

    c = AcpClient(backend, log)
    c.start(cwd=cwd)

    rid = c._send("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
    init = c.wait_response(rid, 15)
    print(f"[{tag}路] protocolVersion={init.get('protocolVersion')}", flush=True)

    rid = c._send("session/new", {"cwd": cwd, "mcpServers": []})
    new = c.wait_response(rid, 20)
    c.session_id = new.get("sessionId")
    print(f"[{tag}路] sessionId={c.session_id}", flush=True)

    # 铁律 15：OpenCode 后端必须显式设模型+强度并断言回显，fail-fast
    if backend == "opencode":
        rid = c._send("session/set_config_option", {
            "sessionId": c.session_id, "configId": "model", "value": TARGET_MODEL})
        r2 = c.wait_response(rid, 15)
        cur = next((o.get("currentValue") for o in (r2 or {}).get("configOptions", [])
                    if o.get("id") == "model"), None)
        print(f"[c路] set model 回显: {cur!r}", flush=True)
        assert cur == TARGET_MODEL, f"铁律15：模型未被接受 ({cur})"
        eff_opt = next((o for o in (r2 or {}).get("configOptions", [])
                        if o.get("id") == "effort"), None)
        assert eff_opt, "铁律15：切模型后未出现 effort 项"
        rid = c._send("session/set_config_option", {
            "sessionId": c.session_id, "configId": "effort", "value": "max"})
        r3 = c.wait_response(rid, 15)
        eff = next((o.get("currentValue") for o in (r3 or {}).get("configOptions", [])
                    if o.get("id") == "effort"), None)
        print(f"[c路] set effort=max 回显: {eff!r}", flush=True)
        assert eff == "max", f"铁律15：强度未被接受 ({eff})"

    t0 = time.time()
    rid = c._send("session/prompt", {
        "sessionId": c.session_id,
        "prompt": [{"type": "text", "text": problem}]})
    print(f"[{tag}路] 题目已发送（{len(problem)} 字符），等待完成…", flush=True)

    prompt_response = c.wait_response(rid, 2400)  # 数学题上限 40 分钟
    if prompt_response is None and backend == "opencode":
        # 兜底：response 未返回则静默检测（v2 实测 ox-alpha 会返回；双轨保险）
        print(f"[c路] 40 分钟无 response——转静默检测（120s）", flush=True)
        c.wait_silence(120, 600)
        prompt_response = c.wait_response(rid, 5)
    elapsed = time.time() - t0
    sr = (prompt_response or {}).get("stopReason")
    print(f"[{tag}路] 完成：{elapsed:.0f}s stopReason={sr} "
          f"response={'有' if prompt_response else '无'}", flush=True)

    counts_summary = {}
    with open(log) as f:
        for line in f:
            upd = json.loads(line)["msg"].get("params", {}).get("update", {})
            t = upd.get("sessionUpdate")
            if t:
                counts_summary[t] = counts_summary.get(t, 0) + 1
    print(f"[{tag}路] 信号计数: {counts_summary}", flush=True)

    c.stop(try_close=(backend == "opencode"))

    meta = {"sessionId": c.session_id, "elapsed": elapsed, "stopReason": sr,
            "counts": counts_summary}
    (work / f"{tag}_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return 0


# === 组装器与分析 ===

def assemble_acp(jsonl_path):
    """通知流 → ATIF 同构结构（U2 任务 2 原型）。"""
    thought, message, tool_calls = [], [], []
    first_ts = last_ts = None
    usage_out = None
    for line in open(jsonl_path):
        d = json.loads(line)
        m = d["msg"]
        upd = m.get("params", {}).get("update", {})
        st = upd.get("sessionUpdate")
        ts_ = d.get("ts")
        if ts_:
            first_ts = first_ts or ts_
            last_ts = ts_
        if st == "agent_thought_chunk":
            thought.append((upd.get("content") or {}).get("text") or "")
        elif st == "agent_message_chunk":
            message.append((upd.get("content") or {}).get("text") or "")
        elif st == "tool_call":
            tool_calls.append({"kind": upd.get("kind"), "title": upd.get("title")})
        elif st == "usage_update":
            u = upd.get("usage") or {}
            usage_out = u.get("outputTokens", usage_out)
    return {
        "steps": [{"source": "agent",
                   "reasoning_content": "".join(thought),
                   "message": "".join(message),
                   "tool_calls": tool_calls}],
        "metrics": {"completion_tokens": usage_out},
        "first_ts": first_ts, "last_ts": last_ts,
    }


def load_a_export(path):
    data = json.load(open(path))
    thought, message = [], []
    for s in data.get("steps", []):
        if s.get("source") == "agent":
            thought.append(s.get("reasoning_content") or "")
            message.append(s.get("message") or "")
    fm = data.get("final_metrics") or {}
    return {
        "steps": [{"source": "agent",
                   "reasoning_content": "".join(thought),
                   "message": "".join(message)}],
        "metrics": {"completion_tokens": fm.get("total_completion_tokens")},
    }


def try_judgment(struct, label):
    """对组装结构试跑原生判定字段需求（不 import launcher——避免门闸副作用）。"""
    s = struct["steps"][0]
    rc = len(s["reasoning_content"])
    msg = len(s["message"])
    tc = len(s.get("tool_calls") or [])
    comp = struct["metrics"].get("completion_tokens")
    # is_truncated 字段需求复刻：rc>1000 and msg==0 and tc==0 and comp>=24000
    trunc_fields = {"rc>1000": rc > 1000, "msg==0": msg == 0, "tc==0": tc == 0,
                    "comp>=24000": (comp >= 24000) if comp is not None else None}
    verdict = None
    if comp is not None:
        verdict = all([rc > 1000, msg == 0, tc == 0, comp >= 24000])
    print(f"  [{label}] rc={rc} msg={msg} tc={tc} comp={comp} "
          f"is_truncated字段需求={trunc_fields} 判定={verdict}")
    return {"label": label, "rc": rc, "msg": msg, "tool_calls": tc, "comp": comp}


def run_analyze():
    work = WORK
    print("=== 三路内容完整性对比 ===")
    results = {}

    a_path = work / "a_export.json"
    if a_path.exists():
        results["A_p_export"] = try_judgment(load_a_export(a_path), "A(-p基准)")
    else:
        print("  [A路] a_export.json 不存在")

    for tag, label in [("b", "B(devin_acp)"), ("c", "C(opencode_acp)")]:
        jl = work / f"{tag}_acp.jsonl"
        if not jl.exists():
            print(f"  [{label}] {jl.name} 不存在")
            continue
        asm = assemble_acp(jl)
        results[label] = try_judgment(asm, label)

    # C 路原生 export 对照（038 §八机制）
    c_meta = work / "c_meta.json"
    if c_meta.exists() and results.get("C(opencode_acp)"):
        sid = json.loads(c_meta.read_text()).get("sessionId")
        out = work / "c_native_export.json"
        r = subprocess.run(["opencode", "export", sid], capture_output=True, text=True)
        if r.returncode == 0 and len(r.stdout) > 100:
            out.write_text(r.stdout)
            data = json.loads(r.stdout)
            nat_thought = sum(len(p.get("text") or "")
                              for mm in data.get("messages", [])
                              for p in mm.get("parts", []) if p.get("type") == "reasoning")
            nat_msg = sum(len(p.get("text") or "")
                          for mm in data.get("messages", [])
                          for p in mm.get("parts", []) if p.get("type") == "text")
            print(f"\n=== C 路原生 export 对照 ===")
            print(f"  组装器: thought={results['C(opencode_acp)']['rc']} "
                  f"message={results['C(opencode_acp)']['msg']}")
            print(f"  原生export: reasoning={nat_thought} text={nat_msg}")
            ratio_t = results['C(opencode_acp)']['rc'] / nat_thought * 100 if nat_thought else 0
            print(f"  组装/原生 比: thought {ratio_t:.0f}% "
                  f"({'✅ 无损失' if ratio_t > 95 else '⚠️ 有缺口——逐项排查'}）")
        else:
            print(f"  [C路] opencode export 失败: {r.stderr[:200]}")

    (work / "metrics.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print("\nmetrics.json 已写。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem-file", default=str(WORK / "problem.txt"))
    ap.add_argument("--mode", required=True,
                    choices=["p_export", "devin_acp", "opencode_acp", "analyze"])
    args = ap.parse_args()

    if args.mode == "analyze":
        run_analyze()
        return
    if args.mode == "p_export":
        sys.exit(run_p_export(args.problem_file))
    sys.exit(run_acp(args.mode.replace("_acp", ""), args.problem_file))


if __name__ == "__main__":
    main()
