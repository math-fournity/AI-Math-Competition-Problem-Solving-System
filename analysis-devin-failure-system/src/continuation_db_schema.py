"""continuation_db_schema.py — POC-2.7续传Pipe的ArangoDB集合定义

复用db_schema.py的connect_db，新增p27_continuation_*集合。
不修改现有db_schema.py的任何代码。

集合结构：
  p27_continuation_batches: 批次记录
  p27_continuation_runs:    每道题的续传run记录（含rounds_log、final_status等）
  p27_continuation_events:  事件流
  p27_continuation_results: 最终续传结果（COMPLETED/TRUNCATED_AT_MAX + proof路径）
"""

from .continuation_config import (
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    CONTINUATION_BATCHES_COLLECTION,
    CONTINUATION_RUNS_COLLECTION,
    CONTINUATION_EVENTS_COLLECTION,
    CONTINUATION_RESULTS_COLLECTION,
)


def connect_db():
    """连接ArangoDB（复用现有连接配置）"""
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)


def ensure_schema(db):
    """确保续传Pipe的集合存在"""
    all_collections = [
        CONTINUATION_BATCHES_COLLECTION,
        CONTINUATION_RUNS_COLLECTION,
        CONTINUATION_EVENTS_COLLECTION,
        CONTINUATION_RESULTS_COLLECTION,
    ]
    for col_name in all_collections:
        if not db.has_collection(col_name):
            db.create_collection(col_name)

    # === 索引 ===
    runs = db.collection(CONTINUATION_RUNS_COLLECTION)
    for name, fields, unique in [
        ("p27_idx_problem_id", ["problem_id"], False),
        ("p27_idx_batch_id", ["batch_id"], False),
        ("p27_idx_status", ["status"], False),
        ("p27_idx_final_status", ["final_status"], False),
        ("p27_idx_problem_batch", ["problem_id", "batch_id"], True),
    ]:
        try:
            runs.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass

    events = db.collection(CONTINUATION_EVENTS_COLLECTION)
    for name, fields, unique in [
        ("p27_idx_batch_id", ["batch_id"], False),
        ("p27_idx_run_key", ["run_key"], False),
        ("p27_idx_event_type", ["event_type"], False),
    ]:
        try:
            events.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass

    results = db.collection(CONTINUATION_RESULTS_COLLECTION)
    for name, fields, unique in [
        ("p27_idx_problem_id", ["problem_id"], False),
        ("p27_idx_batch_id", ["batch_id"], False),
        ("p27_idx_final_status", ["final_status"], False),
    ]:
        try:
            results.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass


def make_verdict(status, reason, confidence="medium", needs_human_review=False):
    """生成结构化verdict（复用db_schema的模式）"""
    return {
        "auto_status": status,
        "reason": reason,
        "confidence": confidence,
        "needs_human_review": needs_human_review,
    }


def insert_batch(db, batch_doc):
    return db.collection(CONTINUATION_BATCHES_COLLECTION).insert(batch_doc)


def update_batch(db, batch_id, update_fields):
    update_fields["_key"] = batch_id
    return db.collection(CONTINUATION_BATCHES_COLLECTION).update(update_fields)


def insert_run(db, run_doc):
    return db.collection(CONTINUATION_RUNS_COLLECTION).insert(run_doc)


def update_run(db, key, update_fields):
    update_fields["_key"] = key
    return db.collection(CONTINUATION_RUNS_COLLECTION).update(update_fields)


def get_run(db, key):
    return db.collection(CONTINUATION_RUNS_COLLECTION).get(key)


def insert_event(db, batch_id, event_type, data, run_key=None):
    from datetime import datetime, timezone
    doc = {
        "batch_id": batch_id,
        "event_type": event_type,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if run_key:
        doc["run_key"] = run_key
    return db.collection(CONTINUATION_EVENTS_COLLECTION).insert(doc)


def insert_result(db, result_doc):
    return db.collection(CONTINUATION_RESULTS_COLLECTION).insert(result_doc)


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
