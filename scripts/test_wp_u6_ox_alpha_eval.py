#!/usr/bin/env python3
"""test_wp_u6_ox_alpha_eval.py — WP-U6 Ox Alpha 数学能力批量评估

按 manifest 逐题：OpenCode ACP 会话（铁律15断言）→ INITIAL_PROMPT_TEMPLATE 原文
注入 → 收集通知/proof.md → 记录耗时与产出。长命令——放 tmux 跑。

用法：
  python scripts/test_wp_u6_ox_alpha_eval.py                # 全量10题
  python scripts/test_wp_u6_ox_alpha_eval.py --start-from deepmath_103k_00000047
"""
import argparse
import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).parent.parent
WORK = REPO / "tmp" / "wp_u6"
TARGET_MODEL = "openrouter/stealth/ox-alpha"

# 原文模板（src/continuation_launcher.py INITIAL_PROMPT_TEMPLATE 一字不改——兼容性测试）
INITIAL_PROMPT_TEMPLATE = """{original_problem}

请解答上面的数学题。

要求：
1. 给出完整的解答过程
2. 最终答案用 \\boxed{{答案}} 格式给出
3. 数学公式用LaTeX
4. 把证明写到proof.md文件中，不要在对话里输出完整证明

=== 工具使用与防作弊约束 ===

你可以使用工具（Python代码、Lean代码、计算器）辅助解题，也可以进行网络搜索。
但本题必须靠你自己的数学推理能力解决——不能靠"找到答案"解决。

合法使用：
- 用Python做数值计算/符号计算验证你的猜想
- 用Lean形式化验证你的推理步骤
- 搜索通用数学知识（如"群的定义""Hausdorff空间性质"）

作弊行为（禁止）：
- 搜索题目文本本身（可能搜到标准解答）
- 翻找硬盘上的trajectory目录或数据库中的解题记录
- 搜索后直接引用搜到的完整证明
- 查资料时找到关键定理的完整证明后直接抄（你自己推不出来的部分）

主动声明义务：
如果你在搜索/查资料过程中遇到了和题目解答直接相关的内容，你必须在proof.md
开头加一个"作弊风险声明"章节，说明：
1. 你通过什么方式接触到了什么相关内容
2. 你对这些内容的使用情况（直接引用/参考/虽然看到但独立推导）

不声明但被审计AI发现作弊 = 该题作废。
声明了但确实独立推导 = 该题有效但附注。
"""


def ts():
    return datetime.now(timezone.utc).isoformat()


class AcpClient:
    def __init__(self, log_path):
        self.log_path = str(log_path)
        self.proc = None
        self.msg_id = 0
        self.session_id = None
        self.responses = {}
        self.lock = threading.Lock()
        self.running = False
        self.last_msg_ts = time.time()

    def _send(self, method, params=None):
        self.msg_id += 1
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        msg["id"] = self.msg_id
        with open(self.log_path, "a") as f:
            f.write(json.dumps({"ts": ts(), "dir": "→", "msg": msg}, ensure_ascii=False) + "\n")
        self.last_msg_ts = time.time()
        with self.lock:
            self.responses[self.msg_id] = {"pending": True}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        return self.msg_id

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
                continue
            with open(self.log_path, "a") as f:
                f.write(json.dumps({"ts": ts(), "dir": "←", "msg": msg}, ensure_ascii=False) + "\n")
            self.last_msg_ts = time.time()
            with self.lock:
                if "id" in msg and ("result" in msg or "error" in msg):
                    self.responses[msg["id"]] = msg.get("result", msg.get("error"))
            if msg.get("method") == "session/request_permission" and "id" in msg:
                opts = msg.get("params", {}).get("options", [])
                pick = next((o["optionId"] for o in opts if o.get("kind") == "allow_once"),
                            (opts[0]["optionId"] if opts else "allow_once"))
                resp = {"jsonrpc": "2.0", "id": msg["id"],
                        "result": {"outcome": {"outcome": "selected", "optionId": pick}}}
                self.proc.stdin.write(json.dumps(resp) + "\n")
                self.proc.stdin.flush()

    def call(self, method, params, timeout):
        rid = self._send(method, params)
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                v = self.responses.get(rid)
                if v is not None and not isinstance(v, dict) or (
                        isinstance(v, dict) and not v.get("pending")):
                    return v
            time.sleep(0.5)
        return None

    def wait_silence(self, quiet, max_wait):
        deadline = time.time() + max_wait
        while time.time() < deadline:
            if time.time() - self.last_msg_ts >= quiet:
                return True
            time.sleep(2)
        return False

    def stop(self, try_close=True):
        """终止 acp server 子进程（防孤儿进程累积——U6 执行中实证的坑）"""
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


def eval_one(entry, effort="max"):
    pid = entry["run_key"].replace("p27-full-", "")
    work = WORK / pid
    work.mkdir(parents=True, exist_ok=True)
    log = work / f"{pid}.jsonl"
    if log.exists():
        log.unlink()

    prompt = INITIAL_PROMPT_TEMPLATE.format(original_problem=entry["problem_text"])
    c = AcpClient(str(log))
    c.proc = subprocess.Popen(["opencode", "acp", "--cwd", str(work)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True)
    c.running = True
    threading.Thread(target=c._reader_loop, daemon=True).start()

    init = c.call("initialize", {"protocolVersion": 1, "clientCapabilities": {}}, 15)
    new = c.call("session/new", {"cwd": str(work), "mcpServers": []}, 20)
    c.session_id = new.get("sessionId")

    r2 = c.call("session/set_config_option",
                {"sessionId": c.session_id, "configId": "model", "value": TARGET_MODEL}, 15)
    cur = next((o.get("currentValue") for o in (r2 or {}).get("configOptions", [])
                if o.get("id") == "model"), None)
    assert cur == TARGET_MODEL, f"铁律15 model 未接受: {cur}"
    eff_opt = next((o for o in (r2 or {}).get("configOptions", []) if o.get("id") == "effort"), None)
    assert eff_opt, "铁律15 effort 项缺失"
    r3 = c.call("session/set_config_option",
                {"sessionId": c.session_id, "configId": "effort", "value": effort}, 15)
    eff = next((o.get("currentValue") for o in (r3 or {}).get("configOptions", [])
                if o.get("id") == "effort"), None)
    assert eff == effort, f"铁律15 effort 未接受: {eff}"

    t0 = time.time()
    rid = c.call.__wrapped__ if False else c._send(
        "session/prompt", {"sessionId": c.session_id,
                           "prompt": [{"type": "text", "text": prompt}]})
    resp = None
    deadline = time.time() + 2400
    while time.time() < deadline:
        with c.lock:
            v = c.responses.get(rid)
            if v is not None and (not isinstance(v, dict) or not v.get("pending")):
                resp = v
                break
        time.sleep(2)
    elapsed = time.time() - t0
    sr = (resp or {}).get("stopReason")
    print(f"  [{pid}] 完成 {elapsed:.0f}s stopReason={sr}", flush=True)

    # 组装 message 与 usage
    msgs, thought_len = [], 0
    usage_out = None
    for line in open(log):
        d = json.loads(line)
        m = d["msg"]
        upd = m.get("params", {}).get("update", {})
        st = upd.get("sessionUpdate")
        if st == "agent_message_chunk":
            msgs.append((upd.get("content") or {}).get("text") or "")
        elif st == "agent_thought_chunk":
            thought_len += len((upd.get("content") or {}).get("text") or "")
        elif st == "usage_update":
            u = upd.get("usage") or {}
            usage_out = u.get("outputTokens", usage_out)
    full_msg = "".join(msgs)
    boxed = re.findall(r"\\boxed\{([^}]*)\}", full_msg)
    try:
        resp_usage = (resp or {}).get("usage", {}).get("outputTokens")
    except Exception:
        resp_usage = None
    proof_md = work / "proof.md"
    proof_boxed = None
    if proof_md.exists():
        proof_boxed = re.findall(r"\\boxed\{([^}]*)\}", proof_md.read_text())

    result = {
        "run_key": entry["run_key"], "layer": entry["layer"],
        "elapsed": round(elapsed), "stopReason": sr,
        "msg_chars": len(full_msg), "thought_chars": thought_len,
        "boxed_in_message": boxed[:3], "proof_md_exists": proof_md.exists(),
        "boxed_in_proof": [b[:80] for b in (proof_boxed or [])][:3],
        "outputTokens_stream": usage_out, "outputTokens_response": resp_usage,
        "sessionId": c.session_id,
    }
    (work / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"  [{pid}] msg={len(full_msg)}c thought={thought_len}c "
          f"boxed(msg)={len(boxed)} proof.md={proof_md.exists()} "
          f"outTok={resp_usage or usage_out}", flush=True)

    c.stop(try_close=True)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(WORK / "manifest.json"))
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--start-from", help="从此 pid 开始（断点续跑）")
    ap.add_argument("--effort", default="max",
                    help="推理强度（阶段2诊断用 low/max 对比）")
    args = ap.parse_args()

    manifest = json.load(open(args.manifest))
    started = args.start_from is None
    results = []
    for entry in manifest:
        pid = entry["run_key"].replace("p27-full-", "")
        if not started:
            if pid == args.start_from:
                started = True
            else:
                continue
        if len(results) >= args.limit:
            break
        print(f"[{ts()[11:19]}] === {entry['layer']} {pid} ===", flush=True)
        try:
            results.append(eval_one(entry, args.effort))
        except AssertionError as e:
            print(f"  [{pid}] ❌ 断言失败: {e}", flush=True)
            results.append({"run_key": entry["run_key"], "layer": entry["layer"],
                            "error": str(e)})
        except Exception as e:
            print(f"  [{pid}] ❌ 异常: {e}", flush=True)
            results.append({"run_key": entry["run_key"], "layer": entry["layer"],
                            "error": str(e)})

    out = WORK / "eval_results.json"
    prev = json.loads(out.read_text()) if out.exists() else []
    prev.extend(results)
    out.write_text(json.dumps(prev, ensure_ascii=False, indent=1))
    print(f"\n共 {len(prev)} 条结果写入 {out}")


if __name__ == "__main__":
    main()
