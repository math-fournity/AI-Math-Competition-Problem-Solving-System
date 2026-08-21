"""run_proof_audit_pipeline.py — Pipe 5 审计 Pipe 端到端入口

一键运行审计 Pipe 的三个阶段：
  1. collector: 收集 completed 题入审计队列
  2. launcher: 并发启动 devin cli 审计
  3. result_collector: 解析审计结果，更新 DB

用法：
  # 完整运行（三阶段）
  python -m scripts.run_proof_audit_pipeline --batch-id paudit-p27-full

  # 只运行某一阶段
  python -m scripts.run_proof_audit_pipeline --batch-id paudit-p27-full --stage collect
  python -m scripts.run_proof_audit_pipeline --batch-id paudit-p27-full --stage launch
  python -m scripts.run_proof_audit_pipeline --batch-id paudit-p27-full --stage collect-results

  # 限制题数（测试用）
  python -m scripts.run_proof_audit_pipeline --batch-id paudit-test --limit 5
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def run_collect(batch_id, limit, filter_prefix):
    """阶段1: 收集 completed 题入审计队列"""
    from src.proof_audit_collector import collect_completed_for_audit
    print(f"\n{'='*60}")
    print(f"阶段 1/3: 收集待审计题")
    print(f"{'='*60}")
    count = collect_completed_for_audit(
        batch_id, limit=limit, filter_prefix=filter_prefix)
    return count


def run_launch(batch_id, concurrency, max_runtime, poll_seconds):
    """阶段2: 并发启动 devin cli 审计"""
    from src.proof_audit_launcher import launch_batch
    print(f"\n{'='*60}")
    print(f"阶段 2/3: 并发启动审计 devin cli")
    print(f"{'='*60}")
    launch_batch(
        batch_id=batch_id,
        concurrency=concurrency,
        max_runtime=max_runtime,
        poll_seconds=poll_seconds,
    )


def run_collect_results(batch_id, limit):
    """阶段3: 收集审计结果，更新 DB"""
    from src.proof_audit_result_collector import collect_results
    print(f"\n{'='*60}")
    print(f"阶段 3/3: 收集审计结果")
    print(f"{'='*60}")
    count = collect_results(batch_id, limit=limit)
    return count


def register_gates():
    """注册门闸到 DB（让 Master Agent 可见）"""
    from src.step_gate import sync_registry_to_db
    n = sync_registry_to_db()
    print(f"  门闸注册: {n} 个门闸已同步到 DB")


def main():
    parser = argparse.ArgumentParser(description="Pipe 5 审计 Pipe 端到端入口")
    parser.add_argument("--batch-id", required=True, help="审计批次ID（如 paudit-p27-full）")
    parser.add_argument("--stage", choices=["collect", "launch", "collect-results", "all"],
                        default="all", help="运行阶段（默认 all=三阶段顺序运行）")
    parser.add_argument("--limit", type=int, default=10000, help="限制题数")
    parser.add_argument("--filter-prefix", help="题目ID前缀过滤")
    parser.add_argument("--concurrency", type=int, default=5, help="审计并发数")
    parser.add_argument("--max-runtime", type=int, default=600, help="单轮最大运行时间秒")
    parser.add_argument("--poll-seconds", type=int, default=10, help="轮询间隔秒")
    parser.add_argument("--register-gates", action="store_true",
                        help="运行前注册门闸到 DB")
    args = parser.parse_args()

    # 注册门闸
    if args.register_gates or args.stage == "all":
        register_gates()

    # 按阶段运行
    if args.stage in ("all", "collect"):
        run_collect(args.batch_id, args.limit, args.filter_prefix)

    if args.stage in ("all", "launch"):
        run_launch(args.batch_id, args.concurrency, args.max_runtime, args.poll_seconds)

    if args.stage in ("all", "collect-results"):
        run_collect_results(args.batch_id, args.limit)

    print(f"\n{'='*60}")
    print(f"完成: batch={args.batch_id} stage={args.stage}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
