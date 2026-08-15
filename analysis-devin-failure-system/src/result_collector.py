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
from src.db_schema import connect_db, ensure_schema, insert_result, update_run, update_batch
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
    pattern1 = r"```xml\s*(<analysis>.*?</analysis>)\s*```"
    m = re.search(pattern1, text, re.DOTALL)
    if m:
        return m.group(1)

    # 方法2：直接搜索<analysis>...</analysis>（贪婪匹配最外层）
    # 用嵌套深度计数来匹配最外层的</analysis>
    start_idx = text.find("<analysis>")
    if start_idx < 0:
        return None
    # 找匹配的</analysis>——从start_idx开始，计数嵌套深度
    depth = 0
    pos = start_idx
    while pos < len(text):
        open_idx = text.find("<analysis>", pos)
        close_idx = text.find("</analysis>", pos)
        if close_idx < 0:
            break
        if open_idx >= 0 and open_idx < close_idx:
            depth += 1
            pos = open_idx + len("<analysis>")
        else:
            depth -= 1
            pos = close_idx + len("</analysis>")
            if depth == 0:
                return text[start_idx:pos]
    # 兜底：用非贪婪正则
    pattern2 = r"(<analysis>.*?</analysis>)"
    m = re.search(pattern2, text, re.DOTALL)
    if m:
        return m.group(1)

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
    for tag in target_tags:
        # 匹配 <tag>...</tag>（非贪婪）
        pattern = rf"<{tag}>(.*?)</{tag}>"
        m = re.search(pattern, xml_string, re.DOTALL)
        if m:
            result[tag] = m.group(1).strip()
    
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
    """收集一个批次的所有分析结果"""
    logger.info(f"结果收集开始 batch={batch_id}")
    print(f"=== 收集结果 batch={batch_id} ===")

    # 加载launch_results
    results_path = OUTPUT_BASE / batch_id / "launch_results.json"
    if not results_path.exists():
        print(f"ERROR: launch_results.json not found at {results_path}")
        print("请先运行 analysis_launcher")
        return

    with open(str(results_path)) as f:
        launch_results = json.load(f)

    completed = launch_results["completed"]
    print(f"  待收集: {len(completed)}")

    db = connect_db()
    ensure_schema(db)

    all_results = []
    parsed_count = 0
    no_xml_count = 0
    no_output_count = 0
    incomplete_count = 0

    for i, item in enumerate(completed):
        pid = item["problem_id"]
        analysis_exp_id = item["analysis_exp_id"]
        run_key = item.get("run_key", "")

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
