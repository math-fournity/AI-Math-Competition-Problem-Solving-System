#!/bin/bash
# monitor_check_continuation.sh — POC-2.7续传Pipe的标准化Monitor Pipe检查脚本
# 用法: ./scripts/monitor_check_continuation.sh <batch_id> [monitor_tmux_session]
# 输出6项检查结果: Monitor Pipe pane输出 / alerts / 进程状态 / 进度 / 续传质量 / 通过率判定
#
# 检查规范: specs/p27_monitor_spec.md
# 这个脚本是对monitor_check_selection.sh的continuation版本——针对POC-2.7续传监控。
# 每次检查都要调用此脚本，它在输出最后提醒你去检查Monitor Pipe留下的检查结果。

set -uo pipefail

BATCH_ID="${1:?用法: $0 <batch_id> [monitor_tmux_session]}"
MONITOR_SESSION="${2:-monitor-p27}"
PY="/Users/user/glm5.2-math-worktree/.venv/bin/python3"
PROJ_ROOT="/Users/user/glm5.2-math-worktree"
ANALYSIS_DIR="$PROJ_ROOT/analysis-devin-failure-system"

echo "============================================"
echo "POC-2.7续传Monitor检查 @ $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "  batch_id: $BATCH_ID"
echo "  monitor_session: $MONITOR_SESSION"
echo "  检查规范: specs/p27_monitor_spec.md"
echo "============================================"

# --- 检查1: Monitor Pipe的tmux pane输出（最近轮次+AI_REVIEW抽样）---
echo ""
echo "=== 1. Monitor Pipe pane输出（最近5轮）==="
if tmux has-session -t "$MONITOR_SESSION" 2>/dev/null; then
    tmux capture-pane -t "$MONITOR_SESSION" -p -S -200 2>/dev/null | grep -E "监控轮次|ALERT|AI_REVIEW|status|progress|final_status|pass_rate" | tail -30
else
    echo "  [ERROR] tmux session '$MONITOR_SESSION' 不存在！Monitor Pipe可能已退出。"
fi
echo ""
echo "  >> 需要检查："
echo "     - 每轮是否有新ALERT？alert类型是什么（critical/warning/info）？"
echo "     - AI_REVIEW抽样的结果——需按specs/p27_monitor_spec.md §3.3的C1-C5标准检查"
echo "     - progress是否在推进？如果停滞，检查launcher日志"
echo "     - pass_rate是否在增长？目标COMPLETED≥50%（415号§7.1）"

# --- 检查2: alerts集合（新alert）---
echo ""
echo "=== 2. alerts集合（新alert）==="
cd "$ANALYSIS_DIR"
$PY -m src.monitor_continuation --batch-id "$BATCH_ID" --check-alerts 2>&1
echo ""
echo "  >> 需要检查（按specs/p27_monitor_spec.md §2分类处理）："
echo "     [A类自动检查]"
echo "     - session_health critical → launcher可能挂了，检查进程状态（第3项）"
echo "     - queue_stalled → 检查collector是否在处理completed队列"
echo "     - rate_limit critical → 立即降并发（修改batch.concurrency）"
echo "     - zombie_sessions → 手动kill空panesession"
echo "     - export_missing → 检查D盘是否挂载、trajectory目录是否可写"
echo "     - failure_rate → 检查failure_breakdown，判断是AI能力问题还是基础设施问题"
echo "     - launcher_dead → 重启launcher"
echo "     - long_running → 检查是否真的stall，可能需要kill后重新入队"
echo "     [B类续传质量检查]"
echo "     - proof_missing → COMPLETED但无proof.md，需重跑"
echo "     - proof_no_boxed → proof.md无boxed答案，需检查是否真正完成"
echo "     - proof_too_small → proof.md太小，可能内容不完整"
echo "     - handover_missing → v2方案但无HANDOVER.md，Pipe A失败"
echo "     - all_rounds_truncated → 5轮全截断，可能是真正的思维错误"
echo "     [C类AI review]"
echo "     - ai_review_sample → 读proof.md和HANDOVER.md，按C1-C5标准逐项检查"
echo "     处理完alert后用 --resolve-alert <key> 标记为fixed"
echo "     需要重跑的题：从alert的problem_ids字段获取problem_id，"
echo "       在DB中找到对应的run，将status改回prepared，重新入队"

# --- 检查3: 进程状态（launcher + monitor_continuation）---
echo ""
echo "=== 3. 进程状态 ==="
LAUNCHER_PID=$(pgrep -f "continuation_launcher.*$BATCH_ID" | head -1 || true)
MONITOR_PID=$(pgrep -f "src.monitor_continuation.*$BATCH_ID" | head -1 || true)
if [ -n "$LAUNCHER_PID" ]; then
    ps -p "$LAUNCHER_PID" -o pid,pcpu,etime,stat,command 2>/dev/null | tail -1 | awk '{print "  launcher: PID="$1" CPU="$2"% ELAPSED="$3" STAT="$4}'
else
    echo "  launcher: [NOT RUNNING] — run_continuation_pipeline进程不存在"
fi
if [ -n "$MONITOR_PID" ]; then
    ps -p "$MONITOR_PID" -o pid,pcpu,etime,stat 2>/dev/null | tail -1 | awk '{print "  monitor: PID="$1" CPU="$2"% ELAPSED="$3" STAT="$4}'
else
    echo "  monitor: [NOT RUNNING] — monitor_continuation进程不存在"
fi

# tmux p27-sessions数量
P27_COUNT=$(tmux list-sessions 2>/dev/null | grep "^p27-" | wc -l | tr -d ' ')
echo "  tmux p27-sessions: $P27_COUNT"
echo ""
echo "  >> 需要检查："
echo "     - launcher和monitor进程是否都在运行？NOT RUNNING = 需要重启"
echo "     - STAT=S+/Ss+ = 正常睡眠；STAT=R = 正在执行；STAT=Z = 僵尸进程（需kill）"
echo "     - CPU 0% + ELAPSED很长 = 可能在sleep中（正常）或卡住（不正常）"
echo "     - tmux p27-sessions应≈并发数；为0可能是session刚完成正在启动下一个"
echo "     - 如果p27-sessions持续为0，检查launcher日志是否有rate_limit_pause"

# --- 检查4: 进度（DB状态分布）---
echo ""
echo "=== 4. 进度 ==="
cd "$PROJ_ROOT"
$PY -c "
import sys; sys.path.insert(0, 'analysis-devin-failure-system')
from src.continuation_db_schema import connect_db
db = connect_db()
aql = 'FOR run IN p27_continuation_runs FILTER run.batch_id == @bid COLLECT status = run.status WITH COUNT INTO c RETURN {status, count: c}'
cursor = db.aql.execute(aql, bind_vars={'bid': '$BATCH_ID'}, ttl=60)
total_done = 0
total_fail = 0
total = 0
for r in sorted(cursor, key=lambda x: -x['count']):
    print(f'  {r[\"status\"]:25s} {r[\"count\"]:>4}')
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
    if fail_rate > 15:
        print(f'  [WARNING] 失败率>15%阈值！')
else:
    print(f'  失败: 0')
" 2>&1
echo ""
echo "  >> 需要检查："
echo "     - 进度是否在推进？对比上次检查的completed数"
echo "     - rate_limited/dead_session/failed_stall是否有新增？有则需重新入队"
echo "     - 失败率>15% = 需要降并发或检查rate limit"

# --- 检查5: 续传质量汇总 ---
echo ""
echo "=== 5. 续传质量汇总 ==="
cd "$PROJ_ROOT"
$PY -c "
import sys, os; sys.path.insert(0, 'analysis-devin-failure-system')
from src.continuation_db_schema import connect_db
from pathlib import Path
db = connect_db()
aql = 'FOR run IN p27_continuation_runs FILTER run.batch_id == @bid FILTER run.final_status != null RETURN run'
cursor = db.aql.execute(aql, bind_vars={'bid': '$BATCH_ID'}, ttl=120)
runs = list(cursor)
if not runs:
    print('  无已完成的run')
else:
    # final_status分布
    from collections import Counter
    fs_dist = Counter(r.get('final_status', '?') for r in runs)
    print(f'  final_status分布: {dict(fs_dist)}')

    # proof.md统计
    proof_exists = 0
    proof_has_boxed = 0
    proof_too_small = 0
    for r in runs:
        if r.get('final_status') == 'COMPLETED':
            proof_path = r.get('proof_path', '')
            if not proof_path:
                work_dir = r.get('work_dir', '')
                if work_dir:
                    proof_path = str(Path(work_dir) / 'proof.md')
            if proof_path and os.path.exists(proof_path):
                proof_exists += 1
                size = os.path.getsize(proof_path)
                if size < 1024:
                    proof_too_small += 1
                with open(proof_path) as f:
                    content = f.read()
                if '\\\\boxed' in content or 'boxed{' in content:
                    proof_has_boxed += 1
    print(f'  proof.md: 存在={proof_exists}, 有boxed={proof_has_boxed}, 太小={proof_too_small}')

    # 截断模式统计
    all_truncated = 0
    for r in runs:
        if r.get('final_status') == 'TRUNCATED_AT_MAX':
            rounds = r.get('rounds_log', [])
            if len(rounds) >= 3 and all(rd.get('truncated', False) for rd in rounds):
                all_truncated += 1
    print(f'  5轮全截断（可能思维错误）: {all_truncated}')

    # 平均轮次
    completed_rounds = [len(r.get('rounds_log', [])) for r in runs if r.get('final_status') == 'COMPLETED']
    if completed_rounds:
        avg_rounds = sum(completed_rounds) / len(completed_rounds)
        print(f'  COMPLETED平均轮次: {avg_rounds:.1f}')
" 2>&1
echo ""
echo "  >> 需要检查："
echo "     - proof.md存在数 vs COMPLETED数——不匹配说明有proof_missing"
echo "     - 有boxed数 vs 存在数——不匹配说明有proof_no_boxed"
echo "     - 5轮全截断数——这些是真正的思维错误候选"
echo "     - COMPLETED平均轮次——如果>4说明大部分题需要很多轮才能完成"

# --- 检查6: 通过率判定（对照415号§7.1）---
echo ""
echo "=== 6. 通过率判定（415号§7.1）==="
cd "$PROJ_ROOT"
$PY -c "
import sys; sys.path.insert(0, 'analysis-devin-failure-system')
from src.continuation_db_schema import connect_db
db = connect_db()
aql = 'FOR run IN p27_continuation_runs FILTER run.batch_id == @bid FILTER run.final_status != null COLLECT fs = run.final_status WITH COUNT INTO c RETURN {final_status: fs, count: c}'
cursor = db.aql.execute(aql, bind_vars={'bid': '$BATCH_ID'}, ttl=60)
dist = {r['final_status']: r['count'] for r in cursor}
total = sum(dist.values())
completed = dist.get('COMPLETED', 0)
truncated = dist.get('TRUNCATED_AT_MAX', 0)
if total > 0:
    pass_rate = completed / total
    print(f'  COMPLETED={completed} / total={total} = {pass_rate:.1%}')
    if pass_rate >= 0.80:
        print(f'  判定: 大部分是截断错误 → POC-2.5需要重新选题，Pipe 1判定基础有严重问题')
    elif pass_rate >= 0.50:
        print(f'  判定: 部分截断错误，部分思维错误 → 失败的题进入POC-2.5b')
    else:
        print(f'  判定: 大部分是真正的思维错误 → POC-2.5候选题基础基本成立')
    print(f'  通过标准: COMPLETED≥50% → {\"通过\" if pass_rate >= 0.50 else \"未通过（当前进度）\"}')
else:
    print(f'  无已完成的run，无法判定')
" 2>&1
echo ""
echo "  >> 需要检查："
echo "     - 通过率是否≥50%？这是POC-2.7的通过标准（415号§7.1）"
echo "     - 如果通过率<50%，检查续传机制是否需要改进（v2交接文档自动化）"
echo "     - 对TRUNCATED_AT_MAX的题，检查是否有proof.md但答案错误→真正的思维错误"

# --- 检查7: 系统健康（并发数+handover状态+devin cli活跃度）---
echo ""
echo "=== 7. 系统健康 ==="
cd "$PROJ_ROOT"
$PY -c "
import sys, os, time, redis, subprocess
sys.path.insert(0, 'analysis-devin-failure-system')
r = redis.Redis(host='localhost', port=6379, db=0)

# 并发数
running = r.hlen('p27:running')
pending = r.zcard('p27:pending')
completed = r.llen('p27:completed')

# tmux session分类
sessions = subprocess.run(['tmux', 'list-sessions'], capture_output=True, text=True).stdout
p27_solve = [s for s in sessions.split('\n') if 'p27-p27-full-' in s]  # 解题session
p27_handover = [s for s in sessions.split('\n') if s.startswith('p27-') and '-r1-h' in s]  # handover session
p27_service = [s for s in sessions.split('\n') if s.startswith('p27-launcher') or s.startswith('monitor-p27') or s.startswith('p27-watchdog')]

print(f'  Redis: pending={pending} running={running} completed={completed}')
print(f'  tmux: 解题session={len(p27_solve)} handover session={len(p27_handover)} 服务session={len(p27_service)}')

# devin cli进程数
ps = subprocess.run(['ps', 'aux'], capture_output=True, text=True).stdout
devin_p = [l for l in ps.split('\n') if 'devin -p' in l and 'grep' not in l and 'zsh' not in l]
print(f'  devin cli进程: {len(devin_p)}')

# 并发槽利用率
try:
    from src.continuation_db_schema import connect_db
    from src.continuation_config import CONTINUATION_BATCHES_COLLECTION
    db = connect_db()
    batch = db.collection(CONTINUATION_BATCHES_COLLECTION).get('$BATCH_ID')
    conc = batch.get('concurrency', 5) if batch else 5
except:
    conc = 5
print(f'  配置并发数: {conc}')
if running < conc:
    print(f'  [WARNING] running({running}) < concurrency({conc})——handover可能阻塞或devin cli启动慢')
if len(p27_handover) > 0 and running == 0:
    print(f'  [INFO] {len(p27_handover)}个handover生成中，解题session待启动——这是正常的')

# 进度推进检查
print(f'  完成率: {completed}/{completed+pending+running} = {100*completed//max(completed+pending+running,1)}%')
" 2>&1
echo ""
echo "  >> 需要检查："
echo "     - 解题session数是否≈并发数？如果持续为0且handover session很多，handover生成可能太慢"
echo "     - devin cli进程数是否>0？为0说明所有devin cli已退出，可能需要重启"
echo "     - running < concurrency持续很长时间？检查launcher日志是否有handover阻塞"
echo "     - 完成率是否在增长？对比上次检查的completed数"

echo ""
echo ""
echo "============================================"
echo "检查完成 @ $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""
echo ">> 行动清单（按顺序执行）："
echo "   1. 仔细阅读第1项Monitor Pipe pane输出中的每轮ALERT和AI_REVIEW"
echo "   2. 有新alert时逐个recheck（第2项），按specs/p27_monitor_spec.md §2分类处理，处理完用--resolve-alert标记"
echo "   3. 进程NOT RUNNING时重启launcher/monitor（第3项）"
echo "   4. 有新增失败时重新入队（第4项）"
echo "   5. 进度停滞时检查launcher日志和rate_limit_pause状态"
echo "   6. 从alert的problem_ids字段获取需重跑的题，改status为prepared后重新launch"
echo "   7. AI_REVIEW抽样的结果——读proof.md和HANDOVER.md，按specs/p27_monitor_spec.md §3.3的C1-C5标准逐项检查"
echo "   8. 对照第6项通过率判定——如果COMPLETED≥50%，POC-2.7通过"
echo ""
echo ">> 循环监控指令（这是你的核心职责——反复执行直到所有题完成）："
echo "   1. 执行完上述行动清单后，等待60-120秒（让devin cli继续工作）"
echo "   2. 再次运行本脚本: ./scripts/monitor_check_continuation.sh $BATCH_ID"
echo "   3. 根据新的输出重复执行行动清单"
echo "   4. 如此循环，直到第4项进度显示所有题completed或failed（无prepared/running剩余）"
echo "   5. 如果发现系统问题（代码bug/架构问题），修复代码后重启系统，然后继续循环监控"
echo "   6. 如果session被中断，下一个session的AI只需运行本脚本即可恢复全部上下文"
echo "     ——本脚本的输出会告诉你系统当前状态和需要做什么"
echo ""
echo ">> 系统健康判断标准："
echo "   ✅ 健康 = launcher+monitor运行中 + devin cli活跃（pane有内容） + 进度在推进"
echo "   ⚠️ 需关注 = 有新alert + 失败率>15% + handover生成慢"
echo "   ❌修复 = launcher/monitor挂了 + devin cli全卡住 + 进度停滞"
echo "============================================"
