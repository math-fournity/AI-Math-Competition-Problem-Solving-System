"""selfrun_intake.py — ZCode自跑载体intake组件

devin cli载体失效（2026-08-16）后的替代写入端。ZCode主会话/subagent产出
分析（Pipe 1）或审计（Pipe 2）的XML结果后，经本组件进入流水线：

  1. validate — 用collector的同款解析函数做准入校验（保证下游必能解析）
  2. write_export — 按devin --export格式写exports/conversation.json
  3. mark_completed — DB run状态推进到completed，事件带carrier标记
  4. collect_delta — 只收集新completed的run（避免全量重收导致结果翻倍）

设计约束：
  - 只做写入端，不修改launcher/collector/aggregator的任何逻辑
  - conversation.json格式与devin产物一致（steps[].source=="agent"）
  - 所有落盘带selfrun_meta.json，保持运行痕迹可追溯（six-trace-preservation）

用法：
  python -m src.selfrun_intake validate --kind analysis --xml-file out.xml
  python -m src.selfrun_intake ingest-analysis --exp-id <id> --xml-file out.xml [--runtime N]
  python -m src.selfrun_intake ingest-audit --exp-id <id> --xml-file out.xml [--runtime N]
  python -m src.selfrun_intake collect-delta --batch-id <id>
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import ANALYSIS_TRAJECTORY_BASE, OUTPUT_BASE, ANALYSIS_COMPLETE_MARKER
from src.db_schema import (
    connect_db, ensure_schema, insert_event, insert_result, update_run,
    make_verdict, ANALYSIS_RUNS_COLLECTION,
)
from src.result_collector import extract_xml_block, parse_xml, collect_one
from src.audit_result_collector import extract_audit_xml_block, parse_audit_xml
from src.audit_collector import AUDIT_RUNS_COLLECTION
from monitoring.shared_logger import get_logger

logger = get_logger("selfrun_intake")

CARRIER = "zcode-selfrun"
CARRIER_MODEL = "glm-5.2 (ZCode session)"

D1_VERDICTS = {"DIRECTION_ERROR", "TOKEN_LIMIT", "CONNECTION_ERROR", "PARTIAL_PROGRESS"}
D1_OPERABLE = {"DIRECTION_ERROR", "PARTIAL_PROGRESS"}
D2_TYPES = {
    "mod_p_grouping", "mod_p_non_obvious", "quadratic_residue_euler", "lte_lemma",
    "p_adic_valuation", "multi_step_mod_p", "crt", "permutation_polynomial",
    "finite_field_structure", "other",
}
AUDIT_STATUSES = {
    "PASS", "PASS_SELECTABLE", "FAIL_PARSE_ERROR", "FAIL_INCOMPLETE",
    "FAIL_CONTENT_CORRUPT", "FAIL_INCONSISTENT", "PASS_NOT_SELECTABLE",
}
ANALYSIS_FIELDS = [
    "problem_id", "dimension1_verdict", "dimension1_explanation",
    "dimension2_turning_point_type", "dimension2_explanation",
    "ai_direction_summary", "standard_solution_key_technique", "confidence",
]
PLACEHOLDER_LEAKS = ["ONE_OF:", "1-3 sentences", "1 sentence describing", "DIRECTION_ERROR|"]


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# 校验 — 复用collector同款解析函数，准入即保证下游可解析
# ============================================================

def validate_analysis_text(text):
    """校验Pipe 1分析输出。返回(parsed, errors, warnings)"""
    errors, warnings = [], []
    if ANALYSIS_COMPLETE_MARKER not in text:
        errors.append(f"缺少完成标记 {ANALYSIS_COMPLETE_MARKER}")
    xml_block = extract_xml_block(text)
    if not xml_block:
        return None, errors + ["提取不到<analysis>XML块"], warnings
    parsed = parse_xml(xml_block)
    if "_parse_error" in parsed:
        return None, errors + [f"XML解析失败: {parsed.get('_parse_error')}"], warnings

    for f in ANALYSIS_FIELDS:
        if not str(parsed.get(f, "") or "").strip():
            errors.append(f"字段为空: {f}")
    for leak in PLACEHOLDER_LEAKS:
        for f in ["dimension1_explanation", "dimension2_explanation",
                  "ai_direction_summary", "standard_solution_key_technique"]:
            if leak in str(parsed.get(f, "")):
                errors.append(f"字段{f}含模板占位符泄漏: {leak!r}")

    d1 = str(parsed.get("dimension1_verdict", "")).strip()
    if d1 and d1 not in D1_VERDICTS:
        errors.append(f"dimension1_verdict非法: {d1}")
    d2 = str(parsed.get("dimension2_turning_point_type", "")).strip()
    if d1 in D1_OPERABLE and d2 and d2 not in D2_TYPES:
        errors.append(f"dimension2_turning_point_type非法: {d2}")
    conf = str(parsed.get("confidence", "")).strip().lower()
    if conf and conf not in {"high", "medium", "low"}:
        errors.append(f"confidence非法: {conf}")

    # 审计D1/D2可操作性预警（不阻断，但审计会FAIL）
    d1_exp = str(parsed.get("dimension1_explanation", ""))
    d2_exp = str(parsed.get("dimension2_explanation", ""))
    if d1 in D1_OPERABLE and len(d1_exp) < 100:
        warnings.append(f"dimension1_explanation仅{len(d1_exp)}字符，审计D1要求>=100")
    if d1 in D1_OPERABLE and len(d2_exp) < 100:
        warnings.append(f"dimension2_explanation仅{len(d2_exp)}字符，审计D2要求>=100")
    if d1 in D1_OPERABLE and "<" in d1_exp and "/dimension" in d1_exp:
        errors.append("dimension1_explanation含XML标签泄漏")
    if d1 in D1_OPERABLE and "<" in d2_exp and "/dimension" in d2_exp:
        errors.append("dimension2_explanation含XML标签泄漏")
    return parsed, errors, warnings


def validate_audit_text(text):
    """校验Pipe 2审计输出。返回(parsed, errors, warnings)"""
    errors, warnings = [], []
    if "### AUDIT COMPLETE" not in text:
        errors.append("缺少完成标记 ### AUDIT COMPLETE")
    xml_block = extract_audit_xml_block(text)
    if not xml_block:
        return None, errors + ["提取不到<audit>XML块"], warnings
    parsed = parse_audit_xml(xml_block)
    status = str(parsed.get("audit_status", "")).strip()
    if status not in AUDIT_STATUSES:
        errors.append(f"audit_status非法或为空: {status!r}")
    if not parsed.get("check_results"):
        errors.append("check_results为空")
    return parsed, errors, warnings


# ============================================================
# 落盘 — devin export格式 + selfrun_meta
# ============================================================

def write_export(kind, exp_id, output_text, runtime_seconds=None):
    """写exports/conversation.json（devin格式）+ selfrun_meta.json"""
    traj_dir = ANALYSIS_TRAJECTORY_BASE / exp_id
    exports_dir = traj_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    marker = ANALYSIS_COMPLETE_MARKER if kind == "analysis" else "### AUDIT COMPLETE"
    conv = {
        "schema_version": 1,
        "session_id": f"{CARRIER}-{exp_id}",
        "agent": CARRIER,
        "steps": [
            {
                "step_id": 0,
                "timestamp": _utc_now(),
                "source": "user",
                "message": f"(AGENTS.md prompt for {exp_id} — 见work_dir)",
                "extra": {"prompt_file": str(Path(os.environ.get("SOLVER_BASE", "/Volumes/data/math-agent-glm5.2-tmux-agents-dir")) / "analysis-devin-failure" / exp_id / 'AGENTS.md')},
            },
            {
                "step_id": 1,
                "timestamp": _utc_now(),
                "source": "agent",
                "message": output_text,
                "extra": {"carrier": CARRIER, "model": CARRIER_MODEL},
            },
        ],
        "final_metrics": {
            "carrier": CARRIER,
            "model": CARRIER_MODEL,
            "runtime_seconds": runtime_seconds,
            "completed": marker in output_text,
        },
    }
    export_path = exports_dir / "conversation.json"
    export_path.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = {
        "carrier": CARRIER,
        "model": CARRIER_MODEL,
        "kind": kind,
        "exp_id": exp_id,
        "ingested_at": _utc_now(),
        "runtime_seconds": runtime_seconds,
        "output_chars": len(output_text),
    }
    (exports_dir / "selfrun_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return export_path


# ============================================================
# DB状态推进
# ============================================================

def mark_analysis_completed(db, exp_id, batch_id, runtime_seconds=None):
    """analysis_run状态 → completed（对齐launcher完成时的字段集）"""
    run = db.collection(ANALYSIS_RUNS_COLLECTION).get(exp_id)
    if run is None:
        # 兜底：按analysis_exp_id索引查
        cur = db.aql.execute(
            f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.analysis_exp_id == @e RETURN r",
            bind_vars={"e": exp_id}, ttl=30)
        rows = list(cur)
        if not rows:
            raise ValueError(f"analysis_runs中找不到 {exp_id}")
        run = rows[0]
    key = run["_key"]
    now = _utc_now()
    update_run(db, key, {
        "status": "completed",
        "ended_at": now,
        "updated_at": now,
        "runtime_seconds": runtime_seconds,
        "end_reason": "selfrun_complete",
        "verdict": make_verdict("completed", "selfrun_complete"),
        "carrier": {"type": CARRIER, "model": CARRIER_MODEL, "replaces": "devin-cli"},
    })
    insert_event(db, run.get("batch_id", batch_id), "analysis_selfrun_completed", {
        "analysis_exp_id": exp_id,
        "problem_id": run.get("problem_id"),
        "carrier": CARRIER,
        "runtime_seconds": runtime_seconds,
    }, run_key=key)
    return key


def mark_audit_completed(db, exp_id, runtime_seconds=None):
    """audit_run状态 → completed"""
    run = db.collection(AUDIT_RUNS_COLLECTION).get(exp_id)
    if run is None:
        raise ValueError(f"audit_runs中找不到 {exp_id}")
    now = _utc_now()
    upd = {k: v for k, v in {
        "status": "completed",
        "ended_at": now,
        "updated_at": now,
        "runtime_seconds": runtime_seconds,
        "end_reason": "selfrun_complete",
        "carrier": {"type": CARRIER, "model": CARRIER_MODEL, "replaces": "devin-cli"},
    }.items()}
    upd["_key"] = exp_id
    db.collection(AUDIT_RUNS_COLLECTION).update(upd)
    return exp_id


# ============================================================
# 增量收集 — 只处理completed且未collected的run
# ============================================================

def collect_delta(batch_id):
    """收集批次中新completed的run（不重收已results_collected的，避免结果翻倍）

    与result_collector.collect_batch的单条路径完全一致（collect_one+insert_result），
    并把结果追加到collected_results.json快照。
    """
    db = connect_db()
    ensure_schema(db)
    aql = (
        f"FOR run IN {ANALYSIS_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'completed' "
        f"RETURN {{_key: run._key, problem_id: run.problem_id, analysis_exp_id: run.analysis_exp_id}}"
    )
    rows = list(db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=120))
    print(f"  completed未收集: {len(rows)}")

    collected_path = OUTPUT_BASE / batch_id / "collected_results.json"
    if collected_path.exists():
        with open(str(collected_path)) as f:
            snapshot = json.load(f)
    else:
        snapshot = {"total": 0, "parsed": 0, "no_xml": 0, "no_output": 0, "incomplete": 0, "results": []}

    n_parsed = 0
    for item in rows:
        result = collect_one(item["analysis_exp_id"], item["problem_id"], batch_id)
        result["run_key"] = item["_key"]
        snapshot["results"].append(result)
        snapshot["total"] += 1
        if result.get("status") == "parsed":
            n_parsed += 1
            snapshot["parsed"] += 1
            insert_result(db, result)
            update_run(db, item["_key"], {"status": "results_collected", "updated_at": _utc_now()})
        else:
            snapshot[result.get("status", "no_output")] = snapshot.get(result.get("status", "no_output"), 0) + 1
    with open(str(collected_path), "w") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"  本次收集: parsed={n_parsed}, 其他={len(rows) - n_parsed}")
    print(f"  快照更新: {collected_path}")
    return n_parsed


# ============================================================
# CLI
# ============================================================

def _read_text(path):
    return Path(path).read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="ZCode自跑载体intake")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="只校验不落盘")
    p_val.add_argument("--kind", choices=["analysis", "audit"], required=True)
    p_val.add_argument("--xml-file", required=True)

    p_an = sub.add_parser("ingest-analysis", help="校验+落盘+DB推进（Pipe 1）")
    p_an.add_argument("--exp-id", required=True)
    p_an.add_argument("--xml-file", required=True)
    p_an.add_argument("--runtime", type=int, default=None)
    p_an.add_argument("--batch-id", default=None, help="DB查不到时兜底用")

    p_au = sub.add_parser("ingest-audit", help="校验+落盘+DB推进（Pipe 2）")
    p_au.add_argument("--exp-id", required=True)
    p_au.add_argument("--xml-file", required=True)
    p_au.add_argument("--runtime", type=int, default=None)

    p_cd = sub.add_parser("collect-delta", help="增量收集批次新completed的run")
    p_cd.add_argument("--batch-id", required=True)

    args = parser.parse_args()

    if args.cmd == "validate":
        text = _read_text(args.xml_file)
        if args.kind == "analysis":
            parsed, errors, warnings = validate_analysis_text(text)
        else:
            parsed, errors, warnings = validate_audit_text(text)
        for w in warnings:
            print(f"WARN: {w}")
        if errors:
            for e in errors:
                print(f"ERROR: {e}")
            sys.exit(1)
        print("VALID")

    elif args.cmd == "ingest-analysis":
        text = _read_text(args.xml_file)
        parsed, errors, warnings = validate_analysis_text(text)
        for w in warnings:
            print(f"WARN: {w}")
        if errors:
            for e in errors:
                print(f"ERROR: {e}")
            sys.exit(1)
        export_path = write_export("analysis", args.exp_id, text, args.runtime)
        db = connect_db()
        ensure_schema(db)
        key = mark_analysis_completed(db, args.exp_id, args.batch_id, args.runtime)
        print(f"INGESTED analysis exp_id={args.exp_id} run_key={key}")
        print(f"  export: {export_path}")

    elif args.cmd == "ingest-audit":
        text = _read_text(args.xml_file)
        parsed, errors, warnings = validate_audit_text(text)
        for w in warnings:
            print(f"WARN: {w}")
        if errors:
            for e in errors:
                print(f"ERROR: {e}")
            sys.exit(1)
        export_path = write_export("audit", args.exp_id, text, args.runtime)
        db = connect_db()
        ensure_schema(db)
        key = mark_audit_completed(db, args.exp_id, args.runtime)
        print(f"INGESTED audit exp_id={args.exp_id} run_key={key}")
        print(f"  export: {export_path}")

    elif args.cmd == "collect-delta":
        collect_delta(args.batch_id)


if __name__ == "__main__":
    main()
