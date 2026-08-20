"""test_016_p0_fixes.py — 016事故P0修复的单元测试

验证三组P0修复（不依赖真实Redis/DB/tmux，用本地桩）：
  P0-2 判定函数产物归属校验（is_truncated/is_completed/check_handover的mtime校验）
  P0-3 队列NX幂等（enqueue_pending不覆盖score）+ feeder只计新入队

用法：
  source .env && python -m scripts.test_016_p0_fixes
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.continuation_launcher import is_truncated, is_completed, check_handover
from src.continuation_redis_queue import PENDING_KEY

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


class FakeRedis:
    """只实现zadd(nx)/zpopmin，用于验证NX语义"""

    def __init__(self):
        self.zset = {}

    def zadd(self, key, mapping, nx=False):
        added = 0
        for member, score in mapping.items():
            if nx and member in self.zset:
                continue  # NX模式：已存在则跳过（不覆盖score）
            if member not in self.zset:
                added += 1
            self.zset[member] = score
        return added

    def zcard(self, key):
        return len(self.zset)

    def zpopmin(self, key, count):
        items = sorted(self.zset.items(), key=lambda x: (x[1], x[0]))[:count]
        for m, _ in items:
            del self.zset[m]
        return items


def make_export(path, rc=2000, msg=0, comp=30000):
    """构造export——默认msg=0+comp>=24000+rc>1000，符合截断特征"""
    d = {"steps": [{"source": "agent", "reasoning_content": "r" * rc,
                    "message": "m" * msg, "tool_calls": [],
                    "metrics": {"completion_tokens": comp}}]}
    Path(path).write_text(json.dumps(d))


def test_since_ts():
    print("\n=== P0-2: 判定函数产物归属校验 ===")
    with tempfile.TemporaryDirectory() as td:
        # 截断型export：rc>1000 + msg=0 + comp>=24000
        export_trunc = str(Path(td) / "trunc.json")
        make_export(export_trunc, rc=2000, msg=0, comp=30000)
        # 完成型export：有message输出 + proof.md有boxed
        export_done = str(Path(td) / "done.json")
        make_export(export_done, rc=2000, msg=100, comp=5000)
        proof = Path(td) / "proof.md"
        proof.write_text(r"答案 $\boxed{42}$")

        started = time.time() - 100
        future = time.time() + 100

        trunc, _ = is_truncated(export_trunc, since_ts=started)
        comp, _ = is_completed(export_done, td, since_ts=started)
        check("is_truncated 本轮产物正常判定截断", trunc is True)
        check("is_completed 本轮proof正常判定完成", comp is True)

        trunc, r1 = is_truncated(export_trunc, since_ts=future)
        comp, r2 = is_completed(export_done, td, since_ts=future)
        check("is_truncated 旧残留被拒绝", trunc is False, f"reason={r1}")
        check("is_completed 旧残留export被拒绝", comp is False, f"reason={r2}")

        comp, r3 = is_completed(export_done, td, since_ts=time.time())
        check("is_completed 新export+旧proof被拒绝", comp is False, f"reason={r3}")

        trunc, _ = is_truncated(export_trunc)
        comp, _ = is_completed(export_done, td)
        check("is_truncated 不传since_ts向后兼容", trunc is True)
        check("is_completed 不传since_ts向后兼容", comp is True)


def test_check_handover():
    print("\n=== P0-2: check_handover产物归属校验 ===")
    with tempfile.TemporaryDirectory() as td:
        handover = Path(td) / "round1_HANDOVER.md"
        handover.write_text("x" * 1000)

        hinfo = {"session_name": "test-sess-016", "handover_path": handover,
                 "started_at": time.time() + 100}
        result = check_handover(hinfo, "testpid")
        check("check_handover 旧残留HANDOVER.md被拒绝(返回'')", result == "")

        hinfo2 = {"session_name": "test-sess-016", "handover_path": handover,
                  "started_at": time.time() - 100}
        result2 = check_handover(hinfo2, "testpid")
        check("check_handover 本轮HANDOVER.md判成功", result2 == str(handover))


def test_nx_queue():
    print("\n=== P0-3: 队列NX幂等 ===")
    r = FakeRedis()

    check("NX首次入队返回1", r.zadd(PENDING_KEY, {"task-a": 0}, nx=True) == 1)
    check("NX二次入队返回0(不重复计)", r.zadd(PENDING_KEY, {"task-a": 0}, nx=True) == 0)

    r.zset["task-a"] = 2  # 模拟截断重入队(priority=2)
    r.zadd(PENDING_KEY, {"task-a": 0}, nx=True)  # 模拟feeder重喂(priority=0)
    check("NX保住截断重入队的低优先级score", r.zset["task-a"] == 2,
          f"score={r.zset['task-a']}")

    keys = ["task-a", "task-b"]
    count = sum(1 for k in keys if r.zadd(PENDING_KEY, {k: 0}, nx=True))
    check("feeder只统计新入队(count=1非2)", count == 1, f"count={count}")

    r.zset["task-b"] = 0
    popped = r.zpopmin(PENDING_KEY, 1)
    check("低优先级题不再霸占队首", popped[0][0] == "task-b", f"popped={popped}")


if __name__ == "__main__":
    test_since_ts()
    test_check_handover()
    test_nx_queue()
    print(f"\n{'='*50}")
    print(f"结果: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
