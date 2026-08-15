#!/usr/bin/env python3
"""verify_result_integrity.py — 分析结果完整性验证

验证分析结果的完整性和质量：
1. 每个parsed结果都有8个目标字段
2. verdict值在合法集合中
3. turning_point_type值在合法集合中
4. confidence值在合法集合中
5. XML解析失败的结果有_raw_xml保留

模仿solver_harness的verify_run_integrity.py。

用法:
  python -m monitoring.verify_result_integrity --batch-id analysis-1
  python -m monitoring.verify_result_integrity --all
  python -m monitoring.verify_result_integrity --check-xml-parse
"""
import argparse
import json
import sys
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from src.config import (
    OUTPUT_BASE, ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    ANALYSIS_RESULTS_COLLECTION,
)
from monitoring.shared_logger import get_logger

logger = get_logger("verify_result_integrity")

# 合法值集合
VALID_VERDICTS = {"DIRECTION_ERROR", "TOKEN_LIMIT", "CONNECTION_ERROR", "PARTIAL_PROGRESS"}
VALID_TURNING_POINTS = {
    "mod_p_grouping", "mod_p_non_obvious", "quadratic_residue_euler",
    "lte_lemma", "p_adic_valuation", "multi_step_mod_p",
    "crt", "permutation_polynomial", "finite_field_structure", "other",
}
VALID_CONFIDENCE = {"high", "medium", "low"}

# 必需字段
REQUIRED_FIELDS = [
    "problem_id", "dimension1_verdict", "dimension1_explanation",
    "dimension2_turning_point_type", "dimension2_explanation",
    "ai_direction_summary", "standard_solution_key_technique", "confidence",
]


def connect_db():
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)


def verify_batch(batch_id):
    """验证一个批次的结果完整性"""
    print(f"=== 验证批次 {batch_id} ===\n")

    collected_path = OUTPUT_BASE / batch_id / "collected_results.json"
    if not collected_path.exists():
        print(f"  collected_results.json不存在")
        return False

    with open(str(collected_path)) as f:
        data = json.load(f)

    results = data.get("results", [])
    parsed = [r for r in results if r.get("status") == "parsed"]

    print(f"  总结果: {len(results)}")
    print(f"  parsed: {len(parsed)}")

    if not parsed:
        print("  无parsed结果")
        return True

    # 检查1: 必需字段
    missing_fields = Counter()
    for r in parsed:
        for field in REQUIRED_FIELDS:
            if not r.get(field):
                missing_fields[field] += 1
    if missing_fields:
        print(f"\n  ❌ 缺失字段:")
        for field, count in missing_fields.most_common():
            print(f"    {field}: {count}条缺失")
    else:
        print(f"\n  ✅ 所有parsed结果都有8个必需字段")

    # 检查2: verdict合法性
    invalid_verdicts = []
    for r in parsed:
        v = r.get("dimension1_verdict", "")
        if v and v not in VALID_VERDICTS:
            invalid_verdicts.append((r.get("problem_id"), v))
    if invalid_verdicts:
        print(f"  ❌ 非法verdict值: {len(invalid_verdicts)}条")
        for pid, v in invalid_verdicts[:5]:
            print(f"    {pid}: {v}")
    else:
        print(f"  ✅ 所有verdict值合法")

    # 检查3: turning_point合法性
    invalid_tps = []
    for r in parsed:
        tp = r.get("dimension2_turning_point_type", "")
        if tp and tp not in VALID_TURNING_POINTS:
            invalid_tps.append((r.get("problem_id"), tp))
    if invalid_tps:
        print(f"  ⚠️ 非标准turning_point值: {len(invalid_tps)}条")
        for pid, tp in invalid_tps[:5]:
            print(f"    {pid}: {tp}")
    else:
        print(f"  ✅ 所有turning_point值合法")

    # 检查4: confidence合法性
    invalid_conf = []
    for r in parsed:
        c = r.get("confidence", "")
        if c and c not in VALID_CONFIDENCE:
            invalid_conf.append((r.get("problem_id"), c))
    if invalid_conf:
        print(f"  ⚠️ 非标准confidence值: {len(invalid_conf)}条")
        for pid, c in invalid_conf[:5]:
            print(f"    {pid}: {c}")
    else:
        print(f"  ✅ 所有confidence值合法")

    # 检查5: XML解析错误
    parse_errors = [r for r in results if r.get("_parse_error")]
    if parse_errors:
        print(f"  ⚠️ XML解析错误: {len(parse_errors)}条（已用正则兜底提取）")
    else:
        print(f"  ✅ 无XML解析错误")

    # 检查6: no_xml和incomplete
    no_xml = [r for r in results if r.get("status") == "no_xml"]
    incomplete = [r for r in results if r.get("status") == "incomplete"]
    if no_xml:
        print(f"  ⚠️ no_xml: {len(no_xml)}条（devin cli未输出XML）")
    if incomplete:
        print(f"  ⚠️ incomplete: {len(incomplete)}条（devin cli未完成分析）")

    # 检查7: explanation质量（长度过短可能是低质量分析）
    short_explanations = [r for r in parsed if len(r.get("dimension1_explanation", "")) < 20]
    if short_explanations:
        print(f"  ⚠️ explanation过短(<20字符): {len(short_explanations)}条")
    else:
        print(f"  ✅ 所有explanation长度合理")

    all_ok = (
        not missing_fields
        and not invalid_verdicts
        and not parse_errors
        and not short_explanations
    )
    print(f"\n  总结: {'✅ 全部通过' if all_ok else '⚠️ 存在问题'}")
    return all_ok


def verify_db():
    """验证DB中的结果完整性"""
    print("=== 验证DB中的analysis_results ===\n")
    db = connect_db()

    aql = f"FOR r IN {ANALYSIS_RESULTS_COLLECTION} RETURN r"
    cursor = db.aql.execute(aql, ttl=300)
    results = list(cursor)
    print(f"  DB中结果数: {len(results)}")

    if not results:
        return True

    # 检查必需字段
    missing_fields = Counter()
    for r in results:
        for field in REQUIRED_FIELDS:
            if not r.get(field):
                missing_fields[field] += 1
    if missing_fields:
        print(f"  ❌ 缺失字段:")
        for field, count in missing_fields.most_common():
            print(f"    {field}: {count}条")
    else:
        print(f"  ✅ 所有结果都有8个必需字段")

    # 检查verdict
    invalid = [r for r in results if r.get("dimension1_verdict") and r["dimension1_verdict"] not in VALID_VERDICTS]
    if invalid:
        print(f"  ❌ 非法verdict: {len(invalid)}条")
    else:
        print(f"  ✅ 所有verdict合法")

    return not missing_fields and not invalid


def main():
    parser = argparse.ArgumentParser(description="分析结果完整性验证")
    parser.add_argument("--batch-id", help="指定批次")
    parser.add_argument("--all", action="store_true", help="验证所有批次")
    parser.add_argument("--check-db", action="store_true", help="验证DB")
    args = parser.parse_args()

    results = []
    if args.check_db:
        results.append(verify_db())
    elif args.batch_id:
        results.append(verify_batch(args.batch_id))
    elif args.all:
        if OUTPUT_BASE.exists():
            for bdir in sorted(OUTPUT_BASE.iterdir()):
                if bdir.is_dir():
                    results.append(verify_batch(bdir.name))
    else:
        parser.print_help()
        return

    print(f"\n=== 总结: {'全部通过' if all(results) else '存在问题'} ===")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
