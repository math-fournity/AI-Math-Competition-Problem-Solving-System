#!/usr/bin/env python3
"""export_new_problems.py — 从A系统（解题系统A）导出 tier=1 模型能力失败题到B系统

A系统 = /Users/user/AI-Math-Normal-Solver/（devin_problem_runs集合）
B系统 = 当前repo（p27_continuation_runs集合）

B系统的目的是把A系统没做出来的 tier=1 模型能力失败题用续传方法重做。

查询方向（v3修正，对齐405报告）：
  从 problem_extraction_progress 侧 FILTER tier=1 → JOIN devin_problem_runs
  查最后 run 的 status，只保留模型能力失败的题。

  之前从 devin_problem_runs 侧查（不查 tier），导致：
  - 混入 tier=2/tier=3 的失败题
  - 漏掉 DPR 中 difficulty_tier=null 的 tier=1 题
  详见 dev-docs/025-题目来源审查报告.md

用法:
  # 增量模式：只导出新题，合并到现有 problem_list.json
  python -m scripts.export_new_problems --batch-id p27-full
  python -m scripts.export_new_problems --batch-id p27-full --limit 100  # 测试
  python -m scripts.export_new_problems --batch-id p27-full --dry-run    # 只看不写

  # 全量重建模式：用 405 报告的 AQL 重新生成完整 problem_list.json
  python -m scripts.export_new_problems --batch-id p27-full --rebuild
  python -m scripts.export_new_problems --batch-id p27-full --rebuild --dry-run
"""
import argparse
import json
import os
import sys
from pathlib import Path
from collections import Counter

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from arango import ArangoClient

# A系统模型能力失败的status（对齐405报告，v3修正）
# 405报告用：failed_token_limit/ai_gave_up/failed_stall/failed_thinking_spin/
#            failed_no_proof/invalid_tool_use
# 旧版有 failed_tool_stall 但405报告没有，v3对齐405报告去掉它
MODEL_FAILURE_STATUSES = [
    'failed_token_limit', 'ai_gave_up', 'failed_thinking_spin',
    'failed_no_proof', 'failed_stall', 'invalid_tool_use'
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


def get_tier1_failed_problems(db):
    """查A系统所有 tier=1 模型能力失败的题（405报告的AQL方向）

    从 problem_extraction_progress 侧 FILTER tier=1，
    JOIN devin_problem_runs 查最后 run 的 status。
    只查 batch_id='pipe-runner' 的 run（pipe系统的run）。
    """
    aql = (
        'FOR p IN problem_extraction_progress '
        '  FILTER p.difficulty_tier == 1 '
        '  LET last_run = ('
        '    FOR r IN devin_problem_runs '
        '      FILTER r.problem_id == p._key '
        '      FILTER r.batch_id == "pipe-runner" '
        '      FILTER r.status != "running" '
        '      SORT r.ended_at DESC '
        '      LIMIT 1 '
        '      RETURN {status: r.status, exp_id: r.exp_id, ended_at: r.ended_at}'
        '  ) '
        '  FILTER LENGTH(last_run) > 0 '
        '  FILTER last_run[0].status IN @statuses '
        '  RETURN {'
        '    problem_id: p._key, '
        '    exp_id: last_run[0].exp_id, '
        '    status: last_run[0].status, '
        '    source_dataset: p.source_dataset, '
        '    answer: p.answer, '
        '    has_solution: p.has_solution'
        '  }'
    )
    failed = list(db.aql.execute(
        aql, bind_vars={'statuses': MODEL_FAILURE_STATUSES}, ttl=300))
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
        "source_dataset": problem.get('source_dataset'),
        "a_status": problem.get('status'),
    }


def main():
    parser = argparse.ArgumentParser(description="从A系统导出tier=1失败题到B系统")
    parser.add_argument("--batch-id", default="p27-full", help="B系统batch_id")
    parser.add_argument("--limit", type=int, help="限制导出题数（测试用）")
    parser.add_argument("--dry-run", action="store_true", help="只看不写")
    parser.add_argument("--rebuild", action="store_true",
                        help="全量重建模式：用405报告AQL重新生成完整problem_list.json")
    parser.add_argument("--output", default=str(PROBLEM_LIST_FILE),
                        help="输出文件路径")
    args = parser.parse_args()

    print(f"=== 从A系统导出 tier=1 失败题到B系统 ===")
    print(f"  batch_id: {args.batch_id}")
    print(f"  模式: {'全量重建' if args.rebuild else '增量合并'}")
    print()

    db = connect_db()

    # 1. 查A系统 tier=1 失败题（405报告AQL方向）
    print("查询A系统 tier=1 模型能力失败题（PEP侧 FILTER tier=1 → JOIN DPR）...")
    a_failed = get_tier1_failed_problems(db)
    print(f"  tier=1 失败题总数: {len(a_failed)}")

    # 按 source_dataset 统计
    source_counts = Counter(p.get('source_dataset', 'unknown') for p in a_failed)
    print(f"  按source分布:")
    for s, n in source_counts.most_common():
        print(f"    {s}: {n}")

    # 按 status 统计
    status_counts = Counter(p.get('status', 'unknown') for p in a_failed)
    print(f"  按status分布:")
    for s, n in status_counts.most_common():
        print(f"    {s}: {n}")

    if args.limit:
        a_failed = a_failed[:args.limit]
        print(f"  限制导出: {len(a_failed)}题")

    # 2. 构造problem_list条目
    # 注意：seed_export 缺失的题不跳过——collector 可以用方法2（AGENTS.md）提取题目文本
    print("\n构造problem_list条目...")
    entries = []
    no_export = 0
    for p in a_failed:
        entry = build_problem_entry(p)
        if not entry["export_exists"]:
            no_export += 1
        entries.append(entry)

    print(f"  总条目: {len(entries)}")
    print(f"  seed_export存在: {len(entries) - no_export}")
    print(f"  seed_export缺失（用AGENTS.md提取文本）: {no_export}")

    if args.rebuild:
        # 全量重建模式：直接用查询结果替换 problem_list.json
        print(f"\n[全量重建] 用 {len(entries)} 题替换 problem_list.json")

        if args.dry_run:
            print("[dry-run] 不写入文件。")
            # 对比现有 problem_list
            if PROBLEM_LIST_FILE.exists():
                with open(PROBLEM_LIST_FILE) as f:
                    existing = json.load(f)
                existing_pids = {e["problem_id"] for e in existing}
                new_pids = {e["problem_id"] for e in entries}
                added = new_pids - existing_pids
                removed = existing_pids - new_pids
                print(f"  现有: {len(existing)}题")
                print(f"  新版: {len(entries)}题")
                print(f"  新增: {len(added)}题")
                print(f"  移除: {len(removed)}题")
            return

        with open(args.output, 'w') as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        print(f"\n✅ problem_list.json已重建: {len(entries)}题")
        print(f"  文件: {args.output}")

    else:
        # 增量合并模式（原逻辑）
        # 3. 查B系统已有题
        print("查询B系统已有题...")
        b_pids = get_b_existing_pids(db)
        print(f"  B系统已有题: {len(b_pids)}")

        # 4. 计算需要新增的题
        new_problems = [p for p in entries if p['problem_id'] not in b_pids]
        print(f"  需要新增的题: {len(new_problems)}")

        if not new_problems:
            print("\n无新题可导入。")
            return

        # 5. 合并到现有problem_list
        existing = []
        if PROBLEM_LIST_FILE.exists():
            with open(PROBLEM_LIST_FILE) as f:
                existing = json.load(f)
            print(f"\n现有problem_list: {len(existing)}题")

        # 去重
        existing_pids = {e["problem_id"] for e in existing}
        truly_new = [e for e in new_problems if e["problem_id"] not in existing_pids]
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

    print(f"\n下一步: python -m src.continuation_collector --batch-id {args.batch_id}")
    print(f"  （collector会跳过已存在的run，只创建新题的run记录）")


if __name__ == "__main__":
    main()
