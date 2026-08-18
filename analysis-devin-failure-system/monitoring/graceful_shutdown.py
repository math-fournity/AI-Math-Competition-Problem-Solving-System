#!/usr/bin/env python3
"""graceful_shutdown.py — 优雅退出支持

各launcher/monitor通过本模块注册退出钩子，收到SIGTERM/SIGINT时：
1. 设置全局stop_flag
2. 主循环检查stop_flag，完成当前操作后退出
3. 不kill任何devin cli的tmux session（它们独立运行，自然完成）

用法:
  from monitoring.graceful_shutdown import register_shutdown, should_stop

  register_shutdown("continuation_launcher")
  while True:
      if should_stop():
          logger.info("收到退出信号，不再启动新run，等待running自然完成")
          break
      # ... 正常工作

设计参考：xishujuzhen/solver_harness/pipe/graceful_shutdown.py
"""
import signal
import threading
from monitoring.shared_logger import get_logger

logger = get_logger("shutdown")

_stop_flag = threading.Event()
_service_name = "unknown"


def _signal_handler(signum, frame):
    """信号处理函数——只设置flag，不直接退出"""
    sig_name = signal.Signals(signum).name
    logger.info(f"收到信号 {sig_name}, 服务={_service_name}, 设置stop_flag")
    _stop_flag.set()


def register_shutdown(service_name: str):
    """注册优雅退出——处理SIGTERM和SIGINT"""
    global _service_name
    _service_name = service_name

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    logger.info(f"优雅退出已注册: 服务={service_name} (SIGTERM/SIGINT → 完成当前操作后退出, 不kill devin session)")


def should_stop() -> bool:
    """检查是否应该停止"""
    return _stop_flag.is_set()


def wait_for_stop(timeout: float = None) -> bool:
    """等待stop信号"""
    return _stop_flag.wait(timeout)


def clear_stop():
    """清除stop flag（用于恢复后重新启动）"""
    _stop_flag.clear()
