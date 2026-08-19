#!/bin/bash
# monitor_check.sh — 标准化的Monitor Pipe检查脚本
# 用法: ./scripts/monitor_check.sh <batch_id> [monitor_tmux_session]
# 输出4项检查结果: Monitor Pipe pane输出 / alerts / 进程状态 / 进度
#
# 这个脚本是为了避免每次监控时inline编写检查命令——标准化后索引到AGENTS.md。
# 每个检查项后附带"需要检查"提示，提醒AI逐项检查而非只看数字。

set -uo pipefail

BATCH_ID="${1:?用法: $0 <batch_id> [monitor_tmux_session]}"
MONITOR_SESSION="${2:-monitor-pipe}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(dirname "$SCRIPT_DIR")"
PY="$PROJ_ROOT/.venv/bin/python3"
ANALYSIS_DIR="$PROJ_ROOT"

echo "============================================"
echo "Monitor Pipe 标准化检查 @ $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "  batch_id: $BATCH_ID"
echo "  monitor_session: $MONITOR_SESSION"
echo "============================================"

# --- 检查1: Monitor Pipe的tmux pane输出（最近轮次+AI_REVIEW抽样）---
echo ""
echo "=== 1. Monitor Pipe pane输出（最近5轮）==="
if tmux has-session -t "$MONITOR_SESSION" 2>/dev/null; then
    tmux capture-pane -t "$MONITOR_SESSION" -p -S -200 2>/dev/null | grep -E "监控轮次|ALERT|AI_REVIEW|status|progress" | tail -20
else
    echo "  [ERROR] tmux session '$MONITOR_SESSION' 不存在！Monitor Pipe可能已退出。"
fi
echo ""
echo "  >> 需要检查："
echo "     - 每轮是否有新ALERT？alert类型是什么（critical/warning/info）？"
echo "     - AI_REVIEW抽样的2条结果——audit_status是否合理？FAIL项是否是已知问题（D1动词/XML泄漏）？"
echo "     - progress是否在推进？如果停滞，检查launcher日志"
echo "     - 轮次间隔是否正常（应约5分钟一轮）？如果间隔过长，Monitor Pipe可能卡住"

# --- 检查2: alerts集合（新alert）---
echo ""
echo "=== 2. alerts集合（新alert）==="
cd "$ANALYSIS_DIR"
$PY -m src.monitor_pipe --batch-id "$BATCH_ID" --check-alerts 2>&1
echo ""
echo "  >> 需要检查："
echo "     - 新alert如果有：逐个recheck，确认是真实问题还是已知问题"
echo "     - ai_review_sample：用get_audit_output+parse_audit_xml验证抽样判定"
echo "     - failure_rate：检查failure_breakdown中rate_limited/failed_stall的比例"
echo "     - status_inconsistency：检查是否是D1动词列表或PARTIAL_PROGRESS定义问题"
echo "     - session_health/launcher_dead：检查进程是否真的挂了"
echo "     - 处理完alert后用 --resolve-alert <key> 标记为fixed"

# --- 检查3: 进程状态（launcher + monitor_pipe）---
echo ""
echo "=== 3. 进程状态 ==="
LAUNCHER_PID=$(pgrep -f "run_audit_pipeline.*$BATCH_ID" | head -1 || true)
MONITOR_PID=$(pgrep -f "src.monitor_pipe.*$BATCH_ID" | head -1 || true)
if [ -n "$LAUNCHER_PID" ]; then
    ps -p "$LAUNCHER_PID" -o pid,pcpu,etime,stat,command 2>/dev/null | tail -1 | awk '{print "  launcher: PID="$1" CPU="$2"% ELAPSED="$3" STAT="$4}'
else
    echo "  launcher: [NOT RUNNING] — run_audit_pipeline进程不存在"
fi
if [ -n "$MONITOR_PID" ]; then
    ps -p "$MONITOR_PID" -o pid,pcpu,etime,stat 2>/dev/null | tail -1 | awk '{print "  monitor: PID="$1" CPU="$2"% ELAPSED="$3" STAT="$4}'
else
    echo "  monitor: [NOT RUNNING] — monitor_pipe进程不存在"
fi

# tmux au-sessions数量
AU_COUNT=$(tmux list-sessions 2>/dev/null | grep "^au-" | wc -l | tr -d ' ')
echo "  tmux au-sessions: $AU_COUNT"
echo ""
echo "  >> 需要检查："
echo "     - launcher和monitor进程是否都在运行？NOT RUNNING = 需要重启"
echo "     - STAT=S+/Ss+ = 正常睡眠；STAT=R = 正在执行；STAT=Z = 僵尸进程（需kill）"
echo "     - CPU 0% + ELAPSED很长 = 可能在sleep中（正常）或卡住（不正常）"
echo "     - tmux au-sessions应≈并发数；为0可能是session刚完成正在启动下一个"
echo "     - 如果au-sessions持续为0，检查launcher日志是否有rate_limit_pause"

# --- 检查4: 进度（DB状态分布）---
echo ""
echo "=== 4. 进度 ==="
cd "$PROJ_ROOT"
$PY -c "
import sys; sys.path.insert(0, '.')
from src.db_schema import connect_db
db = connect_db()
aql = 'FOR run IN audit_runs FILTER run.batch_id == @bid COLLECT status = run.status WITH COUNT INTO c RETURN {status, count: c}'
cursor = db.aql.execute(aql, bind_vars={'bid': '$BATCH_ID'}, ttl=60)
total_done = 0
total_fail = 0
for r in sorted(cursor, key=lambda x: -x['count']):
    print(f'  {r[\"status\"]}: {r[\"count\"]}')
    if r['status'] not in ('prepared', 'running'):
        total_done += r['count']
    if 'fail' in r['status'] or 'dead' in r['status'] or 'rate_limited' in r['status']:
        total_fail += r['count']
print(f'  ---')
print(f'  总完成: {total_done}/1521 ({100*total_done//1521}%)')
if total_fail > 0:
    fail_rate = 100 * total_fail // max(total_done, 1)
    print(f'  失败: {total_fail} (失败率{fail_rate}%)')
    if fail_rate > 10:
        print(f'  [WARNING] 失败率>10%阈值！')
else:
    print(f'  失败: 0')
" 2>&1
echo ""
echo "  >> 需要检查："
echo "     - 进度是否在推进？对比上次检查的completed数"
echo "     - rate_limited/dead_session/failed_stall是否有新增？有则需重新入队"
echo "     - 失败率>10% = 需要降并发或检查rate limit"
echo "     - prepared数在减少但completed没增加 = 可能任务在失败而非完成"

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
echo "============================================"
