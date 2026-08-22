"""解题侧形式化交付包的最小归档、执行与结构检查。

本模块只记录直接事实：源码是否归档、命令是否真实运行、版本/退出码/日志、
报告字段和明显逃逸口。它绝不裁定数学证明或形式化覆盖是否充分；该裁决属于
WP-05 的独立审计 AI 和现有 Gate。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


REPORT_MARKERS = (
    "FORMAL_STATEMENT",
    "CLAIM_COVERAGE",
    "TOOLCHAIN",
    "REPRODUCE",
    "RESULTS_AND_LOGS",
    "ESCAPE_HATCHES",
    "FINITE_SEARCH_BOUNDARY",
    "UNCOVERED",
    "SUFFICIENCY_ARGUMENT",
)

COVERAGE_KINDS = {
    "trusted_kernel",
    "finite_computation",
    "symbolic_check",
    "other",
}

ESCAPE_PATTERNS = {
    "sorry": re.compile(r"\bsorry\b", re.IGNORECASE),
    "admit": re.compile(r"\badmit(?:ted)?\b", re.IGNORECASE),
    "axiom": re.compile(r"^\s*(?:private\s+)?axiom\b", re.IGNORECASE | re.MULTILINE),
}

SECRET_PATTERNS = (
    re.compile(r"sk-or-v1-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

EXTERNAL_PATH_PATTERN = re.compile(r"(?:/tmp/|/Users/|/home/)")

SAFE_RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_round_dir(round_dir: str | Path) -> Path:
    root = Path(round_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "formal").mkdir(exist_ok=True)
    (root / "formal_logs").mkdir(exist_ok=True)
    (root / "verification").mkdir(exist_ok=True)
    return root


def _ensure_inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"路径不在Round目录内: {resolved}") from exc
    return resolved


def find_secrets(text: str) -> list[str]:
    return [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]


def _redact_secrets(text: str) -> tuple[str, bool]:
    changed = False
    for pattern in SECRET_PATTERNS:
        text, count = pattern.subn("[REDACTED_SECRET]", text)
        changed = changed or count > 0
    return text, changed


def archive_artifact(
    source: str | Path,
    round_dir: str | Path,
    *,
    category: str = "formal",
    target_name: str | None = None,
) -> dict[str, Any]:
    """把临时/外部验证资产复制进Round，拒绝缺失、symlink和secret。

    ``category`` 仅允许 ``formal`` 或 ``verification``。返回归档相对路径、hash
    和原始路径是否位于 ``/tmp``；调用方可随后安全回收原临时文件。
    """
    if category not in ("formal", "verification"):
        raise ValueError("category必须是formal或verification")
    src = Path(source)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"待归档资产不存在: {src}")
    if src.is_symlink():
        raise ValueError(f"拒绝归档symlink: {src}")
    text = src.read_text(errors="replace")
    if findings := find_secrets(text):
        raise ValueError(f"待归档资产疑似含secret: {findings}")

    root = _ensure_round_dir(round_dir)
    name = target_name or src.name
    if Path(name).name != name or name in ("", ".", ".."):
        raise ValueError("target_name必须是单个安全文件名")
    dest = _ensure_inside(root / category / name, root)
    if dest.exists():
        raise FileExistsError(f"归档目标已存在，拒绝覆盖: {dest}")
    shutil.copy2(src, dest)
    return {
        "path": str(dest.relative_to(root)),
        "sha256": _sha256(dest),
        "bytes": dest.stat().st_size,
        "source_was_tmp": src.resolve().is_relative_to(Path("/tmp").resolve()),
    }


def _validate_argv(argv: Sequence[str]) -> list[str]:
    command = [str(part) for part in argv]
    if not command or not command[0].strip():
        raise ValueError("验证命令不能为空")
    for index, part in enumerate(command):
        if "\x00" in part or "\n" in part:
            raise ValueError("命令参数含非法换行/NUL")
        if "/tmp/" in part or part == "/tmp":
            raise ValueError("可重跑命令不得依赖/tmp路径；请先归档")
        if find_secrets(part):
            raise ValueError("命令参数疑似含secret，拒绝记录")
        candidate = Path(part)
        if candidate.is_absolute():
            raise ValueError(f"命令不得使用绝对路径，请通过PATH或归档相对路径运行: {part}")
        if index > 0 and ".." in candidate.parts:
            raise ValueError(f"命令资产参数不得越出Round目录: {part}")
    return command


def _sanitized_env() -> dict[str, str]:
    blocked = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    return {
        key: value for key, value in os.environ.items()
        if not any(word in key.upper() for word in blocked)
    }


def run_formal_command(
    round_dir: str | Path,
    *,
    run_name: str,
    command: Sequence[str],
    coverage_kind: str,
    version_command: Sequence[str] | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """在Round目录运行形式化/验证命令并保存不可覆盖的证据。

    不使用shell。stdout/stderr若意外出现secret形态会在落盘前脱敏，并在元数据
    标记。exit code 0只代表命令成功，不代表数学充分。
    """
    if not SAFE_RUN_NAME.fullmatch(run_name):
        raise ValueError("run_name只能含字母数字._-且不超过80字符")
    if coverage_kind not in COVERAGE_KINDS:
        raise ValueError(f"未知coverage_kind: {coverage_kind}")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds必须为正数")

    root = _ensure_round_dir(round_dir)
    argv = _validate_argv(command)
    version_argv = _validate_argv(version_command or [argv[0], "--version"])
    logs = root / "formal_logs"
    stdout_path = logs / f"{run_name}.stdout.log"
    stderr_path = logs / f"{run_name}.stderr.log"
    meta_path = logs / f"{run_name}.run.json"
    for path in (stdout_path, stderr_path, meta_path):
        if path.exists():
            raise FileExistsError(f"验证记录已存在，拒绝覆盖: {path}")

    env = _sanitized_env()
    started_at = utc_now()
    try:
        version_result = subprocess.run(
            version_argv, cwd=root, env=env, capture_output=True, text=True,
            timeout=min(timeout_seconds, 30), check=False,
        )
        version_text = (version_result.stdout or version_result.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        version_result = None
        version_text = f"VERSION_COMMAND_FAILED: {type(exc).__name__}: {exc}"

    timed_out = False
    execution_error = None
    try:
        result = subprocess.run(
            argv, cwd=root, env=env, capture_output=True, text=True,
            timeout=timeout_seconds, check=False,
        )
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stderr += f"\nTIMEOUT after {timeout_seconds}s"
    except OSError as exc:
        exit_code = None
        stdout = ""
        stderr = f"EXECUTION_ERROR: {type(exc).__name__}: {exc}"
        execution_error = str(exc)

    stdout, stdout_redacted = _redact_secrets(stdout)
    stderr, stderr_redacted = _redact_secrets(stderr)
    version_text, version_redacted = _redact_secrets(version_text)
    stdout_path.write_text(stdout)
    stderr_path.write_text(stderr)

    record = {
        "schema_version": 1,
        "run_name": run_name,
        "coverage_kind": coverage_kind,
        "command": argv,
        "version_command": version_argv,
        "tool_version": version_text,
        "version_exit_code": None if version_result is None else version_result.returncode,
        "cwd": ".",
        "started_at": started_at,
        "ended_at": utc_now(),
        "timeout_seconds": timeout_seconds,
        "timed_out": timed_out,
        "execution_error": execution_error,
        "exit_code": exit_code,
        "succeeded": exit_code == 0 and not timed_out,
        "stdout_path": str(stdout_path.relative_to(root)),
        "stderr_path": str(stderr_path.relative_to(root)),
        "secret_redacted": stdout_redacted or stderr_redacted or version_redacted,
        "mathematical_sufficiency_decided": False,
    }
    meta_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return {**record, "record_path": str(meta_path.relative_to(root))}


def _iter_package_text_files(root: Path) -> Iterable[Path]:
    for base in (root / "formal", root / "verification"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_symlink():
                continue
            if path.is_file() and path.stat().st_size <= 2_000_000:
                yield path


def inspect_formal_package(round_dir: str | Path) -> dict[str, Any]:
    """返回形式化交付的确定性事实，不给出充分性PASS/FAIL。"""
    root = Path(round_dir).resolve()
    proof = root / "proof.md"
    report = root / "formal_verification.md"
    formal_dir = root / "formal"
    logs_dir = root / "formal_logs"
    verification_dir = root / "verification"

    missing = []
    for path, label in (
        (proof, "proof.md"),
        (formal_dir, "formal/"),
        (report, "formal_verification.md"),
        (logs_dir, "formal_logs/"),
    ):
        if not path.exists():
            missing.append(label)

    report_text = report.read_text(errors="replace") if report.is_file() else ""
    missing_markers = [marker for marker in REPORT_MARKERS if marker not in report_text]
    source_files = list(_iter_package_text_files(root)) if formal_dir.exists() else []
    escape_hatches: dict[str, list[str]] = {}
    secret_findings: dict[str, list[str]] = {}
    external_path_findings: dict[str, list[str]] = {}
    symlinks = []

    for base in (formal_dir, verification_dir):
        if base.exists():
            symlinks.extend(
                str(path.relative_to(root)) for path in base.rglob("*") if path.is_symlink())

    for path in source_files:
        text = path.read_text(errors="replace")
        hits = [name for name, pattern in ESCAPE_PATTERNS.items() if pattern.search(text)]
        if hits:
            escape_hatches[str(path.relative_to(root))] = hits
        if secrets := find_secrets(text):
            secret_findings[str(path.relative_to(root))] = secrets
        if paths := sorted(set(EXTERNAL_PATH_PATTERN.findall(text))):
            external_path_findings[str(path.relative_to(root))] = paths
    for path in (proof, report):
        if path.is_file():
            text = path.read_text(errors="replace")
            if secrets := find_secrets(text):
                secret_findings[str(path.relative_to(root))] = secrets
            if paths := sorted(set(EXTERNAL_PATH_PATTERN.findall(text))):
                external_path_findings[str(path.relative_to(root))] = paths

    run_records = []
    if logs_dir.is_dir():
        for path in sorted(logs_dir.glob("*.run.json")):
            try:
                record = json.loads(path.read_text())
                record["record_path"] = str(path.relative_to(root))
                run_records.append(record)
            except (json.JSONDecodeError, OSError):
                run_records.append({"record_path": str(path.relative_to(root)), "invalid": True})

    missing_run_logs = []
    for record in run_records:
        for field in ("stdout_path", "stderr_path"):
            rel = record.get(field)
            try:
                exists_inside = bool(rel) and _ensure_inside(root / rel, root).is_file()
            except ValueError:
                exists_inside = False
            if not exists_inside:
                missing_run_logs.append(f"{record.get('record_path')}:{field}")

    coverage_kinds = sorted({
        record.get("coverage_kind") for record in run_records
        if record.get("coverage_kind") in COVERAGE_KINDS
    })
    proof_has_boxed = proof.is_file() and "\\boxed" in proof.read_text(errors="replace")
    structurally_complete = not any((
        missing,
        missing_markers,
        not source_files,
        not run_records,
        missing_run_logs,
        symlinks,
        secret_findings,
        external_path_findings,
        not proof_has_boxed,
    ))
    all_runs_succeeded = bool(run_records) and all(
        record.get("succeeded") is True for record in run_records)

    return {
        "schema_version": 1,
        "round_dir": str(root),
        "missing_assets": missing,
        "missing_report_markers": missing_markers,
        "proof_has_boxed": proof_has_boxed,
        "formal_source_paths": [str(path.relative_to(root)) for path in source_files],
        "run_records": run_records,
        "coverage_kinds": coverage_kinds,
        "all_runs_succeeded": all_runs_succeeded,
        "escape_hatches": escape_hatches,
        "secret_findings": secret_findings,
        "external_path_findings": external_path_findings,
        "symlinks": symlinks,
        "missing_run_logs": missing_run_logs,
        "structurally_complete": structurally_complete,
        "mathematical_sufficiency_decided": False,
        "requires_independent_audit": True,
    }


def formal_round_log_fields(round_dir: str | Path) -> dict[str, Any]:
    """生成WP-02登记进rounds_log的稳定形式化字段。"""
    root = Path(round_dir).resolve()
    report = inspect_formal_package(root)
    return {
        "formal_dir": str(root / "formal"),
        "formal_verification_path": str(root / "formal_verification.md"),
        "formal_logs_dir": str(root / "formal_logs"),
        "verification_dir": str(root / "verification"),
        "formal_source_paths": [str(root / path) for path in report["formal_source_paths"]],
        "formal_run_record_paths": [
            str(root / record["record_path"]) for record in report["run_records"]
        ],
        "formal_structurally_complete": report["structurally_complete"],
        "formal_all_runs_succeeded": report["all_runs_succeeded"],
        "formal_escape_hatches": report["escape_hatches"],
        "formal_coverage_kinds": report["coverage_kinds"],
        "formal_requires_independent_audit": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="形式化交付包归档/运行/结构检查")
    sub = parser.add_subparsers(dest="action", required=True)

    inspect_parser = sub.add_parser("inspect", help="检查交付包结构，不裁定数学充分性")
    inspect_parser.add_argument("--round-dir", required=True)

    archive_parser = sub.add_parser("archive", help="复制临时验证资产进Round")
    archive_parser.add_argument("--round-dir", required=True)
    archive_parser.add_argument("--source", required=True)
    archive_parser.add_argument("--category", choices=("formal", "verification"), default="formal")
    archive_parser.add_argument("--target-name")

    run_parser = sub.add_parser("run", help="运行已归档命令并保存版本/日志/退出码")
    run_parser.add_argument("--round-dir", required=True)
    run_parser.add_argument("--run-name", required=True)
    run_parser.add_argument("--coverage-kind", choices=sorted(COVERAGE_KINDS), required=True)
    run_parser.add_argument("--timeout", type=int, default=120)
    run_parser.add_argument("command", nargs=argparse.REMAINDER,
                            help="命令argv；可在前面使用--分隔")

    args = parser.parse_args()
    if args.action == "inspect":
        result = inspect_formal_package(args.round_dir)
    elif args.action == "archive":
        result = archive_artifact(
            args.source, args.round_dir, category=args.category,
            target_name=args.target_name)
    else:
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        result = run_formal_command(
            args.round_dir, run_name=args.run_name, command=command,
            coverage_kind=args.coverage_kind, timeout_seconds=args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
