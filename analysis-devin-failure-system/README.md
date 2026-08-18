# analysis-devin-failure-system

> **用途**：批量并发devin cli实例的运行框架——包含4个Pipe（分析/审计/选题/续传），每个Pipe都是独立的连续工作系统，配合Monitor Pipe实现持续监控。
>
> **未来AI必读**：创建新Pipe前，必须先读`docs/framework-checklist.md`——它列出了新Pipe必须考虑的所有12个方面。

## 快速导航

### 我要创建新Pipe

→ 读`docs/framework-checklist.md`（12项必查清单）→ 参考`MonitorPipe.md` §6（11步操作指南）→ 以Pipe 4为模板复制

### 我要运行现有Pipe

| Pipe | 启动命令 | 检查命令 | 文档 |
|---|---|---|---|
| Pipe 1 分析 | `run_pipeline.py --batch-id {id} --step all` | `scripts/monitor_check.sh {id}` | — |
| Pipe 2 审计 | `run_audit_pipeline.py --batch-id {id} --step all` | `scripts/monitor_check.sh {id}` | — |
| Pipe 3 选题 | `run_selection_pipeline.py --batch-id {id} --step all` | `scripts/monitor_check_selection.sh {id}` | — |
| Pipe 4 续传 | `run_continuation_pipeline.py --batch-id {id} --step all` | `scripts/monitor_check_continuation.sh {id}` | `POC-2.7/README.md` |

### 我要停止正在运行的Pipe

```bash
# 优雅停止（默认）——不kill devin实例，等running自然完成
python -m src.continuation_launcher --batch-id {id} --stop

# 强制停止——kill所有devin实例+清空队列
python -m src.continuation_launcher --batch-id {id} --stop --force
```

### 我要调整并发数

```bash
# 修改DB中batch记录的concurrency字段（launcher下次poll时生效）
.venv/bin/python3 -c "
from src.continuation_db_schema import connect_db
db = connect_db()
db.collection('p27_continuation_batches').update({'_key': '{id}', 'concurrency': 20})
print('concurrency updated to 20')
"
```

## 文档体系

### `docs/`——架构设计文档

| 文档 | 用途 | 何时读 |
|---|---|---|
| `framework-checklist.md` | **新Pipe必读**——12项必查清单 | 创建新Pipe前 |
| `architecture.md` | 4个Pipe的演进与组件职责 | 理解系统整体架构时 |
| `graceful-shutdown.md` | 优雅停止设计——信号处理、不kill devin实例 | 实现停止功能时 |
| `dynamic-concurrency.md` | 动态并发设计——运行期调整并发数 | 实现并发调整时 |
| `monitor-pipe-pattern.md` | Monitor Pipe设计范式（本地版） | 实现Monitor Pipe时 |
| `operational-concerns.md` | 运维关注点——rate limit/stall/zombie/多轮续传/断点续传 | 实现launcher核心逻辑时 |
| `selfrun-workflow.md` | selfrun工作流 | 使用selfrun模式时 |
| `solver-trajectory-schema.md` | trajectory数据schema | 处理trajectory数据时 |

### `specs/`——检查规范（系统资产）

| 文件 | 用途 |
|---|---|
| `p27_monitor_spec.md` | Pipe 4续传的检查规范（A类9项/B类7项/C类5项） |

### 外部文档

| 文档 | 位置 | 用途 |
|---|---|---|
| `MonitorPipe.md` | 项目repo根目录 | Monitor Pipe完整设计范式+新Pipe实现指南 |
| `~/.config/devin/rules/monitor-pipe-design-paradigm.md` | 全局rule | always-on，触发条件+三层架构定义 |

## 架构概览

```
collect → feed → launch → collect-results
  ↑          ↑        ↑          ↑
  │          │        │          │
  │     Redis队列   devin cli    DB+文件
  │     (pending)   (tmux)      (产出)
  │
数据源
(ArangoDB/文件/API)
```

每个Pipe都有这4步，加上Monitor Pipe持续监控：

```
Monitor Pipe（独立tmux session）
  ├── 按检查规范执行A类+B类自动检查
  ├── C类AI review抽样→标记needs_ai_review
  ├── 发现问题→写alert到DB
  └── Master AI通过检查脚本发现alert并处理
```

**4个Pipe的演进**：Pipe 1共享基础设施 → Pipe 2/3共享+扩展 → Pipe 4独立自包含（推荐新Pipe采用）

详见`docs/architecture.md`。

## 共享基础设施

| 文件 | 用途 | 被谁共享 |
|---|---|---|
| `monitoring/shared_logger.py` | 统一日志 | 所有Pipe |
| `monitoring/graceful_shutdown.py` | 优雅退出（SIGTERM/SIGINT→设flag） | 所有Pipe的launcher+monitor |
| `src/config.py` | 路径常量+DB连接+RATE_LIMIT_PATTERNS | Pipe 1/2/3 |
| `src/db_schema.py` | ArangoDB集合定义+connect_db() | Pipe 1/2/3 |
| `monitoring/redis_queue.py` | Redis队列操作（`analysis:`前缀） | Pipe 1/2 |

## 设计原则

1. **独立自包含**（Pipe 4模式）——新Pipe不修改现有Pipe的代码
2. **优雅停止**——停launcher不kill devin实例，等running自然完成
3. **动态并发**——运行期可调整并发数，不需要重启
4. **Monitor Pipe**——应该由AI智能检查的项目全部放入Pipe，结果收集到DB
5. **DB-文件双向可追溯**——DB中run记录指向工作目录，工作目录有产出文件
6. **痕迹保留**——alert写入ArangoDB，全过程可审计
