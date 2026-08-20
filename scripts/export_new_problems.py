#!/usr/bin/env python3
"""export_new_problems.py — 从A系统（解题系统A）导出新的失败题到B系统的problem_list.json

A系统 = /Users/user/glm5.2-math-worktree/（devin_problem_runs集合）
B系统 = 当前repo（p27_continuation_runs集合）

B系统的目的是把A系统没做出来的题（模型能力失败）用续传方法重做。
本脚本查A系统的失败题，排除B系统已有的题，导出为新的problem_list条目。

用法:
  python -m scripts.export_new_problems --batch-id p27-full
  python -m scripts.export_new_problems --batch-id p27-full --limit 100  # 测试
  python -m scripts.export_new_problems --batch-id p27-full --dry-run    # 只看不写
"""
import argparse
import json
import os
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from arango import ArangoClient

# A系统模型能力失败的status（不重试的失败）
MODEL_FAILURE_STATUSES = [
    'failed_token_limit', 'ai_gave_up', 'failed_thinking_spin',
    'failed_tool_stall', 'failed_no_proof', 'failed_stall'
]

# 文件路径
PROBLEM_LIST_FILE = PROJECT_ROOT / "data" / "poc_2.7" / "problem_list.json"
TRAJECTORY_BASE = "/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory"


def connect_db():
    """连接ArangoDB"""
    host = os.environ.get('ARANGO_HOST', 'http://localhost:8529')
    dbname = os.environ.get('ARANGO_DB', 'xishujuzhen_math_glm52')
    user = os.environ.get('ARANGO_USER', 'root')
    password = os.environ.get('ARANGO_PASS', '')
    c = ArangoClient(hosts=host)
    return c.db(dbname, username=user, password=password)


def get_a_failed_problems(db):
    """查A系统所有模型能力失败的题（每个题取最后一次run的status）"""
    failed = list(db.aql.execute(
        'FOR r IN devin_problem_runs '
        'FILTER r.status IN @statuses '
        'COLLECT pid = r.problem_id INTO runs = r '
        'LET last_run = (FOR x IN runs SORT x.ended_at DESC LIMIT 1 RETURN x)[0] '
        'FILTER last_run.status IN @statuses '
        'RETURN {problem_id: pid, exp_id: last_run.exp_id, status: last_run.status}',
        bind_vars={'statuses': MODEL_FAILURE_STATUSES}, ttl=300))
    return failed


def get_b_existing_pids(db):
    """查B系统已有的problem_id集合"""
    pids = list(db.aql.execute(
        'FOR r IN p27_continuation_runs RETURN r.problem_id', ttl=60))
    return set(pids)


def build_problem_entry(problem):
    """从A系统的失败题构造B系统的problem_list条目"""
    pid = problem['problem_id']
    exp_id = problem['exp_id']
    seed_export = f"{TRAJECTORY_BASE}/{exp_id}/exports/conversation.json"
    problem_file = f"{TRAJECTORY_BASE}/_pipe/problems/{exp_id}/AGENTS.md"
    solver_dir = f"/Volumes/data/math-agent-glm5.2-tmux-agents-dir/{exp_id}"

    return {
        "problem_id": pid,
        "exp_id": exp_id,
        "seed_export": seed_export,
        "problem_path": f"{solver_dir}/problem.txt",
        "agents_md_path": problem_file,
        "export_exists": os.path.exists(seed_export),
    }


def main():
    parser = argparse.ArgumentParser(description="从A系统导出新失败题到B系统")
    parser.add_argument("--batch-id", default="p27-full", help="B系统batch_id")
    parser.add_argument("--limit", type=int, help="限制导出题数（测试用）")
    parser.add_argument("--dry-run", action="store_true", help="只看不写")
    parser.add_argument("--output", default=str(PROBLEM_LIST_FILE),
                        help="输出文件路径")
    args = parser.parse_args()

    print(f"=== 从A系统导出新失败题到B系统 ===")
    print(f"  batch_id: {args.batch_id}")
    print()

    db = connect_db()

    # 1. 查A系统失败题
    print("查询A系统失败题...")
    a_failed = get_a_failed_problems(db)
    print(f"  A系统失败题总数: {len(a_failed)}")

    # 2. 查B系统已有题
    print("查询B系统已有题...")
    b_pids = get_b_existing_pids(db)
    print(f"  B系统已有题: {len(b_pids)}")

    # 3. 计算需要新增的题
    new_problems = [p for p in a_failed if p['problem_id'] not in b_pids]
    print(f"  需要新增的题: {len(new_problems)}")

    if args.limit:
        new_problems = new_problems[:args.limit]
        print(f"  限制导出: {len(new_problems)}题")

    # 4. 构造problem_list条目
    print("\n构造problem_list条目...")
    entries = []
    skip_no_export = 0
    for p in new_problems:
        entry = build_problem_entry(p)
        if not entry["export_exists"]:
            skip_no_export += 1
            continue  # 跳过seed_export不存在的题
        entries.append(entry)

    print(f"  可导入（seed_export存在）: {len(entries)}")
    print(f"  跳过（seed_export缺失）: {skip_no_export}")

    if not entries:
        print("\n无新题可导入。")
        return

    # 5. 合并到现有problem_list
    existing = []
    if PROBLEM_LIST_FILE.exists():
        with open(PROBLEM_LIST_FILE) as f:
            existing = json.load(f)
        print(f"\n现有problem_list: {len(existing)}题")

    # 去重——避免重复加入
    existing_pids = {e["problem_id"] for e in existing}
    truly_new = [e for e in entries if e["problem_id"] not in existing_pids]
    print(f"  去重后真正新增: {len(truly_new)}题")

    if args.dry_run:
        print("\n[dry-run] 不写入文件。")
        print(f"  如果执行，problem_list将从{len(existing)}题增加到{len(existing) + len(truly_new)}题")
        return

    # 6. 写入文件
    merged = existing + truly_new
    with open(args.output, 'w') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"\n✅ problem_list.json已更新: {len(existing)} → {len(merged)}题")
    print(f"  新增: {len(truly_new)}题")
    print(f"  文件: {args.output}")
    print(f"\n下一步: python -m src.continuation_collector --batch-id {args.batch_id}")
    print(f"  （collector会跳过已存在的run，只创建新题的run记录）")


if __name__ == "__main__":
    main()
