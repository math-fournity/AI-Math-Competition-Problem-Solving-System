#!/usr/bin/env python3
"""audit_asset_retention.py — WP-S 项6：解题运行结果资产存量盘点（只读）

扫描 p27_continuation_runs 全部 run 的 rounds_log 每条记录的五个路径字段，
Path.exists() 判存在，输出每类字段的缺失率表与缺失样本。

特殊口径：
  - round==1 条目按 "work_dir 的 round1_export.json 或 traj 的 round1 位置
    任一存在" 计（WP-S 双写前的旧 run 可能只有前者）
  - partial proof（round*_proof_partial.md）单独统计——WP-S 项1 前应为 0

只读：发现缺失仅记录，不做任何修复。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.continuation_config import CONTINUATION_SOLVER_BASE, CONTINUATION_TRAJECTORY_BASE
from src.continuation_db_schema import connect_db

FIELDS = ["export", "prompt_path", "proof_path", "handover_path", "map_path"]
MAX_SAMPLES = 20


def main():
    db = connect_db()
    runs = db.collection("p27_continuation_runs")
    all_runs = list(runs.all())
    print(f"扫描 {len(all_runs)} 个 run…")

    stats = {f: {"total": 0, "exists": 0, "missing": 0, "samples": []} for f in FIELDS}
    r1 = {"total": 0, "via_workdir": 0, "via_traj": 0, "missing": 0, "samples": []}
    partial_count = 0
    runs_with_partial = []

    for r in all_runs:
        rk = r["_key"]
        work_dir = None
        # work_dir 从 rounds_log 或 run 文档取；退化用约定路径
        wd_guess = CONTINUATION_SOLVER_BASE / rk
        td = CONTINUATION_TRAJECTORY_BASE / rk

        for entry in (r.get("rounds_log") or []):
            rnd = entry.get("round")
            for f in FIELDS:
                val = entry.get(f)
                if not val:
                    continue  # 空值不计入存在性统计（该轮本就没有此产物）
                stats[f]["total"] += 1
                if Path(val).exists():
                    stats[f]["exists"] += 1
                else:
                    stats[f]["missing"] += 1
                    if len(stats[f]["samples"]) < MAX_SAMPLES:
                        stats[f]["samples"].append(f"{rk} r{rnd}: {val}")

        # round1 特殊口径
        if r.get("rounds_log"):
            r1["total"] += 1
            via_wd = (wd_guess / "round1_export.json").exists()
            via_traj = (td / "round1" / "exports" / "conversation.json").exists()
            if via_wd:
                r1["via_workdir"] += 1
            if via_traj:
                r1["via_traj"] += 1
            if not via_wd and not via_traj:
                r1["missing"] += 1
                if len(r1["samples"]) < MAX_SAMPLES:
                    r1["samples"].append(rk)

        # partial proof 存量
        if wd_guess.exists():
            found = list(wd_guess.glob("round*_proof_partial.md"))
            if found:
                partial_count += len(found)
                runs_with_partial.append(f"{rk} ({len(found)}份)")

    # 输出
    lines = []
    lines.append("# 050 — 解题运行结果资产存量盘点报告（WP-S 项6）\n")
    lines.append("> 只读盘点。数据源：p27_continuation_runs.rounds_log 五路径字段 + ")
    lines.append("work_dir/traj 实物存在性检查。\n")
    lines.append(f"\n## 一、五字段存量\n")
    lines.append("| 字段 | 有值总数 | 存在 | 缺失 | 缺失率 |")
    lines.append("|---|---|---|---|---|")
    for f in FIELDS:
        s = stats[f]
        rate = f"{s['missing']/s['total']*100:.1f}%" if s["total"] else "N/A"
        lines.append(f"| {f} | {s['total']} | {s['exists']} | {s['missing']} | {rate} |")

    lines.append("\n### 缺失样本（每类最多20条）\n")
    for f in FIELDS:
        if stats[f]["samples"]:
            lines.append(f"**{f}**：")
            for s in stats[f]["samples"]:
                lines.append(f"- {s}")

    lines.append(f"\n## 二、round1 特殊口径\n")
    lines.append(f"- 有 rounds_log 的 run：{r1['total']}")
    lines.append(f"- work_dir 镜像存在：{r1['via_workdir']}")
    lines.append(f"- traj 双写位置存在：{r1['via_traj']}（WP-S 起新 run 才有）")
    lines.append(f"- 两处皆缺：{r1['missing']}")
    if r1["samples"]:
        lines.append(f"- 两处皆缺样本：{r1['samples'][:10]}")

    lines.append(f"\n## 三、partial proof 存量（WP-S 项1 生效后）\n")
    lines.append(f"- 全库 round*_proof_partial.md 共 {partial_count} 份")
    if runs_with_partial:
        for x in runs_with_partial[:20]:
            lines.append(f"- {x}")

    out = "\n".join(lines)
    print(out[:3000])
    report = Path(__file__).parent.parent / "dev-docs" / "050-资产存量盘点报告.md"
    report.write_text(out + "\n")
    print(f"\n报告已写 {report}")


if __name__ == "__main__":
    main()
