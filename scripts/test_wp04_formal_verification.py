#!/usr/bin/env python3
"""WP-04 解题侧形式化交付回归（本机Lean/Python，无DB/Redis/网络）。"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.formal_verification import (  # noqa: E402
    REPORT_MARKERS,
    archive_artifact,
    formal_round_log_fields,
    inspect_formal_package,
    run_formal_command,
)


FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "formal"


def copy_fixture(name, target):
    shutil.copytree(FIXTURES / name, target)
    return Path(target)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_clean_lean_kernel_delivery():
    with tempfile.TemporaryDirectory() as td:
        round_dir = copy_fixture("lean_clean", Path(td) / "round1")
        run = run_formal_command(
            round_dir,
            run_name="lean_clean",
            command=["lean", "formal/Main.lean"],
            version_command=["lean", "--version"],
            coverage_kind="trusted_kernel",
        )
        assert run["succeeded"] is True, run
        assert "Lean (version" in run["tool_version"]
        report = inspect_formal_package(round_dir)
        assert report["structurally_complete"] is True, report
        assert report["all_runs_succeeded"] is True
        assert report["escape_hatches"] == {}
        assert report["coverage_kinds"] == ["trusted_kernel"]
        assert report["mathematical_sufficiency_decided"] is False
        assert report["requires_independent_audit"] is True

        fields = formal_round_log_fields(round_dir)
        assert fields["formal_structurally_complete"] is True
        assert fields["formal_all_runs_succeeded"] is True
        assert fields["formal_requires_independent_audit"] is True
        for key in (
            "formal_dir", "formal_verification_path", "formal_logs_dir",
            "verification_dir", "formal_source_paths", "formal_run_record_paths",
        ):
            assert fields[key], key


def test_lean_sorry_is_reported_even_when_command_succeeds():
    with tempfile.TemporaryDirectory() as td:
        round_dir = copy_fixture("lean_sorry", Path(td) / "round1")
        run = run_formal_command(
            round_dir,
            run_name="lean_sorry",
            command=["lean", "formal/Main.lean"],
            coverage_kind="trusted_kernel",
        )
        # Lean接受sorry并给warning；这正是不能只看exit code的反例。
        assert run["succeeded"] is True, run
        report = inspect_formal_package(round_dir)
        assert report["structurally_complete"] is True
        assert report["all_runs_succeeded"] is True
        assert report["escape_hatches"] == {
            "formal/Main.lean": ["sorry", "admit", "axiom"]}
        assert report["mathematical_sufficiency_decided"] is False


def test_python_finite_evidence_stays_finite():
    with tempfile.TemporaryDirectory() as td:
        round_dir = copy_fixture("python_finite", Path(td) / "round1")
        run = run_formal_command(
            round_dir,
            run_name="python_finite",
            command=["python3", "formal/check_finite.py"],
            coverage_kind="finite_computation",
        )
        assert run["succeeded"] is True
        assert "0..100 only" in (round_dir / run["stdout_path"]).read_text()
        report = inspect_formal_package(round_dir)
        assert report["structurally_complete"] is True
        assert report["coverage_kinds"] == ["finite_computation"]
        assert "trusted_kernel" not in report["coverage_kinds"]
        assert report["requires_independent_audit"] is True


def test_tmp_archive_and_missing_source_guards():
    with tempfile.TemporaryDirectory() as td:
        round_dir = Path(td) / "round1"
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix="wp04-", dir="/tmp", delete=False) as handle:
            handle.write("print('archived verification asset')\n")
            tmp_source = Path(handle.name)
        try:
            archived = archive_artifact(
                tmp_source, round_dir, category="verification", target_name="check.py")
            assert archived["source_was_tmp"] is True
            assert (round_dir / archived["path"]).is_file()
        finally:
            tmp_source.unlink(missing_ok=True)

        try:
            archive_artifact("/tmp/wp04-definitely-missing.py", round_dir)
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("缺失临时脚本被虚构成已归档")

        try:
            run_formal_command(
                round_dir, run_name="bad_tmp", command=["python3", "/tmp/lost.py"],
                coverage_kind="finite_computation")
        except ValueError:
            pass
        else:
            raise AssertionError("可重跑命令错误接受/tmp依赖")


def test_cross_round_failure_then_fix_preserves_old_logs():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        round1 = copy_fixture("lean_clean", root / "round1")
        (round1 / "formal" / "Main.lean").write_text(
            "theorem broken (n : Nat) : n = n := by\n  this_is_not_lean\n")
        failed = run_formal_command(
            round1, run_name="lean_failed", command=["lean", "formal/Main.lean"],
            coverage_kind="trusted_kernel")
        assert failed["succeeded"] is False
        old_paths = [round1 / failed["record_path"], round1 / failed["stderr_path"]]
        old_hashes = {str(path): file_hash(path) for path in old_paths}

        round2 = copy_fixture("lean_clean", root / "round2")
        fixed = run_formal_command(
            round2, run_name="lean_fixed", command=["lean", "formal/Main.lean"],
            coverage_kind="trusted_kernel")
        assert fixed["succeeded"] is True
        assert inspect_formal_package(round1)["all_runs_succeeded"] is False
        assert inspect_formal_package(round2)["all_runs_succeeded"] is True
        assert old_hashes == {str(path): file_hash(path) for path in old_paths}


def test_secret_external_path_and_overwrite_guards():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        round_dir = root / "round1"
        source = root / "secret.py"
        source.write_text("OPENROUTER_API_KEY='not-a-real-secret-but-must-not-archive'\n")
        try:
            archive_artifact(source, round_dir)
        except ValueError:
            pass
        else:
            raise AssertionError("疑似secret被归档")

        safe = root / "safe.py"
        safe.write_text("print('safe')\n")
        archive_artifact(safe, round_dir, target_name="safe.py")
        try:
            archive_artifact(safe, round_dir, target_name="safe.py")
        except FileExistsError:
            pass
        else:
            raise AssertionError("同名formal资产被覆盖")

        try:
            run_formal_command(
                round_dir, run_name="absolute", command=[sys.executable, "formal/safe.py"],
                coverage_kind="finite_computation")
        except ValueError:
            pass
        else:
            raise AssertionError("绝对可执行路径进入可重跑命令")

        external_round = copy_fixture("lean_clean", root / "round_external")
        with (external_round / "formal_verification.md").open("a") as handle:
            handle.write("\nUnarchived dependency: /Users/someone/private/checker\n")
        external_report = inspect_formal_package(external_round)
        assert "formal_verification.md" in external_report["external_path_findings"]
        assert external_report["structurally_complete"] is False


def test_report_template_and_prompts_keep_stable_contract():
    report_template = (PROJECT_ROOT / "templates" / "formal_verification_TEMPLATE.md").read_text()
    for marker in REPORT_MARKERS:
        assert marker in report_template
    for prompt_name in ("prompt_round1_p.md", "prompt_solver_p.md"):
        prompt = (PROJECT_ROOT / "templates" / "v3" / prompt_name).read_text()
        for token in (
            "候选成功", "formal/", "formal_verification.md", "formal_logs/",
            "有限搜索", "普遍命题", "独立审计", "`/tmp`",
        ):
            assert token in prompt, (prompt_name, token)
    observer = (PROJECT_ROOT / "templates" / "v3" / "prompt_observer_p.md").read_text()
    assert "形式化覆盖状态" in observer and "验证欠账与资产状态" in observer


def main():
    tests = [value for name, value in globals().items()
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")


if __name__ == "__main__":
    main()
