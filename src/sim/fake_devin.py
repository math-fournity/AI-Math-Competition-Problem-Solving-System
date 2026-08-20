"""fake_devin.py — 剧本演员：模拟devin cli的全流程行为

被launcher在tmux里启动（SIM_MODE=1时替换devin命令，见continuation_launcher
的launch_solve/start_handover）。不连DB、不依赖env——只读命令行参数和
work_dir/sim_scenario.json，按剧本写真文件后退出，让下游一切判定逻辑
（is_truncated/is_completed/check_handover/DONE.md检测/stall检测）面对
与生产完全相同的产物形态。

用法（launcher自动构造，无需手跑）：
  python -m src.sim.fake_devin --role solve --run-key K --round 2 \
      --work-dir W --export E
  python -m src.sim.fake_devin --role handover --run-key K --round 2 \
      --work-dir W --handover-out H

动作语义见scenarios.py的模块注释。所有动作先sleep --delay（默认3秒），
让主循环的poll节奏与真实运行一致。
"""
import argparse
import json
import sys
import time
from pathlib import Path


def load_scenario(work_dir):
    path = Path(work_dir) / "sim_scenario.json"
    if not path.exists():
        # 没有剧本文件=最保守行为：截断（系统会继续续传而不是误判完成）
        return {"name": "(default)", "solve": {"*": "truncate"}, "handover": "ok"}
    return json.loads(path.read_text())


def resolve_action(scenario, round_num):
    table = scenario.get("solve", {})
    return table.get(str(round_num)) or table.get("*") or "truncate"


def truncated_export():
    """截断态export——is_truncated判True的完整条件（对齐TRUNC_COMP_TOKENS_MIN=24000）"""
    return {
        "steps": [
            {
                "source": "agent",
                "reasoning_content": "让我继续深入思考这个问题的下一步。" * 80,
                "message": "",
                "tool_calls": [],
                "metrics": {"completion_tokens": 25000},
            }
        ]
    }


def completed_export():
    """完成态export——agent step有message输出（msg>0）"""
    return {
        "steps": [
            {
                "source": "agent",
                "reasoning_content": "经过完整的推导，结论已经清晰。",
                "message": "The final answer is $\\boxed{42}$.",
                "tool_calls": [],
                "metrics": {"completion_tokens": 8000},
            }
        ]
    }


def proof_text():
    # PROOF_COMPLETE_MARKER = r"\\boxed"（正则，匹配字面\boxed）——内容必须含\boxed
    return (
        "# Proof\n\n## Solution\n\nWe establish the result step by step.\n\n"
        "Step 1: Setup the framework and notation for the argument.\n\n"
        "Step 2: Reduce to the key inequality.\n\n"
        "Step 3: Conclude by combining the estimates above.\n\n"
        "Therefore the answer is $\\boxed{42}$.\n"
    )


def handover_text(round_num):
    # check_handover要求size>=500且mtime晚于启动——内容写给足
    return (
        f"# HANDOVER for round {round_num}\n\n"
        "## 上一轮进展\n- 已完成前半部分推导\n- 关键中间结论已记录\n\n"
        "## 当前卡点\n- 推理在最后一步被截断\n- 需要从中间结论继续\n\n"
        "## 下一轮建议\n- 从Step 3的估计式继续\n- 目标写出完整证明\n\n"
        "## 面包屑地图摘要\n- 见round_conversation_map.md\n\n" + "详细上下文。" * 40
    )


def act_solve(args, scenario):
    action = resolve_action(scenario, args.round)
    print(f"[fake_devin] role=solve run={args.run_key} round={args.round} action={action}")
    if action == "truncate":
        time.sleep(args.delay)
        Path(args.export).write_text(json.dumps(truncated_export(), indent=2))
        print(f"[fake_devin] 截断态export已写入: {args.export}")
        return 0
    if action == "complete":
        time.sleep(args.delay)
        Path(args.export).write_text(json.dumps(completed_export(), indent=2))
        (Path(args.work_dir) / "proof.md").write_text(proof_text())
        print(f"[fake_devin] 完成态export+proof.md已写入: {args.work_dir}")
        return 0
    if action == "dead":
        time.sleep(args.delay)
        print("[fake_devin] 模拟死亡：无产物直接退出")
        return 1
    if action == "stall":
        # 打印一行让pane有过活动，然后永远沉默——stall检测靠pane哈希静止
        print(f"[fake_devin] 模拟stall：round {args.round} 开始漫长思考...")
        time.sleep(999999)
        return 0
    print(f"[fake_devin] 未知动作: {action}，按截断处理")
    time.sleep(args.delay)
    Path(args.export).write_text(json.dumps(truncated_export(), indent=2))
    return 0


def act_handover(args, scenario):
    mode = scenario.get("handover", "ok")
    print(f"[fake_devin] role=handover run={args.run_key} round={args.round} mode={mode}")
    if mode == "timeout":
        # 不写文件不退出——check_handover超时后强制kill（回退v1）
        print("[fake_devin] 模拟Pipe A超时：挂起不产出")
        time.sleep(999999)
        return 0
    time.sleep(args.delay)
    Path(args.handover_out).write_text(handover_text(args.round))
    print(f"[fake_devin] HANDOVER.md已写入: {args.handover_out}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="全流程模拟的剧本演员（fake devin cli）")
    ap.add_argument("--role", choices=["solve", "handover"], required=True)
    ap.add_argument("--run-key", required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--export", default="", help="solve角色的export输出路径")
    ap.add_argument("--handover-out", default="", help="handover角色的HANDOVER.md输出路径")
    ap.add_argument("--delay", type=float, default=3.0, help="动作前延迟（模拟真实节奏）")
    args = ap.parse_args()

    scenario = load_scenario(args.work_dir)
    if args.role == "solve":
        sys.exit(act_solve(args, scenario))
    sys.exit(act_handover(args, scenario))


if __name__ == "__main__":
    main()
