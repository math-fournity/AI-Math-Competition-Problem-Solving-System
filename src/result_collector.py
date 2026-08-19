"""result_collector.py — 结果收集组件

从devin cli的export（conversation.json）或tmux pane中提取XML分析结果。

数据源优先级：
  1. exports/conversation.json — devin cli --export导出，最可靠
  2. tmux/tmux_pipe.log — tmux pipe-pane输出，兜底
  3. tmux capture-pane — 实时pane内容，最后兜底

XML提取方法：
  在文本中搜索 <analysis>...</analysis> 块，用xml.etree.ElementTree解析

用法：
  python -m src.result_collector --batch-id analysis-1
"""

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import (
    ANALYSIS_TRAJECTORY_BASE, OUTPUT_BASE,
    ANALYSIS_COMPLETE_MARKER, XML_BLOCK_START, XML_BLOCK_END,
)
from src.db_schema import connect_db, ensure_schema, insert_result, update_run, update_batch, ANALYSIS_RUNS_COLLECTION
from monitoring.shared_logger import get_logger

logger = get_logger("result_collector")


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def extract_xml_block(text):
    """从文本中提取<analysis>...</analysis> XML块

    Args:
        text: 包含XML的文本

    Returns:
        XML字符串，或None
    """
    # 去掉ANSI转义码（tmux_pipe.log中可能有）
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    text = re.sub(r'\x1b\][^\x07]*\x07', '', text)

    # 方法1：搜索```xml ... ```代码块中的<analysis>
    # 取最后一个匹配——agent可能先输出模板格式再输出实际内容
    pattern1 = r"```xml\s*(<analysis>.*?</analysis>)\s*```"
    matches1 = re.findall(pattern1, text, re.DOTALL)
    if matches1:
        # 取最后一个非模板的匹配
        for m in reversed(matches1):
            # 跳过模板原文（含"1-3 sentences"等占位符）
            if "1-3 sentences" not in m and "ONE_OF:" not in m:
                return m
        # 如果都是模板，取最后一个
        return matches1[-1]

    # 方法2：直接搜索<analysis>...</analysis>
    # 取最后一个匹配（正确的分析通常在最后）
    pattern2 = r"(<analysis>.*?</analysis>)"
    matches2 = re.findall(pattern2, text, re.DOTALL)
    if matches2:
        for m in reversed(matches2):
            if "1-3 sentences" not in m and "ONE_OF:" not in m:
                return m
        return matches2[-1]

    return None


def parse_xml(xml_string):
    """解析XML，返回dict

    Args:
        xml_string: XML字符串

    Returns:
        dict with keys: problem_id, dimension1_verdict, dimension1_explanation,
                        dimension2_turning_point_type, dimension2_explanation,
                        ai_direction_summary, standard_solution_key_technique, confidence
    """
    # 先尝试标准XML解析
    try:
        root = ET.fromstring(xml_string)
        result = {}
        for child in root:
            result[child.tag] = child.text.strip() if child.text else ""
        return result
    except ET.ParseError:
        pass

    # 标准解析失败——用正则逐字段提取（处理数学公式中的<>/嵌套问题）
    result = {}
    target_tags = [
        "problem_id", "dimension1_verdict", "dimension1_explanation",
        "dimension2_turning_point_type", "dimension2_explanation",
        "ai_direction_summary", "standard_solution_key_technique", "confidence",
    ]
    # 模板占位符——这些是模板中的描述文字，不是实际分析内容
    template_placeholders = {
        "1-3 sentences explaining the verdict",
        "1-3 sentences describing the key turning point in the standard solution",
        "1 sentence describing what direction the AI's thinking went",
        "1 sentence describing the key technique in the standard solution",
    }

    for tag in target_tags:
        # 方法1：匹配 <tag>...</tag>（非贪婪，正确闭合）
        pattern = rf"<{tag}>(.*?)</{tag}>"
        matches = re.findall(pattern, xml_string, re.DOTALL)
        for m in matches:
            val = m.strip()
            # 跳过模板占位符
            if val.lower() in {p.lower() for p in template_placeholders}:
                continue
            # 跳过ONE_OF格式的模板值
            if val.startswith("ONE_OF:") or val.startswith("DIRECTION_ERROR|"):
                continue
            # 清除混入的XML标签（标签闭合错误时，内容可能包含</dimension...>和后续标签）
            if "</" in val:
                # 截断到第一个错误闭合标签之前
                val = re.split(r"</\w+>", val)[0].strip()
            result[tag] = val
            break

        # 方法2：如果方法1没匹配到，尝试处理标签闭合错误
        # 如 <dimension2_explanation>内容</dimension2_turning_point_type>
        if tag not in result:
            # 匹配 <tag>内容</任意tag>——取下一个标签闭合
            pattern2 = rf"<{tag}>(.*?)</\w+>"
            m2 = re.search(pattern2, xml_string, re.DOTALL)
            if m2:
                val = m2.group(1).strip()
                if val and val.lower() not in {p.lower() for p in template_placeholders}:
                    if not val.startswith("ONE_OF:") and not val.startswith("DIRECTION_ERROR|"):
                        result[tag] = val

    if result:
        return result

    # 都失败了——返回原始XML
    return {"_parse_error": "regex_extraction_failed", "_raw_xml": xml_string[:500]}


def get_export_text(analysis_exp_id):
    """从conversation.json获取devin cli的输出文本
    
    Args:
        analysis_exp_id: 分析实验ID
    
    Returns:
        文本字符串，或None
    """
    traj_dir = ANALYSIS_TRAJECTORY_BASE / analysis_exp_id
    export_path = traj_dir / "exports" / "conversation.json"

    if export_path.exists():
        with open(str(export_path)) as f:
            conv = json.load(f)
        parts = []
        if isinstance(conv, dict):
            steps = conv.get("steps", [])
            for step in steps:
                if not isinstance(step, dict):
                    continue
                if step.get("source") == "agent":
                    msg = step.get("message", "")
                    if isinstance(msg, str) and msg.strip():
                        parts.append(msg)
                rc = step.get("reasoning_content", "")
                if isinstance(rc, str) and rc.strip():
                    parts.append(rc)
        if parts:
            return "\n".join(parts)

    # 兜底1：tmux_pipe.log（去掉ANSI转义码）
    pipe_path = traj_dir / "tmux" / "tmux_pipe.log"
    if pipe_path.exists() and pipe_path.stat().st_size > 100:
        raw = pipe_path.read_text(encoding="utf-8", errors="replace")
        # 去掉ANSI转义码
        import re
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw)
        clean = re.sub(r'\x1b\][^\x07]*\x07', '', clean)
        return clean

    return None


def get_pane_text(analysis_exp_id):
    """从tmux capture-pane获取文本（兜底）"""
    session_name = f"an-{analysis_exp_id[:48]}"
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-1000"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout
    except Exception:
        return ""


def collect_one(analysis_exp_id, problem_id, batch_id):
    """收集一道题的分析结果
    
    Args:
        analysis_exp_id: 分析实验ID
        problem_id: 题目ID
        batch_id: 批次ID
    
    Returns:
        dict with analysis result, or None
    """
    # 优先级1：export
    text = get_export_text(analysis_exp_id)

    # 优先级2：tmux pane（兜底）
    if not text or ANALYSIS_COMPLETE_MARKER not in text:
        pane_text = get_pane_text(analysis_exp_id)
        if pane_text and (ANALYSIS_COMPLETE_MARKER in pane_text or XML_BLOCK_START in pane_text):
            text = pane_text

    if not text:
        return {"problem_id": problem_id, "status": "no_output", "batch_id": batch_id}

    # 检查完成标记
    has_complete = ANALYSIS_COMPLETE_MARKER in text

    # 提取XML
    xml_block = extract_xml_block(text)
    if not xml_block:
        return {
            "problem_id": problem_id,
            "status": "no_xml" if has_complete else "incomplete",
            "batch_id": batch_id,
            "text_sample": text[-500:] if text else "",
        }

    # 解析XML
    parsed = parse_xml(xml_block)
    parsed["problem_id"] = problem_id
    parsed["batch_id"] = batch_id
    parsed["analysis_exp_id"] = analysis_exp_id
    parsed["status"] = "parsed"
    parsed["has_complete_marker"] = has_complete

    return parsed


def collect_batch(batch_id):
    """收集一个批次的所有分析结果

    数据源优先级：
    1. 从DB取status=completed的run（新架构，推荐）
    2. 从launch_results.json取completed列表（旧架构，兼容）
    """
    logger.info(f"结果收集开始 batch={batch_id}")
    print(f"=== 收集结果 batch={batch_id} ===")

    db = connect_db()
    ensure_schema(db)

    # 优先从DB取completed的run
    aql = (
        f"FOR run IN {ANALYSIS_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status IN ['completed', 'results_collected'] "
        f"RETURN {{_key: run._key, problem_id: run.problem_id, analysis_exp_id: run.analysis_exp_id}}"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=120)
    completed = list(cursor)

    if not completed:
        # 兼容旧架构：从launch_results.json取
        results_path = OUTPUT_BASE / batch_id / "launch_results.json"
        if not results_path.exists():
            print(f"ERROR: DB中无completed的run，且launch_results.json不存在")
            print(f"请先运行 analysis_control start --batch-id {batch_id}")
            return
        with open(str(results_path)) as f:
            launch_results = json.load(f)
        completed = launch_results["completed"]

    print(f"  待收集: {len(completed)}")

    all_results = []
    parsed_count = 0
    no_xml_count = 0
    no_output_count = 0
    incomplete_count = 0

    for i, item in enumerate(completed):
        pid = item["problem_id"]
        analysis_exp_id = item["analysis_exp_id"]
        run_key = item.get("_key", item.get("run_key", ""))

        if (i + 1) % 50 == 0:
            print(f"  进度: {i+1}/{len(completed)}")

        result = collect_one(analysis_exp_id, pid, batch_id)
        # 补充run_key到result中
        if run_key:
            result["run_key"] = run_key
        all_results.append(result)

        status = result.get("status", "unknown")
        if status == "parsed":
            parsed_count += 1
            # 写入DB
            try:
                insert_result(db, result)
                # 同时更新run状态为results_collected
                if run_key:
                    update_run(db, run_key, {
                        "status": "results_collected",
                        "updated_at": _utc_now(),
                    })
            except Exception:
                pass
        elif status == "no_xml":
            no_xml_count += 1
            if run_key:
                try:
                    update_run(db, run_key, {
                        "status": "no_xml",
                        "updated_at": _utc_now(),
                        "end_reason": "no_xml_in_output",
                    })
                except Exception:
                    pass
        elif status == "no_output":
            no_output_count += 1
            if run_key:
                try:
                    update_run(db, run_key, {
                        "status": "no_output",
                        "updated_at": _utc_now(),
                        "end_reason": "no_tmux_pipe_log",
                    })
                except Exception:
                    pass
        elif status == "incomplete":
            incomplete_count += 1
            if run_key:
                try:
                    update_run(db, run_key, {
                        "status": "incomplete",
                        "updated_at": _utc_now(),
                        "end_reason": "analysis_incomplete",
                    })
                except Exception:
                    pass

    print(f"\n  收集完成:")
    print(f"    parsed: {parsed_count}")
    print(f"    no_xml: {no_xml_count}")
    print(f"    no_output: {no_output_count}")
    print(f"    incomplete: {incomplete_count}")
    logger.info(f"结果收集完成 batch={batch_id}: parsed={parsed_count}, no_xml={no_xml_count}, no_output={no_output_count}, incomplete={incomplete_count}")

    # 更新batch记录
    update_batch(db, batch_id, {
        "status": "results_collected",
        "updated_at": _utc_now(),
        "parsed_count": parsed_count,
        "no_xml_count": no_xml_count,
        "no_output_count": no_output_count,
        "incomplete_count": incomplete_count,
    })

    # 保存结果
    output_path = OUTPUT_BASE / batch_id / "collected_results.json"
    with open(str(output_path), "w") as f:
        json.dump({
            "total": len(all_results),
            "parsed": parsed_count,
            "no_xml": no_xml_count,
            "no_output": no_output_count,
            "incomplete": incomplete_count,
            "results": all_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"  结果保存到: {output_path}")

    return all_results


def main():
    parser = argparse.ArgumentParser(description="收集分析结果")
    parser.add_argument("--batch-id", required=True, help="批次ID")
    args = parser.parse_args()

    collect_batch(args.batch_id)


if __name__ == "__main__":
    main()
