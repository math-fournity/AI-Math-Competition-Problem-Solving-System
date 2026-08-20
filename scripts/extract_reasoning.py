#!/usr/bin/env python3
"""
从 conversation.json / export.json 提取所有 agent step 的 reasoning_content。

用法：
    python3 extract_reasoning.py <export.json路径> [-o <输出路径>]
    python3 extract_reasoning.py <export.json路径> --stdout

默认输出：与输入同目录的 <stem>_reasoning.txt
每个 agent step 的 reasoning_content 前加分隔标记：
    === STEP {idx} (step_id={id}) reasoning_content [{N}c] ===
"""
import json
import sys
import argparse
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("-o", "--output")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()

    data = json.loads(Path(args.export).read_text(encoding="utf-8"))
    steps = data.get("steps", []) if isinstance(data, dict) else []
    parts = []
    for idx, st in enumerate(steps):
        if not isinstance(st, dict):
            continue
        if st.get("source") != "agent":
            continue
        rc = st.get("reasoning_content") or ""
        sid = st.get("step_id", "?")
        parts.append(f"\n\n=== STEP {idx} (step_id={sid}) reasoning_content [{len(rc)}c] ===\n{rc}")
    out = "\n".join(parts).strip() + "\n"
    if args.stdout:
        sys.stdout.write(out)
        return
    outp = Path(args.output) if args.output else Path(args.export).with_name(
        Path(args.export).stem + "_reasoning.txt")
    outp.write_text(out, encoding="utf-8")
    print(f"wrote {outp} ({len(out)}c)")


if __name__ == "__main__":
    main()
