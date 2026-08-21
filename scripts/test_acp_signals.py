#!/usr/bin/env python3
"""ACP 协议信号测试客户端——验证 devin acp 的所有 session/update 通知变体。

启动 devin acp 作为子进程，通过 stdin/stdout 交换 JSON-RPC 2.0 消息，
记录所有收到的信号（state_update / agent_thought_chunk / agent_message_chunk /
tool_call_update / plan_update / session/request_permission 等）。

用法:
    python scripts/test_acp_signals.py --prompt "1+1=?" --model glm-5-2
    python scripts/test_acp_signals.py --prompt-file /path/to/problem.txt --model glm-5-2
    python scripts/test_acp_signals.py --prompt "1+1=?" --timeout 60

输出:
    - 实时打印每个 JSON-RPC 消息（带时间戳和方向）
    - 结束时打印信号统计摘要
    - 完整日志写入 acp_test_log.jsonl
"""

import argparse
import json
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from datetime import datetime, timezone


class ACPClient:
    """最小 ACP 客户端——只做信号验证，不做权限处理（自动批准全部）。"""

    def __init__(self, model="glm-5-2", log_path="acp_test_log.jsonl"):
        self.model = model
        self.log_path = log_path
        self.proc = None
        self.msg_id = 0
        self.session_id = None
        self.signals = []  # 收到的所有信号
        self.signals_lock = threading.Lock()
        self.reader_thread = None
        self.running = False
        self.idle_event = threading.Event()
        self.permission_event = threading.Event()
        self.permission_response = True  # 自动批准

    def _next_id(self):
        self.msg_id += 1
        return self.msg_id

    def _log(self, direction, msg):
        """记录消息到日志和 stdout。"""
        ts = datetime.now(timezone.utc).isoformat()
        entry = {"ts": ts, "direction": direction, "msg": msg}
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # stdout 简洁打印
        method = msg.get("method", "")
        result = msg.get("result")
        error = msg.get("error")
        params = msg.get("params", {})
        update = params.get("update", {})
        session_update = update.get("sessionUpdate", "")

        if direction == "→":
            print(f"  [{ts[11:19]}] → {method} (id={msg.get('id','')})")
        elif direction == "←":
            if method:
                # notification or request from agent
                if session_update:
                    extra = ""
                    if session_update == "state_update":
                        extra = f" state={update.get('state','')} stopReason={update.get('stopReason','')}"
                    elif session_update == "tool_call_update":
                        extra = f" status={update.get('status','')} kind={update.get('kind','')} title={update.get('title','')[:60]}"
                    elif "chunk" in session_update:
                        content = update.get("content", {})
                        text = (content.get("text", "") or "")[:80]
                        extra = f" text={text!r}"
                    elif session_update in ("agent_message", "agent_thought", "user_message"):
                        content = update.get("content", [])
                        if content:
                            text = (content[0].get("text", "") or "")[:80]
                            extra = f" text={text!r}"
                    print(f"  [{ts[11:19]}] ← NOTIF {session_update}{extra}")
                    with self.signals_lock:
                        self.signals.append({
                            "ts": ts,
                            "type": session_update,
                            "detail": {k: v for k, v in update.items()
                                       if k not in ("content",) and v}
                        })
                elif method == "session/request_permission":
                    print(f"  [{ts[11:19]}] ← REQUEST {method}")
                    self.permission_event.set()
                else:
                    print(f"  [{ts[11:19]}] ← {method} (id={msg.get('id','')})")
            elif result is not None:
                print(f"  [{ts[11:19]}] ← RESULT (id={msg.get('id','')})")
            elif error is not None:
                print(f"  [{ts[11:19]}] ← ERROR (id={msg.get('id','')}) {error}")
            else:
                print(f"  [{ts[11:19]}] ← {msg}")
        else:
            print(f"  [{ts[11:19]}] {direction} {msg}")

    def _send(self, method, params=None, *, notification=False):
        """发送 JSON-RPC 消息到 devin acp stdin。"""
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        if not notification:
            msg["id"] = self._next_id()
        data = json.dumps(msg) + "\n"
        self._log("→", msg)
        self.proc.stdin.write(data)
        self.proc.stdin.flush()
        return msg.get("id")

    def _reader_loop(self):
        """读取 devin acp stdout 的 JSON-RPC 消息。"""
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
                # 可能是非 JSON 输出（日志？）
                print(f"  [non-JSON] {line[:200]}")
                continue

            self._log("←", msg)

            # 处理 agent → client 的请求（如 session/request_permission）
            if "method" in msg and "id" in msg:
                # 这是 agent 发来的请求，需要回复
                if msg["method"] == "session/request_permission":
                    # v1 格式: result.outcome = {"outcome": "selected", "optionId": "allow_once"}
                    # 选择第一个 allow_once 选项（或 allow_always）
                    options = msg.get("params", {}).get("options", [])
                    selected_option = None
                    for opt in options:
                        if opt.get("kind") == "allow_once":
                            selected_option = opt["optionId"]
                            break
                    if not selected_option and options:
                        selected_option = options[0]["optionId"]

                    response = {
                        "jsonrpc": "2.0",
                        "id": msg["id"],  # id 可以是 string 或 number
                        "result": {
                            "outcome": {
                                "outcome": "selected",
                                "optionId": selected_option or "allow_once",
                            }
                        },
                    }
                    self._log("→", response)
                    self.proc.stdin.write(json.dumps(response) + "\n")
                    self.proc.stdin.flush()
                    # 重置 permission event
                    self.permission_event.clear()

            # 处理 state_update: idle
            update = msg.get("params", {}).get("update", {})
            if update.get("sessionUpdate") == "state_update":
                if update.get("state") == "idle":
                    self.idle_event.set()

        self.running = False

    def start(self):
        """启动 devin acp 子进程。"""
        env = os.environ.copy()
        cmd = ["devin", "acp", "--model", self.model]
        print(f"启动: {' '.join(cmd)}")
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.running = True

        # stderr 单独读（避免阻塞）
        def stderr_reader():
            while self.running:
                line = self.proc.stderr.readline()
                if not line:
                    break
                print(f"  [stderr] {line.rstrip()[:200]}")
        threading.Thread(target=stderr_reader, daemon=True).start()

        # 启动 stdout reader
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()

    def initialize(self):
        """ACP initialize——协商协议版本和能力。devin acp 返回 protocolVersion=1（v1）。"""
        req_id = self._send("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {},
        })
        # 等待响应（reader thread 会打印）
        time.sleep(2)
        return req_id

    def new_session(self, cwd=None):
        """创建新 session。v1 协议要求 mcpServers 字段（可以为空数组）。"""
        params = {
            "cwd": cwd or os.getcwd(),
            "mcpServers": [],
        }
        req_id = self._send("session/new", params)
        # 等待响应——需要从响应中提取 sessionId
        time.sleep(2)
        # 从日志中提取 sessionId
        with open(self.log_path) as f:
            for line in f:
                entry = json.loads(line)
                msg = entry["msg"]
                if msg.get("id") == req_id and "result" in msg:
                    sid = msg["result"].get("sessionId")
                    if sid:
                        self.session_id = sid
                        print(f"  sessionId = {sid}")
                        return sid
        return None

    def prompt(self, text):
        """发送 prompt。v1 中 session/prompt 是 request-response——
        agent 处理完后返回 {stopReason: "end_turn"}。
        session/update 通知在处理期间推送。"""
        if not self.session_id:
            print("  错误：无 sessionId")
            return None
        params = {
            "sessionId": self.session_id,
            "prompt": [{"type": "text", "text": text}],
        }
        req_id = self._send("session/prompt", params)
        return req_id

    def wait_idle(self, timeout=300):
        """等待完成。v1 中 session/prompt 返回 result={stopReason} 表示完成。
        也检测 v2 的 state_update: idle（以防 devin 混用）。"""
        return self.idle_event.wait(timeout=timeout)

    def wait_prompt_response(self, req_id, timeout=300):
        """v1 模式：等待 session/prompt 的 response（含 stopReason）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with open(self.log_path) as f:
                for line in f:
                    entry = json.loads(line)
                    msg = entry["msg"]
                    if msg.get("id") == req_id and "result" in msg:
                        return msg["result"]
            time.sleep(1)
        return None

    def cancel(self):
        """取消当前操作。"""
        self._send("session/cancel", {
            "sessionId": self.session_id or "default",
        }, notification=True)

    def close_session(self):
        """关闭 session。"""
        self._send("session/close", {
            "sessionId": self.session_id or "default",
        })

    def stop(self):
        """停止子进程。"""
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

    def signal_summary(self):
        """打印信号统计。"""
        print("\n" + "=" * 60)
        print("信号统计摘要")
        print("=" * 60)
        with self.signals_lock:
            counts = {}
            for s in self.signals:
                t = s["type"]
                counts[t] = counts.get(t, 0) + 1
            for t, c in sorted(counts.items()):
                print(f"  {t}: {c}")
            print(f"  总计: {len(self.signals)} 个信号")

            # 打印时间线
            if len(self.signals) >= 2:
                first = self.signals[0]["ts"]
                last = self.signals[-1]["ts"]
                print(f"  首个信号: {first}")
                print(f"  末个信号: {last}")

            # 检测间隔——5分钟内无信号的情况
            if len(self.signals) >= 2:
                max_gap = 0
                max_gap_pair = None
                for i in range(1, len(self.signals)):
                    t1 = datetime.fromisoformat(self.signals[i-1]["ts"])
                    t2 = datetime.fromisoformat(self.signals[i]["ts"])
                    gap = (t2 - t1).total_seconds()
                    if gap > max_gap:
                        max_gap = gap
                        max_gap_pair = (i-1, i)
                print(f"  最大信号间隔: {max_gap:.1f}s (信号[{max_gap_pair[0]}]→[{max_gap_pair[1]}])")
        print("=" * 60)


def main():
    ap = argparse.ArgumentParser(description="ACP 协议信号测试客户端")
    ap.add_argument("--prompt", help="内联 prompt 文本")
    ap.add_argument("--prompt-file", help="从文件读取 prompt")
    ap.add_argument("--model", default="glm-5-2", help="模型名")
    ap.add_argument("--timeout", type=int, default=120, help="最大等待秒数")
    ap.add_argument("--log", default="acp_test_log.jsonl", help="日志文件路径")
    args = ap.parse_args()

    prompt_text = args.prompt
    if args.prompt_file:
        prompt_text = Path(args.prompt_file).read_text()
    if not prompt_text:
        print("错误：必须提供 --prompt 或 --prompt-file")
        sys.exit(1)

    # 清空旧日志
    with open(args.log, "w") as f:
        pass

    client = ACPClient(model=args.model, log_path=args.log)

    print("\n=== 阶段1: 启动 devin acp ===")
    client.start()
    time.sleep(1)

    print("\n=== 阶段2: initialize ===")
    client.initialize()
    time.sleep(2)

    print("\n=== 阶段3: session/new ===")
    client.new_session()
    time.sleep(1)

    print("\n=== 阶段4: session/prompt ===")
    print(f"  prompt: {prompt_text[:100]!r}")
    prompt_req_id = client.prompt(prompt_text)

    print("\n=== 阶段5: 等待 session/update 通知 + prompt response ===")
    print(f"  (最长等待 {args.timeout}s)")
    # v1 模式：等待 session/prompt 的 response（含 stopReason）
    # session/update 通知会在处理期间推送
    result = client.wait_prompt_response(prompt_req_id, timeout=args.timeout) if prompt_req_id else None

    if result:
        print(f"\n  ✓ 收到 prompt response: {result}")
    else:
        print(f"\n  ✗ {args.timeout}s 内未收到 prompt response——发送 cancel")
        client.cancel()
        time.sleep(2)

    print("\n=== 阶段6: 信号统计 ===")
    client.signal_summary()

    print("\n=== 阶段7: 关闭 ===")
    # devin acp 的 sessionCapabilities 没有 close——用 cancel + 进程终止
    try:
        client.cancel()
        time.sleep(1)
    except Exception:
        pass
    client.stop()

    print(f"\n完整日志: {args.log}")
    print("完成。")


if __name__ == "__main__":
    main()
