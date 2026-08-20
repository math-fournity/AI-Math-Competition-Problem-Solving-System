"""step_gate.py — 步进门闸（Step Gate）：基于数据库信号的单步跟踪系统

设计动机（016事故后，用户提出的方向）：Master Agent 必须能"卡住"系统的
每一个关键动作、检查之前的工作、再放行。016事故中launcher在18分钟里做了
上千次"启动devin cli"动作，Master Agent既看不见也拦不住。

铁律：**门闸只设在改变系统状态的动作上**（启动进程/杀session/重入队/
删产物文件/写终态）。只读判定（is_truncated等）不打闸——它们已经通过
行为流水（src/observability.py）全量记录。若每一步都等放行，系统吞吐
归零，7x24自动运行不存在。

两种模式（存在ArangoDB的 p27_step_gates 集合，每门闸一个文档）：
  auto  （默认）闸门直接通过，写行为流水 gate_pass 事件——系统行为与
        无门闸时完全一致，Master Agent事后可审计每一次通过。
  hold  动作冻结：代码轮询DB等 proceed 字段 0→1（由Master Agent设置），
        然后**代码自己把proceed重置为0**再继续执行。这就是单步跟踪。

Master Agent操作（CLI）：
  python -m src.step_gate --register     # 注册/刷新门闸目录（XPATH注册表）
  python -m src.step_gate --list         # 查看所有门闸：位置/文档/模式/触发次数
  python -m src.step_gate --hold GATE-ID # 切到hold（下一个该动作会被冻结）
  python -m src.step_gate --auto GATE-ID # 切回auto
  python -m src.step_gate --step GATE-ID # 放行（proceed置1，代码执行后自清零）
  python -m src.step_gate --pending      # 查看正在等待放行的门闸
  python -m src.step_gate --hold-all / --auto-all

定位代码（XPATH方式——不用行号，行号随代码变动失效）：
  每个门闸的gate_id（如GATE-P27-LAUNCH-SOLVE）是全局唯一字符串，
  `grep -rn "GATE-P27-LAUNCH-SOLVE" src/` 直接定位到代码块；
  DB文档和代码注释里都存着file/function/gate_id三元组；
  代码块周围有自包含注释（是什么/为什么追踪/放行前检查什么）。

安全设计：
  - DB不可达时默认auto放行（门闸是审计/调试工具，不能因DB故障拖死系统）；
  - 模式读取有10秒内存缓存（Master Agent设hold后最多10秒生效）；
  - hold等待中心跳写入行为流水（每60秒一条gate_waiting），Master Agent
    能看到"系统正卡在哪个闸"。

⚠️ 已知代价：hold阻塞的是launcher主循环本身，期间运行中session的stall
检测暂停。hold是调试/审计模式，不要长时间挂着不管。
"""
import argparse
import functools
import inspect
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.observability import log_flow  # noqa: E402

COLLECTION = "p27_step_gates"
MODE_CACHE_TTL = 10.0        # 模式缓存秒数——hold设置后最多10秒生效
HOLD_POLL_SECONDS = 2.0      # hold模式下轮询DB的间隔
HOLD_HEARTBEAT_SECONDS = 60.0  # hold等待时的心跳间隔（写行为流水）

_db = None
_mode_cache = {"ts": 0.0, "modes": {}}

# ============================================================
# 装饰器与注册表——门闸目录从被装饰函数自动收集，永不与代码漂移
# ============================================================

# 运行时注册表：gate_id -> {file, function, doc, first_seen}
_registry = {}


def gated(func):
    """把一个"改变系统状态的动作"封装成可单步跟踪的门闸函数。

    用法：
        @gated
        def launch_solve(run_key, work_dir, ...):
            \"\"\"这里写自包含注释文档：这个动作是什么/为什么追踪/
            放行前Master Agent应检查什么。docstring会进DB注册表。\"\"\"
            ...实际动作...

    装饰器行为：
      - 注册：gate_id由函数名生成（GATE-{NAME}），file/function/doc自动
        从函数元数据收集（inspect）——注册表永不与代码漂移；
      - auto模式（默认）：直接执行，前后写行为流水gate_pass事件；
      - hold模式：冻结在函数入口，轮询DB等proceed 0→1（Master Agent
        用 --step 放行），代码自己把proceed重置为0后执行；
      - DB不可达：降级为auto（门闸不能拖死系统）。

    调用点可传 gate_ctx={"run_key":..., "pid":...} 提供流水上下文
    （装饰器拦截该参数，不透传给原函数）。不传时自动取kwargs里的run_key。
    """
    gate_id = _gate_id_for(func.__name__)

    @functools.wraps(func)
    def wrapper(*args, gate_ctx=None, **kwargs):
        ctx = dict(gate_ctx or {})
        if not ctx and kwargs.get("run_key"):
            ctx["run_key"] = kwargs["run_key"]
        _gate_pass_or_wait(gate_id, ctx)
        result = func(*args, **kwargs)
        log_flow("gate_done", run_key=ctx.get("run_key"), gate_id=gate_id)
        return result

    wrapper._gate_id = gate_id
    _register_gate(gate_id, func)
    return wrapper


def _gate_id_for(func_name):
    """函数名→gate_id：launch_solve → GATE-LAUNCH-SOLVE（grep直达）"""
    return "GATE-" + func_name.upper().replace("_", "-")


def _register_gate(gate_id, func):
    try:
        src_file = inspect.getsourcefile(func)
    except (TypeError, OSError):
        src_file = "?"
    _registry[gate_id] = {
        "gate_id": gate_id,
        "file": str(Path(src_file).relative_to(PROJECT_ROOT))
        if src_file and src_file != "?" else "?",
        "function": func.__name__,
        "doc": (func.__doc__ or "").strip(),
        "first_seen": _utc_now(),
    }


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _get_db():
    global _db
    if _db is None:
        from src.continuation_db_schema import connect_db
        _db = connect_db()
    return _db


# ============================================================
# 运行时：auto通过 / hold等待放行
# ============================================================

def _load_modes():
    """读所有门闸的模式（带缓存）。DB不可达→全部auto（降级不拖死系统）。"""
    now = time.time()
    if now - _mode_cache["ts"] < MODE_CACHE_TTL:
        return _mode_cache["modes"]
    modes = {}
    try:
        db = _get_db()
        _ensure_collection(db)
        for doc in db.collection(COLLECTION).all():
            modes[doc["_key"]] = doc.get("mode", "auto")
    except Exception:
        modes = {}  # DB不可达→默认auto
    _mode_cache["ts"] = now
    _mode_cache["modes"] = modes
    return modes


def _gate_pass_or_wait(gate_id, ctx):
    """门闸入口：auto则记流水直接通过；hold则冻结等Master Agent放行。"""
    mode = _load_modes().get(gate_id, "auto")
    if mode != "hold":
        log_flow("gate_pass", run_key=ctx.get("run_key"), gate_id=gate_id,
                 mode="auto", **{k: v for k, v in ctx.items() if k != "run_key"})
        return

    # hold模式——冻结等待
    log_flow("gate_waiting", run_key=ctx.get("run_key"), gate_id=gate_id,
             mode="hold", **{k: v for k, v in ctx.items() if k != "run_key"})
    start = time.time()
    last_heartbeat = 0.0
    _mark_waiting(gate_id, ctx, _utc_now())
    try:
        while True:
            doc = None
            try:
                doc = _get_db().collection(COLLECTION).get(gate_id)
            except Exception:
                pass  # DB瞬断——继续轮询（不能因为DB抖动漏执行动作）
            if doc and doc.get("proceed") == 1:
                # 放行信号到了——代码自己reset为0，然后继续执行
                try:
                    _get_db().collection(COLLECTION).update({
                        "_key": gate_id, "proceed": 0,
                        "waiting_for": None, "waiting_since": None,
                    })
                except Exception:
                    pass
                log_flow("gate_release", run_key=ctx.get("run_key"),
                         gate_id=gate_id, waited_seconds=round(time.time() - start, 1))
                return
            # 心跳——Master Agent在行为流水里能看到"还卡着"
            if time.time() - last_heartbeat >= HOLD_HEARTBEAT_SECONDS:
                log_flow("gate_waiting", run_key=ctx.get("run_key"),
                         gate_id=gate_id, mode="hold",
                         waited_seconds=round(time.time() - start, 1))
                last_heartbeat = time.time()
            time.sleep(HOLD_POLL_SECONDS)
    finally:
        _mark_not_waiting(gate_id)


def _mark_waiting(gate_id, ctx, since):
    """把等待上下文写进DB文档——Master Agent用 --pending 直接看到谁在等"""
    try:
        _get_db().collection(COLLECTION).update({
            "_key": gate_id, "waiting_for": ctx, "waiting_since": since,
        })
    except Exception:
        pass


def _mark_not_waiting(gate_id):
    try:
        _get_db().collection(COLLECTION).update({
            "_key": gate_id, "waiting_for": None, "waiting_since": None,
        })
    except Exception:
        pass


def _ensure_collection(db):
    if not db.has_collection(COLLECTION):
        db.create_collection(COLLECTION)


def sync_registry_to_db():
    """把装饰器收集的注册表upsert进DB（--register / launcher启动时调用）。"""
    import src.continuation_launcher  # noqa: F401  触发装饰器收集
    db = _get_db()
    _ensure_collection(db)
    col = db.collection(COLLECTION)
    now = _utc_now()
    n = 0
    for gate_id, info in _registry.items():
        doc = col.get(gate_id)
        fields = {
            "file": info["file"], "function": info["function"],
            "doc": info["doc"], "updated_at": now,
            "mode": doc.get("mode", "auto") if doc else "auto",
            "proceed": doc.get("proceed", 0) if doc else 0,
            "pass_count": doc.get("pass_count", 0) if doc else 0,
        }
        if doc:
            fields["_key"] = gate_id
            fields["_rev"] = doc["_rev"]
            col.update(fields)
        else:
            fields["_key"] = gate_id
            col.insert(fields)
        n += 1
    return n


# ============================================================
# CLI——Master Agent的操作面
# ============================================================

def _invalidate_cache():
    global _mode_cache
    _mode_cache["ts"] = 0.0


def _main():
    ap = argparse.ArgumentParser(description="步骤门闸管理（单步跟踪系统）")
    ap.add_argument("--register", action="store_true",
                    help="注册/刷新门闸目录到DB（import launcher自动收集）")
    ap.add_argument("--list", action="store_true", help="列出所有门闸")
    ap.add_argument("--hold", metavar="GATE-ID", help="切到hold模式")
    ap.add_argument("--auto", metavar="GATE-ID", help="切回auto模式")
    ap.add_argument("--step", metavar="GATE-ID",
                    help="放行（proceed置1，等待中的代码自清零后继续）")
    ap.add_argument("--pending", action="store_true", help="查看正在等待放行的门闸")
    ap.add_argument("--hold-all", action="store_true", help="所有门闸切hold")
    ap.add_argument("--auto-all", action="store_true", help="所有门闸切auto")
    args = ap.parse_args()

    if not any([args.register, args.list, args.hold, args.auto, args.step,
                args.pending, args.hold_all, args.auto_all]):
        ap.print_help()
        return

    db = _get_db()
    _ensure_collection(db)
    col = db.collection(COLLECTION)

    def set_mode(gate_id, mode):
        doc = col.get(gate_id)
        if not doc:
            print(f"  ❌ 门闸不存在: {gate_id}（先 --register）")
            return
        col.update({"_key": gate_id, "mode": mode,
                    "waiting_for": None, "waiting_since": None})
        print(f"  ✅ {gate_id}: {doc.get('mode')} → {mode}")
        _invalidate_cache()

    if args.register:
        n = sync_registry_to_db()
        print(f"  ✅ 已注册{n}个门闸到 {COLLECTION}")
        _list_gates(col)
    elif args.list:
        _list_gates(col)
    elif args.hold:
        set_mode(args.hold, "hold")
    elif args.auto:
        set_mode(args.auto, "auto")
    elif args.step:
        doc = col.get(args.step)
        if not doc:
            print(f"  ❌ 门闸不存在: {args.step}")
            return
        col.update({"_key": args.step, "proceed": 1})
        wf = doc.get("waiting_for") or {}
        print(f"  ✅ 已放行 {args.step}（等待中的run: {wf.get('run_key', '无')}）")
    elif args.pending:
        _list_pending(col)
    else:  # hold-all / auto-all
        mode = "hold" if args.hold_all else "auto"
        n = 0
        for doc in col.all():
            col.update({"_key": doc["_key"], "mode": mode})
            n += 1
        print(f"  ✅ {n}个门闸全部切到 {mode}")
        _invalidate_cache()


def _list_gates(col):
    print(f"=== 步进门闸目录（{COLLECTION}）===")
    print("定位方式：grep -rn <函数名> src/ —— 函数名即日志标志，直达代码块\n")
    for doc in sorted(col.all(), key=lambda d: d["_key"]):
        mode = doc.get("mode", "auto")
        flag = "🔒 hold" if mode == "hold" else "   auto"
        wf = doc.get("waiting_for")
        waiting = f" ⏳ 等待放行: {wf.get('run_key')}" if wf else ""
        print(f"{flag}  {doc['_key']}")
        print(f"        {doc.get('file')} :: {doc.get('function')}{waiting}")
        doc_text = (doc.get("doc") or "").replace("\n", " ")[:100]
        print(f"        {doc_text}")
        print()


def _list_pending(col):
    print("=== 正在等待放行的门闸 ===")
    found = False
    for doc in col.all():
        if doc.get("waiting_for"):
            found = True
            print(f"  ⏳ {doc['_key']} (自 {doc.get('waiting_since')})")
            print(f"     上下文: {doc['waiting_for']}")
            print(f"     放行: python -m src.step_gate --step {doc['_key']}")
            print(f"     说明: {(doc.get('doc') or '').splitlines()[0][:100]}")
            print()
    if not found:
        print("  （无——没有门闸在等待）")


if __name__ == "__main__":
    # 注意：python -m src.step_gate 会把本文件作为__main__模块运行，
    # 与launcher import的src.step_gate是两个实例——装饰器注册表在后者。
    # 必须委托给真正的src.step_gate模块，否则注册表读到的是空的。
    from src.step_gate import _main
    _main()

