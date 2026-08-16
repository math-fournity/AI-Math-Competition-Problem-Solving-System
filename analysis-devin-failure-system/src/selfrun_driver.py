"""selfrun_driver.py — selfrun波次调度器

把"派subagent分析"从手工操作固化为可复现流程：
  plan    生成下一波任务文件（每agent一份，含完整指令+题目清单），自动回收此前丢任务的孤儿题
  status  检查所有已派发任务的产出状态（缺产出/未校验/已入库）
  sweep   批量校验新产出，--ingest时落盘入库并增量收集
  recheck 抽样生成双盲重分析任务（输出到selfrun_check.xml，用于测一致率）

任务文件即派发单元：主会话只需对每份任务文件派一个subagent，
prompt里只引用任务文件路径，不再手抄题号/路径（消灭抄写错误）。

用法：
  python -m src.selfrun_driver plan --count 12 [--source polymath] [--per-agent 2]
  python -m src.selfrun_driver status
  python -m src.selfrun_driver sweep [--ingest]
  python -m src.selfrun_driver recheck --count 5
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import OUTPUT_BASE, ANALYSIS_SOLVER_BASE
from src.db_schema import connect_db, ANALYSIS_RUNS_COLLECTION
from src.selfrun_intake import (
    validate_analysis_text, write_export, mark_analysis_completed, collect_delta,
)
from monitoring.shared_logger import get_logger

logger = get_logger("selfrun_driver")

SELFRUN_DIR = OUTPUT_BASE / "selfrun"
TASK_TEMPLATE = Path(__file__).parent.parent / "templates" / "selfrun_subagent_task.md"
RETRY_STATUSES = ["queued", "pending_retry", "failed_stall", "rate_limited",
                  "dead_session", "no_xml", "incomplete", "running", "completed"]
BATCH_ID = "full-analysis-30c"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# 剩余清单
# ============================================================

def get_remaining(db, source=None, limit=None):
    done = set()
    for bid in ["full-analysis-30c", "full-analysis-v2"]:
        done |= set(db.aql.execute(
            "FOR r IN analysis_runs FILTER r.batch_id == @bid "
            "FILTER r.status == 'results_collected' RETURN DISTINCT r.problem_id",
            bind_vars={"bid": bid}))
    rem = []
    for r in db.aql.execute(
        f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.batch_id == @bid "
            f"FILTER r.status IN @st FILTER r.problem_id NOT IN @done RETURN r",
            bind_vars={"bid": BATCH_ID, "st": RETRY_STATUSES, "done": sorted(done)},
            ttl=300):
        wd = r.get("work_dir", "")
        am = Path(wd) / "AGENTS.md" if wd else None
        if not am or not am.exists():
            continue
        out = Path(wd) / "selfrun_output.xml"
        if out.exists():
            continue  # 已有产出，等sweep
        if source and not r["problem_id"].startswith(source):
            continue
        rem.append({
            "exp_id": r["analysis_exp_id"], "pid": r["problem_id"],
            "agents_md": str(am), "output": str(out), "size": am.stat().st_size,
        })
    rem.sort(key=lambda x: x["size"])
    if limit:
        rem = rem[:limit]
    return rem


# ============================================================
# 任务文件
# ============================================================

def _task_files():
    return sorted(SELFRUN_DIR.glob("wave*_agent*.md"))


def _parse_task_file(path):
    """解析任务文件中的题目条目"""
    text = path.read_text(encoding="utf-8")
    items = []
    for m in re.finditer(r"- exp_id: (\S+)\n- problem_id: (\S+)\n- agents_md: (\S+)", text):
        items.append({"exp_id": m.group(1), "pid": m.group(2), "agents_md": m.group(3)})
    return items


def _render_task_file(items, agent_idx, wave_num, check_mode=False):
    lines = []
    for i, it in enumerate(items, 1):
        out = (Path(it["agents_md"]).parent / ("selfrun_check.xml" if check_mode else "selfrun_output.xml")).resolve()
        kb = (Path(it["agents_md"]).stat().st_size + 1023) // 1024
        lines.append(f"### 题{i}")
        lines.append(f"- exp_id: {it['exp_id']}")
        lines.append(f"- problem_id: {it['pid']}")
        lines.append(f"- agents_md: {it['agents_md']} （约{kb}KB）")
        lines.append(f"- 输出到: {out}")
        lines.append("")
    body = "\n".join(lines)
    template = TASK_TEMPLATE.read_text(encoding="utf-8")
    return template.replace("{{TASKS}}", body)


def _next_wave_num():
    nums = [int(m.group(1)) for f in _task_files()
            if (m := re.match(r"wave(\d+)_agent", f.name))]
    return (max(nums) + 1) if nums else 1


def cmd_plan(args):
    db = connect_db()
    # 孤儿回收：此前任务文件中产出仍缺失的题，优先重新派发
    orphans = []
    for tf in _task_files():
        for it in _parse_task_file(tf):
            if "selfrun_check" in str(tf):
                continue
            out = Path(it["agents_md"]).parent / "selfrun_output.xml"
            if not out.exists():
                orphans.append({**it, "output": str(out),
                                "size": Path(it["agents_md"]).stat().st_size})
    # 去重
    seen = set()
    orphans = [o for o in orphans if not (o["pid"] in seen or seen.add(o["pid"]))]

    fresh = get_remaining(db, source=args.source, limit=args.count)
    # fresh里排除orphans已含的
    op = {o["pid"] for o in orphans}
    fresh = [f for f in fresh if f["pid"] not in op][:max(0, args.count - len(orphans))]
    todo = orphans + fresh
    if not todo:
        print("无待派发任务")
        return

    wave = _next_wave_num()
    groups = [todo[i:i + args.per_agent] for i in range(0, len(todo), args.per_agent)]
    print(f"=== 生成波次 wave{wave:03d}：{len(todo)}题/{len(groups)}个agent任务"
          f"（孤儿回收{len(orphans)}题） ===")
    for k, g in enumerate(groups, 1):
        p = SELFRUN_DIR / f"wave{wave:03d}_agent{k}.md"
        p.write_text(_render_task_file(g, k, wave), encoding="utf-8")
        print(f"  {p}  ({len(g)}题: {', '.join(x['pid'] for x in g)})")
    print("\n派发提示：对每个任务文件派一个subagent，prompt只需：")
    print("  『用Read读取<任务文件路径>并严格执行其中的全部指令，完成后按其汇报格式汇报。』")


def cmd_status(args):
    db = connect_db()
    all_items, missing, present, ingested = [], [], [], 0
    for tf in _task_files():
        if "selfrun_check" in str(tf):
            continue
        for it in _parse_task_file(tf):
            all_items.append(it)
            out = Path(it["agents_md"]).parent / "selfrun_output.xml"
            if not out.exists():
                missing.append(it["pid"])
            else:
                present.append(it["pid"])
                run = db.collection(ANALYSIS_RUNS_COLLECTION).get(it["exp_id"])
                if run and run.get("status") == "results_collected":
                    ingested += 1
    # 校验未入库的产出
    invalid = []
    verdicts = {}
    for it in all_items:
        out = Path(it["agents_md"]).parent / "selfrun_output.xml"
        if not out.exists():
            continue
        run = db.collection(ANALYSIS_RUNS_COLLECTION).get(it["exp_id"])
        if run and run.get("status") == "results_collected":
            continue
        parsed, errors, _ = validate_analysis_text(out.read_text(encoding="utf-8"))
        if errors:
            invalid.append((it["pid"], errors[:2]))
        elif parsed:
            verdicts[it["pid"]] = parsed.get("dimension1_verdict", "?")
    print(f"已派发: {len(all_items)}  产出缺失: {len(missing)}  产出就绪: {len(present)}  已入库: {ingested}")
    if missing:
        print(f"  缺失: {', '.join(missing[:20])}{' ...' if len(missing) > 20 else ''}")
    if invalid:
        print(f"  校验失败: {len(invalid)}")
        for pid, errs in invalid[:10]:
            print(f"    {pid}: {errs}")
    if verdicts:
        from collections import Counter
        print(f"  待入库产出判定分布: {dict(Counter(verdicts.values()))}")
    rem = get_remaining(db)
    print(f"剩余未派发（含跨波）: {len(rem)}")


def cmd_sweep(args):
    db = connect_db()
    n_ok, n_bad = 0, 0
    for tf in _task_files():
        for it in _parse_task_file(tf):
            out = Path(it["agents_md"]).parent / "selfrun_output.xml"
            if not out.exists():
                continue
            run = db.collection(ANALYSIS_RUNS_COLLECTION).get(it["exp_id"])
            if run and run.get("status") == "results_collected":
                continue
            text = out.read_text(encoding="utf-8")
            parsed, errors, warnings = validate_analysis_text(text)
            if errors:
                n_bad += 1
                print(f"INVALID {it['pid']}: {errors[:2]}")
                continue
            if args.ingest:
                write_export("analysis", it["exp_id"], text)
                mark_analysis_completed(db, it["exp_id"], BATCH_ID)
            n_ok += 1
    print(f"校验通过: {n_ok}  失败: {n_bad}")
    if args.ingest and n_ok:
        collect_delta(BATCH_ID)


def cmd_recheck(args):
    """从最近入库的selfrun产出中抽样，生成双盲重分析任务（selfrun_check.xml）"""
    db = connect_db()
    rows = list(db.aql.execute(
        f"FOR r IN {ANALYSIS_RUNS_COLLECTION} FILTER r.batch_id == @bid "
        f"FILTER r.status == 'results_collected' FILTER r.carrier != null "
        f"SORT r.updated_at DESC LIMIT @n RETURN r",
        bind_vars={"bid": BATCH_ID, "n": args.count}, ttl=60))
    if not rows:
        print("无可抽样的selfrun入库结果")
        return
    import random
    random.seed(args.seed if args.seed is not None else 7)
    picks = random.sample(rows, min(args.count, len(rows)))
    wave = _next_wave_num()
    print(f"=== 双盲重分析抽样 {len(picks)}题 ===")
    groups = [picks[i:i + args.per_agent] for i in range(0, len(picks), args.per_agent)]
    for k, g in enumerate(groups, 1):
        items = [{"exp_id": r["analysis_exp_id"], "pid": r["problem_id"],
                  "agents_md": str(Path(r["work_dir"]) / "AGENTS.md")} for r in g]
        p = SELFRUN_DIR / f"wave{wave:03d}_agent{k}_selfcheck.md"
        p.write_text(_render_task_file(items, k, wave, check_mode=True), encoding="utf-8")
        print(f"  {p}  ({len(items)}题: {', '.join(x['pid'] for x in items)})")
    print("输出到各题的selfrun_check.xml（不覆盖主产出）")


def main():
    ap = argparse.ArgumentParser(description="selfrun波次调度器")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="生成下一波任务文件")
    p.add_argument("--count", type=int, default=6)
    p.add_argument("--source", default=None, help="题库前缀过滤（如polymath）")
    p.add_argument("--per-agent", type=int, default=2)
    p = sub.add_parser("status", help="产出状态总览")
    p = sub.add_parser("sweep", help="批量校验（--ingest入库+增量收集）")
    p.add_argument("--ingest", action="store_true")
    p = sub.add_parser("recheck", help="双盲重分析抽样")
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--per-agent", type=int, default=2)
    p.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    SELFRUN_DIR.mkdir(parents=True, exist_ok=True)
    {"plan": cmd_plan, "status": cmd_status, "sweep": cmd_sweep, "recheck": cmd_recheck}[args.cmd](args)


if __name__ == "__main__":
    main()
