"""session_registry.py — Session编号化管理

所有devin cli实例（solve/handover/monitor_exec）的tmux session注册到p27_sessions集合。
全局seq单调递增，永不复用。

详见 specs/p27_session_management_and_polish_spec.md §A。

命名规则：
  p27-s{seq:04d}-solve-{run_key_short}-r{round}
  p27-s{seq:04d}-handover-{run_key_short}-r{round}
  p27-s{seq:04d}-monitor-exec-{exec_seq}

状态流转：
  running → done      (DONE.md出现，export已落盘，可安全清理)
  running → stuck     (超时/rate_limit但DONE.md未出现——不kill，不占并发槽)
  done → cleaned      (Master Agent在用户授意下kill-session)
  stuck → cleaned     (Master Agent在用户授意下kill-session)
"""

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .continuation_config import SESSIONS_COLLECTION, SESSION_COUNTER_KEY


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _ts():
    return int(time.time())


def _tmux_has_session(name: str) -> bool:
    try:
        r = subprocess.run(
            ["tmux", "has-session", "-t", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _list_tmux_p27_sessions():
    """列出tmux中所有p27-s开头的session（编号化的session），排除服务session"""
    EXCLUDE = {"p27-launcher", "monitor-p27", "p27-watchdog"}
    try:
        result = subprocess.run(
            ["tmux", "list-sessions"], capture_output=True, text=True, timeout=5
        )
        sessions = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            name = line.split(":")[0]
            if name.startswith("p27-s") and name not in EXCLUDE:
                sessions.append(name)
        return sessions
    except Exception:
        return []


def allocate_seq(db) -> int:
    """原子递增全局seq，返回新分配的序号。

    用ArangoDB的update实现原子递增：
    1. 读取session_counter文档的当前counter值
    2. update文档，counter+1
    3. 返回新的counter值作为seq

    注意：counter文档用"counter"字段而非"seq"字段——因为p27_session_idx_seq
    是seq字段上的unique索引，counter文档如果也有seq字段会和新session记录的seq冲突。

    ArangoDB的update是原子的（单文档级别），并发调用不会冲突。
    如果极端并发下出现冲突，重试一次。
    """
    col = db.collection(SESSIONS_COLLECTION)
    for attempt in range(3):
        try:
            doc = col.get(SESSION_COUNTER_KEY)
            if doc is None:
                # counter文档不存在——重新初始化
                col.insert({"_key": SESSION_COUNTER_KEY, "counter": 0})
                doc = col.get(SESSION_COUNTER_KEY)
            # 兼容旧文档：如果doc有"seq"字段无"counter"字段，迁移
            if "counter" not in doc and "seq" in doc:
                old_seq = doc["seq"]
                col.update({"_key": SESSION_COUNTER_KEY, "counter": old_seq, "seq": None})
                doc = col.get(SESSION_COUNTER_KEY)
            new_seq = doc.get("counter", 0) + 1
            col.update({"_key": SESSION_COUNTER_KEY, "counter": new_seq})
            return new_seq
        except Exception:
            if attempt == 2:
                raise
            time.sleep(0.1)


def make_session_key(seq: int) -> str:
    """生成session的_key（注册表文档主键）"""
    return f"p27-s{seq:04d}"


def make_session_name(seq: int, session_type: str, suffix: str = "") -> str:
    """生成tmux session名

    Args:
        seq: 全局序号
        session_type: solve | handover | monitor_exec
        suffix: 类型特定的后缀（如run_key-r{round}或exec_seq）

    Returns:
        如 p27-s0042-solve-CC101bare-r2
    """
    prefix = make_session_key(seq)
    if suffix:
        return f"{prefix}-{session_type}-{suffix}"
    return f"{prefix}-{session_type}"


def create_session_record(db, seq: int, session_name: str, session_type: str,
                          batch_id: str, **extra) -> dict:
    """创建session注册表记录

    Args:
        db: ArangoDB连接
        seq: 全局序号
        session_name: tmux session名
        session_type: solve | handover | monitor_exec
        batch_id: 批次ID
        **extra: 额外字段（run_key/round/export_path/work_dir/triggered_by_alert等）

    Returns:
        创建的文档dict
    """
    now_iso = _utc_now()
    now_ts = _ts()
    doc = {
        "_key": make_session_key(seq),
        "seq": seq,
        "session_name": session_name,
        "type": session_type,
        "batch_id": batch_id,
        "started_at": now_iso,
        "started_at_ts": now_ts,
        "done_md": False,
        "done_md_at": None,
        "export_path": extra.get("export_path", ""),
        "work_dir": extra.get("work_dir", ""),
        "tmux_log_path": extra.get("tmux_log_path", ""),
        "report_path": extra.get("report_path", ""),
        "worklog_path": extra.get("worklog_path", ""),
        "prev_worklog_path": extra.get("prev_worklog_path", ""),
        "status": "running",
        "tmux_alive": True,
        "pid": extra.get("pid"),
        "exit_code": None,
        "notes": "",
    }
    # solve/handover特有字段
    if "run_key" in extra:
        doc["run_key"] = extra["run_key"]
    if "round" in extra:
        doc["round"] = extra["round"]
    # monitor_exec特有字段
    if "exec_seq" in extra:
        doc["exec_seq"] = extra["exec_seq"]
    if "triggered_by_alert" in extra:
        doc["triggered_by_alert"] = extra["triggered_by_alert"]

    db.collection(SESSIONS_COLLECTION).insert(doc)
    return doc


def update_session_status(db, session_key: str, status: str, **fields):
    """更新session状态

    Args:
        db: ArangoDB连接
        session_key: session的_key（如p27-s0042）
        status: running | done | stuck | cleaned
        **fields: 额外更新的字段（done_md/done_md_at/exit_code/tmux_alive/notes等）
    """
    update = {"_key": session_key, "status": status}
    update.update(fields)
    db.collection(SESSIONS_COLLECTION).update(update)


def get_session(db, session_key: str) -> Optional[dict]:
    """读取session记录"""
    return db.collection(SESSIONS_COLLECTION).get(session_key)


def get_session_by_name(db, session_name: str) -> Optional[dict]:
    """通过session_name查找session记录"""
    aql = (
        f"FOR s IN {SESSIONS_COLLECTION} "
        f"FILTER s.session_name == @name "
        f"RETURN s"
    )
    cursor = db.aql.execute(aql, bind_vars={"name": session_name}, ttl=60)
    docs = list(cursor)
    return docs[0] if docs else None


def list_sessions(db, batch_id: str = None, status: str = None,
                  session_type: str = None, limit: int = 100) -> list:
    """查询session列表

    Args:
        db: ArangoDB连接
        batch_id: 按批次过滤（None=所有批次）
        status: 按状态过滤（None=所有状态）
        session_type: 按类型过滤（None=所有类型）
        limit: 最多返回多少条

    Returns:
        session记录列表，按seq降序（最新的在前）
    """
    filters = []
    bind_vars = {}
    # 排除session_counter文档（它也在这个集合中，但不是session记录）
    filters.append(f"s._key != @counter_key")
    bind_vars["counter_key"] = SESSION_COUNTER_KEY
    if batch_id:
        filters.append("s.batch_id == @batch_id")
        bind_vars["batch_id"] = batch_id
    if status:
        filters.append("s.status == @status")
        bind_vars["status"] = status
    if session_type:
        filters.append("s.type == @type")
        bind_vars["type"] = session_type

    where_clause = f"FILTER {' AND '.join(filters)}" if filters else ""
    aql = (
        f"FOR s IN {SESSIONS_COLLECTION} "
        f"{where_clause} "
        f"SORT s.seq DESC "
        f"LIMIT {limit} "
        f"RETURN s"
    )
    cursor = db.aql.execute(aql, bind_vars=bind_vars, ttl=60)
    return list(cursor)


def find_orphaned_sessions(db) -> list:
    """注册表中有但tmux中已不存在的session

    这些session已自然退出（devin cli自己退出，tmux session消失）。
    done状态的应标记为cleaned。
    stuck状态的需人工检查（可能是devin cli崩溃）。
    """
    tmux_sessions = set(_list_tmux_p27_sessions())
    aql = (
        f"FOR s IN {SESSIONS_COLLECTION} "
        f"FILTER s.status IN ['running', 'stuck'] "
        f"RETURN s"
    )
    cursor = db.aql.execute(aql, ttl=60)
    orphaned = []
    for s in cursor:
        if s["session_name"] not in tmux_sessions:
            orphaned.append(s)
    return orphaned


def find_unregistered_sessions(db) -> list:
    """tmux中有但注册表中没有的session（孤儿session）

    可能是手动启动的devin cli，未经过注册表。
    """
    tmux_sessions = set(_list_tmux_p27_sessions())
    aql = f"FOR s IN {SESSIONS_COLLECTION} RETURN s.session_name"
    cursor = db.aql.execute(aql, ttl=60)
    registered = set(cursor)
    unregistered = tmux_sessions - registered
    return list(unregistered)


def update_tmux_alive_status(db):
    """更新所有running/stuck状态session的tmux_alive字段

    每轮检查时调用——对比注册表和tmux实际状态。
    发现orphaned的session（tmux已消失但注册表还是running/stuck）：
    - 如果done_md=True → 标记为done
    - 如果done_md=False → 保持stuck（可能是devin cli崩溃）
    """
    tmux_sessions = set(_list_tmux_p27_sessions())
    aql = (
        f"FOR s IN {SESSIONS_COLLECTION} "
        f"FILTER s.status IN ['running', 'stuck'] "
        f"RETURN s"
    )
    cursor = db.aql.execute(aql, ttl=60)
    for s in cursor:
        alive = s["session_name"] in tmux_sessions
        if not alive:
            # tmux session已消失
            if s.get("done_md"):
                # DONE.md已出现 → 标记为done
                update_session_status(
                    db, s["_key"], "done",
                    tmux_alive=False, done_md_at=_utc_now()
                )
            else:
                # 无DONE.md → 保持stuck（如果原来是running改为stuck）
                new_status = "stuck" if s["status"] == "running" else s["status"]
                update_session_status(
                    db, s["_key"], new_status, tmux_alive=False,
                    notes=(s.get("notes", "") + " | tmux session消失但无DONE.md").strip(" |")
                )
        else:
            # tmux session还在——更新tmux_alive
            if s.get("tmux_alive") != True:
                update_session_status(db, s["_key"], s["status"], tmux_alive=True)


def check_done_md(db, session_key: str) -> bool:
    """检查session的DONE.md是否出现

    DONE.md路径 = export_path的parent目录 / "DONE.md"
    """
    s = get_session(db, session_key)
    if not s:
        return False
    export_path = s.get("export_path", "")
    if not export_path:
        return False
    done_marker = Path(export_path).parent / "DONE.md"
    if done_marker.exists():
        # 读取exit code
        try:
            exit_code = done_marker.read_text().strip()
        except Exception:
            exit_code = None
        update_session_status(
            db, session_key, "done",
            done_md=True, done_md_at=_utc_now(),
            tmux_alive=_tmux_has_session(s["session_name"]),
            exit_code=exit_code,
        )
        return True
    return False


def mark_stuck(db, session_key: str, reason: str = ""):
    """标记session为stuck状态（不kill，释放并发槽）

    用于rate_limited/timeout/stall场景——devin cli可能还在写export，
    不应该kill，但也不应该继续占并发槽。
    """
    s = get_session(db, session_key)
    if not s:
        return
    notes = s.get("notes", "")
    if reason:
        notes = f"{notes} | {reason}".strip(" |") if notes else reason
    update_session_status(
        db, session_key, "stuck",
        notes=notes,
    )


def clean_session(db, session_key: str) -> bool:
    """安全清理一个session——只在done状态时kill tmux session

    Returns:
        True=已清理, False=未清理（状态不是done，需用户授意）
    """
    s = get_session(db, session_key)
    if not s:
        return False
    if s["status"] not in ("done", "stuck"):
        # running状态不能清理
        return False
    # kill tmux session
    if _tmux_has_session(s["session_name"]):
        subprocess.run(
            ["tmux", "kill-session", "-t", s["session_name"]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=5,
        )
    # 标记为cleaned
    update_session_status(db, session_key, "cleaned", tmux_alive=False)
    return True


def clean_done_sessions(db) -> dict:
    """批量清理所有done状态的session（安全操作，export已落盘）

    Returns:
        {"cleaned": N, "failed": M, "details": [...]}
    """
    done_sessions = list_sessions(db, status="done", limit=1000)
    cleaned = 0
    failed = 0
    details = []
    for s in done_sessions:
        if clean_session(db, s["_key"]):
            cleaned += 1
            details.append(f"cleaned {s['_key']} ({s['session_name']})")
        else:
            failed += 1
            details.append(f"failed {s['_key']} (status={s['status']})")
    return {"cleaned": cleaned, "failed": failed, "details": details}


def consistency_check(db) -> dict:
    """一致性检查——注册表 vs tmux实际session

    Returns:
        {
            "registered_count": N,
            "tmux_count": M,
            "orphaned_in_registry": [...],  # 注册表有但tmux无
            "unregistered_in_tmux": [...],  # tmux有但注册表无
        }
    """
    tmux_sessions = set(_list_tmux_p27_sessions())
    orphaned = find_orphaned_sessions(db)
    unregistered = find_unregistered_sessions(db)

    aql = f"FOR s IN {SESSIONS_COLLECTION} FILTER s._key != @counter_key RETURN s"
    cursor = db.aql.execute(aql, bind_vars={"counter_key": SESSION_COUNTER_KEY}, ttl=60)
    registered_count = len(list(cursor))

    return {
        "registered_count": registered_count,
        "tmux_count": len(tmux_sessions),
        "orphaned_in_registry": [
            {"key": s["_key"], "session_name": s["session_name"],
             "status": s["status"], "done_md": s.get("done_md", False)}
            for s in orphaned
        ],
        "unregistered_in_tmux": list(unregistered),
    }
