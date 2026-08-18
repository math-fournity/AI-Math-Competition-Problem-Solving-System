#!/usr/bin/env python3
"""fetch_poc0_with_problems.py — 获取Pipe 3产出+原始题面+标准解答，供POC-0精筛使用。

从poc0_candidates.json读取Pipe 3产出，从原始数据集获取题面和解答，
产出完整的POC-0候选题清单（含5否决项审查所需的所有信息）。
"""
import sys
import json
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import DATASET_PATHS

OUTPUT_DIR = Path(__file__).parent.parent / "output"

# === 加载poc0_candidates.json ===
with open(OUTPUT_DIR / "poc0_candidates.json") as f:
    data = json.load(f)

# === 统计需要的题库 ===
all_pids = []
for cat in ["yes_candidates", "false_friend_candidates", "boundary_candidates"]:
    for r in data[cat]:
        all_pids.append(r["problem_id"])

sources_needed = set()
for pid in all_pids:
    if pid.startswith("polymath_"):
        sources_needed.add("polymath")
    elif pid.startswith("deepmath_103k_"):
        sources_needed.add("deepmath")
    elif pid.startswith("oda_math_460k_"):
        sources_needed.add("oda_math")
    elif pid.startswith("omni_math_"):
        sources_needed.add("omni_math")
    elif pid.startswith("amo_bench_"):
        sources_needed.add("amo_bench")

print(f"需要的题库: {sources_needed}")
print(f"总题数: {len(all_pids)}")

# === 按需加载题库 ===
datasets = {}

if "polymath" in sources_needed:
    print("加载PolyMath...")
    import pyarrow.parquet as pq
    polymath = {}
    for key in ["polymath", "polymath_normal", "polymath_revised"]:
        path = DATASET_PATHS.get(key)
        if not path or not path.exists():
            print(f"  {key}: 路径不存在 {path}")
            continue
        t = pq.read_table(str(path))
        for row in t.to_pylist():
            rid = row["id"]
            if rid not in polymath:  # 不覆盖
                polymath[rid] = {
                    "problem": row.get("problem", ""),
                    "solution": row.get("solution", ""),
                    "answer": str(row.get("answer", "")),
                }
    datasets["polymath"] = polymath
    print(f"  PolyMath: {len(polymath)}题")

if "deepmath" in sources_needed:
    print("加载DeepMath...")
    import pyarrow.parquet as pq
    import os
    deepmath = {}
    idx = 0
    dir_path = DATASET_PATHS["deepmath_dir"]
    for fname in sorted(os.listdir(str(dir_path))):
        if not fname.endswith(".parquet"):
            continue
        t = pq.read_table(str(dir_path / fname))
        for row in t.to_pylist():
            deepmath[idx] = {
                "problem": row.get("question", ""),
                "solution": row.get("r1_solution_1", ""),
                "answer": str(row.get("final_answer", "")),
            }
            idx += 1
    datasets["deepmath"] = deepmath
    print(f"  DeepMath: {len(deepmath)}题")

if "oda_math" in sources_needed:
    print("加载ODA-Math...")
    import pyarrow.parquet as pq
    import os
    oda_math = {}
    dir_path = DATASET_PATHS["oda_math_dir"]
    for fname in sorted(os.listdir(str(dir_path))):
        if not fname.endswith(".parquet"):
            continue
        t = pq.read_table(str(dir_path / fname))
        for row in t.to_pylist():
            rid = row["id"]
            oda_math[rid] = {
                "problem": row.get("question", ""),
                "solution": row.get("response", ""),
                "answer": str(row.get("expected_answer", "")),
            }
    datasets["oda_math"] = oda_math
    print(f"  ODA-Math: {len(oda_math)}题")

if "omni_math" in sources_needed:
    print("加载Omni-MATH...")
    omni_math = {}
    path = DATASET_PATHS["omni_math"]
    with open(str(path)) as f:
        for line in f:
            d = json.loads(line)
            omni_math[d["id"]] = {
                "problem": d.get("problem", ""),
                "solution": d.get("solution", ""),
                "answer": str(d.get("answer", "")),
            }
    datasets["omni_math"] = omni_math
    print(f"  Omni-MATH: {len(omni_math)}题")

if "amo_bench" in sources_needed:
    print("加载AMO-Bench...")
    import pyarrow.parquet as pq
    amo_bench = {}
    path = DATASET_PATHS["amo_bench"]
    t = pq.read_table(str(path))
    for row in t.to_pylist():
        amo_bench[row["question_id"]] = {
            "problem": row.get("prompt", ""),
            "solution": row.get("solution", ""),
            "answer": str(row.get("answer", "")),
        }
    datasets["amo_bench"] = amo_bench
    print(f"  AMO-Bench: {len(amo_bench)}题")

# === 匹配题面 ===
def match_problem(pid):
    """根据problem_id匹配题面和解答"""
    m = re.match(r"^polymath_(\d+)$", pid)
    if m:
        rid = int(m.group(1))
        ds = datasets.get("polymath", {})
        return ds.get(rid)
    m = re.match(r"^deepmath_103k_(\d+)$", pid)
    if m:
        idx = int(m.group(1))
        ds = datasets.get("deepmath", {})
        return ds.get(idx)
    m = re.match(r"^oda_math_460k_(\d+)$", pid)
    if m:
        rid = int(m.group(1))
        ds = datasets.get("oda_math", {})
        return ds.get(rid)
    m = re.match(r"^omni_math_(\d+)$", pid)
    if m:
        rid = int(m.group(1))
        ds = datasets.get("omni_math", {})
        return ds.get(rid)
    m = re.match(r"^amo_bench_(\d+)$", pid)
    if m:
        qid = int(m.group(1))
        ds = datasets.get("amo_bench", {})
        return ds.get(qid)
    return None

# === 为每道题添加题面和解答 ===
found_count = 0
not_found = []
for cat in ["yes_candidates", "false_friend_candidates", "boundary_candidates"]:
    for r in data[cat]:
        pid = r["problem_id"]
        sol_data = match_problem(pid)
        if sol_data:
            r["problem_text"] = sol_data.get("problem", "")
            r["standard_solution_text"] = sol_data.get("solution", "")
            r["standard_answer"] = sol_data.get("answer", "")
            found_count += 1
        else:
            r["problem_text"] = None
            r["standard_solution_text"] = None
            r["standard_answer"] = None
            not_found.append(pid)

print(f"\n题面匹配: {found_count}/{len(all_pids)}")
if not_found:
    print(f"未找到题面: {not_found[:10]}{'...' if len(not_found)>10 else ''}")

# === 产出完整JSON ===
output_path = OUTPUT_DIR / "poc0_candidates_full.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"\n完整产出: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")

# === 打印47道YES候选题的完整信息（供精筛审查） ===
print(f"\n{'='*100}")
print("47道YES候选题完整信息（供5否决项审查）:")
print(f"{'='*100}")
for i, r in enumerate(sorted(data["yes_candidates"], key=lambda x: (x["selection"]["batch"] or "", x["problem_id"]))):
    s = r["selection"]
    a = r["analysis"]
    pt = r.get("problem_text") or ""
    print(f"\n--- [{i+1}/47] {r['problem_id']} (batch={s['batch']}, d2_reclass={s['d2_reclassified']}) ---")
    print(f"  proc_sig={s['process_signal_observability']}, leak={s['leakage_risk']}, diff={s['difficulty_estimate']}, branch={s['branch_position_hint']}")
    print(f"  题面: {pt[:200]}...")
    print(f"  标准解答关键技术: {a.get('standard_solution_key_technique', 'N/A')[:200]}")
    print(f"  AI方向: {a.get('ai_direction_summary', 'N/A')[:150]}")
    print(f"  选题理由: {s.get('selection_reason', 'N/A')[:200]}")
