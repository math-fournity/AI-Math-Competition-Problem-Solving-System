"""shared_logger.py — 错题分析系统共享日志基础设施

所有分析系统脚本通过本模块获取logger，统一写入日志目录。

日志规范（模仿solver_harness的shared_logger）：
- 日志目录: /Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/analysis-devin-failure/_logs/
- 单文件分片: 1MB
- 总量限制: 1GB（约1000个分片）
- 循环滚动: 达到上限后覆盖最老的文件
- 格式: [时间] [级别] [模块] 消息
- 同时输出到文件和stdout（方便tmux中查看）

用法:
  from monitoring.shared_logger import get_logger
  logger = get_logger("launcher")
  logger.info("启动分析批次 batch=analysis-1 concurrency=10")
  logger.error("XML解析失败", exc_info=True)
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path

# 日志目录
LOG_BASE = Path(os.environ.get("TRAJECTORY_BASE", "/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory")) / "analysis-devin-failure" / "_logs"
LOG_BASE.mkdir(parents=True, exist_ok=True)

# 日志参数
MAX_BYTES_PER_FILE = 1 * 1024 * 1024  # 1MB per file
MAX_TOTAL_BYTES = 1 * 1024 * 1024 * 1024  # 1GB total
BACKUP_COUNT = MAX_TOTAL_BYTES // MAX_BYTES_PER_FILE  # 1024

# 日志格式
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 已创建的logger缓存
_loggers = {}


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """获取一个模块的logger。

    每个模块（launcher/collector/aggregator等）有自己的日志文件，
    同时也写入一个统一的analysis.log。

    Args:
        name: 模块名（如"launcher", "collector", "aggregator"）
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

    # 1. 模块专属日志文件
    module_log = LOG_BASE / f"{name}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        str(module_log),
        maxBytes=MAX_BYTES_PER_FILE,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 2. 统一日志文件
    pipe_log = LOG_BASE / "analysis.log"
    pipe_handler = logging.handlers.RotatingFileHandler(
        str(pipe_log),
        maxBytes=MAX_BYTES_PER_FILE,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    pipe_handler.setLevel(level)
    pipe_handler.setFormatter(formatter)
    logger.addHandler(pipe_handler)

    # 3. stdout（方便tmux中查看）
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    _loggers[name] = logger
    return logger
