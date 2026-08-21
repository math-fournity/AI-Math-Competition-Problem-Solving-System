#!/usr/bin/env python3
"""test_wp_u1_acp_smoke.py — WP-U1 双后端 ACP 冒烟脚本

亲手复验双 ACP 后端在本机可用（直接检查铁律——037 的声称不算数）：
  --backend devin     → devin acp（glm-5-2）
  --backend opencode  → opencode acp --cwd <tmp>（ox-alpha，配置驱动）

流程（两后端同一套）：
  initialize → session/new → session/prompt（写读文件任务）
  → 全通知落盘 tmp/wp_u1_<backend>.jsonl → 统计信号 → 验证文件写出 → 终止

完成判定差异（skill 文档的核心差异）：
  devin     = 等 session/prompt 的 response（含 stopReason）
  opencode  = response 可能不返回——先短等 response（15s），再静默 30s 收尾

用法:
  python scripts/test_wp_u1_acp_smoke.py --backend devin
  python scripts/test_wp_u1_acp_smoke.py --backend opencode
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).parent.parent
PROMPT = ("Write the text 'U1 smoke ok' to the file {txt} (create it), "
          "then read the file back and tell me its content.")


class SmokeClient:
    def __init__(self, backend, log_path):
        self.backend = backend
        self.log_path = log_path
        self.proc = None
        self.msg_id = 0
        self.session_id = None
        self.responses = {}          # id -> result/error
        self.signals = []            # session/update 通知
        self.lock = threading.Lock()
        self.running = False
        self.last_msg_ts = time.time()

    def _next_id(self):
        self.msg_id += 1
        return self.msg_id

    def _log(self, direction, msg):
        ts = datetime.now(timezone.utc).isoformat()
        with open(self.log_path, "a") as f:
            f.write(json.dumps({"ts": ts, "dir": direction, "msg": msg},
                               ensure_ascii=False) + "\n")
        self.last_msg_ts = time.time()
        with self.lock:
            if "id" in msg and ("result" in msg or "error" in msg):
                self.responses[msg["id"]] = msg.get("result", msg.get("error"))
            upd = msg.get("params", {}).get("update", {})
            if upd.get("sessionUpdate"):
                self.signals.append({"ts": ts, "type": upd["sessionUpdate"]})

    def _send(self, method, params=None, notification=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        if not notification:
            msg["id"] = self._next_id()
        self._log("→", msg)
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        return msg.get("id")

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
                print(f"  [non-JSON] {line[:150]}")
                continue
            self._log("←", msg)
            # agent→client 请求（Devin 权限）：自动选第一个 allow 选项
            if "method" in msg and "id" in msg:
                if msg["method"] == "session/request_permission":
                    opts = msg.get("params", {}).get("options", [])
                    pick = next((o["optionId"] for o in opts
                                 if o.get("kind") == "allow_once"),
                                opts[0]["optionId"] if opts else "allow_once")
                    self._log("→", {"jsonrpc": "2.0", "id": msg["id"],
                                    "result": {"outcome": {
                                        "outcome": "selected", "optionId": pick}}})
                    self.proc.stdin.write(json.dumps(
                        {"jsonrpc": "2.0", "id": msg["id"],
                         "result": {"outcome": {
                             "outcome": "selected", "optionId": pick}}}) + "\n")
                    self.proc.stdin.flush()

    def start(self, cwd):
        if self.backend == "devin":
            cmd = ["devin", "acp", "--model", "glm-5-2"]
        else:
            cmd = ["opencode", "acp", "--cwd", cwd]
        print(f"启动: {' '.join(cmd)}")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
        self.running = True

        def err_reader():
            while self.running:
                line = self.proc.stderr.readline()
                if not line:
                    break
        threading.Thread(target=err_reader, daemon=True).start()
        threading.Thread(target=self._reader_loop, daemon=True).start()

    def wait_response(self, req_id, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if req_id in self.responses:
                    return self.responses[req_id]
            time.sleep(0.5)
        return None

    def wait_silence(self, quiet_seconds, max_wait):
        """等静默——quiet_seconds 无新消息即认为完成。"""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            if time.time() - self.last_msg_ts >= quiet_seconds:
                return True
            time.sleep(1)
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

    def summary(self):
        counts = {}
        with self.lock:
            for s in self.signals:
                counts[s["type"]] = counts.get(s["type"], 0) + 1
        print("\n=== 信号统计 ===")
        for t, c in sorted(counts.items()):
            print(f"  {t}: {c}")
        print(f"  总计: {len(self.signals)}")
        return counts


def run(backend):
    txt = f"/tmp/wp_u1_{backend}.txt"
    log = REPO / "tmp" / f"wp_u1_{backend}.jsonl"
    log.parent.mkdir(exist_ok=True)
    if log.exists():
        log.unlink()
    Path(txt).unlink(missing_ok=True)

    workdir = str(REPO / "tmp" / f"wp_u1_{backend}_cwd")
    Path(workdir).mkdir(parents=True, exist_ok=True)

    c = SmokeClient(backend, str(log))
    c.start(cwd=workdir)

    rid = c._send("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
    init = c.wait_response(rid, 15)
    pv = (init or {}).get("protocolVersion")
    print(f"initialize: protocolVersion={pv}")
    assert pv == 1, f"protocolVersion != 1: {pv}"

    rid = c._send("session/new", {"cwd": workdir, "mcpServers": []})
    resp = c.wait_response(rid, 20)
    c.session_id = (resp or {}).get("sessionId")
    print(f"session/new: {c.session_id}")
    assert c.session_id, "无 sessionId"

    t0 = time.time()
    rid = c._send("session/prompt", {
        "sessionId": c.session_id,
        "prompt": [{"type": "text", "text": PROMPT.format(txt=txt)}]})

    prompt_response = None
    if backend == "devin":
        prompt_response = c.wait_response(rid, 300)
    else:
        # OpenCode：response 可能不返回——短等 15s 后转静默检测
        prompt_response = c.wait_response(rid, 15)
        if prompt_response is None:
            print("（15s 内无 prompt response——转静默检测，符合 skill 预期）")
            c.wait_silence(quiet_seconds=30, max_wait=300)

    elapsed = time.time() - t0
    print(f"完成，耗时 {elapsed:.0f}s；prompt response: "
          f"{json.dumps(prompt_response, ensure_ascii=False)[:200] if prompt_response else '未返回'}")

    counts = c.summary()
    c.stop(try_close=(backend == "opencode"))

    # 验证文件写出
    ok = Path(txt).exists() and "U1 smoke ok" in Path(txt).read_text()
    print(f"\n文件写读任务: {'✅ 成功' if ok else '❌ 失败'}（{txt}: "
          f"{Path(txt).read_text()[:50] if Path(txt).exists() else '缺失'}）")

    thought = counts.get("agent_thought_chunk", 0)
    print(f"thought_chunk: {thought}（OpenCode 断言 >0：{'✅' if backend != 'opencode' or thought > 0 else '❌'}）")
    return {"counts": counts, "elapsed": elapsed, "file_ok": ok,
            "prompt_response": prompt_response, "thought": thought}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True, choices=["devin", "opencode"])
    args = ap.parse_args()
    result = run(args.backend)
    ok = result["file_ok"] and (args.backend != "opencode" or result["thought"] > 0)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
