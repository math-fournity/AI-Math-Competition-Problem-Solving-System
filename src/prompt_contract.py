"""v3 三角色提示词的最小稳定渲染接口。

WP-03 只冻结模板文件、占位符和角色合同，不接生产 launcher。这里故意不用
``str.format``：数学 LaTeX 含大量普通花括号，逐个替换大写占位符更安全。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = PROJECT_ROOT / "templates" / "v3"
PLACEHOLDER_RE = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")

TEMPLATE_SPECS = {
    "round1": {
        "path": TEMPLATE_ROOT / "prompt_round1_p.md",
        "fields": {"ORIGINAL_PROBLEM"},
    },
    "observer": {
        "path": TEMPLATE_ROOT / "prompt_observer_p.md",
        "fields": {
            "ROUND_NUM", "PREV_NUM", "ORIGINAL_PROBLEM", "PREV_ROUND_DIR",
            "PREV_WORK_NOTES_PATH", "TRAJECTORY_TOOL_PATH", "TRAJECTORY_ROOT",
            "MAP_PATH", "EXPORT_PATH", "NOTES_PATH",
        },
    },
    "solver": {
        "path": TEMPLATE_ROOT / "prompt_solver_p.md",
        "fields": {
            "ROUND_NUM", "PREV_NUM", "ORIGINAL_PROBLEM", "NOTES_PATH", "ROUND_DIR",
        },
    },
}


def template_fields(role: str) -> set[str]:
    """返回模板实际出现的占位符，并校验角色名。"""
    if role not in TEMPLATE_SPECS:
        raise ValueError(f"未知prompt角色: {role}")
    text = TEMPLATE_SPECS[role]["path"].read_text()
    return set(PLACEHOLDER_RE.findall(text))


def validate_template(role: str) -> None:
    """断言模板实际占位符与冻结接口完全一致。"""
    expected = set(TEMPLATE_SPECS[role]["fields"])
    actual = template_fields(role)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            f"{role}模板占位符漂移: missing={missing}, unknown={unknown}")


def render_prompt(role: str, values: Mapping[str, object]) -> str:
    """严格渲染一个角色模板。

    缺字段、额外字段和渲染后遗留的大写占位符都直接报错，便于生产接线
    fail-fast。普通 LaTeX ``{...}`` 不会被识别成占位符。
    """
    if role not in TEMPLATE_SPECS:
        raise ValueError(f"未知prompt角色: {role}")
    validate_template(role)
    expected = set(TEMPLATE_SPECS[role]["fields"])
    provided = set(values)
    missing = expected - provided
    extra = provided - expected
    if missing or extra:
        raise ValueError(
            f"{role}渲染字段不匹配: missing={sorted(missing)}, extra={sorted(extra)}")

    rendered = TEMPLATE_SPECS[role]["path"].read_text()
    for field in sorted(expected):
        rendered = rendered.replace("{" + field + "}", str(values[field]))
    leftovers = sorted(set(PLACEHOLDER_RE.findall(rendered)))
    if leftovers:
        raise ValueError(f"{role}渲染后仍有占位符: {leftovers}")
    return rendered


def validate_all_templates() -> None:
    for role in TEMPLATE_SPECS:
        validate_template(role)
