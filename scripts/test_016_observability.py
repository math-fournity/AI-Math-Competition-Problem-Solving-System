"""test_016_observability.py — 行为流水可观测性层的单元测试

验证016事故后的新检查维度：
  1. log_flow写JSONL + read_flow过滤（run_key/since/tail）
  2. flow_stats聚合——失控循环嫌疑识别
  3. check_launch_churn——A14启动抖动告警（模拟016事故场景）
  4. _batch_concurrency——从DB读并发设定

用法：
  source .env && python -m scripts.test_016_observability
"""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.observability as obs
from src.observability import log_flow, read_flow, flow_stats

PASS = 0
FAIL = 0
REAL_FLOW_DIR = Path(__file__).parent.parent / "log" / "flow"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def test_write_read():
    print("\n=== 1. log_flow写入 + read_flow过滤 ===")
    with tempfile.TemporaryDirectory() as td:
        obs.FLOW_DIR = Path(td)
        try:
            log_flow("batch_start", batch_id="test-batch", concurrency=1)
            log_flow("dequeue", run_key="run-a", priority=0)
            log_flow("launch_solve", run_key="run-a", pid="a", round=2,
                     session_name="s0001")
            log_flow("judge", run_key="run-a", pid="a", round=2,
                     outcome="truncated", reason="rc=3000c")
            log_flow("requeue", run_key="run-a", pid="a", priority=2,
                     reason="truncated_r2")
            log_flow("launch_solve", run_key="run-b", pid="b", round=1,
                     session_name="s0002")

            entries = read_flow()
            check("写入6条全部可读", len(entries) == 6, f"got {len(entries)}")
            check("JSONL字段完整(ts/event)",
                  all("ts" in e and "event" in e for e in entries))

            only_a = read_flow(run_key="run-a")
            check("run_key过滤", len(only_a) == 4 and all(
                e["run_key"] == "run-a" for e in only_a))
            check("event过滤", len(read_flow(event="launch_solve")) == 2)

            tailed = read_flow(tail=2)
            check("tail=2取最后2条",
                  tailed[-1]["run_key"] == "run-b" and len(tailed) == 2)

            old = datetime.now(timezone.utc) - timedelta(hours=2)
            check("since过滤（2h前→全包含）", len(read_flow(since=old)) == 6)
            future = datetime.now(timezone.utc) + timedelta(hours=1)
            check("since过滤（未来→全排除）", len(read_flow(since=future)) == 0)
        finally:
            obs.FLOW_DIR = REAL_FLOW_DIR


def test_stats_churn():
    print("\n=== 2. flow_stats聚合——失控循环识别 ===")
    with tempfile.TemporaryDirectory() as td:
        obs.FLOW_DIR = Path(td)
        try:
            for i in range(8):
                log_flow("launch_handover", run_key="run-a", pid="a", round=1,
                         session_name=f"s1{i:04d}")
            for i in range(2):
                log_flow("launch_solve", run_key="run-b", pid="b", round=1,
                         session_name=f"s2{i:04d}")
            log_flow("judge", run_key="run-a", outcome="truncated")
            log_flow("requeue", run_key="run-a", priority=2,
                     reason="truncated_r1")

            s = flow_stats()
            check("总事件数=12", s["total"] == 12, f"got {s['total']}")
            check("churn嫌疑识别到run-a(8次)",
                  s["churn_suspects"].get("run-a") == 8,
                  f"got {s['churn_suspects']}")
            check("run-b不在嫌疑(2次)", "run-b" not in s["churn_suspects"])
            check("每题启动Top10正确",
                  s["per_run_launch_top10"].get("run-a") == 8)
            check("判定分布统计", s["judge_outcomes"].get("truncated") == 1)
            check("重入队原因统计",
                  s["requeue_reasons"].get("truncated_r1") == 1)
        finally:
            obs.FLOW_DIR = REAL_FLOW_DIR


def test_a14_churn_alert():
    print("\n=== 3. A14 check_launch_churn告警（模拟事故） ===")
    with tempfile.TemporaryDirectory() as td:
        obs.FLOW_DIR = Path(td)
        try:
            from src.monitor_continuation import check_launch_churn
            alerts = check_launch_churn(None, "test-batch")
            check("无流水时不告警", alerts == [], f"got {alerts}")

            for i in range(2):
                log_flow("launch_solve", run_key="run-ok", pid="ok",
                         round=1, session_name=f"sok{i}")
            alerts = check_launch_churn(None, "test-batch")
            check("正常启动不告警", alerts == [], f"got {alerts}")

            for i in range(6):
                log_flow("launch_handover", run_key="run-bad", pid="bad",
                         round=1, session_name=f"sbad{i}")
            alerts = check_launch_churn(None, "test-batch")
            check("失控循环触发critical告警", len(alerts) == 1
                  and alerts[0][0] == "launch_churn"
                  and alerts[0][1] == "critical", f"got {alerts}")
            check("告警包含取证命令",
                  "observability" in alerts[0][2].get("command", ""))
            check("告警包含churn明细",
                  alerts[0][2].get("churn_detail", {}).get("run-bad") == 6)
        finally:
            obs.FLOW_DIR = REAL_FLOW_DIR


class FakeCol:
    def __init__(self, doc):
        self.doc = doc

    def get(self, key):
        return self.doc


class FakeBatchDB:
    def __init__(self, doc):
        self.doc = doc

    def collection(self, name):
        return FakeCol(self.doc)


def test_batch_concurrency():
    print("\n=== 4. _batch_concurrency从DB读设定 ===")
    from src.monitor_continuation import _batch_concurrency

    check("DB有concurrency=1时返回1",
          _batch_concurrency(FakeBatchDB({"concurrency": 1}), "b", 5) == 1)
    check("DB无文档时fallback CLI参数",
          _batch_concurrency(FakeBatchDB(None), "b", 5) == 5)
    check("DB无concurrency字段时fallback",
          _batch_concurrency(FakeBatchDB({"status": "launching"}), "b", 5) == 5)


if __name__ == "__main__":
    test_write_read()
    test_stats_churn()
    test_a14_churn_alert()
    test_batch_concurrency()
    print(f"\n{'='*50}")
    print(f"结果: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)

