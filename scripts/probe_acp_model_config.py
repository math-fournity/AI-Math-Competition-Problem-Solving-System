#!/usr/bin/env python3
"""probe_acp_model_config.py — 探针：ACP 模型选择 + 思考强度(variants)机制实证

回答两个问题（2026-08-21 用户提出）：
  1. 思考强度怎么设？——session/set_config {configId:"effort", value:...}
     （前提：该模型在 models.dev 元数据里声明了 reasoning_options→variants）
  2. 如何确认 OpenCode 确实接受了模型？——set_config 的响应回显更新后的
     configOptions（含 currentValue），断言它即验证。

流程：initialize → session/new → 打印初始 configOptions → set_config 换
openrouter/stealth/ox-alpha → 断言回显 → 查 effort 项是否出现 → 有则设 high →
再断言 → 结束。
"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

TARGET_MODEL = "openrouter/stealth/ox-alpha"
LOG = Path("tmp/wp_probe_model.jsonl")


class Probe:
    def __init__(self):
        self.msg_id = 0
        self.responses = {}
        self.lock = threading.Lock()
        self.proc = None

    def _send(self, method, params=None, notification=False):
        self.msg_id += 1
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        if not notification:
            msg["id"] = self.msg_id
        with open(LOG, "a") as f:
            f.write(json.dumps({"dir": "→", "msg": msg}) + "\n")
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        return msg.get("id")

    def _reader(self):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            with open(LOG, "a") as f:
                f.write(json.dumps({"dir": "←", "msg": msg}) + "\n")
            with self.lock:
                if "id" in msg and ("result" in msg or "error" in msg):
                    self.responses[msg["id"]] = msg.get("result", msg.get("error"))
                # 权限自动批准
                if msg.get("method") == "session/request_permission":
                    opts = msg.get("params", {}).get("options", [])
                    pick = next((o["optionId"] for o in opts if o.get("kind") == "allow_once"),
                                (opts[0]["optionId"] if opts else "allow_once"))
                    resp = {"jsonrpc": "2.0", "id": msg["id"],
                            "result": {"outcome": {"outcome": "selected", "optionId": pick}}}
                    self.proc.stdin.write(json.dumps(resp) + "\n")
                    self.proc.stdin.flush()

    def wait(self, rid, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if rid in self.responses:
                    return self.responses[rid]
            time.sleep(0.3)
        return None


def main():
    LOG.parent.mkdir(exist_ok=True)
    LOG.unlink(missing_ok=True)
    cwd = str(Path("tmp/wp_u1_opencode_cwd").resolve())
    p = Probe()
    p.proc = subprocess.Popen(["opencode", "acp", "--cwd", cwd],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True)
    threading.Thread(target=p._reader, daemon=True).start()

    rid = p._send("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
    init = p.wait(rid)
    print(f"[1] initialize: protocolVersion={init.get('protocolVersion')}")

    rid = p._send("session/new", {"cwd": cwd, "mcpServers": []})
    new = p.wait(rid)
    sid = new.get("sessionId")
    initial_opts = new.get("configOptions", [])
    model_opt = next((o for o in initial_opts if o["id"] == "model"), {})
    print(f"[2] session/new: {sid}")
    print(f"    初始模型 currentValue = {model_opt.get('currentValue')!r}  ← 未显式选择时的落点")
    print(f"    初始 configOption ids = {[o['id'] for o in initial_opts]}")

    # 换目标模型——SDK 0.16.1 的方法名是 session/set_config_option
    rid = p._send("session/set_config_option", {"sessionId": sid,
                                                "configId": "model",
                                                "value": TARGET_MODEL})
    set_resp = p.wait(rid)
    opts_after = (set_resp or {}).get("configOptions", [])
    model_after = next((o for o in opts_after if o["id"] == "model"), {})
    accepted = model_after.get("currentValue")
    print(f"[3] set_config(model={TARGET_MODEL})")
    print(f"    响应回显 currentValue = {accepted!r}  "
          f"{'✅ 接受确认' if accepted == TARGET_MODEL else '❌ 未接受'}")
    ids_after = [o["id"] for o in opts_after]
    print(f"    切后 configOption ids = {ids_after}")

    # 若出现 effort 项 → 设置思考强度
    effort_opt = next((o for o in opts_after if o["id"] == "effort"), None)
    if effort_opt:
        values = [x["value"] for x in effort_opt.get("options", [])]
        print(f"[4] 该模型声明了思考强度 variants: {values}"
              f"（当前 {effort_opt.get('currentValue')!r}）")
        want = "max" if "max" in values else ("high" if "high" in values else values[-1])
        rid = p._send("session/set_config_option", {"sessionId": sid,
                                                    "configId": "effort", "value": want})
        eff_resp = p.wait(rid)
        eff_after = next((o for o in (eff_resp or {}).get("configOptions", [])
                          if o["id"] == "effort"), {})
        got = eff_after.get("currentValue")
        print(f"    set_config(effort={want}) → 回显 {got!r} "
              f"{'✅' if got == want else '❌'}")
    else:
        print("[4] 该模型未声明思考强度 variants（models.dev 无 reasoning_options）"
              "——effort 不可用，思考行为由模型默认控制")

    p._send("session/close", {"sessionId": sid})
    time.sleep(1)
    try:
        p.proc.terminate()
    except Exception:
        pass
    print("[done]")


if __name__ == "__main__":
    main()
