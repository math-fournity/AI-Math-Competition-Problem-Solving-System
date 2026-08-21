"""proof_audit_db_schema.py — Pipe 5 proof 审计系统的 ArangoDB 集合管理

复用 continuation_db_schema 的 connect_db，新增 p27_proof_audit_* 集合。
不修改现有 continuation_db_schema 的任何代码。

集合结构（见 dev-docs/029 §4）：
  p27_proof_audit_runs: 每道题的审计 run 记录
  p27_proof_audits:     审计结果（含 check_results / cheating_analysis / proof_text 备份）
"""
from .continuation_config import (
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
)
from .proof_audit_config import (
    PROOF_AUDIT_RUNS_COLLECTION,
    PROOF_AUDITS_COLLECTION,
)
from monitoring.shared_logger import get_logger, log_event

logger = get_logger("proof_audit_db_schema")


def connect_db():
    """连接 ArangoDB——复用续传系统的连接参数"""
    from arango import ArangoClient
    client = ArangoClient(hosts=ARANGO_HOST)
    return client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASSWORD)


def ensure_schema(db):
    """确保审计 Pipe 的集合存在 + 索引就绪"""
    all_collections = [
        PROOF_AUDIT_RUNS_COLLECTION,
        PROOF_AUDITS_COLLECTION,
    ]
    log_event(logger, "info", "ensure_schema", collections=",".join(all_collections))
    for col_name in all_collections:
        if not db.has_collection(col_name):
            db.create_collection(col_name)

    # === 索引 ===
    runs = db.collection(PROOF_AUDIT_RUNS_COLLECTION)
    for name, fields, unique in [
        ("paudit_idx_source_run_key", ["source_run_key"], False),
        ("paudit_idx_problem_id", ["problem_id"], False),
        ("paudit_idx_batch_id", ["batch_id"], False),
        ("paudit_idx_status", ["status"], False),
    ]:
        try:
            runs.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass

    audits = db.collection(PROOF_AUDITS_COLLECTION)
    for name, fields, unique in [
        ("paudit_idx_source_run_key", ["source_run_key"], False),
        ("paudit_idx_problem_id", ["problem_id"], False),
        ("paudit_idx_batch_id", ["batch_id"], False),
        ("paudit_idx_audit_status", ["audit_status"], False),
    ]:
        try:
            audits.add_index({"type": "persistent", "fields": fields, "unique": unique, "name": name})
        except Exception:
            pass


# === AQL 封装 ===

def insert_audit_run(db, run_doc):
    """插入审计 run 记录"""
    log_event(logger, "debug", "insert_audit_run", run_key=run_doc.get("_key", ""))
    return db.collection(PROOF_AUDIT_RUNS_COLLECTION).insert(run_doc)


def update_audit_run(db, key, update_fields):
    """更新审计 run 记录"""
    log_event(logger, "debug", "update_audit_run", run_key=key)
    update_fields["_key"] = key
    return db.collection(PROOF_AUDIT_RUNS_COLLECTION).update(update_fields)


def get_audit_run(db, key):
    """获取审计 run 记录"""
    return db.collection(PROOF_AUDIT_RUNS_COLLECTION).get(key)


def insert_proof_audit(db, audit_doc):
    """插入审计结果"""
    log_event(logger, "debug", "insert_proof_audit", problem_id=audit_doc.get("problem_id", ""))
    return db.collection(PROOF_AUDITS_COLLECTION).insert(audit_doc)


def update_continuation_run_audit_status(db, run_key, audit_status, audit_passed, audited_at,
                                          audit_run_key=None):
    """更新续传 run 的审计状态字段"""
    from .continuation_db_schema import update_run
    update_fields = {
        "audit_status": audit_status,
        "audit_passed": audit_passed,
        "audited_at": audited_at,
    }
    if audit_run_key:
        update_fields["audit_run_key"] = audit_run_key
    update_run(db, run_key, update_fields)


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
