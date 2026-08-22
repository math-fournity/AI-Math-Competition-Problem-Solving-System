"""continuation_config.py — 续传解题管线（原POC-2.7 Pipe 4）配置常量

续传解题管线的全局配置：DB集合名/Redis key/模型/路径/阈值。
当前系统只有这一条管线——Pipe 1/2/3（分析/审计/选题）已于2026-08-20删除
（历史：本Pipe曾以"不修改Pipe 1/2/3任何代码"为设计原则接入4 Pipe体系，
复用analysis_launcher的stall/rate_limit/zombie检测模式，用独立p27:前缀
和p27_continuation_*集合避免冲突——这套隔离设计保留至今）。
"""

from pathlib import Path
import os

# === 路径常量 ===
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# D盘路径（原始做题数据）
D_SOLVER_DIR = Path(os.environ.get("SOLVER_BASE", "/Volumes/data/math-agent-glm5.2-tmux-agents-dir"))
D_TRAJ_DIR = Path(os.environ.get("TRAJECTORY_BASE", "/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory"))

# POC-2.7数据目录
POC_2_7_DIR = PROJECT_ROOT / "data" / "poc_2.7"
PROBLEM_LIST_FILE = POC_2_7_DIR / "problem_list.json"
RESULTS_FILE = POC_2_7_DIR / "results.json"

# 续传Pipe的工作目录和trajectory目录（独立于batch_continue_948.py的workdirs/trajectories）
CONTINUATION_SOLVER_BASE = D_SOLVER_DIR / "p27-continuation"
CONTINUATION_TRAJECTORY_BASE = D_TRAJ_DIR / "p27-continuation"

# conversation_mapper.py（v2方案的面包屑地图生成器）
MAPPER_SCRIPT = PROJECT_ROOT / "scripts" / "conversation_mapper.py"
CONTINUE_SPEC = PROJECT_ROOT / "docs" / "patterns" / "续传规范文档.md"

# === ArangoDB配置（复用现有）===
# ARANGO_DB/ARANGO_HOST支持env覆盖（.env里的值优先生效）——这也是全流程模拟
# （src/sim/，见dev-docs/017）的隔离旋钮：sim用独立DB名，与生产完全隔离。
ARANGO_HOST = os.environ.get("ARANGO_HOST", "http://localhost:8529")
ARANGO_DB = os.environ.get("ARANGO_DB", "xishujuzhen_math_glm52")
ARANGO_USER = "root"
ARANGO_PASSWORD = "moira123"

# SIM_MODE=1时launcher启动的devin cli命令替换为src/sim/fake_devin.py（剧本演员），
# 用于全流程模拟（详见dev-docs/017）。生产绝不设置此变量。
SIM_MODE = os.environ.get("SIM_MODE", "") == "1"

# Pipe A（HANDOVER生成）超时秒数——异步路径的强制kill阈值。
# env可调是为了sim的h_timeout剧本不用等600秒。
HANDOVER_TIMEOUT_SECONDS = int(os.environ.get("HANDOVER_TIMEOUT_SECONDS", "600"))

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
# model名必须是 devin models list 中的有效值
# GLM-5.2系列：glm-5-2(High/Free) / glm-5-2-max / glm-5-2-1m / glm-5-2-none
# 注意：不是 glm-5.2-high（点号+high后缀无效），正确名是 glm-5-2
DEVIN_MODEL = "glm-5-2"
DEVIN_PERMISSION_MODE = "dangerous"

# === 并发配置（续传比分析任务慢，需要更长的timeout/stall）===
# 并发数不在此写死（AGENTS.md 硬约束）：唯一来源 DB batch.concurrency，
# set-concurrency 设置；DB 无记录且未传参时 launcher 报错退出
DEFAULT_MAX_RUNTIME_SECONDS = 1800   # 30分钟（续传单轮可能thinking spin很久）
DEFAULT_STALL_SECONDS = 600          # 10分钟无活动判定为stall（续传解题thinking可能很长）
DEFAULT_POLL_SECONDS = 15            # 轮询间隔
# 每次调度窗口默认处理5个数学Round；不是题目生命周期上限。未正确解答的题
# 在窗口结束后保持可继续，未来窗口从下一绝对Round接续（WP-01）。
DEFAULT_ROUND_WINDOW_SIZE = 5
# 兼容旧import；新代码使用DEFAULT_ROUND_WINDOW_SIZE。
DEFAULT_MAX_ROUNDS = DEFAULT_ROUND_WINDOW_SIZE

# === 截断判定 ===
TRUNC_COMP_TOKENS_MIN = 24000        # completion_tokens >= 24000 判定为截断

# === 完成标记 ===
# 续传Pipe的devin cli会写proof.md，完成标记是proof.md存在且有boxed答案
PROOF_COMPLETE_MARKER = r"\\boxed"
PROOF_FILE_NAME = "proof.md"

# === 错误模式检测与失败分类 ===
# WP-I：定义迁移至 src/devin_cli_failure_detection.py（续传+审计共享模块）——
# 此处 re-export 保持既有 import 路径兼容（兼容层；新代码应直接 import 共享模块）
from src.devin_cli_failure_detection import (  # noqa: F401
    RATE_LIMIT_PATTERNS, CONNECTION_PATTERNS,
    INFRA_FAILURES, MODEL_FAILURES, MAX_RETRIES,
)

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
