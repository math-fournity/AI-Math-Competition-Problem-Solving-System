"""observability.py — 行为流水日志（flow ledger），016事故后的过程可观测性层

为什么存在：2026-08-20事故（dev-docs/016）中，monitor的所有A类检查都是
"存量快照"（队列长度/session数/状态计数），完全看不到"流动过程"——同一道题
18分钟被启动上千次，存量视角只看到pending一直是500。launcher的关键判定
（为什么截断、为什么重入队、为什么跳过）只存在于tmux pane里，kill即丢失。

设计：launcher的**每个状态转移**都追加一行JSONL到 log/flow/flow-YYYYMMDD.jsonl。
这是"系统行为黑匣子"——Master Agent用CLI回看任意时间窗口的完整逻辑流动：
  谁被dequeue → 为什么被跳过/启动 → 判定结果是什么 → 重入队还是完成

事件类型：
  batch_start        批次启动
  graceful_stop      优雅停止
  dequeue            run从pending队列取出（含priority）
  skip_duplicate     P0-1防抖拦截（内存dict已有）
  skip_orphan        P0-1防抖拦截（注册表有活跃孤儿session）
  launch_solve       启动解题devin cli（含session_name）
  launch_handover    启动HANDOVER生成devin cli（含session_name）
  requeue            重入队（截断/防抖，含priority和reason）
  judge              判定结果（completed/truncated/stale_proof/stale_export/
                     dead_session等，含reason和since_ts细节）
  round_done         一轮完成
  run_completed      整题完成（final_status）
  run_failed         整题失败（含reason）

用法（launcher内）：
  from src.observability import log_flow
  log_flow("launch_solve", run_key=run_key, pid=pid, round=round_num,
           session_name=session_name)

用法（Master Agent查看）：
  python -m src.observability --tail 50          # 最近50条
  python -m src.observability --run-key p27-full-amo_bench_00000006
  python -m src.observability --since 1h         # 最近1小时
  python -m src.observability --stats --since 1h # 聚合：启动频率/抖动/判定分布
  python -m src.observability --clean-days 14    # 清理14天前的流水文件

写入是尽力而为（best-effort）：流水日志失败绝不影响launcher主流程。
"""
import argparse
import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FLOW_DIR = PROJECT_ROOT / "log" / "flow"

# 保留策略（默认天数）——flow文件每天一个，超过14天可清理
DEFAULT_RETENTION_DAYS = 14


def _now():
    return datetime.now(timezone.utc)


def _flow_file(ts: datetime = None) -> Path:
    ts = ts or _now()
    return FLOW_DIR / f"flow-{ts.strftime('%Y%m%d')}.jsonl"


def log_flow(event: str, run_key: str = None, **fields):
    """追加一条行为流水（JSONL）。失败静默——黑匣子不能拖垮飞机。"""
    try:
        FLOW_DIR.mkdir(parents=True, exist_ok=True)
        now = _now()
        entry = {
            "ts": now.isoformat(),
            "ts_ms": int(time.time() * 1000),
            "event": event,
            "run_key": run_key,
        }
        entry.update(fields)
        with open(_flow_file(now), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


# ============================================================
# 读侧：给Master Agent的回看工具
# ============================================================

def _parse_since(since_str):
    """'1h'/'30m'/'2d' → datetime；非法返回None"""
    if not since_str:
        return None
    s = since_str.strip().lower()
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if s and s[-1] in mult and s[:-1].isdigit():
        return _now() - timedelta(seconds=int(s[:-1]) * mult[s[-1]])
    return None


def read_flow(since: datetime = None, run_key: str = None, event: str = None,
              tail: int = None):
    """读流水文件，返回entries列表（按时间升序）。

    自动跨天文件合并读取；tail=N时取最后N条。
    """
    entries = []
    files = sorted(FLOW_DIR.glob("flow-*.jsonl")) if FLOW_DIR.exists() else []
    for fp in files:
        # since过滤——早于当天0点(UTC)的文件可整文件跳过
        if since is not None:
            try:
                day = datetime.strptime(fp.stem, "flow-%Y%m%d").replace(
                    tzinfo=timezone.utc)
                if day + timedelta(days=1) <= since:
                    continue
            except ValueError:
                pass
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if since is not None:
                        try:
                            ets = datetime.fromisoformat(e["ts"])
                        except (KeyError, ValueError):
                            ets = None
                        if ets is not None and ets < since:
                            continue
                    if run_key is not None and e.get("run_key") != run_key:
                        continue
                    if event is not None and e.get("event") != event:
                        continue
                    entries.append(e)
        except OSError:
            continue
    if tail is not None:
        entries = entries[-tail:]
    return entries


def flow_stats(since: datetime = None):
    """聚合统计——Master Agent的"系统流动健康"一眼视图。

    返回dict：
      total: 事件总数
      window_seconds: 统计窗口
      per_run_launch: 每run_key的launch次数（降序Top10）
      churn_suspects: 1小时内launch>=5的run_key（失控循环嫌疑）
      events_per_minute: 每分钟事件数（速率）
      launch_per_minute: 每分钟启动数
      judge_outcomes: 判定结果分布（Top10）
      requeue_reasons: 重入队原因分布
    """
    entries = read_flow(since=since)
    now = _now()
    if entries:
        try:
            window = max(1.0, (now - datetime.fromisoformat(entries[0]["ts"]))
                         .total_seconds())
        except (KeyError, ValueError):
            window = 1.0
    else:
        window = 1.0

    per_run_launch = Counter()
    launch_events = 0
    judge_outcomes = Counter()
    requeue_reasons = Counter()
    event_counts = Counter()
    hour_ago = now - timedelta(hours=1)
    per_run_launch_1h = Counter()

    for e in entries:
        event = e.get("event", "?")
        event_counts[event] += 1
        rk = e.get("run_key")
        if event in ("launch_solve", "launch_handover"):
            launch_events += 1
            if rk:
                per_run_launch[rk] += 1
                try:
                    if datetime.fromisoformat(e["ts"]) >= hour_ago:
                        per_run_launch_1h[rk] += 1
                except (KeyError, ValueError):
                    pass
        elif event == "judge":
            judge_outcomes[e.get("outcome", "?")] += 1
        elif event == "requeue":
            requeue_reasons[e.get("reason", "?")] += 1

    return {
        "total": len(entries),
        "window_seconds": int(window),
        "events_per_minute": round(len(entries) / (window / 60), 2),
        "launch_per_minute": round(launch_events / (window / 60), 2),
        "per_run_launch_top10": dict(per_run_launch.most_common(10)),
        "churn_suspects": {rk: n for rk, n in per_run_launch_1h.items() if n >= 5},
        "judge_outcomes": dict(judge_outcomes.most_common(10)),
        "requeue_reasons": dict(requeue_reasons.most_common(10)),
        "event_counts": dict(event_counts.most_common()),
    }


def clean_old_files(days: int = DEFAULT_RETENTION_DAYS):
    """清理days天前的流水文件"""
    cutoff = _now() - timedelta(days=days)
    removed = []
    if FLOW_DIR.exists():
        for fp in FLOW_DIR.glob("flow-*.jsonl"):
            try:
                day = datetime.strptime(fp.stem, "flow-%Y%m%d").replace(
                    tzinfo=timezone.utc)
                if day < cutoff:
                    fp.unlink()
                    removed.append(fp.name)
            except ValueError:
                continue
    return removed


def _main():
    ap = argparse.ArgumentParser(description="行为流水查看工具（016可观测性层）")
    ap.add_argument("--tail", type=int, help="最近N条")
    ap.add_argument("--run-key", help="按run_key过滤")
    ap.add_argument("--event", help="按事件类型过滤")
    ap.add_argument("--since", help="时间窗口，如 30m/1h/2d")
    ap.add_argument("--stats", action="store_true", help="聚合统计视图")
    ap.add_argument("--clean-days", type=int, help="清理N天前的流水文件并退出")
    args = ap.parse_args()

    if args.clean_days is not None:
        removed = clean_old_files(args.clean_days)
        print(f"清理了{len(removed)}个文件: {removed}")
        return

    since = _parse_since(args.since)

    if args.stats:
        s = flow_stats(since=since)
        print(f"=== 行为流水统计（窗口={args.since or '全部'}，共{s['total']}条）===")
        print(f"  事件速率: {s['events_per_minute']}/分钟，启动速率: {s['launch_per_minute']}/分钟")
        print(f"  事件分布: {json.dumps(s['event_counts'], ensure_ascii=False)}")
        if s["per_run_launch_top10"]:
            print(f"  每题启动次数Top10: {json.dumps(s['per_run_launch_top10'], ensure_ascii=False)}")
        if s["churn_suspects"]:
            print(f"  ⚠️ 失控循环嫌疑（1小时内启动≥5次）: {json.dumps(s['churn_suspects'], ensure_ascii=False)}")
        if s["judge_outcomes"]:
            print(f"  判定结果分布: {json.dumps(s['judge_outcomes'], ensure_ascii=False)}")
        if s["requeue_reasons"]:
            print(f"  重入队原因分布: {json.dumps(s['requeue_reasons'], ensure_ascii=False)}")
        return

    entries = read_flow(since=since, run_key=args.run_key, event=args.event,
                        tail=args.tail)
    if not entries:
        print("无流水记录（log/flow/ 下无匹配文件）")
        return
    for e in entries:
        rk = e.get("run_key") or "-"
        extras = {k: v for k, v in e.items()
                  if k not in ("ts", "ts_ms", "event", "run_key") and v is not None}
        extra_str = " ".join(f"{k}={v}" for k, v in extras.items())
        print(f"{e.get('ts', '?')[:19]} [{e.get('event', '?')}] {rk} {extra_str}")


if __name__ == "__main__":
    _main()

