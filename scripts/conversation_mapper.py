#!/usr/bin/env python3
"""
conversation.json 面包屑地图生成器
====================================
不假设schema，递归遍历conversation.json，生成三层面包屑地图：
  第一层：顶层概览
  第二层：steps数组概要（按时间顺序）
  第三层：每个agent step的内部字段详情

地图输出为Markdown格式，供编写HANDOVER.md的AI阅读。

用法：
    python3 conversation_mapper.py <conversation.json路径>
    python3 conversation_mapper.py <conversation.json路径> -o <输出路径>
    python3 conversation_mapper.py <conversation.json路径> --stdout  # 输出到stdout

设计约束：
  - 不假设任何字段名（reasoning_content/tool_calls/observation等都不是硬编码的）
  - 递归遍历任意JSON结构
  - 大字段只记录元数据（path/type/size/preview），不复制完整内容
  - 按数组顺序遍历（steps的顺序就是时间顺序）
"""

import json
import os
import sys
import argparse
from pathlib import Path


# === 语义提示（基于字段名英文含义，非schema假设）===
# 如果字段名不在提示表中，遍历程序照常工作，只是没有提示
SEMANTIC_HINTS = {
    "reasoning_content": "thinking内容（AI内部思考）",
    "thinking": "thinking内容（AI内部思考）",
    "message": "消息内容（TUI输出或用户输入）",
    "tool_calls": "工具调用列表",
    "function_name": "工具函数名",
    "arguments": "工具调用参数",
    "observation": "工具返回结果",
    "results": "结果列表",
    "content": "内容",
    "source": "来源（system/user/agent）",
    "metrics": "指标（token统计等）",
    "completion_tokens": "completion token数（截断判定用）",
    "prompt_tokens": "prompt token数",
    "cached_tokens": "缓存token数",
    "step_id": "步骤ID",
    "timestamp": "时间戳",
    "model_name": "模型名",
    "generation_model": "生成模型",
    "session_id": "会话ID",
    "schema_version": "schema版本",
    "tool_call_id": "工具调用ID",
    "source_call_id": "来源调用ID（对应tool_call_id）",
    "command": "命令内容",
    "file_path": "文件路径",
    "name": "名称",
    "version": "版本",
    "backend": "后端",
    "permission_mode": "权限模式",
    "tool_definitions": "工具定义列表",
    "extra": "额外信息",
    "telemetry": "遥测信息",
    "final_metrics": "最终指标",
    "total_steps": "总步骤数",
}

# 大字段阈值
SMALL_FIELD_MAX = 200      # < 200c: 小字段，地图含完整值
MEDIUM_FIELD_MAX = 5000    # 200-5000c: 中字段，地图含前200字符预览
LARGE_FIELD_MAX = 50000    # 5000-50000c: 大字段，地图只有长度和前100字符
# > 50000c: 超大字段，地图只有长度和前100字符，标记为"超大"


def classify_size(s, length):
    """对字符串字段分类大小。"""
    if length < SMALL_FIELD_MAX:
        return "小"
    elif length < MEDIUM_FIELD_MAX:
        return "中"
    elif length < LARGE_FIELD_MAX:
        return "大"
    else:
        return "超大"


def format_value_preview(v, max_len=200):
    """格式化值的预览。"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        if len(v) <= max_len:
            return v.replace("\n", "\\n")
        return v[:max_len].replace("\n", "\\n") + "..."
    if isinstance(v, list):
        return f"[list, {len(v)} elements]"
    if isinstance(v, dict):
        return f"[dict, {len(v)} keys: {list(v.keys())[:5]}]"
    return str(v)


def format_size(v):
    """格式化节点大小。"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return f"{len(v)}c"
    if isinstance(v, list):
        return f"list[{len(v)}]"
    if isinstance(v, dict):
        return f"dict[{len(v)}keys]"
    return "?"


def get_semantic_hint(field_name):
    """获取字段名的语义提示。"""
    return SEMANTIC_HINTS.get(field_name, "")


# === 第一层：顶层概览 ===

def generate_top_level(data):
    """生成顶层概览。"""
    lines = []
    lines.append("# Conversation.json 面包屑地图")
    lines.append("")
    lines.append(f"> 生成程序：`scripts/conversation_mapper.py`")
    lines.append(f"> 遍历原则：不假设schema，递归遍历所有节点")
    lines.append("")

    lines.append("## 第一层：顶层概览")
    lines.append("")
    lines.append("```")
    if isinstance(data, dict):
        for k, v in data.items():
            size = format_size(v)
            hint = get_semantic_hint(k)
            hint_str = f"  ← {hint}" if hint else ""

            if isinstance(v, str) and len(v) < SMALL_FIELD_MAX:
                lines.append(f"  {k}  [{type(v).__name__}, {size}]  {format_value_preview(v)}{hint_str}")
            elif isinstance(v, (int, float, bool)) or v is None:
                lines.append(f"  {k}  [{type(v).__name__}, {size}]  {format_value_preview(v)}{hint_str}")
            elif isinstance(v, dict):
                lines.append(f"  {k}  [{type(v).__name__}, {size}]{hint_str}")
                # 展开一层
                for k2, v2 in v.items():
                    size2 = format_size(v2)
                    hint2 = get_semantic_hint(k2)
                    hint_str2 = f"  ← {hint2}" if hint2 else ""
                    if isinstance(v2, str) and len(v2) < SMALL_FIELD_MAX:
                        lines.append(f"    {k}.{k2}  [{type(v2).__name__}, {size2}]  {format_value_preview(v2)}{hint_str2}")
                    elif isinstance(v2, (int, float, bool)) or v2 is None:
                        lines.append(f"    {k}.{k2}  [{type(v2).__name__}, {size2}]  {format_value_preview(v2)}{hint_str2}")
                    else:
                        lines.append(f"    {k}.{k2}  [{type(v2).__name__}, {size2}]{hint_str2}")
            elif isinstance(v, list):
                lines.append(f"  {k}  [{type(v).__name__}, {size}]{hint_str}")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# === 第二层：steps数组概要 ===

def generate_steps_overview(data):
    """生成steps数组的概要。"""
    lines = []
    steps = data.get("steps") if isinstance(data, dict) else None

    if not isinstance(steps, list):
        # 如果没有steps字段，遍历顶层所有list字段
        lines.append("## 第二层：数组字段概要")
        lines.append("")
        lines.append("（未找到'steps'字段，列出所有顶层数组字段）")
        lines.append("")
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    lines.append(f"### {k} [list, {len(v)} elements]")
                    lines.append("")
                    generate_array_overview(lines, v, k)
        return "\n".join(lines)

    lines.append("## 第二层：steps数组概要（按时间顺序）")
    lines.append("")
    lines.append(f"共 {len(steps)} 个step")
    lines.append("")
    lines.append("```")

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            lines.append(f"  steps[{i}]  [{type(step).__name__}]  {format_value_preview(step, 100)}")
            continue

        # 收集step的关键信息（不假设字段名，但优先展示常见字段）
        source = step.get("source", "?")
        size = format_size(step)

        # 尝试找到"消息"字段（可能是message或content）
        msg_field = None
        for candidate in ["message", "content", "text"]:
            if candidate in step:
                msg_field = candidate
                break

        msg_size = ""
        msg_preview = ""
        if msg_field:
            msg_val = step.get(msg_field, "")
            if isinstance(msg_val, str):
                msg_size = f"{msg_field}={len(msg_val)}c"
                msg_preview = format_value_preview(msg_val, 80)
            else:
                msg_size = f"{msg_field}={format_size(msg_val)}"

        # 尝试找到"thinking"字段
        rc_field = None
        for candidate in ["reasoning_content", "thinking"]:
            if candidate in step:
                rc_field = candidate
                break
        rc_size = ""
        if rc_field:
            rc_val = step.get(rc_field, "")
            if isinstance(rc_val, str):
                rc_size = f"reasoning={len(rc_val)}c"

        # 尝试找到"tool_calls"字段
        tc_field = None
        for candidate in ["tool_calls", "tools"]:
            if candidate in step:
                tc_field = candidate
                break
        tc_info = ""
        if tc_field:
            tc_val = step.get(tc_field, [])
            if isinstance(tc_val, list) and len(tc_val) > 0:
                # 尝试获取函数名
                fn_names = []
                for tc_item in tc_val:
                    if isinstance(tc_item, dict):
                        fn = tc_item.get("function_name") or tc_item.get("name") or tc_item.get("function", {}).get("name", "?") if isinstance(tc_item.get("function"), dict) else tc_item.get("function_name", "?")
                        fn_names.append(str(fn))
                tc_info = f"tool={','.join(fn_names)}"
            else:
                tc_info = f"tool=无"

        # 尝试找到"observation"字段
        obs_field = None
        for candidate in ["observation", "tool_results", "results"]:
            if candidate in step:
                obs_field = candidate
                break
        obs_info = ""
        if obs_field:
            obs_val = step.get(obs_field, {})
            if isinstance(obs_val, dict):
                results = obs_val.get("results", [])
                if isinstance(results, list):
                    total_obs = sum(len(r.get("content", "") or "") for r in results if isinstance(r, dict))
                    obs_info = f"obs={total_obs}c"
            elif isinstance(obs_val, list):
                total_obs = sum(len(r.get("content", "") or "") for r in obs_val if isinstance(r, dict))
                obs_info = f"obs={total_obs}c"

        # 组装概要行
        parts = [f"steps[{i}]", f"source={source}", f"[{size}]"]
        if msg_size:
            parts.append(msg_size)
        if rc_size:
            parts.append(rc_size)
        if tc_info:
            parts.append(tc_info)
        if obs_info:
            parts.append(obs_info)

        line = "  " + "  ".join(parts)
        if msg_preview and len(msg_preview) < 80:
            line += f"  ← {msg_preview}"
        lines.append(line)

    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# === 第三层：每个agent step的详情 ===

def generate_step_detail(step, index):
    """生成单个step的详情。"""
    lines = []

    if not isinstance(step, dict):
        lines.append(f"### steps[{index}]  [{type(step).__name__}]")
        lines.append("")
        lines.append(f"值: {format_value_preview(step, 200)}")
        lines.append("")
        return "\n".join(lines)

    source = step.get("source", "unknown")
    lines.append(f"### steps[{index}] (source={source}) 详情")
    lines.append("")

    # 递归遍历step的所有字段
    lines.append("```")
    walk_step(lines, step, f"steps[{index}]", depth=0, max_depth=6)
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def walk_step(lines, obj, path, depth=0, max_depth=6):
    """递归遍历step的内部结构，生成面包屑。"""
    if depth > max_depth:
        return

    indent = "  " * depth

    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}.{k}"
            vtype = type(v).__name__
            size = format_size(v)
            hint = get_semantic_hint(k)
            hint_str = f"  ← {hint}" if hint else ""

            if v is None:
                lines.append(f"{indent}{child_path}  [null]{hint_str}")
            elif isinstance(v, bool):
                lines.append(f"{indent}{child_path}  [bool, {size}]  {v}{hint_str}")
            elif isinstance(v, (int, float)):
                lines.append(f"{indent}{child_path}  [{vtype}, {size}]  {v}{hint_str}")
            elif isinstance(v, str):
                size_class = classify_size(v, len(v))
                if size_class == "小":
                    lines.append(f"{indent}{child_path}  [str, {size}]  {format_value_preview(v, 200)}{hint_str}")
                elif size_class == "中":
                    lines.append(f"{indent}{child_path}  [str, {size}] (中字段)  预览: {format_value_preview(v, 200)}{hint_str}")
                elif size_class == "大":
                    lines.append(f"{indent}{child_path}  [str, {size}] (大字段，需read)  预览: {format_value_preview(v, 100)}{hint_str}")
                else:
                    lines.append(f"{indent}{child_path}  [str, {size}] (超大字段，需read)  预览: {format_value_preview(v, 100)}{hint_str}")
            elif isinstance(v, list):
                lines.append(f"{indent}{child_path}  [list, {len(v)} elements]{hint_str}")
                # 遍历list的所有元素
                for i, item in enumerate(v):
                    walk_step(lines, item, f"{child_path}[{i}]", depth + 1, max_depth)
            elif isinstance(v, dict):
                lines.append(f"{indent}{child_path}  [dict, {len(v)} keys]{hint_str}")
                walk_step(lines, v, child_path, depth + 1, max_depth)

    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            walk_step(lines, item, f"{path}[{i}]", depth, max_depth)

    elif obj is None:
        lines.append(f"{indent}{path}  [null]")
    elif isinstance(obj, (int, float, bool, str)):
        lines.append(f"{indent}{path}  [{type(obj).__name__}, {format_size(obj)}]  {format_value_preview(obj, 200)}")


# === 主函数 ===

def generate_map(json_path, output_path=None, to_stdout=False):
    """生成面包屑地图。"""
    with open(json_path) as f:
        data = json.load(f)

    sections = []

    # 第一层：顶层概览
    sections.append(generate_top_level(data))

    # 第二层：steps数组概要
    sections.append(generate_steps_overview(data))

    # 第三层：每个step的详情（展开所有step，不遗漏任何节点）
    steps = data.get("steps") if isinstance(data, dict) else None
    if isinstance(steps, list):
        sections.append("## 第三层：所有step详情")
        sections.append("")
        sections.append("> 以下展开所有step（system/user/agent），确保不遗漏任何节点")
        sections.append("")
        for i, step in enumerate(steps):
            if isinstance(step, dict):
                sections.append(generate_step_detail(step, i))

    # 统计摘要
    sections.append("## 统计摘要")
    sections.append("")
    if isinstance(steps, list):
        agent_steps = [s for s in steps if isinstance(s, dict) and s.get("source") == "agent"]
        system_steps = [s for s in steps if isinstance(s, dict) and s.get("source") == "system"]
        user_steps = [s for s in steps if isinstance(s, dict) and s.get("source") == "user"]
        sections.append(f"- 总step数: {len(steps)}")
        sections.append(f"- system step: {len(system_steps)}")
        sections.append(f"- user step: {len(user_steps)}")
        sections.append(f"- agent step: {len(agent_steps)}")
        sections.append("")

        # agent step的工具调用统计
        tool_count = 0
        obs_count = 0
        for s in agent_steps:
            tc = s.get("tool_calls", []) or []
            if tc:
                tool_count += len(tc)
            if "observation" in s:
                obs_count += 1
        sections.append(f"- agent step中有tool_calls的: {sum(1 for s in agent_steps if s.get('tool_calls'))}")
        sections.append(f"- agent step中有observation的: {obs_count}")
        sections.append(f"- 总tool_call数: {tool_count}")

        # 截断检测
        truncated_steps = []
        for i, s in enumerate(agent_steps):
            rc = s.get("reasoning_content", "") or ""
            msg = s.get("message", "") or ""
            tc = s.get("tool_calls", []) or []
            comp = (s.get("metrics", {}) or {}).get("completion_tokens", 0)
            if len(rc) > 1000 and len(msg) == 0 and len(tc) == 0 and comp >= 24000:
                is_last = (i == len(agent_steps) - 1)
                truncated_steps.append((i, is_last))

        sections.append(f"- 截断step数: {len(truncated_steps)}")
        for idx, is_last in truncated_steps:
            pos = "最后" if is_last else "中间"
            sections.append(f"  - agent step {idx} ({pos}step被截断)")

    map_text = "\n".join(sections)

    if to_stdout:
        print(map_text)
    elif output_path:
        with open(output_path, "w") as f:
            f.write(map_text)
        print(f"地图已写入: {output_path}")
    else:
        # 默认输出到conversation.json同目录
        default_path = Path(json_path).parent / "conversation_map.md"
        with open(default_path, "w") as f:
            f.write(map_text)
        print(f"地图已写入: {default_path}")

    return map_text


def main():
    parser = argparse.ArgumentParser(
        description="conversation.json面包屑地图生成器（不假设schema）"
    )
    parser.add_argument("json_path", help="conversation.json文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出路径（默认同目录conversation_map.md）")
    parser.add_argument("--stdout", action="store_true", help="输出到stdout")
    parser.add_argument("--agent-only", action="store_true", help="只展开agent step的详情")

    args = parser.parse_args()

    if not os.path.exists(args.json_path):
        print(f"错误：文件不存在: {args.json_path}")
        sys.exit(1)

    generate_map(args.json_path, output_path=args.output, to_stdout=args.stdout)


if __name__ == "__main__":
    main()
