#!/usr/bin/env python3
"""trace_verify.py — 幂等验证 + 孤立资产检查

对比 asset_inventory.csv 和 trace.csv，找出仍然孤立的资产
（在 asset_inventory.csv 中但不在 trace.csv 的任何关系中）。

产出：
  - 终端输出：孤立资产统计
  - scripts/orphan_assets.csv：孤立资产清单

用法：
    python3 scripts/trace_verify.py
"""

import csv
from pathlib import Path
from collections import Counter

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY_CSV = REPO_ROOT / "scripts" / "asset_inventory.csv"
TRACE_CSV = REPO_ROOT / "trace.csv"
ORPHAN_CSV = REPO_ROOT / "scripts" / "orphan_assets.csv"


def main():
    # 读资产清单
    with open(INVENTORY_CSV, "r", encoding="utf-8") as f:
        inventory = list(csv.DictReader(f))

    # 读 trace.csv，收集所有出现过的资产 (type, id)
    with open(TRACE_CSV, "r", encoding="utf-8") as f:
        trace_rows = list(csv.DictReader(f))

    traced_assets = set()
    for r in trace_rows:
        traced_assets.add((r["source_type"], r["source_id"]))
        traced_assets.add((r["target_type"], r["target_id"]))

    # 找孤立资产
    orphans = []
    for a in inventory:
        key = (a["asset_type"], a["asset_id"])
        if key not in traced_assets:
            orphans.append(a)

    # 统计
    inv_by_type = Counter(a["asset_type"] for a in inventory)
    orphan_by_type = Counter(a["asset_type"] for a in orphans)

    print(f"=== 幂等验证报告 ===")
    print(f"资产清单总数：{len(inventory)}")
    print(f"trace.csv 关系总数：{len(trace_rows)}")
    print(f"已追溯资产数：{len(traced_assets)}")
    print(f"孤立资产数：{len(orphans)}")
    print(f"覆盖率：{(len(inventory) - len(orphans)) / len(inventory) * 100:.1f}%")

    print(f"\n=== 按类型分布 ===")
    print(f"{'类型':<20} {'总数':>6} {'孤立':>6} {'覆盖率':>8}")
    for t in sorted(inv_by_type.keys()):
        total = inv_by_type[t]
        orphan = orphan_by_type.get(t, 0)
        cov = (total - orphan) / total * 100 if total > 0 else 0
        print(f"{t:<20} {total:>6} {orphan:>6} {cov:>7.1f}%")

    # 写孤立资产清单
    if orphans:
        with open(ORPHAN_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["asset_type", "asset_id", "file_path", "description"])
            w.writeheader()
            for a in orphans:
                w.writerow(a)
        print(f"\n孤立资产清单 → {ORPHAN_CSV}")
        print(f"\n=== 孤立资产示例（前20个）===")
        for a in orphans[:20]:
            print(f"  [{a['asset_type']}] {a['asset_id']} — {a['description']}")
    else:
        print(f"\n无孤立资产！全资产覆盖完成。")


if __name__ == "__main__":
    main()
