# 优雅停止设计

## 1. 问题背景

连续工作系统运行时间可能长达数小时到数天。停止时不能直接kill正在运行的devin cli实例——因为：

1. **用户明确要求**（415号§9.6）："已启动的续传run不应该终止"
2. **浪费API配额**——kill devin实例会浪费已消耗的completion_tokens
3. **产出不完整**——kill可能导致proof.md/HANDOVER.md写到一半
4. **DB状态不一致**——kill后run状态卡在running，需要recover处理

## 2. 设计参考

参考解题系统（`xishujuzhen/solver_harness/pipe/`）的优雅停止实现：
- `graceful_shutdown.py`——信号处理模块
- `pipe_stop.sh`——4种停止模式（graceful/finish/force/kill）
- `pipe_control.py`的`stop_service()`——发送SIGINT+等待退出

## 3. 实现

### 3.1 信号处理模块（`monitoring/graceful_shutdown.py`）

```python
import signal, threading

_stop_flag = threading.Event()

def _signal_handler(signum, frame):
    """信号处理函数——只设置flag，不直接退出"""
    _stop_flag.set()

def register_shutdown(service_name):
    """注册优雅退出——处理SIGTERM和SIGINT"""
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

def should_stop() -> bool:
    """检查是否应该停止"""
    return _stop_flag.is_set()
```

**核心设计**：信号处理函数只设flag，不直接退出。主循环检查flag，完成当前操作后退出。

### 3.2 launcher主循环（`continuation_launcher.py`）

```python
def launch_batch(...):
    # 注册优雅退出
    register_shutdown("continuation_launcher")

    while True:
        # 退出条件
        if not running and pending_count(r) == 0:
            break

        # 优雅退出检查——收到SIGTERM/SIGINT后不再启动新run
        if should_stop():
            if not running:
                print("running已全部完成，launcher退出")
                break
            else:
                print(f"不再启动新run，等待{len(running)}个running自然完成...")
                time.sleep(poll_seconds)

        # 启动新的——优雅退出模式下跳过
        while not should_stop() and len(running) < concurrency and pending_count(r) > 0:
            # dequeue + 启动devin cli
            ...

        # 检查running状态（无论是否should_stop都继续检查）
        ...
```

**核心设计**：
1. `should_stop()`为true时，不再dequeue新run
2. 已在running的devin cli session继续独立运行（不kill）
3. 等所有running自然完成后，launcher退出

### 3.3 stop_batch()（`continuation_launcher.py`）

```python
def stop_batch(batch_id, force=False):
    if force:
        # 强制模式：kill所有session+清空队列
        ...
    else:
        # 优雅模式：向launcher发送SIGINT
        launcher_pids = pgrep -f "continuation_launcher.*{batch_id}"
        for pid in launcher_pids:
            os.kill(int(pid), 2)  # SIGINT
        # 不kill devin session，不清空队列
```

**两种模式**：
- **优雅停止**（默认）：`--stop` → 向launcher发送SIGINT → launcher不再启动新run → running自然完成
- **强制停止**：`--stop --force` → kill所有session+清空队列 → 立即停止

## 4. 使用方法

```bash
# 优雅停止（默认）——不kill devin实例
python -m src.continuation_launcher --batch-id p27-full --stop

# 强制停止——kill所有devin实例+清空队列
python -m src.continuation_launcher --batch-id p27-full --stop --force

# 通过continuation_control停止（推荐——自动处理watchdog）
python -m monitoring.continuation_control stop          # 优雅
python -m monitoring.continuation_control stop --force  # 强制
```

## 5. watchdog停止——核心问题

### 问题

watchdog通过launchd自动启动后，停止系统时如果只kill服务tmux session而不停watchdog，watchdog会在30秒内重启刚停掉的服务——导致"停不掉"。

### 根因

watchdog有两种启动方式：
1. **launchd自动启动**——通过plist文件，进程退出后launchd自动重启
2. **手动tmux运行**——`tmux new-session -d -s p27-watchdog "bash continuation_watchdog.sh"`

只kill tmux session不够（launchd会重启）；只unload plist不够（手动运行的进程继续）。

### 解决方案

`stop_watchdog()`函数必须同时做两步：
1. `launchctl unload` plist文件（阻止launchd重启）
2. kill watchdog的tmux session或进程（阻止当前运行的实例）

```python
def stop_watchdog():
    # 步骤1：卸载launchd plist（如果存在）
    if os.path.exists(WATCHDOG_PLIST):
        subprocess.run(["launchctl", "unload", WATCHDOG_PLIST], ...)

    # 步骤2：kill tmux session（如果存在）
    if tmux_running(WATCHDOG_SESSION):
        subprocess.run(["tmux", "kill-session", "-t", WATCHDOG_SESSION], ...)
```

### 在stop命令中的位置

**stop_watchdog()必须是stop命令的第一步**——在停launcher和monitor之前。否则：
1. 停launcher → watchdog检测到launcher死了 → 重启launcher
2. 你以为停了，实际上launcher又被watchdog拉起来了

### 解题系统的同步修复

解题系统（`xishujuzhen/solver_harness/pipe/pipe_stop.sh`）的`--kill`/`--finish`/`--force`三种模式都已加入：
1. `launchctl unload` plist
2. `pkill -f "pipe_watchdog.sh"` kill手动运行的watchdog进程

默认优雅停止模式保留watchdog（守护collector），但在提示中明确告知用户watchdog仍在运行，需要用`--finish`或`--force`来停watchdog。

## 6. 新Pipe如何实现

1. 复制`monitoring/graceful_shutdown.py`（共享模块，不需要复制）
2. launcher启动时调用`register_shutdown("{name}_launcher")`
3. 主循环加入`should_stop()`检查
4. dequeue循环条件加`not should_stop()`
5. `stop_batch()`实现两种模式（graceful+force）
6. **如果有watchdog**——stop命令的第一步必须是`stop_watchdog()`（unload plist + kill session）

**参考**：`continuation_launcher.py`的完整实现 + `continuation_control.py`的`stop_watchdog()`
