"""test_wp_p_export_parse.py — WP-P 执行中发现的收集器解析 bug 修复单测

修复内容：
  1. extract_audit_from_export 的 source 过滤从 'assistant' 改为接受 'agent'
     （实测 export 格式 source 枚举为 system/user/agent——原实现凭空假设了
     'assistant'，导致 10 个真实审计 export 一个都提取不到文本）
  2. collect_results 的"export 存在但无文本"分支接 mark_parse_error
     （截断样本 message 为空，旧代码静默 skip，run 永远停在 audit_status=null）

用法：
  python scripts/test_wp_p_export_parse.py
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.proof_audit_result_collector import (
    extract_audit_from_export,
    collect_results,
)
from src.proof_audit_config import (
    PROOF_AUDIT_RUNS_COLLECTION,
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
    def __init__(self, name):
        self.name = name
        self.inserts = []
        self.updates = []

    def insert(self, doc):
        self.inserts.append(doc)
        return doc

    def update(self, fields):
        self.updates.append((fields.get("_key", ""), dict(fields)))
        return fields

    def get(self, key):
        return None


class MockDB:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        if name not in self.collections:
            self.collections[name] = MockCollection(name)
        return self.collections[name]


def make_export(path, steps):
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "session_id": "test",
        "agent": "test-agent",
        "steps": steps,
        "final_metrics": {},
    }, ensure_ascii=False))


# === 测试 1：真实格式（source='agent'）能提取到文本 ===

def test_agent_source_extracted():
    print("\n=== 测试 1：source='agent' 的文本被提取 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "conversation.json"
        make_export(p, [
            {"step_id": 1, "source": "system", "message": "sys prompt"},
            {"step_id": 2, "source": "user", "message": "题目"},
            {"step_id": 3, "source": "agent", "message": ""},
            {"step_id": 4, "source": "agent",
             "message": "<proof_audit><audit_status>PASS</audit_status></proof_audit>"},
        ])
        text = extract_audit_from_export(str(p))
        check("agent 文本被提取", text is not None and "<proof_audit>" in text,
              f"text={text!r}")


# === 测试 2：旧格式（source='assistant'）仍兼容 ===

def test_assistant_source_tolerated():
    print("\n=== 测试 2：source='assistant' 仍被兼容 ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "conversation.json"
        make_export(p, [
            {"step_id": 1, "source": "assistant", "message": "legacy text"},
        ])
        text = extract_audit_from_export(str(p))
        check("assistant 文本被提取", text == "legacy text", f"text={text!r}")


# === 测试 3：文件不存在返回 None ===

def test_missing_file():
    print("\n=== 测试 3：文件不存在返回 None ===")
    text = extract_audit_from_export("/nonexistent/path/conversation.json")
    check("返回 None", text is None, f"text={text!r}")


# === 测试 4：collect_results 对"export 存在但无文本"走 mark_parse_error ===

def test_no_text_routes_to_mark_parse_error():
    print("\n=== 测试 4：export 存在但无 agent 文本 → mark_parse_error ===")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "conversation.json"
        # 真实截断样本的形态：agent step 存在但 message 为空
        make_export(p, [
            {"step_id": 1, "source": "system", "message": "sys"},
            {"step_id": 2, "source": "agent", "message": ""},
        ])

        db = MockDB()
        audit_run = {
            "_key": "paudit-p27-full-deepmath_103k_00000036",
            "source_run_key": "p27-full-deepmath_103k_00000036",
            "export_path": str(p),
            "status": "completed",
            "audit_status": None,
            "batch_id": "paudit-p27-full",
        }
        mark_called = {"count": 0, "args": None}

        def fake_mark(db_, run_key, audit_run_key, detail):
            mark_called["count"] += 1
            mark_called["args"] = (run_key, audit_run_key, detail)

        with patch("src.proof_audit_result_collector.connect_db", return_value=db), \
             patch("src.proof_audit_result_collector.ensure_schema", return_value=None), \
             patch("src.proof_audit_result_collector.mark_parse_error", side_effect=fake_mark), \
             patch("src.proof_audit_result_collector.audit_finalize_fail") as fail_mock:
            db.aql = MagicMock()
            db.aql.execute.return_value = iter([audit_run])
            collected = collect_results("paudit-p27-full", limit=10)

        check("mark_parse_error 被调用 1 次", mark_called["count"] == 1,
              f"called={mark_called['count']}")
        check("run_key/audit_run_key 正确",
              mark_called["args"] and mark_called["args"][0] == "p27-full-deepmath_103k_00000036"
              and mark_called["args"][1] == "paudit-p27-full-deepmath_103k_00000036",
              f"args={mark_called['args']}")
        check("detail 说明是'无 agent 文本'",
              mark_called["args"] and "agent" in mark_called["args"][2],
              f"detail={mark_called['args'] and mark_called['args'][2]}")
        check("audit_finalize_fail 未被调用", not fail_mock.called)
        check("collected=1（已标记处置）", collected == 1, f"collected={collected}")


# === 测试 5：collect_results 对"export 文件缺失"保持静默 skip ===

def test_missing_file_skips_silently():
    print("\n=== 测试 5：export 文件缺失 → 静默 skip（不标记）===")
    db = MockDB()
    audit_run = {
        "_key": "paudit-p27-full-x-r1",
        "source_run_key": "p27-full-x",
        "export_path": "/nonexistent/conversation.json",
        "status": "completed",
        "audit_status": None,
        "batch_id": "paudit-p27-full",
    }
    mark_called = {"count": 0}

    with patch("src.proof_audit_result_collector.connect_db", return_value=db), \
         patch("src.proof_audit_result_collector.ensure_schema", return_value=None), \
         patch("src.proof_audit_result_collector.mark_parse_error",
               side_effect=lambda *a: mark_called.__setitem__("count", mark_called["count"] + 1)):
        db.aql = MagicMock()
        db.aql.execute.return_value = iter([audit_run])
        collected = collect_results("paudit-p27-full", limit=10)

    check("mark_parse_error 未被调用", mark_called["count"] == 0,
          f"called={mark_called['count']}")
    check("collected=0", collected == 0, f"collected={collected}")


def main():
    print("=" * 60)
    print("WP-P 收集器解析 bug 修复单测")
    print("=" * 60)

    test_agent_source_extracted()
    test_assistant_source_tolerated()
    test_missing_file()
    test_no_text_routes_to_mark_parse_error()
    test_missing_file_skips_silently()

    print("\n" + "=" * 60)
    print(f"结果: {PASS} PASS / {FAIL} FAIL")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
