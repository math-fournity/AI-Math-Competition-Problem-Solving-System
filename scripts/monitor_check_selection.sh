#!/bin/bash
# monitor_check_selection.sh — Pipe 3选题的标准化Monitor Pipe检查脚本
# 用法: ./scripts/monitor_check_selection.sh <batch_id> [monitor_tmux_session]
# 输出5项检查结果: Monitor Pipe pane输出 / alerts / 进程状态 / 进度 / POC字段质量
#
# 这个脚本是对monitor_check.sh的selection版本——针对Pipe 3选题监控。

set -uo pipefail

BATCH_ID="${1:?用法: $0 <batch_id> [monitor_tmux_session]}"
MONITOR_SESSION="${2:-monitor-sel}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(dirname "$SCRIPT_DIR")"
PY="$PROJ_ROOT/.venv/bin/python3"
ANALYSIS_DIR="$PROJ_ROOT"

echo "============================================"
echo "Pipe 3选题Monitor检查 @ $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "  batch_id: $BATCH_ID"
echo "  monitor_session: $MONITOR_SESSION"
echo "============================================"

# --- 检查1: Monitor Pipe的tmux pane输出（最近轮次+AI_REVIEW抽样）---
echo ""
echo "=== 1. Monitor Pipe pane输出（最近5轮）==="
if tmux has-session -t "$MONITOR_SESSION" 2>/dev/null; then
    tmux capture-pane -t "$MONITOR_SESSION" -p -S -200 2>/dev/null | grep -E "监控轮次|ALERT|AI_REVIEW|status|progress" | tail -30
else
    echo "  [ERROR] tmux session '$MONITOR_SESSION' 不存在！Monitor Pipe可能已退出。"
fi
echo ""
echo "  >> 需要检查："
echo "     - 每轮是否有新ALERT？alert类型是什么（critical/warning/info）？"
echo "     - AI_REVIEW抽样的结果——suitable判定是否合理？6字段值是否合理？"
echo "     - progress是否在推进？如果停滞，检查launcher日志"
echo "     - 轮次间隔是否正常（应约2分钟一轮）？如果间隔过长，Monitor Pipe可能卡住"

# --- 检查2: alerts集合（新alert）---
echo ""
echo "=== 2. alerts集合（新alert）==="
cd "$ANALYSIS_DIR"
$PY -m src.monitor_selection --batch-id "$BATCH_ID" --check-alerts 2>&1
echo ""
echo "  >> 需要检查："
echo "     - field_completeness: 哪些problem_id的6字段缺失？需要重跑这些题"
echo "     - value_monopoly: 哪个字段值垄断？如果是branch_position_hint全root，是已知模式（info级别）"
echo "     - invalid_value: 哪些problem_id的字段值非法？需要重跑"
echo "     - logic_inconsistency: 哪些problem_id的字段间逻辑矛盾？需要重跑"
echo "     - ai_review_sample: 检查抽样结果的selection_reason和6字段值是否合理"
echo "     - failure_rate: 检查failure_breakdown中rate_limited/failed_stall的比例"
echo "     - session_health/launcher_dead: 检查进程是否真的挂了"
echo "     - 处理完alert后用 --resolve-alert <key> 标记为fixed"
echo "     - 需要重跑的题：从alert的problem_ids字段获取problem_id，"
echo "       然后在DB中找到对应的selection_run，将status改回prepared，重新launch"

# --- 检查3: 进程状态（launcher + monitor_selection）---
echo ""
echo "=== 3. 进程状态 ==="
LAUNCHER_PID=$(pgrep -f "run_selection_pipeline.*$BATCH_ID" | head -1 || true)
MONITOR_PID=$(pgrep -f "src.monitor_selection.*$BATCH_ID" | head -1 || true)
if [ -n "$LAUNCHER_PID" ]; then
    ps -p "$LAUNCHER_PID" -o pid,pcpu,etime,stat,command 2>/dev/null | tail -1 | awk '{print "  launcher: PID="$1" CPU="$2"% ELAPSED="$3" STAT="$4}'
else
    echo "  launcher: [NOT RUNNING] — run_selection_pipeline进程不存在"
fi
if [ -n "$MONITOR_PID" ]; then
    ps -p "$MONITOR_PID" -o pid,pcpu,etime,stat 2>/dev/null | tail -1 | awk '{print "  monitor: PID="$1" CPU="$2"% ELAPSED="$3" STAT="$4}'
else
    echo "  monitor: [NOT RUNNING] — monitor_selection进程不存在"
fi

# tmux se-sessions数量
SE_COUNT=$(tmux list-sessions 2>/dev/null | grep "^se-" | wc -l | tr -d ' ')
echo "  tmux se-sessions: $SE_COUNT"
echo ""
echo "  >> 需要检查："
echo "     - launcher和monitor进程是否都在运行？NOT RUNNING = 需要重启"
echo "     - STAT=S+/Ss+ = 正常睡眠；STAT=R = 正在执行；STAT=Z = 僵尸进程（需kill）"
echo "     - CPU 0% + ELAPSED很长 = 可能在sleep中（正常）或卡住（不正常）"
echo "     - tmux se-sessions应≈并发数；为0可能是session刚完成正在启动下一个"
echo "     - 如果se-sessions持续为0，检查launcher日志是否有rate_limit_pause"

# --- 检查4: 进度（DB状态分布）---
echo ""
echo "=== 4. 进度 ==="
cd "$PROJ_ROOT"
$PY -c "
import sys; sys.path.insert(0, '.')
from src.db_schema import connect_db
db = connect_db()
aql = 'FOR run IN selection_runs FILTER run.batch_id == @bid COLLECT status = run.status WITH COUNT INTO c RETURN {status, count: c}'
cursor = db.aql.execute(aql, bind_vars={'bid': '$BATCH_ID'}, ttl=60)
total_done = 0
total_fail = 0
total = 0
for r in sorted(cursor, key=lambda x: -x['count']):
    print(f'  {r[\"status\"]}: {r[\"count\"]}')
    total += r['count']
    if r['status'] not in ('prepared', 'running'):
        total_done += r['count']
    if 'fail' in r['status'] or 'dead' in r['status'] or 'rate_limited' in r['status']:
        total_fail += r['count']
print(f'  ---')
print(f'  总完成: {total_done}/{total} ({100*total_done//total if total else 0}%)')
if total_fail > 0:
    fail_rate = 100 * total_fail // max(total_done, 1)
    print(f'  失败: {total_fail} (失败率{fail_rate}%)')
    if fail_rate > 10:
        print(f'  [WARNING] 失败率>10%阈值！')
else:
    print(f'  失败: 0')

# selection_results统计
aql2 = 'FOR r IN selection_results FILTER r.batch_id == @bid COLLECT s = r.suitable WITH COUNT INTO c RETURN {suitable: s, count: c}'
cursor2 = db.aql.execute(aql2, bind_vars={'bid': '$BATCH_ID'}, ttl=60)
suitable_counts = {r['suitable']: r['count'] for r in cursor2}
print(f'  selection_results suitable分布: {suitable_counts}')
yes_count = suitable_counts.get('YES', 0)
print(f'  suitable=YES: {yes_count} (目标30-50)')
" 2>&1
echo ""
echo "  >> 需要检查："
echo "     - 进度是否在推进？对比上次检查的completed数"
echo "     - rate_limited/dead_session/failed_stall是否有新增？有则需重新入队"
echo "     - 失败率>10% = 需要降并发或检查rate limit"
echo "     - suitable=YES的题数是否在增长？目标30-50道"

# --- 检查5: POC字段质量汇总 ---
echo ""
echo "=== 5. POC字段质量汇总 ==="
cd "$PROJ_ROOT"
$PY -c "
import sys; sys.path.insert(0, '.')
from src.db_schema import connect_db
from collections import Counter
db = connect_db()
aql = 'FOR r IN selection_results FILTER r.batch_id == @bid RETURN r'
cursor = db.aql.execute(aql, bind_vars={'bid': '$BATCH_ID'}, ttl=60)
results = list(cursor)
if not results:
    print('  无selection_results')
else:
    poc_fields = ['false_friend_candidate','boundary_case_candidate','process_signal_observability','leakage_risk','difficulty_estimate','branch_position_hint']
    for f in poc_fields:
        dist = Counter(r.get(f, 'MISSING') for r in results)
        print(f'  {f}: {dict(dist)}')
    # 逻辑一致性快速检查
    issues = 0
    for r in results:
        if r.get('suitable') == 'YES' and r.get('batch') == 'N/A':
            issues += 1
        if r.get('suitable') == 'NO' and r.get('batch', 'N/A') != 'N/A':
            issues += 1
        if r.get('suitable') == 'YES' and r.get('false_friend_candidate') == 'yes':
            issues += 1
    print(f'  逻辑一致性问题数: {issues}')
" 2>&1
echo ""
echo "  >> 需要检查："
echo "     - 6个字段的值分布是否有多样性？还是被某个值垄断？"
echo "     - 逻辑一致性问题数应为0，>0则需要查看alert详情定位问题题"
echo "     - false_friend_candidate=yes的题数（目标≥10，412号§7.2）"

echo ""
echo "============================================"
echo "检查完成 @ $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""
echo ">> 行动清单（按顺序执行）："
echo "   1. 仔细阅读第1项Monitor Pipe pane输出中的每轮ALERT和AI_REVIEW"
echo "   2. 有新alert时逐个recheck（第2项），处理完用--resolve-alert标记"
echo "   3. 进程NOT RUNNING时重启launcher/monitor（第3项）"
echo "   4. 有新增失败时重新入队（第4项）"
echo "   5. 进度停滞时检查launcher日志和rate_limit_pause状态"
echo "   6. 从alert的problem_ids字段获取需重跑的题，改status为prepared后重新launch"
echo "============================================"
