# 框架检查清单——新Pipe必须考虑的所有方面

**用途**：未来AI为本系统创建新Pipe时，必须逐项检查本清单。每一项都是已经踩过坑、已经验证过的设计决策，不是可选的——是必须考虑的。

**使用方法**：创建新Pipe前，完整阅读本清单。每一项标注了"参考实现"的文件位置，去读那个文件理解具体怎么做。

---

## 清单总览（12项）

| 序号 | 方面 | 一句话 | 参考实现 |
|---|---|---|---|
| 1 | 独立自包含 | 不修改现有Pipe的代码，所有组件独立 | Pipe 4 (`continuation_*.py`) |
| 2 | Redis前缀隔离 | 用自己的前缀，不与其他Pipe冲突 | `continuation_redis_queue.py` (`p27:`) |
| 3 | ArangoDB集合隔离 | 用自己的集合名，不与其他Pipe冲突 | `continuation_db_schema.py` (`p27_*`) |
| 4 | tmux session命名隔离 | 用自己的前缀，不与其他Pipe冲突 | `continuation_config.py` (`TMUX_PREFIX`) |
| 5 | 动态并发 | 运行期可调整并发数，不需要重启 | `continuation_launcher.py` 第488-497行 |
| 6 | 优雅停止 | 停launcher不kill devin实例，等running自然完成 | `graceful_shutdown.py` + `stop_batch()` |
| 7 | stall检测 | pane_hash变化+idle时间，检测卡住的session | `continuation_launcher.py` `launch_batch()` |
| 8 | rate_limit处理 | 检测到rate_limit模式后自动暂停20分钟 | `continuation_launcher.py` `launch_batch()` |
| 9 | zombie session清理 | devin退出后tmux残留的空panesession | `continuation_launcher.py` `launch_batch()` |
| 10 | Monitor Pipe | 三层架构（规范+执行+查询），alert到DB | `monitor_continuation.py` + `p27_monitor_spec.md` |
| 11 | DB-文件双向可追溯 | run记录指向work_dir，work_dir有proof.md | `continuation_db_schema.py` + `continuation_collector.py` |
| 12 | 多轮续传（如适用） | v1机械拼接vs v2交接文档，截断判定 | `continuation_launcher.py` `is_truncated()`/`generate_handover()` |

---

## 逐项详解

### 1. 独立自包含

**必须**：新Pipe的所有组件独立，不修改现有Pipe 1/2/3的任何代码。

**为什么**：现有Pipe可能在运行中，修改它们的代码会影响正在运行的任务。独立自包含模式（Pipe 4模式）确保新Pipe与现有Pipe完全隔离。

**怎么做**：
- config/db_schema/redis_queue/collector/feeder/launcher/result_collector全部用`{name}_`前缀的独立文件
- 只共享`monitoring/shared_logger.py`和`monitoring/graceful_shutdown.py`
- 参考Pipe 4的8个文件结构

**参考**：`MonitorPipe.md` §6.2（11个文件清单）+ §6.6陷阱7

### 2. Redis前缀隔离

**必须**：新Pipe的Redis队列用自己的前缀（如`{name}:`），不能复用`p27:`或`analysis:`。

**为什么**：Redis队列是全局共享的，前缀冲突会导致新Pipe的dequeue取到其他Pipe的任务。

**怎么做**：
```python
# {name}_redis_queue.py
PENDING_KEY = "{name}:pending"
COMPLETED_KEY = "{name}:completed"
FAILED_KEY = "{name}:failed"
RUNNING_KEY = "{name}:running"
```

**参考**：`continuation_redis_queue.py`（`p27:`前缀）

### 3. ArangoDB集合隔离

**必须**：新Pipe的ArangoDB集合用自己的名称（如`{name}_runs`），索引名也用自己的前缀。

**为什么**：ArangoDB集合是全局共享的，集合名冲突会导致数据混在一起。

**怎么做**：
```python
# {name}_db_schema.py
RUNS_COLLECTION = "{name}_runs"
BATCHES_COLLECTION = "{name}_batches"
# 索引名
col.add_index({"name": "{name}_idx_status", ...})
```

**参考**：`continuation_db_schema.py`（`p27_continuation_*`集合）

### 4. tmux session命名隔离

**必须**：新Pipe的tmux session用自己的前缀（如`{name}-`），Monitor Pipe的session用`monitor-{name}`。

**为什么**：`tmux list-sessions | grep`用前缀匹配，前缀冲突会匹配到其他Pipe的session。

**怎么做**：
```python
# {name}_config.py
TMUX_PREFIX = "{name}"
# session命名: {name}-{problem_id}-r{round_num}
```

**参考**：`continuation_config.py`（`TMUX_PREFIX = "p27"`）

### 5. 动态并发

**必须**：launcher运行期可调整并发数，不需要重启。

**为什么**：rate_limit时需要降并发，API配额充足时需要升并发。重启launcher会中断正在运行的devin实例。

**怎么做**：launcher主循环每轮从DB读取`batch.concurrency`字段，变了就更新：
```python
batch_doc = db.collection(BATCHES_COLLECTION).get(batch_id)
new_conc = int(batch_doc.get("concurrency", concurrency))
if new_conc != concurrency:
    print(f"  [dynamic] concurrency {concurrency} → {new_conc}")
    concurrency = new_conc
```
修改并发：`db.collection("{name}_batches").update({"_key": batch_id, "concurrency": 20})`

**参考**：`continuation_launcher.py` 第488-497行

**详见**：`docs/dynamic-concurrency.md`

### 6. 优雅停止

**必须**：停止launcher时不kill正在运行的devin cli实例，让它们自然完成。**如果有watchdog，必须先停watchdog再停服务。**

**为什么**：用户明确要求（415号§9.6）"已启动的续传run不应该终止"。kill devin实例会浪费已消耗的API配额，且可能导致产出文件不完整。watchdog如果不先停，会重启刚停掉的服务——导致"停不掉"。

**怎么做**：
1. launcher启动时注册优雅退出：`register_shutdown("{name}_launcher")`
2. 主循环检查`should_stop()`，为true时不再dequeue新run，等running自然完成
3. `stop_batch()`向launcher发送SIGINT（不kill-session，不清队列）
4. 提供`--force`选项用于强制停止（kill所有session+清空队列）
5. **如果有watchdog**——stop命令的第一步必须是`stop_watchdog()`：
   - `launchctl unload` plist文件（阻止launchd重启）
   - kill watchdog的tmux session（阻止当前运行的实例）
   - 两步都要做——只做一步会导致watchdog继续运行或被launchd重启

**参考**：
- `monitoring/graceful_shutdown.py`——信号处理模块
- `continuation_launcher.py` `stop_batch()`——优雅停止实现
- `continuation_launcher.py` `launch_batch()` 第480-490行——should_stop检查
- `monitoring/continuation_control.py` `stop_watchdog()`——watchdog停止实现

**详见**：`docs/graceful-shutdown.md` §5（watchdog停止——核心问题）

### 7. stall检测

**必须**：检测卡住的devin cli session（pane内容长时间无变化）。

**为什么**：devin cli可能因为API错误、网络问题等原因卡住，不退出也不产出。不检测会浪费并发槽。

**怎么做**：每轮poll时对每个running session用`tmux capture-pane`获取pane内容，计算hash。如果hash与上次相同且idle时间>stall_seconds（默认300秒），判定为stall，kill-session并标记为failed_stall。

**参考**：`continuation_launcher.py` `launch_batch()` 中的pane_hash检测逻辑

**详见**：`docs/operational-concerns.md`

### 8. rate_limit处理

**必须**：检测到rate_limit模式后自动暂停一段时间。

**为什么**：glm-5-2 API有速率限制，高并发时容易触发。不暂停会持续触发rate_limit，浪费API调用。

**怎么做**：检测pane输出中的rate_limit模式（`RATE_LIMIT_PATTERNS`），匹配到后设置`rate_limit_paused_until = now + 1200`（20分钟），期间不启动新run。

**参考**：`continuation_launcher.py` `launch_batch()` 中的rate_limit检测逻辑

**详见**：`docs/operational-concerns.md`

### 9. zombie session清理

**必须**：devin cli退出后tmux session可能残留为空pane，需要清理。

**为什么**：tmux session不会在进程退出后自动销毁。残留的空pane session会被`tmux list-sessions`计数，导致并发数判断错误。

**怎么做**：run完成后（成功或失败），`tmux kill-session`清理对应的session。另外检测dead_session——session已退出但run没有完成标记。

**参考**：`continuation_launcher.py` `launch_batch()` 中的zombie清理逻辑

**详见**：`docs/operational-concerns.md`

### 10. Monitor Pipe

**必须**：为新Pipe创建对应的Monitor Pipe，按三层架构实现。

**为什么**：连续工作系统需要持续监控，把应该由Master AI智能检查的项目全部放入Monitor Pipe，结果收集到DB的alert集合中，Master AI通过查询脚本发现alert并处理。

**怎么做**：
1. 写检查规范（`specs/{name}_monitor_spec.md`）——A类自动检查/B类质量检查/C类AI review抽样
2. 实现Monitor Pipe守护进程（`src/monitor_{name}.py`）——按规范执行检查，写alert到`{name}_monitor_alerts`集合
3. 实现检查脚本（`scripts/monitor_check_{name}.sh`）——输出N项检查+行动清单

**参考**：
- `specs/p27_monitor_spec.md`——检查规范
- `src/monitor_continuation.py`——Monitor Pipe守护进程
- `scripts/monitor_check_continuation.sh`——检查脚本
- `MonitorPipe.md`（项目repo根目录）——完整设计范式

**详见**：`docs/monitor-pipe-pattern.md`

### 11. DB-文件双向可追溯

**必须**：DB中每条run记录指向工作目录，工作目录中有产出文件。

**为什么**：审计时需要从DB的run记录找到物理文件，也需要从物理文件找到DB记录。没有双向可追溯，产出无法验证。

**怎么做**：
- DB run记录包含`work_dir`字段（工作目录路径）和`proof_path`字段（产出文件路径）
- collector创建run记录时同时创建工作目录
- launcher更新run记录时同时更新产出文件路径
- result_collector从DB读取run记录，检查产出文件是否存在

**参考**：`continuation_collector.py`（创建run记录+工作目录）+ `continuation_result_collector.py`（检查产出文件）

### 12. 多轮续传（如适用）

**如果新Pipe涉及多轮续传**：必须实现v1机械拼接和v2交接文档两种方案，以及截断判定逻辑。

**为什么**：单次API调用的completion_tokens上限是25000，竞赛数学题的thinking可能需要超过25000 tokens。续传机制让AI在新的API调用中继续思考。

**怎么做**：
- `is_truncated()`——截断判定（rc>1000且msg=0且tc=0且comp≥24000）
- `is_completed()`——完成判定（proof.md有boxed答案）
- `generate_handover()`——v2方案，从完整探索历程提取有效内容整理成HANDOVER.md
- `build_continue_prompt()`——v1方案，机械拼接reasoning_content

**参考**：`continuation_launcher.py` 中的`is_truncated()`/`is_completed()`/`generate_handover()`函数

**详见**：`docs/operational-concerns.md`

---

## 验证清单

创建新Pipe后，逐项验证：

- [ ] import验证——所有模块能正常import
- [ ] CLI验证——`run_{name}_pipeline.py --help`和`-m src.monitor_{name} --help`正常
- [ ] 前缀隔离验证——Redis前缀、ArangoDB集合名、tmux session前缀都不与现有Pipe冲突
- [ ] 动态并发验证——修改DB中batch.concurrency，launcher下次poll时生效
- [ ] 优雅停止验证——`--stop`发送SIGINT，launcher不再启动新run，running自然完成
- [ ] 强制停止验证——`--stop --force`kill所有session+清空队列
- [ ] Monitor Pipe验证——启动后每轮检查正常，alert写入DB
- [ ] 检查脚本验证——`monitor_check_{name}.sh`输出N项检查+行动清单
- [ ] 小批量测试——10题端到端测试
