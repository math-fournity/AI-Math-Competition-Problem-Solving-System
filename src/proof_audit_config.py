"""proof_audit_config.py — Pipe 5 proof 审计系统配置常量

审计 Pipe 的全局配置：DB集合名/Redis key/模型/路径/门闸ID。
复用续传系统的 ArangoDB 连接和 devin cli 配置，但用独立的
p27_proof_audit_* 集合和 paudit: Redis 前缀避免冲突。

设计原则（见 dev-docs/029）：
  - 审计 Pipe 融入门控体系——4 个 @gated 门闸
  - 审计 Pipe 融入 SOP 循环——SOP_01/03/04 扩展审计检查项
  - 审计 AI 不受防作弊约束，但严格审计解题 AI 的数学正确性+作弊检测
"""
from pathlib import Path
import os

# 复用续传系统的路径和 DB 配置
from .continuation_config import (
    PROJECT_ROOT, D_SOLVER_DIR, D_TRAJ_DIR,
    ARANGO_HOST, ARANGO_DB, ARANGO_USER, ARANGO_PASSWORD,
    DEVIN_MODEL, DEVIN_PERMISSION_MODE,
    CONTINUATION_RUNS_COLLECTION, CONTINUATION_RESULTS_COLLECTION,
    MONITOR_ALERTS_COLLECTION,
)

# === 审计 Pipe 的工作目录和 trajectory 目录 ===
# 审计 work_dir 独立于续传 work_dir，避免互相干扰
AUDIT_SOLVER_BASE = D_SOLVER_DIR / "p27-proof-audit"
AUDIT_TRAJECTORY_BASE = D_TRAJ_DIR / "p27-proof-audit"

# === ArangoDB 集合（审计 Pipe 专用）===
PROOF_AUDIT_RUNS_COLLECTION = "p27_proof_audit_runs"
PROOF_AUDITS_COLLECTION = "p27_proof_audits"
# 复用 p27_step_gates（门闸集合）和 p27_monitor_alerts（alert集合）

# === Redis 队列（paudit: 前缀）===
AUDIT_PENDING_KEY = "paudit:pending"
AUDIT_RUNNING_KEY = "paudit:running"
AUDIT_COMPLETED_KEY = "paudit:completed"
AUDIT_FAILED_KEY = "paudit:failed"
AUDIT_STATS_KEY = "paudit:stats"

# === 审计并发配置（审计任务比解题快——只读 proof 不解题）===
# 并发数不在此写死（AGENTS.md 硬约束）：唯一来源 DB batch.concurrency
# （p27_continuation_batches 集合，与续传批次同集合同命令 set-concurrency）；
# DB 无记录且未传参时 launcher 报错退出（WP-G）
AUDIT_MAX_RUNTIME_SECONDS = 600     # 10分钟（审计只读 proof + 判断，不解题）
AUDIT_STALL_SECONDS = 180           # 3分钟无活动判定为 stall
AUDIT_POLL_SECONDS = 10             # 轮询间隔

# === 审计完成标记 ===
AUDIT_COMPLETE_MARKER = "### PROOF AUDIT COMPLETE"
AUDIT_XML_TAG = "proof_audit"

# === 审计结果枚举（见 dev-docs/029 §3.2）===
AUDIT_STATUS_PASS = "PASS"
AUDIT_STATUS_PASS_WITH_CAVEAT = "PASS_WITH_CAVEAT"
AUDIT_STATUS_FAIL_WRONG_ANSWER = "FAIL_WRONG_ANSWER"
AUDIT_STATUS_FAIL_HALLUCINATION = "FAIL_HALLUCINATION"
AUDIT_STATUS_FAIL_INCOMPLETE = "FAIL_INCOMPLETE"
AUDIT_STATUS_FAIL_LOGIC_ERROR = "FAIL_LOGIC_ERROR"
AUDIT_STATUS_FAIL_CHEATING = "FAIL_CHEATING"
AUDIT_STATUS_FAIL_CHEATING_DECLARED = "FAIL_CHEATING_DECLARED"
AUDIT_STATUS_PARSE_ERROR = "PARSE_ERROR"

# PASS 类（进入选题池）
AUDIT_PASS_STATUSES = {AUDIT_STATUS_PASS, AUDIT_STATUS_PASS_WITH_CAVEAT}
# FAIL 类（不进入选题池）
AUDIT_FAIL_STATUSES = {
    AUDIT_STATUS_FAIL_WRONG_ANSWER, AUDIT_STATUS_FAIL_HALLUCINATION,
    AUDIT_STATUS_FAIL_INCOMPLETE, AUDIT_STATUS_FAIL_LOGIC_ERROR,
    AUDIT_STATUS_FAIL_CHEATING, AUDIT_STATUS_FAIL_CHEATING_DECLARED,
}
# 需要改 status=prepared 重做的 FAIL
AUDIT_REDO_STATUSES = {AUDIT_STATUS_FAIL_INCOMPLETE}
# 需要创建 cheating_detected alert 的 FAIL
AUDIT_CHEATING_STATUSES = {AUDIT_STATUS_FAIL_CHEATING, AUDIT_STATUS_FAIL_CHEATING_DECLARED}

# === 门闸 ID（见 dev-docs/029 §6.2）===
GATE_AUDIT_LAUNCH = "GATE-AUDIT-LAUNCH"
GATE_AUDIT_KILL_SESSION = "GATE-AUDIT-KILL-SESSION"
GATE_AUDIT_FINALIZE_PASS = "GATE-AUDIT-FINALIZE-PASS"
GATE_AUDIT_FINALIZE_FAIL = "GATE-AUDIT-FINALIZE-FAIL"

# === tmux session 命名 ===
AUDIT_TMUX_PREFIX = "paudit"
