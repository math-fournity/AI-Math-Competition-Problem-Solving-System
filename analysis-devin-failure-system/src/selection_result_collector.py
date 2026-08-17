"""selection_result_collector.py — Pipe 3选题结果收集组件

从tmux pane/exports提取selection XML，解析选题字段，写入selection_results集合。

复用audit_result_collector.py的XML解析逻辑，但：
  - 提取<selection>...</selection>块（不是<audit>...</audit>）
  - 解析selection字段（problem_id/suitable/batch/d2_reclassified/selection_reason）
  - 写入selection_results集合

用法：
  python -m src.selection_result_collector --batch-id selection-1
"""

import argparse
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import ANALYSIS_TRAJECTORY_BASE, OUTPUT_BASE
from src.db_schema import connect_db, ensure_schema
from src.selection_collector import (
    SELECTION_RUNS_COLLECTION, SELECTION_RESULTS_COLLECTION, SELECTION_BATCHES_COLLECTION,
)
from monitoring.shared_logger import get_logger

logger = get_logger("selection_result_collector")

SELECTION_COMPLETE_MARKER = "### SELECTION COMPLETE"
SELECTION_XML_START = "<selection>"
SELECTION_XML_END = "</selection>"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_selection_output(selection_exp_id):
    """从tmux pane或exports中获取选题AI的输出文本"""
    traj_dir = ANALYSIS_TRAJECTORY_BASE / selection_exp_id

    # 1. 尝试从conversation.json提取
    export_path = traj_dir / "exports" / "conversation.json"
    if export_path.exists():
        try:
            import json
            with open(str(export_path)) as f:
                conv = json.load(f)
            # conversation.json格式：提取最后一条assistant消息
            if isinstance(conv, list):
                for msg in reversed(conv):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        content = msg["content"]
                        if isinstance(content, list):
                            for block in content:
                                if block.get("type") == "text" and block.get("text"):
                                    return block["text"]
                        elif isinstance(content, str):
                            return content
            elif isinstance(conv, dict):
                messages = conv.get("messages", conv.get("transcript", []))
                for msg in reversed(messages):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        return msg["content"] if isinstance(msg["content"], str) else str(msg["content"])
        except Exception as e:
            logger.warning(f"读取conversation.json失败: {e}")

    # 2. 尝试从tmux pipe.log提取
    pipe_log = traj_dir / "tmux" / "tmux_pipe.log"
    if pipe_log.exists():
        return pipe_log.read_text(encoding="utf-8", errors="replace")

    # 3. 尝试从tmux.log提取
    tmux_log = traj_dir / "tmux" / "tmux.log"
    if tmux_log.exists():
        return tmux_log.read_text(encoding="utf-8", errors="replace")

    return None


def extract_selection_xml(text):
    """从文本中提取<selection>...</selection>块"""
    if not text:
        return None

    # 先尝试标准XML解析
    pattern = r"```xml\s*(<selection>.*?</selection>)\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1)

    # 尝试不带code block的
    pattern2 = r"(<selection>.*?</selection>)"
    match2 = re.search(pattern2, text, re.DOTALL)
    if match2:
        return match2.group(1)

    # 尝试从<selection>到结尾
    if SELECTION_XML_START in text:
        start = text.index(SELECTION_XML_START)
        # 找</selection>或### SELECTION COMPLETE
        end1 = text.find(SELECTION_XML_END, start)
        end2 = text.find(SELECTION_COMPLETE_MARKER, start)
        if end1 >= 0:
            return text[start:end1 + len(SELECTION_XML_END)]
        elif end2 >= 0:
            return text[start:end2].strip()
        else:
            return text[start:].strip()

    return None


def parse_selection_xml(xml_block):
    """解析selection XML，返回dict

    Returns:
        dict with keys: problem_id, suitable, batch, d2_reclassified, selection_reason
    """
    if not xml_block:
        return {}

    result = {}
    target_tags = ["problem_id", "suitable", "batch", "d2_reclassified", "selection_reason"]

    for tag in target_tags:
        pattern = rf"<{tag}>(.*?)</{tag}>"
        match = re.search(pattern, xml_block, re.DOTALL)
        if match:
            result[tag] = match.group(1).strip()
        else:
            result[tag] = None

    return result


def collect_batch_results(batch_id):
    """收集选题批次的所有结果"""
    logger.info(f"选题结果收集开始 batch={batch_id}")
    print(f"=== 选题结果收集 batch={batch_id} ===")

    db = connect_db()
    ensure_schema(db)

    if not db.has_collection(SELECTION_RESULTS_COLLECTION):
        db.create_collection(SELECTION_RESULTS_COLLECTION)

    # 获取所有completed的selection_run
    aql = (
        f"FOR run IN {SELECTION_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'completed' "
        f"RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=120)
    runs = list(cursor)
    print(f"  找到{len(runs)}个completed的selection_run")

    collected = 0
    failed_parse = 0
    no_output = 0
    status_counts = Counter()

    for i, run in enumerate(runs):
        run_key = run["_key"]
        selection_exp_id = run.get("selection_exp_id", run_key)
        problem_id = run.get("problem_id", "")
        source_result_key = run.get("source_result_key", "")
        audit_result_key = run.get("audit_result_key", "")

        if (i + 1) % 100 == 0:
            print(f"    进度: {i+1}/{len(runs)}")
            logger.info(f"进度: {i+1}/{len(runs)}")

        # 获取输出
        output = get_selection_output(selection_exp_id)
        if not output:
            no_output += 1
            logger.warning(f"无输出: {selection_exp_id}")
            try:
                db.collection(SELECTION_RESULTS_COLLECTION).insert({
                    "_key": f"selection_result_{run_key}",
                    "selection_run_key": run_key,
                    "problem_id": problem_id,
                    "source_result_key": source_result_key,
                    "batch_id": batch_id,
                    "suitable": "UNKNOWN",
                    "batch": "N/A",
                    "selection_reason": "no output from selection AI",
                    "collected_at": _utc_now(),
                })
            except Exception:
                pass
            continue

        # 提取selection XML
        xml_block = extract_selection_xml(output)
        if not xml_block:
            failed_parse += 1
            logger.warning(f"XML提取失败: {selection_exp_id}")
            try:
                db.collection(SELECTION_RESULTS_COLLECTION).insert({
                    "_key": f"selection_result_{run_key}",
                    "selection_run_key": run_key,
                    "problem_id": problem_id,
                    "source_result_key": source_result_key,
                    "batch_id": batch_id,
                    "suitable": "PARSE_FAILED",
                    "batch": "N/A",
                    "selection_reason": "XML extraction failed",
                    "collected_at": _utc_now(),
                })
            except Exception:
                pass
            continue

        # 解析XML
        parsed = parse_selection_xml(xml_block)
        suitable = parsed.get("suitable", "UNKNOWN")
        status_counts[suitable] += 1

        # 写入selection_results集合
        result_doc = {
            "_key": f"selection_result_{run_key}",
            "selection_run_key": run_key,
            "problem_id": parsed.get("problem_id", problem_id),
            "source_result_key": source_result_key,
            "audit_result_key": audit_result_key,
            "batch_id": batch_id,
            "suitable": suitable,
            "batch": parsed.get("batch", "N/A"),
            "d2_reclassified": parsed.get("d2_reclassified", "unchanged"),
            "selection_reason": parsed.get("selection_reason", ""),
            "collected_at": _utc_now(),
        }
        try:
            db.collection(SELECTION_RESULTS_COLLECTION).insert(result_doc)
            collected += 1
        except Exception as e:
            try:
                update_data = {k: v for k, v in result_doc.items() if k != "_key"}
                update_data["_key"] = result_doc["_key"]
                db.collection(SELECTION_RESULTS_COLLECTION).update(update_data)
                collected += 1
            except Exception as e2:
                logger.error(f"写入selection_results失败: {e2}")

    print(f"\n  收集完成:")
    print(f"    collected: {collected}")
    print(f"    failed_parse: {failed_parse}")
    print(f"    no_output: {no_output}")
    print(f"    suitable分布:")
    for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"      {s}: {c}")
    logger.info(f"收集完成: collected={collected}, failed_parse={failed_parse}, no_output={no_output}")

    # 保存摘要
    try:
        db.collection(SELECTION_BATCHES_COLLECTION).update({
            "_key": batch_id, "status": "collected",
            "updated_at": _utc_now(),
            "collected_count": collected,
            "failed_parse_count": failed_parse,
            "no_output_count": no_output,
            "suitable_counts": dict(status_counts),
        })
    except Exception:
        pass

    results_path = OUTPUT_BASE / batch_id / "selection_results_summary.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    import json
    with open(str(results_path), "w") as f:
        json.dump({
            "collected": collected,
            "failed_parse": failed_parse,
            "no_output": no_output,
            "suitable_counts": dict(status_counts),
        }, f, ensure_ascii=False, indent=2)
    print(f"  结果保存到: {results_path}")


def main():
    parser = argparse.ArgumentParser(description="Pipe 3选题结果收集")
    parser.add_argument("--batch-id", required=True, help="选题批次ID")
    args = parser.parse_args()

    collect_batch_results(args.batch_id)


if __name__ == "__main__":
    main()
