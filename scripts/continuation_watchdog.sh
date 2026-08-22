#!/bin/bash
# continuation_watchdog.sh — POC-2.7续传Pipe看门狗
#
# 每30秒检查launcher和monitor是否活着，死了就重启
# 每5分钟检查p27- devin session数 vs Redis running数，不一致则告警
#
# 启动方式：
#   手动: bash scripts/continuation_watchdog.sh --batch-id p27-full
#   launchd: 见scripts/com.user.continuation-watchdog.plist（需创建）
#
# 停止: tmux kill-session -t p27-watchdog

set -e

export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
ANALYSIS_DIR=$REPO
PY=$REPO/.venv/bin/python3
export PYTHONPATH=$ANALYSIS_DIR

# 参数
BATCH_ID="${2:-p27-full}"
LOG=/tmp/p27-watchdog.log

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [watchdog] $*" >> "$LOG"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [watchdog] $*"
}

# 从参数解析--batch-id
while [[ $# -gt 0 ]]; do
    case $1 in
        --batch-id)
            BATCH_ID="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

log "启动watchdog (batch=$BATCH_ID)"

ensure_service() {
    local name=$1
    local session_name=$2
    local cmd=$3

    if ! tmux has-session -t "$session_name" 2>/dev/null; then
        log "$name ($session_name) 不存在，重启"
        tmux new-session -d -s "$session_name" "$cmd"
    fi
}

last_consistency_check=0

while true; do
    # === 检查launcher ===
    ensure_service "launcher" "p27-launcher" \
        "cd $ANALYSIS_DIR && while true; do $PY -m src.continuation_launcher --batch-id $BATCH_ID --method v2 2>&1; echo '[auto-restart] launcher退出, 5秒后重启...'; sleep 5; done"

    # === 检查monitor ===
    ensure_service "monitor" "monitor-p27" \
        "cd $ANALYSIS_DIR && while true; do $PY -m src.monitor_continuation --batch-id $BATCH_ID --interval 120 2>&1; echo '[auto-restart] monitor退出, 5秒后重启...'; sleep 5; done"

    # === 每5分钟做一次一致性检查 ===
    now=$(date +%s)
    if [ $((now - last_consistency_check)) -gt 300 ]; then
        last_consistency_check=$now

        # p27- session数 vs Redis running数
        # 排除服务session（p27-launcher/p27-watchdog）和monitor-p27
        P27_SESSIONS=$(tmux list-sessions 2>/dev/null | grep "^p27-" | grep -v "p27-launcher" | grep -v "p27-watchdog" | grep -v "monitor-p27" | wc -l | tr -d ' ' || echo 0)
        REDIS_RUNNING=$($PY -c "
import sys; sys.path.insert(0, '$ANALYSIS_DIR')
from src.continuation_redis_queue import get_redis
r = get_redis()
print(r.hlen('p27:running'))
" 2>/dev/null || echo "unknown")

        if [ "$REDIS_RUNNING" != "unknown" ] && [ "$P27_SESSIONS" != "$REDIS_RUNNING" ]; then
            DIFF=$((P27_SESSIONS - REDIS_RUNNING))
            if [ $DIFF -gt 2 ] || [ $DIFF -lt -2 ]; then
                log "WARNING: p27- session数($P27_SESSIONS)与Redis running($REDIS_RUNNING)不一致 (diff=$DIFF)"
                log "  可运行一致性检查: $PY $ANALYSIS_DIR/monitoring/continuation_control.py sessions --consistency-check"
            fi
        fi

        log "一致性检查: p27_sessions=$P27_SESSIONS redis_running=$REDIS_RUNNING"
    fi

    sleep 30
done
