"""db_schema.py — ArangoDB集合定义

分析系统的DB集合：
  analysis_runs: 每道题的分析run记录（problem_id, exp_id, status, verdict等）
  analysis_events: 事件流（launch, complete, timeout, error等）
  analysis_results: 最终分析结果（从devin cli输出中提取的XML解析结果）
"""

from .config import (
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    ANALYSIS_RUNS_COLLECTION, ANALYSIS_EVENTS_COLLECTION, ANALYSIS_RESULTS_COLLECTION,
)


def connect_db():
    """连接ArangoDB，返回db对象"""
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)


def ensure_schema(db):
    """确保分析系统的集合存在"""
    for col_name in [ANALYSIS_RUNS_COLLECTION, ANALYSIS_EVENTS_COLLECTION, ANALYSIS_RESULTS_COLLECTION]:
        if not db.has_collection(col_name):
            db.create_collection(col_name)

    # 索引
    runs = db.collection(ANALYSIS_RUNS_COLLECTION)
    for name, fields, unique in [
        ("idx_problem_id", ["problem_id"], False),
        ("idx_batch_id", ["batch_id"], False),
        ("idx_status", ["status"], False),
        ("idx_problem_batch", ["problem_id", "batch_id"], True),
    ]:
        try:
            runs.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass

    results = db.collection(ANALYSIS_RESULTS_COLLECTION)
    for name, fields, unique in [
        ("idx_problem_id", ["problem_id"], False),
        ("idx_batch_id", ["batch_id"], False),
        ("idx_verdict", ["dimension1_verdict"], False),
        ("idx_turning_point", ["dimension2_turning_point_type"], False),
    ]:
        try:
            results.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass


def insert_run(db, run_doc):
    """插入一条分析run记录"""
    return db.collection(ANALYSIS_RUNS_COLLECTION).insert(run_doc)


def update_run(db, key, update_fields):
    """更新分析run记录"""
    update_fields["_key"] = key
    return db.collection(ANALYSIS_RUNS_COLLECTION).update(update_fields)


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
