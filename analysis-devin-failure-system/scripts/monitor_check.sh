#!/bin/bash
# monitor_check.sh — 标准化的Monitor Pipe检查脚本
# 用法: ./scripts/monitor_check.sh <batch_id> [monitor_tmux_session]
# 输出4项检查结果: Monitor Pipe pane输出 / alerts / 进程状态 / 进度
#
# 这个脚本是为了避免每次监控时inline编写检查命令——标准化后索引到AGENTS.md。

set -euo pipefail

BATCH_ID="${1:?用法: $0 <batch_id> [monitor_tmux_session]}"
MONITOR_SESSION="${2:-monitor-pipe}"
PY="/Users/user/glm5.2-math-worktree/.venv/bin/python3"
PROJ_ROOT="/Users/user/glm5.2-math-worktree"
ANALYSIS_DIR="$PROJ_ROOT/analysis-devin-failure-system"

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

# --- 检查2: alerts集合（新alert）---
echo ""
echo "=== 2. alerts集合（新alert）==="
cd "$ANALYSIS_DIR"
$PY -m src.monitor_pipe --batch-id "$BATCH_ID" --check-alerts 2>&1

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

# --- 检查4: 进度（DB状态分布）---
echo ""
echo "=== 4. 进度 ==="
cd "$PROJ_ROOT"
$PY -c "
import sys; sys.path.insert(0, 'analysis-devin-failure-system')
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
        print(f'  [WARNING] 失败率>{10}%阈值！')
else:
    print(f'  失败: 0')
" 2>&1

echo ""
echo "============================================"
echo "检查完成 @ $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================"
