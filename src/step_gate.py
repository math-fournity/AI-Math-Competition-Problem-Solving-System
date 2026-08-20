"""step_gate.py — 步进门闸（Step Gate）：基于数据库信号的单步跟踪系统

设计动机（016事故后，用户提出的方向）：Master Agent 必须能像工程师单步
跟踪一样"卡住"系统的每一个关键动作、读取该处的检查清单（checklist）、
核对系统的运行在这里是不是对的、再放行。016事故中launcher在18分钟里
做了上千次"启动devin cli"动作，Master Agent既看不见也拦不住。

铁律：**门闸只设在语义动作上**（启动进程/杀session/重入队/删产物文件/
写终态）——即"一个有独立正确性标准的业务动作"。底层I/O封装
（continuation_redis_queue的enqueue/dequeue等）**不设闸**：同一个函数
被多条路径调用，各自的正确性标准不同，写不出统一的checklist。只读判定
不打闸——它们已通过行为流水（src/observability.py）全量记录。若每一个
I/O都等放行，系统吞吐归零，7x24自动运行不存在。

认知闭包（checklist）的传递链——docstring是唯一事实源：
  代码+docstring（含"放行前…检查"段）← 随代码同commit，永不漂移
    │ import时 inspect 反射进注册表
    │ launcher启动/--register 时同步进DB（DB只是缓存/运输层）
    ▼
  代码走到被hold的闸 → 置Y（waiting_for字段，含run_key/pid上下文）
    │ SOP_01例程 / --pending 检查Y
    ▼
  脚本提取"放行前"段完整输出 → Master Agent按清单核对 → --step放行

docstring约定：每个闸的docstring里写"放行前Master Agent应检查："段落，
列出具体核对项（含用什么工具/查什么字段）。这个标题是机器可提取的接口
——--pending和SOP_01检查脚本按它截取闭包。没这段的闸是半成品。

X/Y注意力模型（Master Agent只在Y出现时操心）：
  X = mode（auto/hold）——Master Agent → 代码的控制变量（布防）
  Y = waiting_for（+上下文）——代码 → Master Agent的需求发起（触发）
  无Y = 代码不要求Master Agent操心这个位置（auto模式静默记gate_pass
  流水，事后可审计）。布防未触发（hold了但没走到）也是信息：说明该
  动作路径在此期间没有发生——用 --list 可查。

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
  python -m src.step_gate --step GATE-ID --reason '...' # 放行（附理由，落盘flow流水；代码执行后自清零）
  python -m src.step_gate --pending      # 查看正在等待放行的门闸（含完整checklist）
  python -m src.step_gate --hold-all / --auto-all
  python -m src.step_gate --hold-resource tmux  # 按resource分类批量hold

resource分类标签（不是闸的层级，是横向分组——批量hold用）：
  action 业务组合动作（launch_solve/start_handover）
  redis  队列调度动作（feed_enqueue/requeue_skip/requeue_truncated）
  db     终态写入（finalize_run_completed）
  file   文件删除/覆盖（remove_old_proof/overwrite_round1_seed）
  tmux   进程kill（kill_session）
  例：--hold-resource tmux+file ≈ "冻结所有不可逆动作"。

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
检测暂停。hold是调试/审计模式，不要长时间挂着不管（SOP_01每轮会提醒你
有没有Y在等）。
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


def gated(func=None, resource="action"):
    """把一个"语义动作"封装成可单步跟踪的门闸函数。

    两种用法：
        @gated                      # 默认resource="action"
        @gated(resource="redis")    # 带分类标签（批量hold用的横向分组）

    什么位置设闸：**语义动作**——一个有独立正确性标准的业务动作
    （launch_solve/kill_session/feed_enqueue），checklist能针对它写清楚
    "放行前Master Agent应检查什么"。底层I/O封装不设闸：同一函数被多条
    路径调用，正确性标准各不相同，写不出统一checklist（016设计结论）。

    resource只是分类标签（不是层级、不改变任何行为），供
    --hold-resource批量操作：redis=队列调度 / db=终态写入 / file=文件
    删除覆盖 / tmux=进程kill / action=业务组合动作。

    docstring约定（checklist是门闸的核心，缺了就是半成品）：
        放行前Master Agent应检查：
        1. ...（具体核对项：查什么字段/用什么工具/铁律引用）
    "放行前"这个标题是机器可提取的接口——--pending和SOP_01检查脚本
    按它截取闭包完整输出。

    装饰器行为：
      - 注册：gate_id由函数名生成（GATE-{NAME}），file/function/doc/resource
        自动从函数元数据收集——注册表永不与代码漂移；
      - auto模式（默认）：直接执行，写行为流水gate_pass事件；
      - hold模式：冻结在函数入口，轮询DB等proceed 0→1（Master Agent
        用 --step 放行），代码自己把proceed重置为0后执行；
      - DB不可达：降级为auto（门闸不能拖死系统）。

    Master Agent放行用的CLI不走门闸，hold任何闸都不会自锁。

    调用点可传 gate_ctx={"run_key":..., "pid":...} 提供流水上下文
    （装饰器拦截该参数，不透传给原函数）。不传时自动取kwargs里的run_key。
    """
    def deco(f):
        gate_id = _gate_id_for(f.__name__)

        @functools.wraps(f)
        def wrapper(*args, gate_ctx=None, **kwargs):
            ctx = dict(gate_ctx or {})
            if not ctx and kwargs.get("run_key"):
                ctx["run_key"] = kwargs["run_key"]
            _gate_pass_or_wait(gate_id, ctx)
            result = f(*args, **kwargs)
            log_flow("gate_done", run_key=ctx.get("run_key"),
                     gate_id=gate_id, resource=resource)
            return result

        wrapper._gate_id = gate_id
        _register_gate(gate_id, f, resource)
        return wrapper

    # 支持@gated和@gated(resource=...)两种写法
    if func is not None:
        return deco(func)
    return deco


def _gate_id_for(func_name):
    """函数名→gate_id：launch_solve → GATE-LAUNCH-SOLVE（grep直达）"""
    return "GATE-" + func_name.upper().replace("_", "-")


def extract_checklist(doc: str) -> str:
    """从门闸docstring里提取"放行前…检查"段——认知闭包的机器可提取接口。

    规则：找到含"放行前"的行，从该行截到docstring末尾（checklist约定
    是docstring的最后一段）。找不到该标题时返回整个docstring——闭包
    宁多勿缺。--pending和SOP_01检查脚本都调这个函数。
    """
    if not doc:
        return ""
    lines = doc.strip().splitlines()
    for i, line in enumerate(lines):
        if "放行前" in line:
            return "\n".join(lines[i:]).strip()
    return doc.strip()


def _register_gate(gate_id, func, resource="action"):
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
        "resource": resource,
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
                # 放行信号到了——读取放行理由（落盘论证），reset proceed，继续执行
                reason = doc.get("release_reason", "")
                try:
                    _get_db().collection(COLLECTION).update({
                        "_key": gate_id, "proceed": 0,
                        "waiting_for": None, "waiting_since": None,
                        "release_reason": "",  # 已记入flow流水，清空避免残留
                    })
                except Exception:
                    pass
                log_flow("gate_release", run_key=ctx.get("run_key"),
                         gate_id=gate_id, waited_seconds=round(time.time() - start, 1),
                         reason=reason)
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
    import src.continuation_launcher   # noqa: F401  触发装饰器收集
    import src.continuation_feeder     # noqa: F401  feeder的闸也进注册表
    db = _get_db()
    _ensure_collection(db)
    col = db.collection(COLLECTION)
    now = _utc_now()
    n = 0
    for gate_id, info in _registry.items():
        doc = col.get(gate_id)
        fields = {
            "file": info["file"], "function": info["function"],
            "doc": info["doc"], "resource": info.get("resource", "action"),
            "updated_at": now,
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
    ap.add_argument("--pending", action="store_true",
                    help="查看正在等待放行的门闸（完整输出checklist闭包）")
    ap.add_argument("--hold-all", action="store_true", help="所有门闸切hold")
    ap.add_argument("--auto-all", action="store_true", help="所有门闸切auto")
    ap.add_argument("--hold-resource", metavar="RES",
                    help="按resource分类批量hold（redis/db/file/tmux/action）")
    ap.add_argument("--auto-resource", metavar="RES",
                    help="按resource分类批量auto")
    ap.add_argument("--reason", default="",
                    help="放行理由（落盘到gate_release流水+DB，--step时必填）")
    args = ap.parse_args()

    if not any([args.register, args.list, args.hold, args.auto, args.step,
                args.pending, args.hold_all, args.auto_all,
                args.hold_resource, args.auto_resource]):
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
        if not args.reason:
            print("  ⚠️ 未附放行理由——落盘论证是门闸机制的核心要求")
            print("  ⚠️ 建议: --step GATE-ID --reason '看到1✓+2✓+3✓+4✓，理由：前置条件满足'")
            print("  ⚠️ 仍将放行（兼容测试），但生产中必须附理由")
        col.update({"_key": args.step, "proceed": 1,
                    "release_reason": args.reason or "(未附理由)"})
        wf = doc.get("waiting_for") or {}
        print(f"  ✅ 已放行 {args.step}（等待中的run: {wf.get('run_key', '无')}）")
        if args.reason:
            print(f"  📝 放行理由（已落盘flow流水）: {args.reason}")
    elif args.pending:
        _list_pending(col)
    elif args.hold_resource or args.auto_resource:
        res = args.hold_resource or args.auto_resource
        mode = "hold" if args.hold_resource else "auto"
        n = 0
        for doc in col.all():
            if doc.get("resource") == res:
                col.update({"_key": doc["_key"], "mode": mode,
                            "waiting_for": None, "waiting_since": None})
                n += 1
        if n:
            print(f"  ✅ {res}类{n}个门闸全部切到 {mode}")
        else:
            print(f"  ❌ 无resource={res}的门闸（可用：redis/db/file/tmux/action）")
        _invalidate_cache()
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
    print("门闸=语义动作（checklist可单步核对）；resource=分类标签（批量hold用）")
    print("注意力模型：auto且无waiting_for=不需操心；hold未触发=该路径未发生")
    print("定位方式：grep -rn <函数名> src/ —— 函数名即日志标志，直达代码块\n")
    docs = sorted(col.all(), key=lambda d: (d.get("resource", "action"), d["_key"]))
    current_res = None
    for doc in docs:
        res = doc.get("resource", "action")
        if res != current_res:
            current_res = res
            label = {"redis": "队列调度动作", "db": "终态写入",
                     "file": "文件删除/覆盖", "tmux": "进程kill",
                     "action": "业务组合动作"}.get(res, res)
            print(f"--- [{res}] {label} ---")
        mode = doc.get("mode", "auto")
        flag = "🔒 hold" if mode == "hold" else "   auto"
        wf = doc.get("waiting_for")
        waiting = f" ⏳ 等待放行: {wf.get('run_key')}" if wf else ""
        print(f"{flag}  {doc['_key']}")
        print(f"        {doc.get('file')} :: {doc.get('function')}{waiting}")
        doc_text = (doc.get("doc") or "").replace("\n", " ")[:90]
        print(f"        {doc_text}")
        print()


def _list_pending(col):
    print("=== 正在等待放行的门闸（Y通道——系统冻结在这些位置）===")
    found = False
    for doc in col.all():
        if doc.get("waiting_for"):
            found = True
            print(f"  ⏳ {doc['_key']} (自 {doc.get('waiting_since')})")
            print(f"     上下文: {doc['waiting_for']}")
            print(f"     放行: python -m src.step_gate --step {doc['_key']} --reason '看到1✓+2✓...理由...'")
            print(f"     维持hold: python -m src.step_gate --auto {doc['_key']} 不放行则一直冻结")
            print(f"     --- 认知闭包 / 放行前检查清单 ---")
            for line in extract_checklist(doc.get("doc") or "").splitlines():
                print(f"     {line}")
            print()
    if not found:
        print("  （无——没有门闸在等待，系统未被hold冻结）")


if __name__ == "__main__":
    # 注意：python -m src.step_gate 会把本文件作为__main__模块运行，
    # 与launcher import的src.step_gate是两个实例——装饰器注册表在后者。
    # 必须委托给真正的src.step_gate模块，否则注册表读到的是空的。
    from src.step_gate import _main
    _main()

