"""audit_result_collector.py — Pipe 2审计结果收集组件

从tmux pane/exports/conversation.json中提取审计XML，解析为结构化数据。

复用result_collector.py的XML解析逻辑，但：
  - 提取<audit>...</audit>块（不是<analysis>...</analysis>）
  - 解析audit字段（audit_status/check_results/issues_found）
  - 写入audit_results集合

用法：
  python -m src.audit_result_collector --batch-id audit-1
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import ANALYSIS_TRAJECTORY_BASE, OUTPUT_BASE
from src.db_schema import connect_db, ensure_schema
from src.audit_collector import AUDIT_BATCHES_COLLECTION, AUDIT_RUNS_COLLECTION, AUDIT_RESULTS_COLLECTION
from monitoring.shared_logger import get_logger

logger = get_logger("audit_result_collector")


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def extract_audit_xml_block(text):
    """从文本中提取<audit>...</audit> XML块

    复用result_collector.extract_xml_block的逻辑，但针对<audit>标签。
    """
    # 去掉ANSI转义码
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    text = re.sub(r'\x1b\][^\x07]*\x07', '', text)

    # 方法1：```xml ... ```代码块中的<audit>
    pattern1 = r"```xml\s*(<audit>.*?</audit>)\s*```"
    matches1 = re.findall(pattern1, text, re.DOTALL)
    if matches1:
        for m in reversed(matches1):
            if "ONE_OF:" not in m and "PASS or FAIL" not in m:
                return m
        return matches1[-1]

    # 方法2：直接搜索<audit>...</audit>
    pattern2 = r"(<audit>.*?</audit>)"
    matches2 = re.findall(pattern2, text, re.DOTALL)
    if matches2:
        for m in reversed(matches2):
            if "ONE_OF:" not in m and "PASS or FAIL" not in m:
                return m
        return matches2[-1]

    return None


def parse_audit_xml(xml_string):
    """解析审计XML，返回dict

    Returns:
        dict with keys: analysis_result_key, problem_id, audit_status,
                        check_results (dict), issues_found
    """
    # 先尝试标准XML解析
    try:
        root = ET.fromstring(xml_string)
        result = {}
        for child in root:
            if child.tag == "check_results":
                # check_results是嵌套结构
                checks = {}
                for check_child in child:
                    checks[check_child.tag] = (check_child.text or "").strip()
                result["check_results"] = checks
            else:
                result[child.tag] = (child.text or "").strip() if child.text else ""
        return result
    except ET.ParseError:
        pass

    # 标准解析失败——用正则逐字段提取
    result = {}
    target_tags = ["analysis_result_key", "problem_id", "audit_status", "issues_found"]

    for tag in target_tags:
        pattern = rf"<{tag}>(.*?)</{tag}>"
        matches = re.findall(pattern, xml_string, re.DOTALL)
        for m in matches:
            val = m.strip()
            if val.startswith("ONE_OF:"):
                continue
            if "</" in val:
                val = re.split(r"</\w+>", val)[0].strip()
            result[tag] = val
            break

    # 提取check_results中的各检查项
    check_results = {}
    check_tags = ["A1", "A2", "A3", "A4", "A5", "A6",
                  "B1", "B2", "B3", "C1", "C2", "C3",
                  "D1", "D2", "D3", "D4", "E1"]
    for tag in check_tags:
        pattern = rf"<{tag}>(.*?)</{tag}>"
        matches = re.findall(pattern, xml_string, re.DOTALL)
        for m in matches:
            val = m.strip()
            if "PASS or FAIL" in val:
                continue
            if "</" in val:
                val = re.split(r"</\w+>", val)[0].strip()
            check_results[tag] = val
            break

    result["check_results"] = check_results
    return result


def get_audit_output(audit_exp_id):
    """从trajectory目录获取审计AI的输出文本

    优先级：
    1. exports/conversation.json — 含完整agent message
    2. tmux/tmux_pipe.log — raw pane流
    3. tmux/tmux.log — tee输出
    """
    traj_dir = ANALYSIS_TRAJECTORY_BASE / audit_exp_id

    # 优先级1：conversation.json
    conv_path = traj_dir / "exports" / "conversation.json"
    if conv_path.exists():
        try:
            with open(str(conv_path)) as f:
                conv = json.load(f)
            if isinstance(conv, dict):
                steps = conv.get("steps", [])
                parts = []
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    if step.get("source") == "agent":
                        msg = step.get("message", "")
                        if isinstance(msg, str) and msg.strip():
                            parts.append(msg)
                if parts:
                    return "\n".join(parts)
        except Exception:
            pass

    # 优先级2：tmux_pipe.log
    pipe_path = traj_dir / "tmux" / "tmux_pipe.log"
    if pipe_path.exists() and pipe_path.stat().st_size > 50:
        return pipe_path.read_text(encoding="utf-8", errors="replace")

    # 优先级3：tmux.log
    log_path = traj_dir / "tmux" / "tmux.log"
    if log_path.exists() and log_path.stat().st_size > 50:
        return log_path.read_text(encoding="utf-8", errors="replace")

    return None


def collect_batch_results(batch_id):
    """收集一个审计批次的所有结果"""
    logger.info(f"审计结果收集开始 batch={batch_id}")
    print(f"=== 审计结果收集 batch={batch_id} ===")

    db = connect_db()
    ensure_schema(db)

    # 确保audit_results集合存在
    if not db.has_collection(AUDIT_RESULTS_COLLECTION):
        db.create_collection(AUDIT_RESULTS_COLLECTION)

    # 获取所有completed的audit_run
    aql = (
        f"FOR run IN {AUDIT_RUNS_COLLECTION} "
        f"FILTER run.batch_id == @bid "
        f"FILTER run.status == 'completed' "
        f"RETURN run"
    )
    cursor = db.aql.execute(aql, bind_vars={"bid": batch_id}, ttl=120)
    runs = list(cursor)
    print(f"  completed runs: {len(runs)}")

    collected = 0
    failed_parse = 0
    no_output = 0
    status_counts = Counter()

    for i, run in enumerate(runs):
        audit_exp_id = run.get("audit_exp_id", run.get("_key", ""))
        run_key = run.get("_key", "")
        problem_id = run.get("problem_id", "")
        source_result_key = run.get("source_result_key", "")

        if (i + 1) % 100 == 0:
            print(f"    进度: {i+1}/{len(runs)}")
            logger.info(f"进度: {i+1}/{len(runs)}")

        # 获取审计输出
        output = get_audit_output(audit_exp_id)
        if not output:
            no_output += 1
            logger.warning(f"无输出: {audit_exp_id}")
            continue

        # 提取XML
        xml_block = extract_audit_xml_block(output)
        if not xml_block:
            failed_parse += 1
            logger.warning(f"XML提取失败: {audit_exp_id}")
            # 记录parse失败
            try:
                db.collection(AUDIT_RESULTS_COLLECTION).insert({
                    "_key": f"audit_result_{run_key}",
                    "audit_run_key": run_key,
                    "problem_id": problem_id,
                    "source_result_key": source_result_key,
                    "batch_id": batch_id,
                    "audit_status": "PARSE_FAILED",
                    "check_results": {},
                    "issues_found": "XML extraction failed",
                    "collected_at": _utc_now(),
                })
            except Exception:
                pass
            continue

        # 解析XML
        parsed = parse_audit_xml(xml_block)
        audit_status = parsed.get("audit_status", "UNKNOWN")

        # 后处理：D1动词列表修正
        # 审计AI用的动词列表太窄（identified/missed/explored/used/went/attempted/tried/failed/overlooked/ignored）
        # 导致22%的DIRECTION_ERROR题被误判为PASS_NOT_SELECTABLE
        # 修正：如果audit_status=PASS_NOT_SELECTABLE且D1 FAIL，检查d1_exp是否含扩展动词
        # 如果含扩展动词，升级为PASS_SELECTABLE
        if audit_status == "PASS_NOT_SELECTABLE":
            checks = parsed.get("check_results", {})
            d1_check = checks.get("D1", "")
            if d1_check.startswith("FAIL"):
                # 获取源数据的d1和d1_exp
                src = db.collection("analysis_results").get(source_result_key)
                if src:
                    d1 = src.get("dimension1_verdict", "")
                    d1_exp = (src.get("dimension1_explanation") or "").lower()
                    if d1 in ("DIRECTION_ERROR", "PARTIAL_PROGRESS"):
                        extended_verbs = [
                            "solved", "addressed", "addresses", "computes", "computed",
                            "derives", "derived", "approached", "approach", "tackled",
                            "tackling", "pursued", "pursuing", "focused", "focuses",
                            "engaged", "engages", "worked", "works", "applied", "applies",
                            "chose", "chosen", "selected", "selects", "started", "starts",
                            "began", "begins", "proceeded", "proceeds", "misread", "misinterpreted",
                        ]
                        if any(v in d1_exp for v in extended_verbs):
                            audit_status = "PASS_SELECTABLE"
                            parsed["issues_found"] = (parsed.get("issues_found", "") + 
                                " [post-processed: D1 upgraded to PASS_SELECTABLE due to extended verb list]")

        status_counts[audit_status] += 1

        # 写入audit_results集合
        result_doc = {
            "_key": f"audit_result_{run_key}",
            "audit_run_key": run_key,
            "problem_id": parsed.get("problem_id", problem_id),
            "source_result_key": parsed.get("analysis_result_key", source_result_key),
            "batch_id": batch_id,
            "audit_status": audit_status,
            "check_results": parsed.get("check_results", {}),
            "issues_found": parsed.get("issues_found", ""),
            "collected_at": _utc_now(),
        }
        try:
            db.collection(AUDIT_RESULTS_COLLECTION).insert(result_doc)
            collected += 1
        except Exception as e:
            # 已存在——更新
            try:
                update_data = {k: v for k, v in result_doc.items() if k != "_key"}
                update_data["_key"] = result_doc["_key"]
                db.collection(AUDIT_RESULTS_COLLECTION).update(update_data)
                collected += 1
            except Exception as e2:
                logger.error(f"写入audit_results失败: {e2}")

    print(f"\n  收集完成:")
    print(f"    collected: {collected}")
    print(f"    failed_parse: {failed_parse}")
    print(f"    no_output: {no_output}")
    print(f"    status分布:")
    for status, count in status_counts.most_common():
        print(f"      {status}: {count}")
    logger.info(f"收集完成: collected={collected}, failed_parse={failed_parse}, no_output={no_output}")

    # 更新batch记录
    try:
        db.collection(AUDIT_BATCHES_COLLECTION).update({
            "_key": batch_id,
            "status": "results_collected",
            "updated_at": _utc_now(),
            "collected_count": collected,
            "failed_parse_count": failed_parse,
            "no_output_count": no_output,
            "audit_status_counts": dict(status_counts),
        })
    except Exception:
        pass

    # 保存结果到文件
    results_path = OUTPUT_BASE / batch_id / "audit_results_summary.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(results_path), "w") as f:
        json.dump({
            "batch_id": batch_id,
            "total_completed": len(runs),
            "collected": collected,
            "failed_parse": failed_parse,
            "no_output": no_output,
            "status_counts": dict(status_counts),
        }, f, ensure_ascii=False, indent=2)
    print(f"  结果保存到: {results_path}")

    return collected


def main():
    parser = argparse.ArgumentParser(description="Pipe 2审计结果收集")
    parser.add_argument("--batch-id", required=True, help="审计批次ID")
    args = parser.parse_args()

    collect_batch_results(args.batch_id)


if __name__ == "__main__":
    main()
