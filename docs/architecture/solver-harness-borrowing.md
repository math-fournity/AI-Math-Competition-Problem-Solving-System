# 解题系统借鉴分析——7个值得借鉴的设计

**用途**：记录解题系统（`xishujuzhen/solver_harness/pipe/`）中值得借鉴到错题分析系统的设计，以及对POC-2.7后续工作的帮助。

**分析日期**：2026-08-18

---

## 1. 多模块解耦——6个独立服务（最重要）

### 解题系统的实现

6个独立进程，各自在独立tmux session中运行：

| 服务 | 职责 | 触发方式 | auto-restart |
|---|---|---|---|
| feeder | 从DB取题入Redis pending队列 | low-water mark触发（pending<1000时补充） | ✅ |
| runner | 从Redis dequeue+启动devin cli | 持续轮询，填满并发槽 | ✅ |
| collector | 监控running的session+判定终态 | 持续轮询running队列 | ✅ |
| reporter | 定时输出统计报告 | 定时（60秒） | ✅ |
| retry | 基础设施失败自动重试 | 定时（120秒） | ✅ |
| monitor | Monitor Pipe（alert生成） | 定时（300秒） | ✅ |

### 错题分析系统Pipe 4的现状

`continuation_launcher.py`一个进程做所有事——dequeue+启动+stall检测+rate_limit检测+完成判定+多轮续传。这是单体设计。

### 权衡

**解耦的好处**：
- collector可以独立更新（修判定bug）而不停runner
- retry逻辑独立，不影响launcher主循环
- reporter是轻量级独立进程，不占用launcher的poll时间

**对Pipe 4的权衡**：多轮续传逻辑（v2 handover生成+下一轮prompt构造）与launcher紧耦合——collector判定"截断"后需要立即启动下一轮。拆成独立collector会增加进程间通信复杂度。

**建议**：保留单体launcher，但把retry和reporter拆出去。

---

## 2. auto-restart机制

### 解题系统的实现

用bash while循环包裹每个服务：
```bash
while true; do python runner.py 2>&1; echo "[auto-restart] runner退出, 5秒后重启..."; sleep 5; done
```

服务崩溃（Redis断连、未处理异常）后5秒自动重启。

### 错题分析系统现状

`analysis_control.py`对retry服务有auto-restart，但launcher的`auto_restart=False`。Pipe 4的`continuation_launcher.py`完全没有auto-restart——`run_continuation_pipeline.py`直接在当前进程调用`launch_batch()`。

### 借鉴方案

创建`continuation_control.py`（类似`pipe_control.py`），提供`start`命令把launcher启动到tmux session（带auto-restart）。

**对POC-2.7的帮助**：919题跑8天，launcher崩溃不重启会导致整个batch停滞。

---

## 3. watchdog（launchd守护进程）

### 解题系统的实现

`pipe_watchdog.sh`通过macOS launchd每30秒检查5个服务是否活着，死了就重启；每5分钟跑`recover_from_crash.py`清理zombie。

### 错题分析系统现状

没有watchdog。如果launcher崩溃且没有auto-restart，需要人工发现并重启。

### 借鉴方案

创建`scripts/continuation_watchdog.sh`，适配p27-前缀。可选通过launchd plist自动启动。

**对POC-2.7的帮助**：8天运行期需要无人值守的守护。

---

## 4. 精细化classify()——10+终态分类

### 解题系统的实现

collector.py的`classify()`函数有10+种verdict，按优先级判定：

| 优先级 | verdict | 类型 | 说明 |
|---|---|---|---|
| 1 | answer_leak | 约束违反 | 题目文本包含答案 |
| 2 | ai_gave_up | 模型能力 | AI主动放弃 |
| 3 | candidate_solved | 成功 | 有真实proof+无工具调用 |
| 3.5 | failed_token_limit | 基础设施 | 输出达到max token |
| 3.6 | rate_limited | 基础设施 | API限流 |
| 4 | failed_thinking_spin | 模型能力 | 超时且仍在thinking |
| 4 | failed_timeout | 模型能力 | 超时 |
| 5 | failed_no_proof | 模型能力 | session结束但无proof |
| 6 | dead_session | 基础设施 | devin退出但无proof |
| 6.5 | crash_recovered | 基础设施 | tmux server死亡 |
| 6.6 | failed_stall | 基础设施 | 卡在启动阶段 |

### 错题分析系统Pipe 4现状

终态分类较粗——COMPLETED/TRUNCATED/TRUNCATED_AT_MAX/failed_stall/failed_launch/dead_session。

### 借鉴方案

Pipe 4应借鉴这个分类体系，特别是区分"基础设施失败"（可重试）和"模型能力失败"（不可重试，是数据）。

---

## 5. 基础设施失败 vs 模型能力失败的区分

### 解题系统的实现

`retry_infrastructure.py`明确区分：
```python
# 基础设施失败——重试
INFRA_FAILURES = {"failed_connection", "rate_limited", "launch_error", "dead_session"}

# 模型能力失败——不重试，是Profile数据
MODEL_FAILURES = {
    "failed_token_limit", "failed_output_limit", "ai_gave_up",
    "failed_thinking_spin", "failed_no_proof", "failed_stall",
    "invalid_tool_use",
}
```

### 价值

基础设施失败重试3次后入pending重新启动；模型能力失败不重试——它们是AI能力边界的数据，重试只会得到同样的结果。

### 错题分析系统现状

有`retry_infrastructure.py`但Pipe 4没有集成这个区分。Pipe 4的多轮续传本质上是一种"重试"，但没有区分"基础设施问题导致的失败"（应该重试）和"AI能力问题导致的失败"（不应该续传，是数据）。

### 借鉴方案

Pipe 4的终态分类应明确区分这两类，retry_infrastructure只重试基础设施失败。

---

## 6. 数据验证工具集

### 解题系统的实现

| 工具 | 用途 | 错题分析系统是否有 |
|---|---|---|
| verify_completeness.py | ID完整性/Redis-DB一致性/tmux一致性 | ✅有 |
| verify_run_integrity.py | 无工具调用/真实thinking/真实proof | ❌缺 |
| check_answer_leak.py | 题目文本是否包含答案 | ❌缺 |
| reclassify_failed.py | 重新分类被误判的failed记录 | ❌缺 |
| concurrency_safety_check.py | 竞态条件/资源泄漏检查 | ❌缺 |
| fix_orphan_running.py | 修复DB-Redis孤儿记录 | ❌缺 |

### 借鉴方案

`reclassify_failed.py`和`fix_orphan_running.py`对Pipe 4最有价值——8天运行中collector判定逻辑可能有bug，需要能重新分类；DB-Redis可能出现孤儿记录需要修复。

---

## 7. reporter作为独立服务

### 解题系统的实现

reporter.py是独立进程，每60秒输出统计报告到日志文件。

### 错题分析系统现状

有`reporter.py`但不确定是否作为独立服务用于Pipe 4。Pipe 4的进度信息目前通过`monitor_check_continuation.sh`查询。

### 借鉴方案

reporter作为独立服务可以提供持续的趋势记录（每60秒一条），比每次手动查询更有价值——可以看到吞吐量变化趋势。

---

## 借鉴优先级

| 优先级 | 借鉴项 | 对POC-2.7的帮助 | 工作量 | 实现状态 |
|---|---|---|---|---|
| **P0** | auto-restart for launcher | 防止8天运行中launcher崩溃导致停滞 | 小 | ✅已实现 |
| **P0** | watchdog | launchd守护，自动重启+定期清理zombie | 中 | ✅已实现 |
| **P1** | 基础设施vs模型失败区分 | retry只重试基础设施失败，不浪费API配额 | 中 | ✅已实现 |
| **P1** | reclassify_failed + fix_orphan_running | 修判定bug和DB-Redis孤儿 | 中 | ✅已实现 |
| **P2** | 精细化classify() | 更准确的终态分类，更好的数据分析 | 大 | 待实现 |
| **P2** | reporter独立服务 | 持续趋势记录 | 小 | 待实现 |
| **P3** | 多模块解耦（拆retry/reporter） | collector可独立更新 | 大 | 待实现 |
