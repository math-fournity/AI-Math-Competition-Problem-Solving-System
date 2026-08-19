"""db_schema.py — ArangoDB集合定义

分析系统的DB集合（模仿solver_harness的4集合设计）：
  analysis_batches: 批次记录（batch_id, concurrency, status, status_counts等）
  analysis_runs: 每道题的分析run记录（30+字段，含paths/observability/verdict等）
  analysis_events: 事件流（launch, complete, timeout, error等，有3个索引）
  analysis_results: 最终分析结果（从devin cli输出中提取的XML解析结果）
  analysis_counters: 全局计数器（run_id原子递增，保证exp_id唯一）

与solver_harness的对应关系：
  analysis_batches  ↔ devin_batch_runs
  analysis_runs     ↔ devin_problem_runs
  analysis_events   ↔ devin_run_events
  analysis_counters ↔ devin_counters
  analysis_results  ↔ （新增，解题系统没有这个集合）
"""

from .config import (
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    ANALYSIS_RUNS_COLLECTION, ANALYSIS_EVENTS_COLLECTION, ANALYSIS_RESULTS_COLLECTION,
)

# 新增集合名
ANALYSIS_BATCHES_COLLECTION = "analysis_batches"
ANALYSIS_COUNTERS_COLLECTION = "analysis_counters"


def connect_db():
    """连接ArangoDB，返回db对象"""
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)


def ensure_schema(db):
    """确保分析系统的集合存在"""
    all_collections = [
        ANALYSIS_BATCHES_COLLECTION,
        ANALYSIS_RUNS_COLLECTION,
        ANALYSIS_EVENTS_COLLECTION,
        ANALYSIS_RESULTS_COLLECTION,
        ANALYSIS_COUNTERS_COLLECTION,
    ]
    for col_name in all_collections:
        if not db.has_collection(col_name):
            db.create_collection(col_name)

    # 初始化run_id counter
    if not db.collection(ANALYSIS_COUNTERS_COLLECTION).has("run_id"):
        db.collection(ANALYSIS_COUNTERS_COLLECTION).insert({"_key": "run_id", "value": 0})

    # === 索引 ===
    # analysis_batches索引
    batches = db.collection(ANALYSIS_BATCHES_COLLECTION)
    for name, fields, unique in [
        ("idx_status", ["status"], False),
        ("idx_created_at", ["created_at"], False),
    ]:
        try:
            batches.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass

    # analysis_runs索引（模仿devin_problem_runs）
    runs = db.collection(ANALYSIS_RUNS_COLLECTION)
    for name, fields, unique in [
        ("idx_problem_id", ["problem_id"], False),
        ("idx_batch_id", ["batch_id"], False),
        ("idx_status", ["status"], False),
        ("idx_analysis_exp_id", ["analysis_exp_id"], True),
        ("idx_problem_batch", ["problem_id", "batch_id"], True),
    ]:
        try:
            runs.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass

    # analysis_events索引（模仿devin_run_events）
    events = db.collection(ANALYSIS_EVENTS_COLLECTION)
    for name, fields, unique in [
        ("idx_batch_id", ["batch_id"], False),
        ("idx_run_key", ["run_key"], False),
        ("idx_event_type", ["event_type"], False),
        ("idx_timestamp", ["timestamp"], False),
    ]:
        try:
            events.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass

    # analysis_results索引
    results = db.collection(ANALYSIS_RESULTS_COLLECTION)
    for name, fields, unique in [
        ("idx_problem_id", ["problem_id"], False),
        ("idx_batch_id", ["batch_id"], False),
        ("idx_verdict", ["dimension1_verdict"], False),
        ("idx_turning_point", ["dimension2_turning_point_type"], False),
        ("idx_confidence", ["confidence"], False),
    ]:
        try:
            results.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass


def next_run_id(db):
    """原子递增全局运行ID，确保每次analysis_exp_id唯一。
    用ArangoDB事务保证并发安全——多个launcher同时调也不会冲突。
    模仿solver_harness的next_run_id。"""
    cursor = db.aql.execute(
        f'FOR c IN {ANALYSIS_COUNTERS_COLLECTION} FILTER c._key == "run_id" '
        f'UPDATE c WITH {{value: c.value + 1}} IN {ANALYSIS_COUNTERS_COLLECTION} '
        f'RETURN NEW.value'
    )
    return next(cursor)


def make_analysis_exp_id(batch_id, run_id, problem_id):
    """生成唯一的analysis_exp_id。
    格式：{batch_id}-r{run_id:06d}-{problem_id}
    模仿solver_harness的make_exp_id。"""
    return f"{batch_id}-r{run_id:06d}-{problem_id}"


def make_run_key(analysis_exp_id):
    """生成DB _key（用analysis_exp_id作为key，便于追溯）"""
    # ArangoDB _key不能含/和空格，但可以含-和_
    return analysis_exp_id.replace("/", "-").replace(" ", "-")


def make_paths(analysis_exp_id):
    """生成所有文件路径（模仿solver_harness的make_attempt_paths）
    
    Returns:
        dict with 10+ path keys
    """
    from .config import ANALYSIS_SOLVER_BASE, ANALYSIS_TRAJECTORY_BASE
    sdir = ANALYSIS_SOLVER_BASE / analysis_exp_id
    tdir = ANALYSIS_TRAJECTORY_BASE / analysis_exp_id
    return {
        "solver_dir": str(sdir),
        "trajectory_dir": str(tdir),
        "agents_md_path": str(sdir / "AGENTS.md"),
        "tmux_log_path": str(tdir / "tmux" / "tmux.log"),
        "tmux_pipe_path": str(tdir / "tmux" / "tmux_pipe.log"),
        "export_path": str(tdir / "exports" / "conversation.json"),
        "session_info_path": str(tdir / "session_info.json"),
    }


def make_verdict(status, reason, confidence="medium", needs_human_review=False):
    """生成结构化verdict（模仿solver_harness的make_verdict）"""
    return {
        "auto_status": status,
        "reason": reason,
        "confidence": confidence,
        "needs_human_review": needs_human_review,
    }


def insert_batch(db, batch_doc):
    """插入批次记录"""
    return db.collection(ANALYSIS_BATCHES_COLLECTION).insert(batch_doc)


def update_batch(db, batch_id, update_fields):
    """更新批次记录"""
    update_fields["_key"] = batch_id
    return db.collection(ANALYSIS_BATCHES_COLLECTION).update(update_fields)


def insert_run(db, run_doc):
    """插入一条分析run记录"""
    return db.collection(ANALYSIS_RUNS_COLLECTION).insert(run_doc)


def update_run(db, key, update_fields):
    """更新分析run记录"""
    update_fields["_key"] = key
    return db.collection(ANALYSIS_RUNS_COLLECTION).update(update_fields)


def get_run(db, key):
    """获取分析run记录"""
    return db.collection(ANALYSIS_RUNS_COLLECTION).get(key)


def insert_event(db, batch_id, event_type, data, run_key=None):
    """插入事件"""
    doc = {
        "batch_id": batch_id,
        "event_type": event_type,
        "data": data,
        "timestamp": _utc_now(),
    }
    if run_key:
        doc["run_key"] = run_key
    return db.collection(ANALYSIS_EVENTS_COLLECTION).insert(doc)


def insert_result(db, result_doc):
    """插入分析结果"""
    return db.collection(ANALYSIS_RESULTS_COLLECTION).insert(result_doc)


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
