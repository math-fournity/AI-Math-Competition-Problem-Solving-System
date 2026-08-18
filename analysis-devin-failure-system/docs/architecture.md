# 架构设计——4个Pipe的演进与组件职责

## 1. 系统概览

错题分析系统是一个批量并发devin cli实例的运行框架，包含4个Pipe：

| Pipe | 用途 | 模式 | 核心文件 |
|---|---|---|---|
| Pipe 1 分析 | 判定失败题是"方向出错"还是"token不够" | 共享基础设施 | `data_collector`/`analysis_launcher`/`result_collector`/`aggregator` |
| Pipe 2 审计 | 审计分析结果的质量 | 共享+扩展 | `audit_collector`/`audit_launcher`/`audit_result_collector`/`audit_aggregator` |
| Pipe 3 选题 | 为Mid-Hint实验选题+6字段元数据 | 共享+扩展 | `selection_collector`/`selection_launcher`/`selection_result_collector` |
| Pipe 4 续传 | 948道DIRECTION_ERROR题全量续传 | **独立自包含** | `continuation_config`/`continuation_db_schema`/...（8个文件） |

## 2. 4个Pipe的演进

### Pipe 1（共享基础设施）

最早实现的Pipe。所有共享组件在这一层定义：
- `src/config.py`——路径常量、DB连接、并发配置
- `src/db_schema.py`——ArangoDB集合定义+`connect_db()`/`ensure_schema()`
- `monitoring/redis_queue.py`——Redis队列操作（`analysis:`前缀）
- `monitoring/shared_logger.py`——统一日志
- `src/monitor_pipe.py`——Pipe 1/2共用的Monitor Pipe
- `scripts/monitor_check.sh`——Pipe 1/2共用的检查脚本

### Pipe 2（共享+扩展）

复用Pipe 1的config/db_schema/connect_db，但有自己的：
- `audit_collector`/`audit_launcher`/`audit_result_collector`/`audit_aggregator`
- `monitoring/audit_redis_queue.py`（`audit:`前缀）
- `templates/audit_agents_md.md`

### Pipe 3（共享+扩展）

复用Pipe 1的config/db_schema/connect_db，但有自己的：
- `selection_collector`/`selection_launcher`/`selection_result_collector`
- `src/monitor_selection.py`——独立的Monitor Pipe
- `scripts/monitor_check_selection.sh`——独立的检查脚本
- `templates/selection_agents_md.md`

### Pipe 4（独立自包含）

**推荐新Pipe采用此模式**。不修改现有Pipe的任何代码，所有组件独立：
- `continuation_config.py`——自己的配置常量
- `continuation_db_schema.py`——自己的ArangoDB集合+`connect_db()`
- `continuation_redis_queue.py`——自己的Redis队列（`p27:`前缀）
- `continuation_collector.py`/`continuation_feeder.py`/`continuation_launcher.py`/`continuation_result_collector.py`
- `monitor_continuation.py`——自己的Monitor Pipe
- `specs/p27_monitor_spec.md`——自己的检查规范
- `scripts/monitor_check_continuation.sh`——自己的检查脚本
- `run_continuation_pipeline.py`——端到端入口

**只共享**：`monitoring/shared_logger.py`和`monitoring/graceful_shutdown.py`

## 3. 每个Pipe的4步架构

所有Pipe都遵循相同的4步架构：

```
collect → feed → launch → collect-results
```

| 步骤 | 职责 | 输入 | 输出 |
|---|---|---|---|
| collect | 从数据源取题+创建工作目录+创建DB run记录 | 数据源（ArangoDB/文件/API） | DB中`{name}_runs`集合的prepared记录 |
| feed | 从DB取prepared的run，入Redis pending队列 | DB中prepared记录 | Redis `{name}:pending`队列 |
| launch | 从Redis dequeue+启动devin cli+监控状态+处理完成/失败 | Redis pending队列 | DB中run状态更新+tmux session+产出文件 |
| collect-results | 从DB读取完成的run+检查产出+通过率判定+Markdown汇总 | DB中completed记录 | Markdown汇总报告 |

## 4. 共享基础设施

| 文件 | 用途 | 被谁共享 |
|---|---|---|
| `monitoring/shared_logger.py` | 统一日志（每个模块一个logger） | 所有Pipe |
| `monitoring/graceful_shutdown.py` | 优雅退出（SIGTERM/SIGINT→设flag） | 所有Pipe的launcher+monitor |
| `src/config.py` | 路径常量+DB连接+RATE_LIMIT_PATTERNS | Pipe 1/2/3 |
| `src/db_schema.py` | ArangoDB集合定义+connect_db() | Pipe 1/2/3 |
| `monitoring/redis_queue.py` | Redis队列操作（`analysis:`前缀） | Pipe 1/2 |

## 5. 目录结构

```
analysis-devin-failure-system/
├── README.md                    # 索引——指向docs/
├── docs/                        # 文档体系
│   ├── architecture.md          # 本文件——架构设计
│   ├── framework-checklist.md   # 框架检查清单——新Pipe必读
│   ├── graceful-shutdown.md     # 优雅停止设计
│   ├── dynamic-concurrency.md   # 动态并发设计
│   ├── monitor-pipe-pattern.md  # Monitor Pipe设计范式（本地版）
│   ├── operational-concerns.md  # 运维关注点（rate limit/stall/zombie/多轮续传）
│   ├── selfrun-workflow.md      # selfrun工作流
│   └── solver-trajectory-schema.md # trajectory schema
├── specs/                       # 检查规范（系统资产）
│   └── p27_monitor_spec.md      # Pipe 4的检查规范
├── src/                         # 代码
│   ├── config.py                # Pipe 1/2/3共享配置
│   ├── db_schema.py             # Pipe 1/2/3共享DB
│   ├── data_collector.py        # Pipe 1 collector
│   ├── analysis_launcher.py     # Pipe 1 launcher
│   ├── ...                      # Pipe 1/2/3各组件
│   ├── continuation_config.py   # Pipe 4配置（独立）
│   ├── continuation_db_schema.py# Pipe 4 DB（独立）
│   ├── continuation_redis_queue.py # Pipe 4 Redis（独立）
│   ├── continuation_collector.py# Pipe 4 collector
│   ├── continuation_feeder.py   # Pipe 4 feeder
│   ├── continuation_launcher.py # Pipe 4 launcher（核心）
│   ├── continuation_result_collector.py # Pipe 4 result collector
│   ├── monitor_pipe.py          # Pipe 1/2的Monitor Pipe
│   ├── monitor_selection.py     # Pipe 3的Monitor Pipe
│   └── monitor_continuation.py  # Pipe 4的Monitor Pipe
├── monitoring/                  # 共享基础设施
│   ├── shared_logger.py         # 统一日志
│   ├── graceful_shutdown.py     # 优雅退出
│   ├── redis_queue.py           # Pipe 1/2的Redis队列
│   ├── audit_redis_queue.py     # Pipe 2的Redis队列
│   ├── recover_from_crash.py    # 断电恢复
│   ├── runtime_health_check.py  # 运行时健康检查
│   └── ...
├── scripts/                     # 检查脚本
│   ├── monitor_check.sh         # Pipe 1/2的检查脚本
│   ├── monitor_check_selection.sh # Pipe 3的检查脚本
│   └── monitor_check_continuation.sh # Pipe 4的检查脚本
├── templates/                   # AGENTS.md模板
│   ├── analysis_agents_md.md    # Pipe 1的AGENTS.md模板
│   ├── audit_agents_md.md       # Pipe 2的AGENTS.md模板
│   └── selection_agents_md.md   # Pipe 3的AGENTS.md模板
├── run_pipeline.py              # Pipe 1端到端入口
├── run_audit_pipeline.py        # Pipe 2端到端入口
├── run_selection_pipeline.py    # Pipe 3端到端入口
└── run_continuation_pipeline.py # Pipe 4端到端入口
```

## 6. Pipe 4的DB记录设计

### rounds_log结构

每轮（包括成功/截断/失败）都写入rounds_log，包含完整中间产物路径：

```python
{
    "round": 2,                    # 轮次编号
    "export": ".../round2/exports/conversation.json",  # 本轮export
    "truncated": False,            # 是否截断
    "completed": True,             # 是否完成
    "reason": "proof.md有boxed",   # 完成原因/截断原因/失败原因
    "method": "v2",                # 使用的方法（v2或v1回退）
    "handover_success": True,      # Pipe A是否成功
    "handover_path": ".../round1_HANDOVER.md",  # HANDOVER.md路径
    "map_path": ".../round1_conversation_map.md",  # 面包屑地图路径
    "prompt_path": ".../round2_prompt.txt",  # 续传prompt路径
    "prev_export": ".../round1_export.json",  # 前一轮export路径
    "proof_path": ".../round2_proof.md",  # 归档的proof路径（不会被覆盖）
}
```

通过`make_round_log_entry()`函数统一构造，确保字段名一致。

### event类型

| event_type | 触发时机 | 含义 |
|---|---|---|
| continuation_launched | 每轮启动时 | 含handover_success和session_name |
| continuation_completed | 完成时 | proof.md有boxed |
| continuation_truncated | 截断续传时 | 重新入队等下一轮 |
| continuation_truncated_at_max | 达到最大轮次时 | TRUNCATED_AT_MAX |
| continuation_failed | dead_session/unknown/timeout/stall | 模型能力失败 |
| infra_failure | rate_limited/failed_connection | 基础设施失败 |

### proof.md归档机制

- 完成判定时归档：`shutil.copy2(work_dir/proof.md, work_dir/round{N}_proof.md)`
- 启动新round前删除旧proof.md：防止is_completed误判
- run级`proof_path`指向归档路径（`round{N}_proof.md`），不会被后续round覆盖

### 中间产物路径约定

work_dir内（每道题独立，用round编号区分）：
- `round1_export.json` — Round 1的原始export（从seed_export复制，仅Round 1）
- `round{N}_prompt.txt` — Round N的续传prompt
- `round{N}_handover_prompt.txt` — Round N的Pipe A prompt
- `round{N}_conversation_map.md` — Round N的面包屑地图
- `round{N}_HANDOVER.md` — Round N的交接文档
- `round{N}_handover_run/` — Round N的Pipe A运行目录
- `round{N}_proof.md` — Round N的归档proof
- `proof.md` — 当前round的proof（启动新round前删除，防止is_completed误判）

trajectory目录中按run_key/round{N}/分目录（Round 2+的export和tmux日志）：
- `{run_key}/round{N}/exports/conversation.json` — Round N的export
- `{run_key}/round{N}/tmux/tmux.log` — Round N的tmux日志
