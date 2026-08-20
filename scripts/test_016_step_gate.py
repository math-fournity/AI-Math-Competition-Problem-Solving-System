"""test_016_step_gate.py — 步进门闸（单步跟踪系统）的端到端测试

验证用户提出的"基于数据库信号的单步跟踪"：
  1. @gated装饰器自动注册（函数名=gate_id，docstring=注册表文档）
  2. auto模式直接通过+写行为流水
  3. hold模式冻结→Master Agent置proceed=1→代码自清零继续→行为流水完整
  4. DB不可达时降级auto
  5. 注册表同步DB（file/function/doc三元组）

用法：
  source .env && python -m scripts.test_016_step_gate
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import src.step_gate as sg
from src.step_gate import gated
import src.observability as obs

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


# 测试用门闸函数——函数名即日志标志
@gated
def test_gate_action(run_key, value):
    """【门闸: GATE-TEST-GATE-ACTION】测试用动作——给value加一并返回。

    测试专用：验证装饰器的auto/hold两种模式行为。
    """
    return value + 1


class FakeGateCol:
    """模拟p27_step_gates集合（内存dict+proceed信号）"""

    def __init__(self):
        self.docs = {}

    def get(self, key):
        return self.docs.get(key)

    def insert(self, doc):
        self.docs[doc["_key"]] = doc

    def update(self, fields):
        key = fields["_key"]
        self.docs.setdefault(key, {})
        self.docs[key].update(fields)

    def all(self):
        return list(self.docs.values())


class FakeGateDB:
    def __init__(self):
        self.col = FakeGateCol()

    def has_collection(self, name):
        return True

    def create_collection(self, name):
        pass

    def collection(self, name):
        return self.col


def _patch_db(fake):
    sg._db = fake
    sg._mode_cache["ts"] = 0.0  # 失效缓存


def test_auto_mode():
    print("\n=== 1. auto模式：直接通过+行为流水 ===")
    fake = FakeGateDB()
    _patch_db(fake)
    with tempfile_dir():
        result = test_gate_action("run-x", 10)
        check("auto模式函数正常执行", result == 11)
        flows = obs.read_flow(event="gate_pass")
        check("gate_pass流水已写", any(
            e.get("gate_id") == "GATE-TEST-GATE-ACTION" for e in flows),
            f"flows={flows[-3:]}")


def test_hold_and_step():
    print("\n=== 2. hold模式：冻结→放行→自清零（单步跟踪核心） ===")
    fake = FakeGateDB()
    _patch_db(fake)
    # 切hold（模拟Master Agent --hold）
    fake.col.docs["GATE-TEST-GATE-ACTION"] = {
        "_key": "GATE-TEST-GATE-ACTION", "mode": "hold", "proceed": 0}
    sg._mode_cache["ts"] = 0.0

    with tempfile_dir():
        result_box = {}

        def run_action():
            result_box["value"] = test_gate_action(run_key="run-y", value=100)

        t = threading.Thread(target=run_action)
        t.start()
        time.sleep(1.5)  # 让它进入hold等待

        check("动作被冻结（未执行）", "value" not in result_box)
        doc = fake.col.get("GATE-TEST-GATE-ACTION")
        check("waiting_for写入DB（Master Agent可见）",
              (doc.get("waiting_for") or {}).get("run_key") == "run-y",
              f"doc={doc}")

        # 模拟Master Agent放行（--step）
        fake.col.update({"_key": "GATE-TEST-GATE-ACTION", "proceed": 1})
        t.join(timeout=10)
        check("放行后动作执行", result_box.get("value") == 101,
              f"result={result_box}")

        doc = fake.col.get("GATE-TEST-GATE-ACTION")
        check("proceed被代码自清零", doc.get("proceed") == 0, f"doc={doc}")
        check("waiting_for已清除", not doc.get("waiting_for"))

        flows = obs.read_flow()
        events = [e.get("event") for e in flows
                  if e.get("gate_id") == "GATE-TEST-GATE-ACTION"]
        check("行为流水含waiting→release→done全链",
              "gate_waiting" in events and "gate_release" in events
              and "gate_done" in events, f"events={events}")


def test_db_unreachable():
    print("\n=== 3. DB不可达降级auto（不拖死系统） ===")

    class BrokenDB:
        def __getattr__(self, name):
            raise ConnectionError("DB down")

    sg._db = BrokenDB()
    sg._mode_cache["ts"] = 0.0
    with tempfile_dir():
        result = test_gate_action("run-z", 5)  # 不应抛异常
        check("DB挂了动作仍执行（降级auto）", result == 6)
    sg._db = None
    sg._mode_cache["ts"] = 0.0


def test_registry():
    print("\n=== 4. 注册表：函数名=gate_id + docstring=文档 ===")
    import src.continuation_launcher  # noqa: F401 触发装饰器收集
    check("gate_id由函数名生成",
          "GATE-TEST-GATE-ACTION" in sg._registry)
    info = sg._registry.get("GATE-TEST-GATE-ACTION", {})
    check("file/function三元组收集",
          info.get("function") == "test_gate_action"
          and "step_gate" in info.get("file", "test"), f"info={info}")
    check("docstring进注册表",
          "测试用动作" in info.get("doc", ""))
    check("launcher的8个门闸也注册了",
          "GATE-LAUNCH-SOLVE" in sg._registry
          and "GATE-REQUEUE-TRUNCATED" in sg._registry,
          f"keys={list(sg._registry.keys())}")


class tempfile_dir:
    """行为流水临时目录上下文"""

    def __enter__(self):
        import tempfile
        self.td = tempfile.TemporaryDirectory()
        self._old = obs.FLOW_DIR
        obs.FLOW_DIR = Path(self.td.name)
        return self.td

    def __exit__(self, *a):
        obs.FLOW_DIR = self._old
        self.td.cleanup()


if __name__ == "__main__":
    test_auto_mode()
    test_hold_and_step()
    test_db_unreachable()
    test_registry()
    print(f"\n{'='*50}")
    print(f"结果: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
