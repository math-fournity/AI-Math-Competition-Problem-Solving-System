"""setup.py — sim批次构造器

按剧本造一个批次：fixture题目 + 截断态seed export + prepared状态的run记录
（字段与continuation_collector的run doc完全一致——launcher读什么字段，
这里就造什么字段）。然后由run_sim启动真feeder入队、真launcher调度。

安全护栏（防误伤生产）：必须同时满足——
  1. SIM_MODE=1
  2. ARANGO_DB不是生产库名（xishujuzhen_math_glm52）
  3. SOLVER_BASE不在/Volumes/data（生产文件根）
否则拒绝执行。
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PROD_DB = "xishujuzhen_math_glm52"


def guard_sim_env():
    """三重护栏：环境不是隔离环境就拒绝。"""
    problems = []
    if os.environ.get("SIM_MODE") != "1":
        problems.append("SIM_MODE != 1")
    if os.environ.get("ARANGO_DB", PROD_DB) == PROD_DB:
        problems.append(f"ARANGO_DB == 生产库({PROD_DB})")
    if os.environ.get("SOLVER_BASE", "/Volumes/data/").startswith("/Volumes/data"):
        problems.append("SOLVER_BASE指向生产文件根(/Volumes/data)")
    if problems:
        raise SystemExit(
            "❌ 拒绝在非隔离环境运行sim setup：\n  - " + "\n  - ".join(problems)
            + "\n请用 python -m src.sim.run_sim（它自动设置隔离环境）"
        )


def ensure_sim_database():
    """sim库不存在则创建（root权限）。"""
    import arango
    from src.continuation_config import ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD
    client = arango.ArangoClient(hosts=ARANGO_HOST)
    sysdb = client.db("_system", username=ARANGO_USER, password=ARANGO_PASSWORD)
    if not sysdb.has_database(ARANGO_DB):
        sysdb.create_database(ARANGO_DB)
        print(f"  [setup] sim数据库已创建: {ARANGO_DB}")
    client.close()


FIXTURE_PROBLEM = (
    "Let $f(x) = x^2 - 4x + 3$. Find all real numbers $x$ such that "
    "$f(f(x)) = 0$."
)


def build_batch(batch_id, scenario_name, runs=None):
    """造批次：batch记录 + N个prepared run + work_dir/seed/scenario文件。"""
    guard_sim_env()
    from src.sim import scenarios as sim_scenarios
    from src.continuation_config import (
        CONTINUATION_SOLVER_BASE, CONTINUATION_TRAJECTORY_BASE,
        CONTINUATION_BATCHES_COLLECTION, CONTINUATION_RUNS_COLLECTION,
    )
    from src.continuation_db_schema import connect_db, ensure_schema
    from src.sim.fake_devin import truncated_export

    sc = sim_scenarios.get(scenario_name)
    n = runs or sc["runs"]

    ensure_sim_database()
    db = connect_db()
    ensure_schema(db)

    now = datetime.now(timezone.utc).isoformat()
    batches = db.collection(CONTINUATION_BATCHES_COLLECTION)
    if not batches.get(batch_id):
        batches.insert({
            "_key": batch_id, "batch_id": batch_id, "status": "collecting",
            "total": n, "created_at": now,
        })

    run_keys = []
    for i in range(1, n + 1):
        # 题目id必须带sim前缀——tmux session名含pid后缀，与生产pid隔离
        # 防止launch_solve开头的同名清理tmux_kill误杀生产session
        pid = f"sim_{scenario_name}_{i:04d}"
        run_key = f"{batch_id}-{pid}"
        work_dir = CONTINUATION_SOLVER_BASE / run_key
        work_dir.mkdir(parents=True, exist_ok=True)
        traj_dir = CONTINUATION_TRAJECTORY_BASE / run_key / "round1"
        (traj_dir / "exports").mkdir(parents=True, exist_ok=True)
        (traj_dir / "tmux").mkdir(parents=True, exist_ok=True)

        # seed export：截断态（R1的"原始失败尝试"）
        seed_export = work_dir / "seed_export.json"
        seed_export.write_text(json.dumps(truncated_export(), indent=2))

        (work_dir / "problem.txt").write_text(FIXTURE_PROBLEM)
        (work_dir / "sim_scenario.json").write_text(
            json.dumps(sim_scenarios.scenario_file_content(scenario_name), indent=2))

        run_doc = {
            "_key": run_key,
            "batch_id": batch_id,
            "problem_id": pid,
            "original_exp_id": f"simexp-{i:04d}",
            "seed_export": str(seed_export),
            "work_dir": str(work_dir),
            "trajectory_dir": str(CONTINUATION_TRAJECTORY_BASE / run_key),
            "problem_text": FIXTURE_PROBLEM[:500],
            "problem_path": str(work_dir / "problem.txt"),
            "status": "prepared",
            "final_status": None,
            "rounds_log": [],
            "created_at": now,
            "updated_at": now,
        }
        runs_col = db.collection(CONTINUATION_RUNS_COLLECTION)
        if runs_col.get(run_key):
            runs_col.replace(run_doc)
        else:
            runs_col.insert(run_doc)
        run_keys.append(run_key)

    batches.update({"_key": batch_id, "status": "prepared", "total": n,
                    "updated_at": now})
    print(f"  [setup] 批次就绪: {batch_id} runs={len(run_keys)} 剧本={scenario_name}")
    return run_keys


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="sim批次构造（一般经run_sim调用）")
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--runs", type=int, default=None)
    args = ap.parse_args()
    build_batch(args.batch_id, args.scenario, args.runs)
