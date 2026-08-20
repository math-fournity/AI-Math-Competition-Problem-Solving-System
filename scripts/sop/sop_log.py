"""sop_log.py — SOP 日志模块

日志写入 log/ 目录，循环覆盖机制：
  - 最多 500 个日志文件
  - 每个文件最大 1MB
  - 超过 500 个文件时，最旧的被覆盖
  - 总磁盘占用不超过 500MB

日志文件命名：sop_YYYYMMDD_HHMMSS_NNN.log
  NNN 是序号（000-499），循环复用。

用法：
  from scripts.sop.sop_log import get_logger
  log = get_logger("run")       # 模块名
  log.info("消息")
  log.error("错误")
"""

import logging
import logging.handlers
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent.parent / "log"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 日志参数
MAX_FILES = 500              # 最多500个日志文件
MAX_FILE_SIZE = 1024 * 1024  # 每个文件最大1MB
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name="sop"):
    """获取一个配置好循环日志的 logger。

    Args:
        name: 模块名（如 "run", "checks", "state"）

    Returns:
        logging.Logger 实例
    """
    logger = logging.getLogger(f"sop.{name}")
    if logger.handlers:
        # 已经配置过，不重复添加handler
        return logger

    logger.setLevel(logging.DEBUG)

    # 循环文件handler——最多MAX_FILES个文件，每个最大MAX_FILE_SIZE字节
    # RotatingFileHandler 的 backupCount 参数控制保留的备份文件数
    # 当 backupCount=MAX_FILES 时，最多有 MAX_FILES+1 个文件（当前+备份）
    # 为了严格限制在 MAX_FILES 个文件，用 backupCount=MAX_FILES-1
    handler = logging.handlers.RotatingFileHandler(
        filename=str(LOG_DIR / "sop_current.log"),
        maxBytes=MAX_FILE_SIZE,
        backupCount=MAX_FILES - 1,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # 同时输出到stdout（方便实时观察）
    stdout_handler = logging.StreamHandler()
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    return logger


def get_log_files():
    """获取当前日志目录中的文件列表（按修改时间排序）"""
    files = sorted(LOG_DIR.glob("sop_*.log*"), key=lambda f: f.stat().st_mtime)
    return files


def get_log_dir_size():
    """获取日志目录总大小（字节）"""
    return sum(f.stat().st_size for f in LOG_DIR.glob("sop_*.log*"))


def get_log_dir_info():
    """获取日志目录信息摘要"""
    files = get_log_files()
    total_size = get_log_dir_size()
    return {
        "file_count": len(files),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "max_files": MAX_FILES,
        "max_size_mb": round(MAX_FILES * MAX_FILE_SIZE / (1024 * 1024), 0),
        "dir": str(LOG_DIR),
    }
