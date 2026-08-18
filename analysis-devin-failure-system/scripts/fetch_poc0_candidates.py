#!/usr/bin/env python3
"""fetch_poc0_candidates.py — 从ArangoDB获取Pipe 3产出，供POC-0 CasePack冻结使用。

获取：
  1. 47道suitable=YES候选题（含6项POC准备数据）
  2. 69道false_friend_candidate=yes假朋友候选
  3. 30道boundary_case_candidate=yes边界候选
  4. 每道题对应的analysis_results记录（含d1_exp/d2_exp/standard_solution_key_technique/ai_direction_summary）

产出：output/poc0_candidates.json
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.db_schema import connect_db

OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

db = connect_db()

# === 1. 获取47道YES候选题 ===
aql_yes = '''
FOR r IN selection_results
  FILTER r.batch_id == "selection-full1"
  FILTER r.suitable == "YES"
  SORT r.problem_id
  RETURN r
'''
yes_candidates = list(db.aql.execute(aql_yes, ttl=120))
print(f"YES候选题: {len(yes_candidates)}道")

# === 2. 获取69道假朋友候选 ===
aql_ff = '''
FOR r IN selection_results
  FILTER r.batch_id == "selection-full1"
  FILTER r.false_friend_candidate == "yes"
  SORT r.problem_id
  RETURN r
'''
false_friends = list(db.aql.execute(aql_ff, ttl=120))
print(f"假朋友候选: {len(false_friends)}道")

# === 3. 获取30道边界候选 ===
aql_bc = '''
FOR r IN selection_results
  FILTER r.batch_id == "selection-full1"
  FILTER r.boundary_case_candidate == "yes"
  SORT r.problem_id
  RETURN r
'''
boundary_cases = list(db.aql.execute(aql_bc, ttl=120))
print(f"边界候选: {len(boundary_cases)}道")

# === 4. 获取每道题的analysis_results记录（含题面/标准解答/AI方向摘要） ===
def get_analysis_results(problem_ids):
    """批量获取analysis_results记录"""
    if not problem_ids:
        return {}
    # 用AQL的IN操作符批量查询
    pid_list = json.dumps(problem_ids)
    aql = f'''
    FOR a IN analysis_results
      FILTER a.problem_id IN {pid_list}
      RETURN {{
        problem_id: a.problem_id,
        d1: a.d1,
        d2: a.d2,
        d1_exp: a.d1_exp,
        d2_exp: a.d2_exp,
        standard_solution_key_technique: a.standard_solution_key_technique,
        ai_direction_summary: a.ai_direction_summary,
        confidence: a.confidence,
        problem_statement: a.problem_statement,
        standard_solution: a.standard_solution,
        ai_solution_summary: a.ai_solution_summary
      }}
    '''
    results = list(db.aql.execute(aql, ttl=300))
    return {r["problem_id"]: r for r in results}

# 收集所有problem_id
all_pids = set()
for r in yes_candidates + false_friends + boundary_cases:
    all_pids.add(r["problem_id"])
all_pids = sorted(list(all_pids))
print(f"\n总共需要获取analysis_results的题数: {len(all_pids)}")

analysis_map = get_analysis_results(all_pids)
print(f"成功获取analysis_results: {len(analysis_map)}/{len(all_pids)}")

# 缺失的题
missing = [pid for pid in all_pids if pid not in analysis_map]
if missing:
    print(f"缺失analysis_results的题: {missing[:10]}{'...' if len(missing)>10 else ''}")

# === 5. 合并数据并输出 ===
def merge_selection_with_analysis(selection_records, analysis_map):
    """合并selection_results和analysis_results"""
    merged = []
    for sel in selection_records:
        pid = sel["problem_id"]
        analysis = analysis_map.get(pid, {})
        merged.append({
            "problem_id": pid,
            "selection": {
                "suitable": sel.get("suitable"),
                "batch": sel.get("batch"),
                "d2_reclassified": sel.get("d2_reclassified"),
                "selection_reason": sel.get("selection_reason"),
                "false_friend_candidate": sel.get("false_friend_candidate"),
                "boundary_case_candidate": sel.get("boundary_case_candidate"),
                "process_signal_observability": sel.get("process_signal_observability"),
                "leakage_risk": sel.get("leakage_risk"),
                "difficulty_estimate": sel.get("difficulty_estimate"),
                "branch_position_hint": sel.get("branch_position_hint"),
            },
            "analysis": {
                "d1": analysis.get("d1"),
                "d2": analysis.get("d2"),
                "d1_exp": analysis.get("d1_exp"),
                "d2_exp": analysis.get("d2_exp"),
                "standard_solution_key_technique": analysis.get("standard_solution_key_technique"),
                "ai_direction_summary": analysis.get("ai_direction_summary"),
                "confidence": analysis.get("confidence"),
                "problem_statement": analysis.get("problem_statement"),
                "standard_solution": analysis.get("standard_solution"),
                "ai_solution_summary": analysis.get("ai_solution_summary"),
            }
        })
    return merged

output = {
    "metadata": {
        "batch_id": "selection-full1",
        "fetched_at": "2026-08-17",
        "yes_count": len(yes_candidates),
        "false_friend_count": len(false_friends),
        "boundary_count": len(boundary_cases),
        "analysis_results_coverage": f"{len(analysis_map)}/{len(all_pids)}",
    },
    "yes_candidates": merge_selection_with_analysis(yes_candidates, analysis_map),
    "false_friend_candidates": merge_selection_with_analysis(false_friends, analysis_map),
    "boundary_candidates": merge_selection_with_analysis(boundary_cases, analysis_map),
}

output_path = OUTPUT_DIR / "poc0_candidates.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n产出已写入: {output_path}")
print(f"文件大小: {output_path.stat().st_size / 1024:.1f} KB")

# === 6. 打印YES候选题的简要清单（供快速审查） ===
print(f"\n{'='*80}")
print("47道YES候选题简要清单（按batch排序）:")
print(f"{'='*80}")
print(f"{'problem_id':<25} {'batch':<12} {'d2_reclass':<25} {'proc_sig':<10} {'leak':<8} {'diff':<8} {'branch':<8}")
print("-" * 120)
for r in sorted(output["yes_candidates"], key=lambda x: (x["selection"]["batch"] or "", x["problem_id"])):
    s = r["selection"]
    print(f"{r['problem_id']:<25} {s['batch'] or 'N/A':<12} {s['d2_reclassified'] or 'N/A':<25} {s['process_signal_observability'] or 'N/A':<10} {s['leakage_risk'] or 'N/A':<8} {s['difficulty_estimate'] or 'N/A':<8} {s['branch_position_hint'] or 'N/A':<8}")

print(f"\n{'='*80}")
print(f"假朋友候选前10道:")
print(f"{'='*80}")
for r in output["false_friend_candidates"][:10]:
    s = r["selection"]
    a = r["analysis"]
    print(f"{r['problem_id']:<25} d1={a['d1'] or 'N/A':<10} d2={a['d2'] or 'N/A':<15} leak={s['leakage_risk'] or 'N/A':<8}")
    if a.get("ai_direction_summary"):
        print(f"  AI方向: {a['ai_direction_summary'][:100]}...")

print(f"\n{'='*80}")
print(f"边界候选前10道:")
print(f"{'='*80}")
for r in output["boundary_candidates"][:10]:
    s = r["selection"]
    a = r["analysis"]
    print(f"{r['problem_id']:<25} d1={a['d1'] or 'N/A':<10} d2={a['d2'] or 'N/A':<15} leak={s['leakage_risk'] or 'N/A':<8}")
    if a.get("ai_direction_summary"):
        print(f"  AI方向: {a['ai_direction_summary'][:100]}...")
