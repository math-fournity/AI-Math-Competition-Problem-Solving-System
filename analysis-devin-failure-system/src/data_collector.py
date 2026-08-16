"""data_collector.py — 数据收集组件

从三个数据源收集数据，构造每道题的AGENTS.md：
  1. 题目文本：从solver工作目录的AGENTS.md（或problem.txt）
  2. 标准答案：从题库原始数据文件（parquet/jsonl/lean/json）
  3. AI解题过程：从trajectory目录（4级优先级）

用法：
  python -m src.data_collector --batch-id analysis-1 --limit 100
  python -m src.data_collector --batch-id analysis-1 --problem-ids polymath_01687,deepmath_103k_00021551
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# 添加项目根目录到path（用于import config）
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import (
    SOLVER_BASE, TRAJECTORY_BASE, ANALYSIS_SOLVER_BASE, ANALYSIS_TRAJECTORY_BASE,
    DATASET_PATHS, AGENTS_MD_TEMPLATE, OUTPUT_BASE,
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    THINKING_PRIORITY,
)
from src.db_schema import (
    connect_db, ensure_schema, insert_run, insert_event,
    insert_batch, next_run_id, make_analysis_exp_id, make_run_key, make_paths,
    make_verdict, ANALYSIS_BATCHES_COLLECTION,
)
from monitoring.shared_logger import get_logger

logger = get_logger("data_collector")


# ============================================================
# 数据源1：从ArangoDB获取失败题列表
# ============================================================

def get_failed_problems(limit=None, problem_ids=None):
    """从devin_problem_runs获取失败题，去重取runtime最长的"""
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    db = client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)

    if problem_ids:
        # 指定题号
        placeholders = ", ".join([f'"{pid}"' for pid in problem_ids])
        aql = f'''FOR r IN devin_problem_runs 
          FILTER r.status IN ["failed_no_proof","failed_token_limit","failed_tool_stall"]
          FILTER r.problem_id IN [{placeholders}]
          SORT r.runtime_seconds DESC
          RETURN {{problem_id: r.problem_id, exp_id: r.exp_id, status: r.status, runtime: r.runtime_seconds}}'''
    else:
        aql = '''FOR r IN devin_problem_runs 
          FILTER r.status IN ["failed_no_proof","failed_token_limit","failed_tool_stall"]
          RETURN {problem_id: r.problem_id, exp_id: r.exp_id, status: r.status, runtime: r.runtime_seconds}'''

    all_runs = list(db.aql.execute(aql))
    # 去重：取runtime最长的
    best = {}
    for r in all_runs:
        pid = r["problem_id"]
        rt = r.get("runtime") or 0
        if pid not in best or rt > (best[pid].get("runtime") or 0):
            best[pid] = r

    result = list(best.values())
    if limit:
        result = result[:limit]
    return result


# ============================================================
# 数据源2：从题库获取标准答案
# ============================================================

def load_polymath():
    """加载PolyMath，返回{id: {problem, solution, answer}}"""
    import pyarrow.parquet as pq
    result = {}
    for key in ["polymath", "polymath_normal", "polymath_revised"]:
        path = DATASET_PATHS.get(key)
        if not path or not path.exists():
            continue
        t = pq.read_table(str(path))
        for row in t.to_pylist():
            rid = row["id"]
            result[rid] = {
                "problem": row.get("problem", ""),
                "solution": row.get("solution", ""),
                "answer": str(row.get("answer", "")),
            }
    return result


def load_deepmath():
    """加载DeepMath，返回{index: {problem, solution, answer}}"""
    import pyarrow.parquet as pq
    result = {}
    idx = 0
    dir_path = DATASET_PATHS["deepmath_dir"]
    for fname in sorted(os.listdir(str(dir_path))):
        if not fname.endswith(".parquet"):
            continue
        t = pq.read_table(str(dir_path / fname))
        for row in t.to_pylist():
            result[idx] = {
                "problem": row.get("question", ""),
                "solution": row.get("r1_solution_1", ""),
                "answer": str(row.get("final_answer", "")),
            }
            idx += 1
    return result


def load_oda_math():
    """加载ODA-Math，返回{id: {problem, solution, answer}}"""
    import pyarrow.parquet as pq
    result = {}
    dir_path = DATASET_PATHS["oda_math_dir"]
    for fname in sorted(os.listdir(str(dir_path))):
        if not fname.endswith(".parquet"):
            continue
        t = pq.read_table(str(dir_path / fname))
        for row in t.to_pylist():
            rid = row["id"]
            result[rid] = {
                "problem": row.get("question", ""),
                "solution": row.get("response", ""),
                "answer": str(row.get("expected_answer", "")),
            }
    return result


def load_omni_math():
    """加载Omni-MATH-2，返回{id: {problem, solution, answer}}"""
    result = {}
    path = DATASET_PATHS["omni_math"]
    with open(str(path)) as f:
        for line in f:
            d = json.loads(line)
            result[d["id"]] = {
                "problem": d.get("problem", ""),
                "solution": d.get("solution", ""),
                "answer": str(d.get("answer", "")),
            }
    return result


def load_olympiadbench():
    """加载OlympiadBench，返回{id: {problem, solution, answer}}"""
    result = {}
    path = DATASET_PATHS["olympiadbench"]
    with open(str(path)) as f:
        data = json.load(f)
    for item in data:
        sol = item.get("solution", "")
        if isinstance(sol, list):
            sol = " ".join(sol)
        result[item["id"]] = {
            "problem": item.get("question", ""),
            "solution": sol,
            "answer": str(item.get("final_answer", "")),
        }
    return result


def load_aime():
    """加载AIME，返回{index: {problem, solution, answer}}"""
    result = {}
    path = DATASET_PATHS["aime"]
    with open(str(path)) as f:
        for i, line in enumerate(f):
            d = json.loads(line)
            result[i] = {
                "problem": d.get("problem", ""),
                "solution": d.get("solution", ""),
                "answer": str(d.get("answer", "")),
            }
    return result


def load_amo_bench():
    """加载AMO-Bench，返回{question_id: {problem, solution, answer}}"""
    import pyarrow.parquet as pq
    result = {}
    path = DATASET_PATHS["amo_bench"]
    t = pq.read_table(str(path))
    for row in t.to_pylist():
        result[row["question_id"]] = {
            "problem": row.get("prompt", ""),
            "solution": row.get("solution", ""),
            "answer": str(row.get("answer", "")),
        }
    return result


# 题库加载器注册表
_DATASET_LOADERS = {
    "polymath": load_polymath,
    "deepmath": load_deepmath,
    "oda_math": load_oda_math,
    "omni_math": load_omni_math,
    "olympiadbench": load_olympiadbench,
    "aime": load_aime,
    "amo_bench": load_amo_bench,
}


def match_problem_to_solution(pid, datasets):
    """根据problem_id格式匹配标准解答
    
    Args:
        pid: problem_id字符串
        datasets: dict，{source_name: loaded_data}
    
    Returns:
        (sol_data, source_name) 或 (None, reason)
    """
    # polymath_06607 -> PolyMath id=6607
    m = re.match(r"^polymath_(\d+)$", pid)
    if m:
        rid = int(m.group(1))
        ds = datasets.get("polymath", {})
        if rid in ds:
            return ds[rid], "polymath"
        return None, "polymath_not_found"

    # deepmath_103k_00012349 -> DeepMath index=12349
    m = re.match(r"^deepmath_103k_(\d+)$", pid)
    if m:
        idx = int(m.group(1))
        ds = datasets.get("deepmath", {})
        if idx in ds:
            return ds[idx], "deepmath"
        return None, "deepmath_not_found"

    # oda_math_460k_00013667 -> ODA-Math id=13667
    m = re.match(r"^oda_math_460k_(\d+)$", pid)
    if m:
        rid = int(m.group(1))
        ds = datasets.get("oda_math", {})
        if rid in ds:
            return ds[rid], "oda_math"
        return None, "oda_math_not_found"

    # omni_math_000007 -> Omni-MATH id=7
    m = re.match(r"^omni_math_(\d+)$", pid)
    if m:
        rid = int(m.group(1))
        ds = datasets.get("omni_math", {})
        if rid in ds:
            return ds[rid], "omni_math"
        return None, "omni_math_not_found"

    # mathnet_001631 -> OlympiadBench id=1631
    m = re.match(r"^mathnet_(\d+)$", pid)
    if m:
        oid = int(m.group(1))
        ds = datasets.get("olympiadbench", {})
        if oid in ds:
            return ds[oid], "olympiadbench"
        return None, "olympiadbench_not_found"

    # aime_2024_0012 -> AIME index=11
    m = re.match(r"^aime_2024_(\d+)$", pid)
    if m:
        idx = int(m.group(1)) - 1
        ds = datasets.get("aime", {})
        if idx in ds:
            return ds[idx], "aime"
        return None, "aime_not_found"

    # amo_bench_00000006 -> AMO-Bench question_id=6
    m = re.match(r"^amo_bench_(\d+)$", pid)
    if m:
        qid = int(m.group(1))
        ds = datasets.get("amo_bench", {})
        if qid in ds:
            return ds[qid], "amo_bench"
        return None, "amo_bench_not_found"

    # compfiles_ -> lean文件（暂不支持自动提取）
    if pid.startswith("compfiles_"):
        return None, "compfiles_lean"

    # fate_ -> 无人类解答
    if pid.startswith("fate_"):
        return None, "fate_no_human_solution"

    return None, "unknown_prefix"


# ============================================================
# 数据源3：从trajectory目录获取thinking文本
# ============================================================

def get_thinking_text(exp_id):
    """从trajectory目录获取thinking文本（4级优先级）
    
    Args:
        exp_id: 实验ID
    
    Returns:
        thinking文本字符串，或None
    """
    traj_dir = TRAJECTORY_BASE / exp_id
    if not traj_dir.exists():
        return None

    # 优先级1：mitm/thinking_readable.txt
    path = traj_dir / "mitm" / "thinking_readable.txt"
    if path.exists() and path.stat().st_size > 100:
        content = path.read_text(encoding="utf-8", errors="replace")
        if content.strip():
            return content

    # 优先级2：sessions_db/trajectory.jsonl
    path = traj_dir / "sessions_db" / "trajectory.jsonl"
    if path.exists():
        parts = []
        with open(str(path)) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    thinking = obj.get("thinking", "")
                    if isinstance(thinking, str) and thinking.strip():
                        parts.append(thinking)
                except json.JSONDecodeError:
                    continue
        if parts:
            # 去重（同一thinking可能出现在多个step中）
            seen = set()
            unique = []
            for p in parts:
                if p not in seen:
                    seen.add(p)
                    unique.append(p)
            return "\n".join(unique)

    # 优先级3：exports/conversation.json
    path = traj_dir / "exports" / "conversation.json"
    if path.exists():
        with open(str(path)) as f:
            conv = json.load(f)
        parts = []
        if isinstance(conv, dict):
            steps = conv.get("steps", [])
            for step in steps:
                if not isinstance(step, dict):
                    continue
                rc = step.get("reasoning_content", "")
                if isinstance(rc, str) and rc.strip():
                    parts.append(rc)
                if step.get("source") == "agent":
                    msg = step.get("message", "")
                    if isinstance(msg, str) and msg.strip():
                        parts.append(msg)
        if parts:
            return "\n".join(parts)

    # 优先级4：collector/pane_snapshot_clean.txt
    path = traj_dir / "collector" / "pane_snapshot_clean.txt"
    if path.exists() and path.stat().st_size > 100:
        return path.read_text(encoding="utf-8", errors="replace")

    return None


# ============================================================
# 数据源1补充：从solver工作目录获取题目文本
# ============================================================

def get_problem_text(exp_id):
    """从solver工作目录的AGENTS.md获取题目文本"""
    solver_dir = SOLVER_BASE / exp_id
    agents_path = solver_dir / "AGENTS.md"
    if not agents_path.exists():
        # 尝试problem.txt
        problem_path = solver_dir / "problem.txt"
        if problem_path.exists():
            return problem_path.read_text(encoding="utf-8", errors="replace").strip()
        return None

    content = agents_path.read_text(encoding="utf-8", errors="replace")
    # 题目在"## Problem"之后
    if "## Problem" in content:
        problem_text = content.split("## Problem", 1)[1].strip()
        # 去掉可能的解题约束部分
        if "## 解题约束" in problem_text:
            problem_text = problem_text.split("## 解题约束")[0].strip()
        return problem_text
    return content


# ============================================================
# AGENTS.md构造
# ============================================================

def build_agents_md(problem_id, problem_text, standard_solution, ai_thinking):
    """构造分析用的AGENTS.md

    用手动替换而非str.format——problem_text/standard_solution/ai_thinking中
    可能包含花括号（LaTeX的${7 \choose 2}$），会导致.format()报错。
    """
    template = AGENTS_MD_TEMPLATE.read_text(encoding="utf-8")
    # 手动替换占位符——不解析花括号
    result = template.replace("{problem_id}", problem_id)
    result = result.replace("{problem_text}", problem_text or "[题目文本不可用]")
    result = result.replace("{standard_solution}", standard_solution or "[标准解答不可用]")
    result = result.replace("{ai_thinking}", ai_thinking or "[AI thinking不可用]")
    return result


# ============================================================
# 主流程
# ============================================================

def collect_and_prepare(batch_id, limit=None, problem_ids=None):
    """收集数据，构造AGENTS.md，写入工作目录，写入DB记录"""
    logger.info(f"数据收集开始 batch={batch_id} limit={limit}")
    print(f"=== 数据收集 batch={batch_id} ===")

    # 1. 获取失败题列表
    print("  获取失败题列表...")
    failed = get_failed_problems(limit=limit, problem_ids=problem_ids)
    print(f"  失败题: {len(failed)}")
    logger.info(f"失败题: {len(failed)}")

    # 2. 加载题库
    print("  加载题库...")
    datasets = {}
    for name, loader in _DATASET_LOADERS.items():
        print(f"    {name}...", end=" ", flush=True)
        datasets[name] = loader()
        print(f"{len(datasets[name])}条")
        logger.info(f"题库 {name}: {len(datasets[name])}条")

    # 3. 为每道题构造AGENTS.md
    print("  构造AGENTS.md...")
    logger.info("开始构造AGENTS.md")
    batch_dir = ANALYSIS_SOLVER_BASE / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    # 连接DB
    db = connect_db()
    ensure_schema(db)

    # 写入batch记录
    now = _utc_now()
    batch_doc = {
        "_key": batch_id,
        "status": "collecting",
        "created_at": now,
        "updated_at": now,
        "selected_count": len(failed),
        "selection": {"limit": limit, "problem_ids": problem_ids},
    }
    try:
        insert_batch(db, batch_doc)
    except Exception:
        # batch已存在，更新
        update_data = {k: v for k, v in batch_doc.items() if k != "_key"}
        update_data["_key"] = batch_id
        db.collection(ANALYSIS_BATCHES_COLLECTION).update(update_data)

    prepared = []
    skipped = []

    for i, run in enumerate(failed):
        pid = run["problem_id"]
        exp_id = run["exp_id"]

        if (i + 1) % 100 == 0:
            print(f"    进度: {i+1}/{len(failed)}")
            logger.info(f"进度: {i+1}/{len(failed)}")

        # 获取标准答案
        sol_data, source = match_problem_to_solution(pid, datasets)
        if not sol_data:
            skipped.append({"problem_id": pid, "reason": source})
            continue

        standard_solution = sol_data.get("solution", "")
        if not standard_solution or len(standard_solution) < 50:
            skipped.append({"problem_id": pid, "reason": "solution_too_short"})
            continue

        # 获取thinking
        thinking = get_thinking_text(exp_id)
        if not thinking or len(thinking) < 500:
            skipped.append({"problem_id": pid, "reason": "thinking_too_short"})
            continue

        # 获取题目文本（优先从题库，备选从solver目录）
        problem_text = sol_data.get("problem", "")
        if not problem_text:
            problem_text = get_problem_text(exp_id)

        # 构造AGENTS.md
        agents_md = build_agents_md(pid, problem_text, standard_solution, thinking)

        # 生成唯一analysis_exp_id（用原子递增run_id保证唯一）
        run_id = next_run_id(db)
        analysis_exp_id = make_analysis_exp_id(batch_id, run_id, pid)
        run_key = make_run_key(analysis_exp_id)
        paths = make_paths(analysis_exp_id)

        # 写入工作目录
        work_dir = ANALYSIS_SOLVER_BASE / analysis_exp_id
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "AGENTS.md").write_text(agents_md, encoding="utf-8")

        # 写入DB记录（完整字段，模仿devin_problem_runs）
        run_doc = {
            "_key": run_key,
            "problem_id": pid,
            "batch_id": batch_id,
            "run_id": run_id,
            "source_exp_id": exp_id,
            "analysis_exp_id": analysis_exp_id,
            "work_dir": str(work_dir),
            "status": "prepared",
            "solution_source": source,
            "problem_text_length": len(problem_text or ""),
            "solution_length": len(standard_solution),
            "thinking_length": len(thinking),
            "paths": paths,
            "created_at": now,
            "updated_at": now,
            "observability": {
                "activity_signature": "",
                "last_observed_activity_at": None,
                "last_observed_at": None,
                "markers": {},
                "file_sizes": {},
            },
            "verdict": make_verdict("prepared", "not launched"),
        }
        try:
            insert_run(db, run_doc)
        except Exception:
            # 可能已存在（重复运行），更新
            update_data = {k: v for k, v in run_doc.items() if k != "_key"}
            update_data["_key"] = run_key
            db.collection("analysis_runs").update(update_data)

        prepared.append({
            "problem_id": pid,
            "analysis_exp_id": analysis_exp_id,
            "run_key": run_key,
            "work_dir": str(work_dir),
        })

    # 更新batch记录
    db.collection(ANALYSIS_BATCHES_COLLECTION).update({
        "_key": batch_id,
        "status": "prepared",
        "updated_at": _utc_now(),
        "prepared_count": len(prepared),
        "skipped_count": len(skipped),
        "run_keys": [p["run_key"] for p in prepared],
    })

    print(f"\n  已准备: {len(prepared)}")
    print(f"  跳过: {len(skipped)}")
    logger.info(f"数据收集完成: prepared={len(prepared)}, skipped={len(skipped)}")

    # 统计跳过原因
    from collections import Counter
    skip_reasons = Counter(s["reason"] for s in skipped)
    print("  跳过原因:")
    for reason, count in skip_reasons.most_common():
        print(f"    {reason}: {count}")
        logger.info(f"跳过原因 {reason}: {count}")

    # 保存prepared列表
    prepared_path = OUTPUT_BASE / batch_id / "prepared.json"
    prepared_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(prepared_path), "w") as f:
        json.dump({"prepared": prepared, "skipped": skipped}, f, ensure_ascii=False, indent=2)
    print(f"  已保存到: {prepared_path}")

    return prepared


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description="数据收集——构造分析用AGENTS.md")
    parser.add_argument("--batch-id", required=True, help="批次ID")
    parser.add_argument("--limit", type=int, help="限制题数（调试用）")
    parser.add_argument("--problem-ids", help="指定题号（逗号分隔）")
    parser.add_argument("--problem-ids-file", help="从文件读取题号（每行一个）")
    args = parser.parse_args()

    problem_ids = None
    if args.problem_ids:
        problem_ids = args.problem_ids.split(",")
    elif args.problem_ids_file:
        from pathlib import Path
        text = Path(args.problem_ids_file).read_text()
        problem_ids = [line.strip() for line in text.split("\n") if line.strip()]
        print(f"从文件读取{len(problem_ids)}个题号: {args.problem_ids_file}")

    collect_and_prepare(args.batch_id, limit=args.limit, problem_ids=problem_ids)


if __name__ == "__main__":
    main()
