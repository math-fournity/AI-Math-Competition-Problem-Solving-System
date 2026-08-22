"""分层 trajectory reader 的最小跨后端行为合同。

053 已确定 observer 必须亲自使用分层工具消化完整现场。本模块不解析任何具体
backend schema；它只冻结 reader manifest、共同CLI能力、scan输出和使用证据字段。
OpenCode/legacy/Devin 的小型 adapter 分别在对应工作包实现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence


REQUIRED_CAPABILITIES = {
    "scan",
    "tail",
    "search",
    "inspect",
    "reasoning",
    "tool_input",
    "tool_result",
    "error",
}

REQUIRED_SCAN_FIELDS = {
    "idx",
    "event_type",
    "role",
    "started_at",
    "finish_reason",
    "error_name",
    "tool_names",
    "usage",
    "source_ref",
}

OPERATIONS = {"scan", "tail", "search", "inspect"}


def _safe_relative(value: str, field: str) -> str:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field}必须是实例cwd内的安全相对路径: {value!r}")
    return value


def validate_reader_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """校验一个backend reader向observer公开的能力和路径。"""
    if manifest.get("schema_version") != 1:
        raise ValueError("trajectory reader schema_version必须为1")
    backend = str(manifest.get("backend") or "").strip()
    if not backend:
        raise ValueError("reader manifest缺backend")
    prefix = manifest.get("command_prefix")
    if not isinstance(prefix, Sequence) or isinstance(prefix, (str, bytes)) or not prefix:
        raise ValueError("command_prefix必须是非空argv数组")
    command_prefix = [str(part) for part in prefix]
    for part in command_prefix:
        if not part or "\n" in part or "\x00" in part:
            raise ValueError("command_prefix含非法参数")
        if Path(part).is_absolute() or ".." in Path(part).parts:
            raise ValueError("reader工具必须复制进cwd并通过相对路径/PATH调用")

    trajectory_root = _safe_relative(str(manifest.get("trajectory_root") or ""), "trajectory_root")
    capabilities = set(manifest.get("capabilities") or [])
    missing = REQUIRED_CAPABILITIES - capabilities
    if missing:
        raise ValueError(f"reader能力不完整: missing={sorted(missing)}")
    return {
        "schema_version": 1,
        "backend": backend,
        "command_prefix": command_prefix,
        "trajectory_root": trajectory_root,
        "capabilities": sorted(capabilities),
    }


def validate_scan_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    """校验第一层概览：稳定idx、必要元数据、不展开巨大正文。"""
    seen = set()
    for row in rows:
        missing = REQUIRED_SCAN_FIELDS - set(row)
        if missing:
            raise ValueError(f"scan row缺字段: {sorted(missing)}")
        idx = row.get("idx")
        if not isinstance(idx, int) or idx < 0 or idx in seen:
            raise ValueError(f"scan idx必须是唯一非负整数: {idx!r}")
        seen.add(idx)
        # scan只能给短预览，不得偷塞完整reasoning/tool结果造成通读。
        for forbidden in ("reasoning", "tool_input", "tool_result", "messages"):
            if forbidden in row:
                raise ValueError(f"scan row不得展开{forbidden}正文")
        if len(str(row.get("text_head") or "")) > 500:
            raise ValueError("scan text_head过长，疑似把正文塞进概览")


def build_reader_command(
    manifest: Mapping[str, Any], operation: str, **kwargs: Any,
) -> list[str]:
    """按共同CLI合同构造命令；具体backend reader负责解析自己的原始schema。"""
    checked = validate_reader_manifest(manifest)
    if operation not in OPERATIONS:
        raise ValueError(f"未知trajectory操作: {operation}")
    command = [*checked["command_prefix"], operation, checked["trajectory_root"]]
    if operation == "scan":
        command.append("--json")
    elif operation == "tail":
        chars = int(kwargs.get("chars", 8000))
        if chars <= 0:
            raise ValueError("tail chars必须为正")
        command += ["--chars", str(chars)]
    elif operation == "search":
        pattern = str(kwargs.get("pattern") or "")
        if not pattern:
            raise ValueError("search必须提供pattern")
        command += ["--pattern", pattern]
    else:
        idx = kwargs.get("idx")
        if not isinstance(idx, int) or idx < 0:
            raise ValueError("inspect必须提供非负idx")
        command += ["--idx", str(idx)]
        if kwargs.get("message") is not None:
            message = int(kwargs["message"])
            if message < 0:
                raise ValueError("message必须非负")
            command += ["--message", str(message)]
        for key, flag in (
            ("reasoning", "--reasoning"),
            ("tool_input", "--tool-input"),
            ("tool_result", "--tool-result"),
            ("error", "--error"),
        ):
            if kwargs.get(key):
                command.append(flag)
    return command


def make_read_evidence(
    *,
    operation: str,
    source_round: int,
    command: Sequence[str],
    output_path: str,
    exit_code: int,
    selected_indices: Sequence[int] | None = None,
) -> dict[str, Any]:
    """构造observer真实使用reader的最小可审计记录。"""
    if operation not in OPERATIONS:
        raise ValueError(f"未知trajectory操作: {operation}")
    if source_round <= 0:
        raise ValueError("source_round必须为正")
    _safe_relative(output_path, "output_path")
    indices = list(selected_indices or [])
    if any(not isinstance(idx, int) or idx < 0 for idx in indices):
        raise ValueError("selected_indices必须是非负整数")
    return {
        "operation": operation,
        "source_round": source_round,
        "command": [str(part) for part in command],
        "output_path": output_path,
        "exit_code": int(exit_code),
        "selected_indices": indices,
    }
