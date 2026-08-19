"""continuation_config.py — POC-2.7续传Pipe配置常量

POC-2.7的续传Pipe（Pipe 4），接入错题分析系统框架。
对948道被Pipe 1判定为DIRECTION_ERROR的题启动续传机制。

与现有3个Pipe的关系：
  Pipe 1 分析（analysis_launcher）   → 判定d1=DIRECTION_ERROR
  Pipe 2 审计（audit_launcher）       → 审计分析结果
  Pipe 3 选题（selection_launcher）   → 选题给POC-2.5
  Pipe 4 续传（continuation_launcher）→ 对DIRECTION_ERROR题续传，判定截断vs思维错误  ← 本文件

设计原则：
  - 不修改现有3个Pipe的任何代码
  - 复用analysis_launcher的stall/rate_limit/zombie检测模式
  - 用独立的Redis队列前缀p27:避免冲突
  - 用独立的DB集合p27_continuation_*避免冲突
"""

from pathlib import Path

# === 路径常量 ===
PROJECT_ROOT = Path("/Users/user/glm5.2-math-worktree")

# D盘路径（原始做题数据）
D_SOLVER_DIR = Path("/Volumes/data/math-agent-glm5.2-tmux-agents-dir")
D_TRAJ_DIR = Path("/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory")

# POC-2.7数据目录（与batch_continue_948.py共用）
POC_2_7_DIR = PROJECT_ROOT / "Tell分类学研究过程文档" / "poc_assets" / "poc_2.7" / "poc_2.7"
PROBLEM_LIST_FILE = POC_2_7_DIR / "problem_list.json"
RESULTS_FILE = POC_2_7_DIR / "results.json"

# 续传Pipe的工作目录和trajectory目录（独立于batch_continue_948.py的workdirs/trajectories）
CONTINUATION_SOLVER_BASE = D_SOLVER_DIR / "p27-continuation"
CONTINUATION_TRAJECTORY_BASE = D_TRAJ_DIR / "p27-continuation"

# conversation_mapper.py（v2方案的面包屑地图生成器）
MAPPER_SCRIPT = PROJECT_ROOT / "scripts" / "conversation_mapper.py"
CONTINUE_SPEC = PROJECT_ROOT / "续传规范文档.md"

# === ArangoDB配置（复用现有）===
ARANGO_HOST = "http://localhost:8529"
ARANGO_DB = "xishujuzhen_math_glm52"
ARANGO_USER = "root"
ARANGO_PASSWORD = "moira123"

# 续传Pipe的DB集合（独立于现有Pipe）
CONTINUATION_BATCHES_COLLECTION = "p27_continuation_batches"
CONTINUATION_RUNS_COLLECTION = "p27_continuation_runs"
CONTINUATION_EVENTS_COLLECTION = "p27_continuation_events"
CONTINUATION_RESULTS_COLLECTION = "p27_continuation_results"
MONITOR_ALERTS_COLLECTION = "p27_monitor_alerts"

# === Session编号化管理（见specs/p27_session_management_and_polish_spec.md §A）===
# 所有devin cli实例（solve/handover/monitor_exec）的tmux session注册到这个集合
SESSIONS_COLLECTION = "p27_sessions"
# 全局序号计数器——存在一个单独的文档中，allocate_seq原子递增
SESSION_COUNTER_KEY = "p27_session_counter"
# Monitor Exec Devin的配置（见specs/p27_session_management_and_polish_spec.md §B.7）
MONITOR_EXEC_CONCURRENCY = 1
MONITOR_EXEC_INTERVAL = 300          # 两轮之间的最小间隔（秒）
MONITOR_EXEC_EXPORT_BASE = D_TRAJ_DIR / "p27-monitor-exec"
MONITOR_EXEC_MAX_RUNTIME_SECONDS = 900  # 一轮最多15分钟

# === devin cli配置 ===
DEVIN_MODEL = "glm-5-2"
DEVIN_PERMISSION_MODE = "dangerous"

# === 并发配置（续传比分析任务慢，需要更长的timeout/stall）===
DEFAULT_CONCURRENCY = 5
DEFAULT_MAX_RUNTIME_SECONDS = 1800   # 30分钟（续传单轮可能thinking spin很久）
DEFAULT_STALL_SECONDS = 600          # 10分钟无活动判定为stall（续传解题thinking可能很长）
DEFAULT_POLL_SECONDS = 15            # 轮询间隔
DEFAULT_MAX_ROUNDS = 5               # 最多续传5轮

# === 截断判定 ===
TRUNC_COMP_TOKENS_MIN = 24000        # completion_tokens >= 24000 判定为截断

# === 完成标记 ===
# 续传Pipe的devin cli会写proof.md，完成标记是proof.md存在且有boxed答案
PROOF_COMPLETE_MARKER = r"\\boxed"
PROOF_FILE_NAME = "proof.md"

# === 错误模式检测（复用config.py的模式）===
RATE_LIMIT_PATTERNS = ["rate limit", "rate_limit", "429", "Too Many Requests",
                       "message rate limit", "http 429", "status 429"]
CONNECTION_PATTERNS = ["connection error", "ECONNREFUSED", "ETIMEDOUT",
                       "socket hang up", "fetch failed", "network error",
                       "network request failed", "ECONNRESET"]

# 失败分类
INFRA_FAILURES = {"rate_limited", "failed_connection", "launch_error", "dead_session"}
MODEL_FAILURES = {"failed_timeout", "failed_stall", "failed_no_proof", "truncated_at_max"}

# 重试配置
MAX_RETRIES = 3

# === v2方案配置 ===
# v2方案每轮2个pipe：Pipe A生成HANDOVER.md + Pipe B解题
# 用2个Redis子队列实现流水线
HANDOVER_PENDING_KEY = "p27:pending_handover"   # 待生成HANDOVER.md
SOLVE_PENDING_KEY = "p27:pending_solve"          # 待解题（已有HANDOVER.md）
HANDOVER_RUNNING_KEY = "p27:running_handover"
SOLVE_RUNNING_KEY = "p27:running_solve"
HANDOVER_COMPLETED_KEY = "p27:completed_handover"
SOLVE_COMPLETED_KEY = "p27:completed_solve"
HANDOVER_FAILED_KEY = "p27:failed_handover"
SOLVE_FAILED_KEY = "p27:failed_solve"
STATS_KEY = "p27:stats"

# v1方案用单一队列
V1_PENDING_KEY = "p27:pending"
V1_RUNNING_KEY = "p27:running"
V1_COMPLETED_KEY = "p27:completed"
V1_FAILED_KEY = "p27:failed"

# === tmux session命名 ===
# 格式：p27-{pid}-r{round}（解题） / p27-{pid}-r{round}-h（HANDOVER生成）
TMUX_PREFIX = "p27"
