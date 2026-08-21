"""test_wp_n_parse_error.py — WP-N PARSE_ERROR 修复的单测

验证 029 §3.3 的 PARSE_ERROR 语义在实现中被正确落地：
  1. mark_parse_error 不写 status 字段（与旧实现走 audit_finalize_fail 的本质区别）
  2. audit_status=="PARSE_ERROR"、audit_passed is None
  3. alert 集合多一条 audit_parse_error（key 格式对齐 cheating_detected）
  4. collect_results 的两处 PARSE_ERROR 分支走 mark_parse_error，不走 audit_finalize_fail

测试策略：mock db 对象（不依赖真实 DB 写入的生产集合），monkeypatch
audit_finalize_fail 打标记验证它未被调用。

用法：
  python scripts/test_wp_n_parse_error.py
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.proof_audit_result_collector import (
    mark_parse_error,
    collect_results,
    parse_audit_xml,
)
from src.proof_audit_config import (
    PROOF_AUDIT_RUNS_COLLECTION,
    PROOF_AUDITS_COLLECTION,
    CONTINUATION_RUNS_COLLECTION,
    MONITOR_ALERTS_COLLECTION,
)

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


class MockCollection:
    """模拟 ArangoDB collection——记录所有 insert/update 调用"""

    def __init__(self, name):
        self.name = name
        self.inserts = []   # 记录 insert 的文档
        self.updates = []   # 记录 update 的 (key, fields)
        self.docs = {}      # get(key) 的返回值

    def insert(self, doc):
        self.inserts.append(doc)
        return doc

    def update(self, fields):
        key = fields.get("_key", "")
        self.updates.append((key, dict(fields)))
        self.docs[key] = {**self.docs.get(key, {}), **fields}
        return fields

    def get(self, key):
        return self.docs.get(key)


class MockDB:
    """模拟 ArangoDB——按 collection 名分发到 MockCollection"""

    def __init__(self):
        self.collections = {}

    def collection(self, name):
        if name not in self.collections:
            self.collections[name] = MockCollection(name)
        return self.collections[name]


# === 测试 1：mark_parse_error 直接调用 ===

def test_mark_parse_error_direct():
    print("\n=== 测试 1：mark_parse_error 直接调用 ===")
    db = MockDB()
    run_key = "p27-full-deepmath_103k_00001653"
    audit_run_key = "paudit-p27-full-00001653-r1"
    detail = "XML解析失败，无法提取审计结果"

    mark_parse_error(db, run_key, audit_run_key, detail)

    # 1. 审计 run 被更新
    audit_col = db.collections.get(PROOF_AUDIT_RUNS_COLLECTION)
    check("审计 run 有 1 次 update",
          audit_col is not None and len(audit_col.updates) == 1,
          f"updates={len(audit_col.updates) if audit_col else 'None'}")
    if audit_col and audit_col.updates:
        _, fields = audit_col.updates[0]
        check("审计 run audit_status=PARSE_ERROR",
              fields.get("audit_status") == "PARSE_ERROR",
              f"audit_status={fields.get('audit_status')}")
        check("审计 run audit_passed=None",
              fields.get("audit_passed") is None,
              f"audit_passed={fields.get('audit_passed')}")
        check("审计 run 有 error_message",
              "error_message" in fields and fields["error_message"],
              f"error_message={fields.get('error_message')}")
        check("审计 run 未写 status",
              "status" not in fields,
              f"fields keys={list(fields.keys())}")

    # 2. continuation_runs 被更新——绝不写 status
    runs_col = db.collections.get(CONTINUATION_RUNS_COLLECTION)
    check("runs 有 1 次 update",
          runs_col is not None and len(runs_col.updates) == 1,
          f"updates={len(runs_col.updates) if runs_col else 'None'}")
    if runs_col and runs_col.updates:
        key, fields = runs_col.updates[0]
        check("runs update key 正确",
              key == run_key, f"key={key}")
        check("runs audit_status=PARSE_ERROR",
              fields.get("audit_status") == "PARSE_ERROR",
              f"audit_status={fields.get('audit_status')}")
        check("runs audit_passed=None",
              fields.get("audit_passed") is None,
              f"audit_passed={fields.get('audit_passed')}")
        check("runs 有 audited_at",
              "audited_at" in fields, f"fields keys={list(fields.keys())}")
        check("runs 有 audit_run_key",
              fields.get("audit_run_key") == audit_run_key,
              f"audit_run_key={fields.get('audit_run_key')}")
        # ★ 核心断言：status 未被修改
        check("★ runs status 未被修改（与旧实现的本质区别）",
              "status" not in fields,
              f"fields keys={list(fields.keys())}")

    # 3. alert 集合多一条 audit_parse_error
    alert_col = db.collections.get(MONITOR_ALERTS_COLLECTION)
    check("alert 集合有 1 条 insert",
          alert_col is not None and len(alert_col.inserts) == 1,
          f"inserts={len(alert_col.inserts) if alert_col else 'None'}")
    if alert_col and alert_col.inserts:
        alert = alert_col.inserts[0]
        check("alert _key 前缀 p27-alert-audit_parse_error-",
              alert["_key"].startswith("p27-alert-audit_parse_error-"),
              f"_key={alert['_key']}")
        check("alert alert_type=audit_parse_error",
              alert.get("alert_type") == "audit_parse_error",
              f"alert_type={alert.get('alert_type')}")
        check("alert severity=warning",
              alert.get("severity") == "warning",
              f"severity={alert.get('severity')}")
        check("alert status=new",
              alert.get("status") == "new",
              f"status={alert.get('status')}")
        check("alert details.summary 含 audit_run_key",
              audit_run_key in alert.get("details", {}).get("summary", ""),
              f"summary={alert.get('details', {}).get('summary', '')}")
        check("alert details.run_key 正确",
              alert.get("details", {}).get("run_key") == run_key,
              f"run_key={alert.get('details', {}).get('run_key')}")

    # 4. 没有写 p27_proof_audits（029 §3.3 没让建）
    audits_col = db.collections.get(PROOF_AUDITS_COLLECTION)
    check("未写 p27_proof_audits（PARSE_ERROR 不建审计结果记录）",
          audits_col is None or len(audits_col.inserts) == 0,
          f"inserts={len(audits_col.inserts) if audits_col else 0}")


# === 测试 2：collect_results 的 PARSE_ERROR 分支1（XML 解析失败）===

def test_collect_results_parse_error_branch1():
    print("\n=== 测试 2：collect_results 分支1（parse_audit_xml 返回 None）===")
    db = MockDB()

    # mock 候选 audit_run
    audit_run = {
        "_key": "paudit-p27-full-00001653-r1",
        "source_run_key": "p27-full-deepmath_103k_00001653",
        "export_path": "/fake/export.json",
        "status": "completed",
        "audit_status": None,
        "batch_id": "paudit-p27-full",
    }

    finalize_fail_called = {"count": 0}
    mark_called = {"count": 0}

    with patch("src.proof_audit_result_collector.connect_db", return_value=db), \
         patch("src.proof_audit_result_collector.ensure_schema", return_value=None), \
         patch("src.proof_audit_result_collector.extract_audit_from_export",
               return_value="无 XML 块的假文本"), \
         patch("src.proof_audit_result_collector.audit_finalize_fail",
               side_effect=lambda *a, **k: finalize_fail_called.__setitem__("count", finalize_fail_called["count"] + 1)), \
         patch("src.proof_audit_result_collector.mark_parse_error",
               side_effect=lambda *a, **k: mark_called.__setitem__("count", mark_called["count"] + 1)):
        # mock aql.execute 返回候选
        db.aql = MagicMock()
        db.aql.execute.return_value = iter([audit_run])

        collected = collect_results("paudit-p27-full", limit=10)

    check("audit_finalize_fail 未被调用",
          finalize_fail_called["count"] == 0,
          f"called={finalize_fail_called['count']}")
    check("mark_parse_error 被调用 1 次",
          mark_called["count"] == 1,
          f"called={mark_called['count']}")
    check("collected=1", collected == 1, f"collected={collected}")


# === 测试 3：collect_results 的 PARSE_ERROR 分支2（audit_status 无效）===

def test_collect_results_parse_error_branch2():
    print("\n=== 测试 3：collect_results 分支2（audit_status 无效枚举）===")
    db = MockDB()

    # mock 候选 audit_run——export 文本含 XML 块但 audit_status 是无效值
    audit_run = {
        "_key": "paudit-p27-full-00001999-r1",
        "source_run_key": "p27-full-deepmath_103k_00001999",
        "export_path": "/fake/export2.json",
        "status": "completed",
        "audit_status": None,
        "batch_id": "paudit-p27-full",
    }
    fake_text = "<proof_audit><problem_id>x</problem_id><audit_status>BOGUS</audit_status><audit_summary>s</audit_summary></proof_audit>"

    finalize_fail_called = {"count": 0}
    mark_called = {"count": 0}

    with patch("src.proof_audit_result_collector.connect_db", return_value=db), \
         patch("src.proof_audit_result_collector.ensure_schema", return_value=None), \
         patch("src.proof_audit_result_collector.extract_audit_from_export",
               return_value=fake_text), \
         patch("src.proof_audit_result_collector.audit_finalize_fail",
               side_effect=lambda *a, **k: finalize_fail_called.__setitem__("count", finalize_fail_called["count"] + 1)), \
         patch("src.proof_audit_result_collector.mark_parse_error",
               side_effect=lambda *a, **k: mark_called.__setitem__("count", mark_called["count"] + 1)):
        db.aql = MagicMock()
        db.aql.execute.return_value = iter([audit_run])

        collected = collect_results("paudit-p27-full", limit=10)

    check("audit_finalize_fail 未被调用",
          finalize_fail_called["count"] == 0,
          f"called={finalize_fail_called['count']}")
    check("mark_parse_error 被调用 1 次",
          mark_called["count"] == 1,
          f"called={mark_called['count']}")
    check("collected=1", collected == 1, f"collected={collected}")


# === 测试 4：PASS/FAIL 路径仍走 audit_finalize_pass/fail（未误伤）===

def test_pass_fail_paths_unchanged():
    print("\n=== 测试 4：PASS/FAIL 路径未被误伤 ===")
    db = MockDB()

    audit_run = {
        "_key": "paudit-p27-full-00002000-r1",
        "source_run_key": "p27-full-deepmath_103k_00002000",
        "export_path": "/fake/export3.json",
        "status": "completed",
        "audit_status": None,
        "batch_id": "paudit-p27-full",
    }
    fake_text = "<proof_audit><problem_id>x</problem_id><audit_status>PASS</audit_status><audit_summary>s</audit_summary></proof_audit>"

    finalize_pass_called = {"count": 0}
    finalize_fail_called = {"count": 0}
    mark_called = {"count": 0}

    with patch("src.proof_audit_result_collector.connect_db", return_value=db), \
         patch("src.proof_audit_result_collector.ensure_schema", return_value=None), \
         patch("src.proof_audit_result_collector.extract_audit_from_export",
               return_value=fake_text), \
         patch("src.proof_audit_result_collector.audit_finalize_pass",
               side_effect=lambda *a, **k: finalize_pass_called.__setitem__("count", finalize_pass_called["count"] + 1)), \
         patch("src.proof_audit_result_collector.audit_finalize_fail",
               side_effect=lambda *a, **k: finalize_fail_called.__setitem__("count", finalize_fail_called["count"] + 1)), \
         patch("src.proof_audit_result_collector.mark_parse_error",
               side_effect=lambda *a, **k: mark_called.__setitem__("count", mark_called["count"] + 1)):
        db.aql = MagicMock()
        db.aql.execute.return_value = iter([audit_run])

        collected = collect_results("paudit-p27-full", limit=10)

    check("PASS 走 audit_finalize_pass",
          finalize_pass_called["count"] == 1,
          f"called={finalize_pass_called['count']}")
    check("PASS 不走 audit_finalize_fail",
          finalize_fail_called["count"] == 0,
          f"called={finalize_fail_called['count']}")
    check("PASS 不走 mark_parse_error",
          mark_called["count"] == 0,
          f"called={mark_called['count']}")


# === 测试 5：parse_audit_xml 对无效 audit_status 返回 PARSE_ERROR ===

def test_parse_audit_xml_invalid_status():
    print("\n=== 测试 5：parse_audit_xml 对无效 audit_status 标 PARSE_ERROR ===")
    fake_text = "<proof_audit><problem_id>x</problem_id><audit_status>BOGUS</audit_status><audit_summary>s</audit_summary></proof_audit>"
    parsed = parse_audit_xml(fake_text)
    check("无效 audit_status 被标为 PARSE_ERROR",
          parsed is not None and parsed["audit_status"] == "PARSE_ERROR",
          f"parsed={parsed}")


def main():
    print("=" * 60)
    print("WP-N PARSE_ERROR 修复单测")
    print("=" * 60)

    test_mark_parse_error_direct()
    test_collect_results_parse_error_branch1()
    test_collect_results_parse_error_branch2()
    test_pass_fail_paths_unchanged()
    test_parse_audit_xml_invalid_status()

    print("\n" + "=" * 60)
    print(f"结果: {PASS} PASS / {FAIL} FAIL")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
