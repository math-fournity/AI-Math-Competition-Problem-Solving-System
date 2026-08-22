#!/usr/bin/env python3
"""WP-03 提示词、资产合同与1962离线回归（无模型/DB/Redis）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.prompt_contract import (  # noqa: E402
    PLACEHOLDER_RE,
    TEMPLATE_SPECS,
    render_prompt,
    validate_all_templates,
)


FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "1962"
ASSET_CONTRACT = PROJECT_ROOT / "docs" / "architecture" / "round-artifact-contract.md"


def sample_values(role):
    values = {
        "ORIGINAL_PROBLEM": "Find every object satisfying the stated invariant.",
        "ROUND_NUM": "8",
        "PREV_NUM": "7",
        "PREV_ROUND_DIR": "rounds/round7",
        "PREV_WORK_NOTES_PATH": "rounds/round7/工作笔记.md",
        "MAP_PATH": "rounds/round7/conversation_map.md",
        "EXPORT_PATH": "rounds/round7/conversation.json",
        "NOTES_PATH": "rounds/round8/分析笔记.md",
        "ROUND_DIR": "rounds/round8",
    }
    return {key: values[key] for key in TEMPLATE_SPECS[role]["fields"]}


def test_strict_rendering():
    validate_all_templates()
    for role in TEMPLATE_SPECS:
        rendered = render_prompt(role, sample_values(role))
        assert not PLACEHOLDER_RE.findall(rendered), (role, PLACEHOLDER_RE.findall(rendered))
        assert "Find every object" in rendered
    try:
        render_prompt("round1", {})
    except ValueError:
        pass
    else:
        raise AssertionError("缺字段未fail-fast")
    try:
        render_prompt("round1", {"ORIGINAL_PROBLEM": "p", "EXTRA": "x"})
    except ValueError:
        pass
    else:
        raise AssertionError("额外字段未fail-fast")


def test_role_and_formal_boundaries():
    round1 = TEMPLATE_SPECS["round1"]["path"].read_text()
    observer = TEMPLATE_SPECS["observer"]["path"].read_text()
    solver = TEMPLATE_SPECS["solver"]["path"].read_text()

    assert "不做档案考古" in round1
    assert "持续更新当前目录的 `工作笔记.md`" in round1
    assert "候选成功" in round1 and "不是系统已经确认数学真理" in round1

    assert "你不解题" in observer and "唯一交付物" in observer
    assert "不写 `proof.md`" in observer
    assert observer.index("**scan**") < observer.index("**tail**")
    assert observer.index("**tail**") < observer.index("**search**")
    assert observer.index("**search**") < observer.index("**read**")
    for section in (
        "题目与全局状态", "当前真实前沿", "死路清单", "单一主缺口",
        "对更早档案的修正", "形式化覆盖状态", "验证欠账与资产状态",
    ):
        assert section in observer

    assert "不做大面积历史考古" in solver
    assert "单一主缺口" in solver
    assert "回头重做已经闭环" in solver
    assert "候选成功" in solver and "等待独立审计" in solver

    for text in (round1, solver):
        for required in (
            "formal/", "formal_logs/", "formal_verification.md", "verification/",
            "有限搜索", "普遍命题", "`/tmp`", "sorry", "admit",
        ):
            assert required in text, required


def test_artifact_contract():
    text = ASSET_CONTRACT.read_text()
    required_assets = (
        "prompt.md", "role.json", "notifications.jsonl", "thoughts.jsonl",
        "messages.jsonl", "tools.jsonl", "conversation.json", "conversation_map.md",
        "工作笔记.md", "分析笔记.md", "proof.md", "proof_partial.md", "formal/",
        "formal_verification.md", "formal_logs/", "verification/", "round_result.json",
    )
    for asset in required_assets:
        assert asset in text, asset
    for invariant in (
        "永不覆盖", "mtime", "逐条 flush", "先收集/校验全部资产", "现有 Gate",
    ):
        assert invariant in text, invariant


def test_1962_fixture_is_answer_free_and_complete():
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text())
    assert manifest["answer_free"] is True
    assert manifest["online_model_required"] is False
    cases = manifest["cases"]
    assert [case["id"] for case in cases] == [
        "v1_handover_contrast",
        "r2_scene_to_r3_observer",
        "r3_notes_to_solver",
        "r4_scene_to_r5_observer",
        "r5_notes_to_solver",
    ]

    fixture_text = "\n".join(
        path.read_text() for path in FIXTURE_ROOT.iterdir()
        if path.is_file() and path.name != "manifest.json"
    )
    # 原题最终四组答案不得出现在会被复制给模型的fixture文本中。
    for leaked_answer in ("(2,2,2)", "(2,2,3)", "(2,6,11)", "(3,5,7)"):
        assert leaked_answer not in fixture_text, leaked_answer
    assert "/Users/" not in fixture_text
    assert not (FIXTURE_ROOT / "proof.md").exists()
    for case in cases:
        assert (FIXTURE_ROOT / case["input"]).is_file()
        assert case["role"] in ("observer", "solver")
        assert case["expected_behaviors"]


def test_1962_behavior_tags_are_frozen_in_prompts():
    observer = TEMPLATE_SPECS["observer"]["path"].read_text()
    solver = TEMPLATE_SPECS["solver"]["path"].read_text()
    anchors = {
        "reject_bare_handover": (observer, "不用“已验证”“禁止重验”替代推导供料"),
        "require_derivation_skeleton": (observer, "推导骨架"),
        "preserve_dead_end_reason": (observer, "死因"),
        "scan_tail_targeted_read": (observer, "scan → tail → search/read"),
        "collect_unwritten_tail": (observer, "trajectory 尾部"),
        "record_verification_debt": (observer, "验证欠账与资产状态"),
        "focus_single_gap": (solver, "单一主缺口"),
        "do_not_reverify_closed_branch": (solver, "回头重做已经闭环"),
        "archive_verification_assets": (solver, "禁止只留"),
        "verify_new_theorem": (observer, "形式化覆盖状态"),
        "execute_or_record_debt": (observer, "未执行计划"),
        "correct_earlier_note": (observer, "对更早档案的修正"),
        "assemble_without_reopening": (solver, "组装自包含 proof"),
        "candidate_not_final": (solver, "等待独立审计"),
    }
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text())
    tags = {tag for case in manifest["cases"] for tag in case["expected_behaviors"]}
    assert tags == set(anchors), (tags - set(anchors), set(anchors) - tags)
    for tag, (text, phrase) in anchors.items():
        assert phrase in text, f"{tag}: missing {phrase}"


def test_mixed_prompt_is_not_default_asset():
    assert not list((PROJECT_ROOT / "templates").glob("**/prompt_roundN.md"))
    readme = (PROJECT_ROOT / "templates" / "README.md").read_text()
    assert "混合模板" in readme and "不得在生产默认路径恢复" in readme


def main():
    tests = [value for name, value in globals().items()
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")


if __name__ == "__main__":
    main()
