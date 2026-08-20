"""log_search.py — SOP 日志检索脚本

按结构化字段检索日志文件。日志格式：
  [2026-08-20 01:23:45] [INFO] [analysis.continuation_launcher]
  event=launch_solve problem_id=omni_math_001 round=2 session_key=p27-s0042

用法：
  # 按事件名检索
  python -m scripts.sop.log_search --event launch_solve

  # 按problem_id检索
  python -m scripts.sop.log_search --problem-id omni_math_001

  # 按session_key检索
  python -m scripts.sop.log_search --session-key p27-s0042

  # 按级别检索
  python -m scripts.sop.log_search --level ERROR

  # 按模块检索
  python -m scripts.sop.log_search --module continuation_launcher

  # 组合检索
  python -m scripts.sop.log_search --problem-id omni_math_001 --event mark_stuck

  # 时间范围
  python -m scripts.sop.log_search --since "2026-08-20 01:00" --until "2026-08-20 02:00"

  # 指定日志文件
  python -m scripts.sop.log_search --file log/continuation_launcher.log --event launch_solve

  # 最近N条
  python -m scripts.sop.log_search --event launch_solve --tail 20

  # 统计（不输出详情，只输出统计）
  python -m scripts.sop.log_search --event launch_solve --stats
"""

import argparse
import re
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
LOG_DIR = PROJECT_ROOT / "log"

# 日志行格式1（shared_logger）：
# [2026-08-20 01:23:45] [INFO] [analysis.module] event=xxx key=val ...
# 日志行格式2（sop_log）：
# 2026-08-20 01:23:45 [INFO] sop.module: message
LOG_LINE_RE_1 = re.compile(
    r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] '
    r'\[(\w+)\] '
    r'\[([\w.]+)\] '
    r'(.*)'
)
LOG_LINE_RE_2 = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) '
    r'\[(\w+)\] '
    r'([\w.]+): '
    r'(.*)'
)

# 结构化字段格式：event=xxx key1=val1 key2=val2
FIELD_RE = re.compile(r'(\w+)=(\S+)')


def parse_log_line(line):
    """解析一行日志，返回 (timestamp, level, module, message, fields_dict)

    兼容两种日志格式：
    - shared_logger: [时间] [级别] [模块] 消息
    - sop_log: 时间 [级别] 模块: 消息
    """
    line = line.strip()
    m = LOG_LINE_RE_1.match(line)  # shared_logger 格式
    if not m:
        m = LOG_LINE_RE_2.match(line)  # sop_log 格式
    if not m:
        return None
    ts_str, level, module, message = m.groups()
    fields = {}
    # 提取结构化字段
    for fm in FIELD_RE.finditer(message):
        fields[fm.group(1)] = fm.group(2)
    return {
        "timestamp": ts_str,
        "level": level,
        "module": module,
        "message": message,
        "fields": fields,
    }


def get_log_files(specific_file=None):
    """获取要搜索的日志文件列表"""
    if specific_file:
        p = Path(specific_file)
        if p.exists():
            return [p]
        # 尝试相对路径
        p = PROJECT_ROOT / specific_file
        if p.exists():
            return [p]
        print(f"⚠️ 文件不存在: {specific_file}")
        return []

    # 搜索所有 .log 文件（不搜索 .log.1 等轮转文件，除非指定）
    files = sorted(LOG_DIR.glob("*.log"), key=lambda f: f.name)
    return files


def search_logs(files, filters):
    """搜索日志文件，返回匹配的行列表"""
    results = []
    for log_file in files:
        try:
            with open(log_file, encoding="utf-8", errors="ignore") as f:
                for line_num, line in enumerate(f, 1):
                    parsed = parse_log_line(line)
                    if not parsed:
                        continue

                    # 应用过滤器
                    if not match_filters(parsed, filters):
                        continue

                    parsed["file"] = log_file.name
                    parsed["line_num"] = line_num
                    results.append(parsed)
        except Exception as e:
            print(f"⚠️ 读取 {log_file} 失败: {e}")
    return results


def match_filters(parsed, filters):
    """检查一行是否匹配所有过滤器"""
    # 级别过滤
    if filters.get("level"):
        if parsed["level"] != filters["level"].upper():
            return False

    # 模块过滤
    if filters.get("module"):
        if filters["module"] not in parsed["module"]:
            return False

    # 时间范围过滤
    if filters.get("since"):
        if parsed["timestamp"] < filters["since"]:
            return False
    if filters.get("until"):
        if parsed["timestamp"] > filters["until"]:
            return False

    # 结构化字段过滤
    fields = parsed["fields"]
    if filters.get("event"):
        if fields.get("event") != filters["event"]:
            return False
    if filters.get("problem_id"):
        if fields.get("problem_id") != filters["problem_id"]:
            return False
    if filters.get("session_key"):
        if fields.get("session_key") != filters["session_key"]:
            return False
    if filters.get("round"):
        if fields.get("round") != str(filters["round"]):
            return False

    return True


def print_results(results, show_stats=False, tail=None):
    """输出搜索结果"""
    if tail:
        results = results[-tail:]

    if show_stats:
        print(f"\n=== 统计 ===")
        print(f"  匹配行数: {len(results)}")
        if results:
            # 按event统计
            events = Counter(r["fields"].get("event", "(无event)") for r in results)
            print(f"\n  按事件统计:")
            for event, count in events.most_common():
                print(f"    {event}: {count}")

            # 按level统计
            levels = Counter(r["level"] for r in results)
            print(f"\n  按级别统计:")
            for level, count in levels.most_common():
                print(f"    {level}: {count}")

            # 按module统计
            modules = Counter(r["module"] for r in results)
            print(f"\n  按模块统计:")
            for module, count in modules.most_common():
                print(f"    {module}: {count}")

            # 时间范围
            timestamps = [r["timestamp"] for r in results]
            print(f"\n  时间范围: {timestamps[0]} ~ {timestamps[-1]}")
        return

    print(f"\n=== 搜索结果（{len(results)}条）===\n")
    for r in results:
        print(f"[{r['timestamp']}] [{r['level']}] [{r['module']}] {r['message']}")


def main():
    parser = argparse.ArgumentParser(description="SOP 日志检索")
    parser.add_argument("--file", help="指定日志文件（默认搜索log/下所有.log）")
    parser.add_argument("--event", help="按事件名过滤（如 launch_solve, mark_stuck）")
    parser.add_argument("--problem-id", help="按 problem_id 过滤")
    parser.add_argument("--session-key", help="按 session_key 过滤")
    parser.add_argument("--round", type=int, help="按 round 过滤")
    parser.add_argument("--level", help="按级别过滤（DEBUG/INFO/WARNING/ERROR）")
    parser.add_argument("--module", help="按模块名过滤（如 continuation_launcher）")
    parser.add_argument("--since", help="起始时间（如 2026-08-20 01:00）")
    parser.add_argument("--until", help="结束时间（如 2026-08-20 02:00）")
    parser.add_argument("--tail", type=int, help="只显示最后N条")
    parser.add_argument("--stats", action="store_true", help="只输出统计不输出详情")
    args = parser.parse_args()

    files = get_log_files(args.file)
    if not files:
        print("没有找到日志文件")
        return

    filters = {
        "event": args.event,
        "problem_id": args.problem_id,
        "session_key": args.session_key,
        "round": args.round,
        "level": args.level,
        "module": args.module,
        "since": args.since,
        "until": args.until,
    }

    results = search_logs(files, filters)
    print_results(results, show_stats=args.stats, tail=args.tail)


if __name__ == "__main__":
    main()
