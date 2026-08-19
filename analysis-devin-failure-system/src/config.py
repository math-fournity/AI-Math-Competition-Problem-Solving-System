"""config.py — 配置常量

路径、DB连接、并发配置等。
所有组件共享这些常量。
"""

from pathlib import Path
import os

# === 路径常量 ===
# 项目根目录（动态获取——config.py在src/下，三层parent回到repo根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# solver工作目录基址（devin cli的--work-dir）
SOLVER_BASE = Path(os.environ.get("SOLVER_BASE", "/Volumes/data/math-agent-glm5.2-tmux-agents-dir"))

# trajectory目录基址（AI解题过程数据）
TRAJECTORY_BASE = Path(os.environ.get("TRAJECTORY_BASE", "/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory"))

# 分析系统的工作目录基址（分析devin cli的工作目录）
ANALYSIS_SOLVER_BASE = SOLVER_BASE / "analysis-devin-failure"

# 分析系统的trajectory目录基址
ANALYSIS_TRAJECTORY_BASE = TRAJECTORY_BASE / "analysis-devin-failure"

# 题库数据位置
DATASET_BASE = Path(os.environ.get("DATASET_BASE", "/Volumes/data/math-manify/raw_downloads"))
KNOWLEDGE_BASE = Path(os.environ.get("KNOWLEDGE_BASE", "/Users/user/glm5.2-math-worktree/knowledge/problem_banks"))

# 各题库的具体路径
DATASET_PATHS = {
    "polymath": DATASET_BASE / "PolyMath" / "data" / "train-00000-of-00001.parquet",
    "polymath_normal": DATASET_BASE / "PolyMath" / "normal" / "train-00000-of-00001.parquet",
    "polymath_revised": DATASET_BASE / "PolyMath" / "revised" / "train-00000-of-00001.parquet",
    "deepmath_dir": DATASET_BASE / "DeepMath-103K" / "data",
    "oda_math_dir": DATASET_BASE / "ODA-Math-460k" / "data",
    "omni_math": DATASET_BASE / "Omni-MATH-2" / "Omni-Math-2.jsonl",
    "olympiadbench": KNOWLEDGE_BASE / "aops_instruct" / "eval" / "data" / "olympiadbench" / "test.json",
    "aime": KNOWLEDGE_BASE / "aops_instruct" / "eval" / "data" / "aime24" / "test.jsonl",
    "amo_bench": DATASET_BASE / "AMO-Bench" / "data" / "test-00000-of-00001.parquet",
    "compfiles": KNOWLEDGE_BASE / "compfiles" / "Compfiles",
    "fate": KNOWLEDGE_BASE / "fate",
}

# 模板文件
AGENTS_MD_TEMPLATE = PROJECT_ROOT / "analysis-devin-failure-system" / "templates" / "analysis_agents_md.md"

# 输出目录
OUTPUT_BASE = PROJECT_ROOT / "analysis-devin-failure-system" / "output"

# === ArangoDB配置 ===
ARANGO_HOST = "http://localhost:8529"
ARANGO_DB = "xishujuzhen_math_glm52"
ARANGO_USER = "root"
ARANGO_PASSWORD = "moira123"

# 分析系统的DB集合名
ANALYSIS_RUNS_COLLECTION = "analysis_runs"       # 每道题的分析run记录
ANALYSIS_EVENTS_COLLECTION = "analysis_events"    # 事件流
ANALYSIS_RESULTS_COLLECTION = "analysis_results"  # 最终分析结果

# === devin cli配置 ===
DEVIN_MODEL = "glm-5.2-high"
DEVIN_PERMISSION_MODE = "dangerous"
DEVIN_PROMPT = (
    "请执行以下分析任务：对比标准解答和AI的解题过程，判定AI为什么失败。"
    "分析任务说明、题目、标准解答、AI解题过程已在你收到的prompt文件中。"
    "你不需要read任何文件，不需要调用任何工具。"
    "直接在TUI中输出XML分析结果，不要写任何文件，不要执行任何命令，不要搜索。"
    "结尾输出 ### ANALYSIS COMPLETE"
)

# === 并发配置 ===
DEFAULT_CONCURRENCY = 10
DEFAULT_MAX_RUNTIME_SECONDS = 300    # 5分钟（分析任务比解题快）
DEFAULT_STALL_SECONDS = 120          # 2分钟无活动判定为stall
DEFAULT_POLL_SECONDS = 10            # 轮询间隔

# === thinking文本获取的4级优先级 ===
THINKING_PRIORITY = [
    "mitm/thinking_readable.txt",
    "sessions_db/trajectory.jsonl",
    "exports/conversation.json",
    "collector/pane_snapshot_clean.txt",
]

# === 分析结果中的XML标记 ===
ANALYSIS_COMPLETE_MARKER = "### ANALYSIS COMPLETE"
XML_BLOCK_START = "<analysis>"
XML_BLOCK_END = "</analysis>"

# === 错误模式检测（对齐solver_harness的collector.py）===
# 基础设施失败——重试
RATE_LIMIT_PATTERNS = ["rate limit", "rate_limit", "429", "Too Many Requests",
                       "message rate limit", "http 429", "status 429"]
CONNECTION_PATTERNS = ["connection error", "ECONNREFUSED", "ETIMEDOUT",
                       "socket hang up", "fetch failed", "network error",
                       "network request failed", "ECONNRESET"]

# 失败分类（对齐solver_harness）
# 基础设施失败——重试（网络问题、API限流、进程异常退出）
INFRA_FAILURES = {"rate_limited", "failed_connection", "launch_error", "dead_session"}
# 模型能力失败——不重试（分析超时、分析卡住、无XML输出）
MODEL_FAILURES = {"failed_timeout", "failed_stall", "failed_no_xml", "failed_incomplete"}

# 重试配置
MAX_RETRIES = 3
