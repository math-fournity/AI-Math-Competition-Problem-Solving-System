"""shared_logger.py — 错题分析系统共享日志基础设施

所有分析系统脚本通过本模块获取logger，统一写入日志目录。

日志规范：
- 项目本地日志目录: log/（用于SOP检查和日志检索）
- D盘日志目录: $TRAJECTORY_BASE/analysis-devin-failure/_logs/（保留，历史兼容）
- 单文件分片: 1MB
- 项目本地总量限制: 500MB（约500个分片）
- D盘总量限制: 1GB（约1000个分片）
- 循环滚动: 达到上限后覆盖最老的文件
- 格式: [时间戳] [级别] [模块] 消息 [结构化字段]
- 同时输出到文件和stdout（方便tmux中查看）

结构化日志格式（用于脚本检索）：
  [2026-08-20 01:23:45] [INFO] [analysis.continuation_launcher]
  event=launch_solve problem_id=omni_math_001 round=2 session_key=p27-s0042 batch_id=p27-full

用法:
  from monitoring.shared_logger import get_logger, log_event
  logger = get_logger("continuation_launcher")
  logger.info("启动续传批次 batch=p27-full concurrency=5")

  # 结构化日志（推荐——可被log_search.py按字段检索）
  log_event(logger, "info", "launch_solve",
            problem_id="omni_math_001", round=2,
            session_key="p27-s0042", batch_id="p27-full")
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path

# 项目根目录（动态获取）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 项目本地日志目录（用于SOP检查和日志检索）
LOCAL_LOG_DIR = _PROJECT_ROOT / "log"
LOCAL_LOG_DIR.mkdir(parents=True, exist_ok=True)

# D盘日志目录（保留，历史兼容）
LOG_BASE = Path(os.environ.get("TRAJECTORY_BASE", "/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory")) / "analysis-devin-failure" / "_logs"
try:
    LOG_BASE.mkdir(parents=True, exist_ok=True)
except Exception:
    pass  # D盘可能未挂载

# 日志参数
MAX_BYTES_PER_FILE = 1 * 1024 * 1024  # 1MB per file
LOCAL_BACKUP_COUNT = 499               # 项目本地：500个文件（1当前+499备份）
D_DISK_BACKUP_COUNT = 1024             # D盘：1GB（历史兼容）

# 日志格式——带时间戳
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 已创建的logger缓存
_loggers = {}


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """获取一个模块的logger。

    每个模块有自己的日志文件，同时也写入统一日志文件。
    日志同时写入项目本地log/和D盘_logs/（如果可用）。

    Args:
        name: 模块名（如"continuation_launcher", "session_registry"）
        level: 日志级别

    Returns:
        配置好的logger
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(f"analysis.{name}")
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    # 1. 项目本地——模块专属日志文件
    local_module_log = LOCAL_LOG_DIR / f"{name}.log"
    local_handler = logging.handlers.RotatingFileHandler(
        str(local_module_log),
        maxBytes=MAX_BYTES_PER_FILE,
        backupCount=LOCAL_BACKUP_COUNT,
        encoding="utf-8",
    )
    local_handler.setLevel(level)
    local_handler.setFormatter(formatter)
    logger.addHandler(local_handler)

    # 2. 项目本地——统一日志文件
    local_pipe_log = LOCAL_LOG_DIR / "system.log"
    local_pipe_handler = logging.handlers.RotatingFileHandler(
        str(local_pipe_log),
        maxBytes=MAX_BYTES_PER_FILE,
        backupCount=LOCAL_BACKUP_COUNT,
        encoding="utf-8",
    )
    local_pipe_handler.setLevel(level)
    local_pipe_handler.setFormatter(formatter)
    logger.addHandler(local_pipe_handler)

    # 3. D盘日志（如果可用）
    try:
        d_module_log = LOG_BASE / f"{name}.log"
        d_handler = logging.handlers.RotatingFileHandler(
            str(d_module_log),
            maxBytes=MAX_BYTES_PER_FILE,
            backupCount=D_DISK_BACKUP_COUNT,
            encoding="utf-8",
        )
        d_handler.setLevel(level)
        d_handler.setFormatter(formatter)
        logger.addHandler(d_handler)

        d_pipe_log = LOG_BASE / "analysis.log"
        d_pipe_handler = logging.handlers.RotatingFileHandler(
            str(d_pipe_log),
            maxBytes=MAX_BYTES_PER_FILE,
            backupCount=D_DISK_BACKUP_COUNT,
            encoding="utf-8",
        )
        d_pipe_handler.setLevel(level)
        d_pipe_handler.setFormatter(formatter)
        logger.addHandler(d_pipe_handler)
    except Exception:
        pass  # D盘不可用时只写本地

    # 4. stdout（方便tmux中查看）
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    _loggers[name] = logger
    return logger


def log_event(logger, level, event, **meta):
    """写入结构化日志——可被 log_search.py 按字段检索。

    格式：
      event=<event_name> key1=val1 key2=val2 ...

    示例：
      log_event(logger, "info", "launch_solve",
                problem_id="omni_math_001", round=2,
                session_key="p27-s0042", batch_id="p27-full")
      → [2026-08-20 01:23:45] [INFO] [analysis.continuation_launcher]
        event=launch_solve problem_id=omni_math_001 round=2 session_key=p27-s0042 batch_id=p27-full

    Args:
        logger: get_logger() 返回的 logger
        level: "debug" / "info" / "warning" / "error"
        event: 事件名（如 "launch_solve", "check_done_md", "mark_stuck"）
        **meta: 结构化字段（problem_id, round, session_key, batch_id 等）
    """
    fields = " ".join(f"{k}={v}" for k, v in sorted(meta.items()))
    msg = f"event={event} {fields}" if fields else f"event={event}"
    level_map = {
        "debug": logger.debug,
        "info": logger.info,
        "warning": logger.warning,
        "error": logger.error,
    }
    level_fn = level_map.get(level, logger.info)
    level_fn(msg)


def get_log_dir():
    """获取项目本地日志目录路径"""
    return LOCAL_LOG_DIR


def get_log_files():
    """获取日志文件列表（按修改时间排序）"""
    files = sorted(LOCAL_LOG_DIR.glob("*.log*"), key=lambda f: f.stat().st_mtime)
    return files


def get_log_dir_info():
    """获取日志目录信息摘要"""
    files = get_log_files()
    total_size = sum(f.stat().st_size for f in files)
    return {
        "dir": str(LOCAL_LOG_DIR),
        "file_count": len(files),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "max_files": LOCAL_BACKUP_COUNT + 1,
        "max_size_mb": round((LOCAL_BACKUP_COUNT + 1) * MAX_BYTES_PER_FILE / (1024 * 1024), 0),
    }
