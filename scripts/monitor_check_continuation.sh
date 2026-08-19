#!/bin/bash
# monitor_check_continuation.sh — POC-2.7续传Pipe的标准化检查脚本（Master Agent 接管版）
# 用法: ./scripts/monitor_check_continuation.sh <batch_id> [monitor_tmux_session]
# 输出8项自动化检查结果 + 末尾"AI后续检查清单"（指向 checklist/MasterAgentCheck.md）
#
# 检查规范: docs/specs/p27_monitor_spec.md
# 这个脚本是对monitor_check_selection.sh的continuation版本——针对POC-2.7续传监控。
# 2026-08-19扩展：加第8项runtime_health_check 10维度 + 末尾AI后续检查清单（Master Agent接管Monitor Pipe检查工作）。
# 自动化检查由本脚本完成；需要AI判断的检查项见末尾"AI后续检查清单"，全文加载 checklist/MasterAgentCheck.md 逐项处理。

set -uo pipefail

BATCH_ID="${1:?用法: $0 <batch_id> [monitor_tmux_session]}"
MONITOR_SESSION="${2:-monitor-p27}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(dirname "$SCRIPT_DIR")"
PY="$PROJ_ROOT/.venv/bin/python3"
ANALYSIS_DIR="$PROJ_ROOT"

echo "============================================"
echo "POC-2.7续传Monitor检查 @ $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "  batch_id: $BATCH_ID"
echo "  monitor_session: $MONITOR_SESSION"
echo "  检查规范: specs/p27_monitor_spec.md"
echo "============================================"

# --- 检查1: Monitor Pipe的tmux pane输出（最近轮次+AI_REVIEW抽样）---
echo ""
echo "=== 1. Monitor Pipe pane输出（最近3轮）==="
if tmux has-session -t "$MONITOR_SESSION" 2>/dev/null; then
    # 只取最近3轮的输出，避免历史alert堆积导致输出过长
    tmux capture-pane -t "$MONITOR_SESSION" -p -S -100 2>/dev/null | grep -E "监控轮次|ALERT|AI_REVIEW|status|progress|final_status|pass_rate" | tail -20
else
    echo "  [ERROR] tmux session '$MONITOR_SESSION' 不存在！Monitor Pipe可能已退出。"
fi
echo ""
echo "  >> 需要检查："
echo "     - 每轮是否有新ALERT？alert类型是什么（critical/warning/info）？"
echo "     - AI_REVIEW抽样的结果——需按specs/p27_monitor_spec.md §3.3的C1-C5标准检查"
echo "     - progress是否在推进？如果停滞，检查launcher日志"
echo "     - pass_rate是否在增长？目标COMPLETED≥50%（415号§7.1）"
echo ""
echo "  >> Session注册表状态（编号化管理）："
$PY -c "
import sys; sys.path.insert(0, '$PROJ_ROOT')
from src.continuation_db_schema import connect_db
from src.session_registry import list_sessions
db = connect_db()
for status in ['running', 'stuck', 'done']:
    sessions = list_sessions(db, status=status, limit=100)
    if sessions:
        print(f'     {status}: {len(sessions)}个')
        if status == 'stuck':
            for s in sessions[:3]:
                print(f'       {s[\"_key\"]} ({s[\"session_name\"]}) — {s.get(\"notes\", \"\")[:50]}')
            if len(sessions) > 3:
                print(f'       ... 还有{len(sessions)-3}个')
" 2>/dev/null || echo "     [DB查询失败]"

# --- 检查2: alerts集合（新alert，最多显示5条）---
echo ""
echo "=== 2. alerts集合（新alert，最多5条）==="
cd "$ANALYSIS_DIR"
ALERT_OUTPUT=$($PY -m src.monitor_continuation --batch-id "$BATCH_ID" --check-alerts 2>&1)
ALERT_COUNT=$(echo "$ALERT_OUTPUT" | head -1 | grep -oE '[0-9]+' || echo "0")
echo "$ALERT_OUTPUT" | head -40
if [ "$ALERT_COUNT" -gt 5 ] 2>/dev/null; then
    echo "  ... 还有$((ALERT_COUNT - 5))条alert未显示（用 --check-alerts 查看全部）"
fi
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
import sys; sys.path.insert(0, '.')
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
import sys, os; sys.path.insert(0, '.')
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
import sys; sys.path.insert(0, '.')
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
sys.path.insert(0, '.')
r = redis.Redis(host='localhost', port=6379, db=0)

# 并发数
running = r.hlen('p27:running')
pending = r.zcard('p27:pending')
completed = r.llen('p27:completed')

# tmux session分类——排除服务session（p27-launcher/monitor-p27/p27-watchdog）
SERVICE_SESSIONS = {'p27-launcher', 'monitor-p27', 'p27-watchdog'}
sessions = subprocess.run(['tmux', 'list-sessions'], capture_output=True, text=True).stdout
all_lines = sessions.split('\n')
# 解题session: p27-{run_key_short}-r{round}（不含-h后缀）
p27_solve = [s for s in all_lines if s.startswith('p27-') and '-r' in s and '-h' not in s and s.split(':')[0] not in SERVICE_SESSIONS]
# handover session: p27-{run_key_short}-r{round}-h（任意round的handover）
p27_handover = [s for s in all_lines if s.startswith('p27-') and '-h' in s and s.split(':')[0] not in SERVICE_SESSIONS]
p27_service = [s for s in all_lines if s.startswith('p27-launcher') or s.startswith('monitor-p27') or s.startswith('p27-watchdog')]

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

# --- 检查8: 运行时健康检查（10维度 A-J）---
echo ""
echo "=== 8. 运行时健康检查（10维度 A-J）==="
cd "$PROJ_ROOT"
$PY -m monitoring.runtime_health_check --batch-id "$BATCH_ID" 2>&1 || echo "  [runtime_health_check执行失败——可能Redis未运行或DB未配置]"
echo ""
echo "  >> 需要检查："
echo "     - 10维度中哪些有⚠️问题？逐个关注"
echo "     - [A] Redis原子性：running集合是否有残留"
echo "     - [B] DB-Redis一致性：DB running数 vs Redis running数"
echo "     - [C] 重复run：同一题是否有重复running"
echo "     - [D] 并发上限：是否超过配置并发数"
echo "     - [E] devin进程数：是否有僵尸进程"
echo "     - [F] 网络健康：API是否可达"
echo "     - [G] devin退出健康：异常退出率"
echo "     - [H] 落盘完整性：completed的题是否都有落盘"
echo "     - [I] 批次进度：进度是否在推进"
echo "     - [J] 日志健康：是否有异常日志"

echo ""
echo ""
echo "============================================"
echo "检查完成 @ $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""
echo ">> AI后续检查清单（Master Agent 逐项处理）："
echo "   以下项目需要 Master Agent 全文加载 checklist/MasterAgentCheck.md 逐项处理："
echo ""
echo "   1. [C类AI判断] MON-C1~C5：读proof.md/HANDOVER.md做判断"
echo "      - 详见 checklist/MasterAgentCheck.md §C类AI判断"
echo ""
echo "   2. [self-check] SELF-S1~S17：每轮必须执行的自我检查"
echo "      - 详见 checklist/MasterAgentCheck.md §self-check"
echo ""
echo "   3. [新alert分类处理] 读第2项alerts输出，逐个recheck"
echo "      - 按docs/specs/p27_monitor_spec.md §2分类处理"
echo "      - 处理完用 --resolve-alert <key> 标记为fixed"
echo "      - 详见 checklist/MasterAgentCheck.md §新alert分类处理"
echo ""
echo "   4. [已知问题诊断] MON-A-issue-01~05中未诊断的优先诊断"
echo "      - 详见 checklist/MasterAgentCheck.md §已知问题诊断"
echo ""
echo "   5. [落盘完整性检查] 每个round的完整落盘验证"
echo "      - 详见 checklist/MasterAgentCheck.md §落盘完整性检查"
echo ""
echo "   6. [修复操作] 发现问题后修复，修复后同步更新文档+commit"
echo "      - 详见 checklist/MasterAgentCheck.md §修复操作规范"
echo ""
echo ">> 执行方式："
echo "   - 全文加载 checklist/MasterAgentCheck.md"
echo "   - 逐项处理上述清单中的每一项"
echo "   - 每完成一项立即 commit（含 trace.csv 同步）"
echo "   - 全部处理完后写执行结果记录"
echo ""
echo ">> 系统健康判断标准："
echo "   ✅ 健康 = launcher+monitor运行中 + devin cli活跃（pane有内容） + 进度在推进"
echo "   ⚠️ 需关注 = 有新alert + 失败率>15% + handover生成慢"
echo "   ❌修复 = launcher/monitor挂了 + devin cli全卡住 + 进度停滞"
echo "============================================"
