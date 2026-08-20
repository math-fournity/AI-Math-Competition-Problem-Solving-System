# POC-2.7 Session编号化管理与打磨devin架构规范（系统资产）

**用途**：定义两件事的规范——
1. **Session编号化管理**：所有devin cli实例的tmux session必须编号化命名、注册到DB、状态可追踪，export保留有铁律
2. **打磨devin架构**：Monitor Pipe发现问题后，自动触发一个devin cli实例去修复代码，其export被完整保留

本规范是 `p27_monitor_spec.md` 的演进——后者定义"检查什么"，本规范定义"检查发现问题后怎么自动修复"以及"修复过程的session怎么管"。

**对应文档**：
- 检查规范：`specs/p27_monitor_spec.md`（本规范的前置依赖）
- 设计范式：`MonitorPipe.md`（跨项目的Monitor Pipe设计范式）
- 系统总索引：`AnalysisSystemDesign.md`
- 续传规范：`续传规范文档.md`（项目repo根目录）

**诞生背景**（2026-08-19）：
POC-2.7全量续传运行中，连续修复了30个commit的bug。暴露两个根本问题：
1. **export丢失**：系统过早kill还在写export的devin cli（或其tmux session），导致thinking数据永久丢失。根因是session管理没有"等DONE.md"的铁律，rate_limited/timeout/force-stop都会主动kill
2. **上下文漂移**：Master Agent在长程打磨中，随着上下文增长，当初约定的打磨注意事项被遗忘。根因是打磨约定散落在AGENTS.md/dev-docs/commit message中，没有蒸馏成自包含SOP，也没有从Master Agent下放到专门的devin cli执行

---

## §A. Session编号化管理规范

### A.1 问题诊断

当前session管理有三个缺陷，全部来自最近30个commit的bug修复记录：

| 缺陷 | 表现 | 相关commit |
|---|---|---|
| **命名撞名** | 同一题同轮重跑，session名重复，`tmux_kill`杀掉旧的（可能正在写export） | 06cb5c7（proof.md被覆盖）、34d05f4（export未写入） |
| **无注册表** | `tmux list-sessions`只显示活着的session，死了的没痕迹，无法知道"哪些没产出DONE.md就死了" | 7f22460（服务session混入计数）、3a85f6f（同上） |
| **主动kill无DONE.md的session** | rate_limited/timeout/force-stop都主动kill，devin cli可能还在写export | 34d05f4、87c60fe、81bcbaf（三连修复export缺失） |

### A.2 命名规则

**全局序号**：单调递增的整数，从DB的 `p27_session_counter` 文档读取（`_key=session_counter`，字段 `seq`）。每次创建session前 `seq += 1` 并写回。序号是注册表的主键，永不复用。

**命名格式**：

```
服务session（单例，命名不变，不进注册表）:
  p27-launcher
  monitor-p27
  p27-watchdog

解题session（Solver，进注册表）:
  p27-s{seq:04d}-solve-{run_key_short}-r{round}
  例: p27-s0042-solve-CC101bare-r2

handover session（生成HANDOFF.md的devin，进注册表）:
  p27-s{seq:04d}-handover-{run_key_short}-r{round}
  例: p27-s0043-handover-CC101bare-r1

打磨session（修复代码的devin，进注册表）:
  p27-s{seq:04d}-polish-{alert_type}-{seq_in_alert}
  例: p27-s0044-polish-export_missing-1
```

**`run_key_short`**：run_key的短形式（去掉batch前缀和特殊字符），保证session名可读且不超长。如果run_key本身不超长，直接用run_key。

**为什么用 `p27-s{seq:04d}-` 前缀**：
- `p27-` 保持与现有命名兼容（`list_p27_sessions` 的grep pattern不用改）
- `s{seq:04d}-` 提供全局序号，永不撞名，可按序号枚举
- 后缀语义化（`solve`/`handover`/`polish`），一眼看出session类型

### A.3 注册表 Schema

**ArangoDB collection**：`p27_sessions`（新建，由 `continuation_db_schema.ensure_schema()` 创建）

**文档结构**：

```python
{
    "_key": "p27-s0042",              # = session_name的前半段（去掉语义后缀）
    "seq": 42,                        # 全局序号
    "session_name": "p27-s0042-solve-CC101bare-r2",
    "type": "solve",                  # solve | handover | polish
    "batch_id": "p27-full",

    # solve/handover特有
    "run_key": "p27-full-CC101bare",
    "round": 2,

    # polish特有
    "triggered_by_alert": "p27-alert-20260819-export_missing-CC101bare",
    "alert_type": "export_missing",

    # 通用
    "started_at": "2026-08-19T00:15:26Z",
    "started_at_ts": 1724036126,
    "done_md": False,                 # DONE.md是否出现
    "done_md_at": None,               # DONE.md出现的时间
    "export_path": "/Volumes/data/.../conversation.json",
    "work_dir": "/Volumes/data/...",
    "tmux_log_path": "/Volumes/data/.../tmux/tmux.log",
    "status": "running",              # running | done | stuck | cleaned
    "tmux_alive": True,               # tmux session是否还在（每轮检查时更新）
    "pid": 12345,                     # devin cli进程pid（如果可获取）
    "exit_code": None,                # DONE.md里的exit code
    "notes": "",                      # 自由文本（如"force-stopped by user"）
}
```

**索引**：
- `seq`（unique）——序号唯一（仅session记录有seq字段，session_counter文档用counter字段避开此索引）
- `session_name`（unique）——session名唯一
- `status`——按状态查询
- `batch_id + type`——按批次和类型查询
- `triggered_by_alert`——polish session按触发alert查询

### A.4 状态流转

```
                ┌─────────────────────────────────────────┐
                │                                         │
                ▼                                         │
  created ──► running ──► done ──► cleaned                │
                │              (DONE.md出现,             │
                │               export已落盘,            │
                │               可安全清理)               │
                │                                         │
                ├──► stuck ──────────────────────────────►│
                │   (超时/rate_limit但DONE.md未出现       │
                │    — 不kill, 不占并发槽,                │
                │    等Master Agent在用户授意下处理)       │
                │                                         │
                └──► cleaned (session自然消失,            │
                                 注册表标记cleaned)        │
```

**状态定义**：

| 状态 | 含义 | tmux session | DONE.md | 占并发槽 | 谁能清理 |
|---|---|---|---|---|---|
| `running` | devin cli正在执行 | 存在 | 否 | 是 | 不可清理 |
| `done` | devin cli已退出，export已落盘 | 可能还在（sleep 999999） | 是 | 否 | Master Agent（安全） |
| `stuck` | 超时/rate_limit但devin cli没退出 | 存在 | 否 | 否 | Master Agent（需用户授意） |
| `cleaned` | tmux session已被kill | 不存在 | - | 否 | - |

**关键铁律**：
1. **`running` 状态绝不kill** — devin cli可能正在写export
2. **`stuck` 状态不自动kill** — 标记stuck后从并发槽释放，但session留在tmux里继续跑。只有Master Agent在用户明确授意下才能清理
3. **`done` 状态可以安全清理** — DONE.md已出现，export已落盘，kill session只是清理sleep进程
4. **`cleaned` 是终态** — 一旦标记cleaned，不再变化

### A.5 "绝不kill无DONE.md"的实现要点

当前 `continuation_launcher.py` 里有5处 `tmux_kill`，需要分类处理：

| 场景 | 当前行为 | 新行为 | 理由 |
|---|---|---|---|
| 正常完成（有proof+DONE.md） | kill ✅ | 不变 | DONE.md已出现，安全 |
| dead_session（session已消失） | kill ✅ | 不变 | session已没了，kill是no-op |
| rate_limited | kill ❌ | **改为标记stuck，不kill** | devin可能还在写export，rate_limit是临时问题 |
| timeout | kill ❌ | **改为标记stuck，不kill** | 同上，timeout可能是thinking spin |
| stall | kill ❌ | **改为标记stuck，不kill** | 同上 |
| stop --force | kill所有 ❌ | **改为：只清理done的，stuck的标记后留给用户** | force不应该是"无脑杀" |

**stuck的处理流程**：
1. 在注册表标记 `status=stuck`
2. 从 `running` dict 移除（释放并发槽，让新题能进来）
3. session 留在 tmux 里继续跑（devin cli可能自己恢复或自然退出）
4. 如果devin cli后来自然退出并写了DONE.md → 注册表自动更新为 `done`
5. Master Agent 通过 `sessions --stuck` 发现并处理

**stop --force 的新逻辑**：
```python
def cmd_stop_force():
    # 1. 停watchdog（不变）
    stop_watchdog()
    # 2. 停launcher和monitor服务（不变）
    stop_service("launcher", LAUNCHER_SESSION, graceful=False)
    stop_service("monitor", MONITOR_SESSION, graceful=False)
    # 3. 处理devin cli session——分类处理
    sessions = list_all_p27_sessions_from_registry()
    for s in sessions:
        if s["status"] == "done":
            tmux_kill(s["session_name"])  # 安全清理
            mark_cleaned(s["_key"])
        elif s["status"] == "stuck":
            print(f"  ⚠️ stuck session未清理: {s['session_name']} (需用户授意)")
            print(f"     清理命令: continuation_control sessions --clean {s['_key']}")
        elif s["status"] == "running":
            print(f"  ⚠️ running session未清理: {s['session_name']} (devin cli可能正在写export)")
            print(f"     等待DONE.md或用户授意后清理")
    # 4. 清空Redis队列（不变）
    clear_redis()
```

### A.6 管理命令（加到 `continuation_control.py`）

新增 `sessions` 子命令：

```bash
# 列出所有session（从注册表，对比tmux实际状态）
python -m monitoring.continuation_control sessions --batch-id p27-full

# 只看特定状态
python -m monitoring.continuation_control sessions --status stuck
python -m monitoring.continuation_control sessions --status done
python -m monitoring.continuation_control sessions --status running

# 只看polish session
python -m monitoring.continuation_control sessions --type polish

# 清理特定session（需用户授意——命令本身不问，由调用者保证）
python -m monitoring.continuation_control sessions --clean p27-s0042

# 批量清理所有done的（安全操作，export已落盘）
python -m monitoring.continuation_control sessions --clean-done

# 一致性检查——注册表 vs tmux实际session
python -m monitoring.continuation_control sessions --consistency-check
```

**`--consistency-check` 输出**：
```
=== Session一致性检查 ===
注册表中有 45 个session，tmux中有 43 个session

注册表有但tmux无（已自然退出，需标记cleaned）:
  p27-s0042 (status=done, DONE.md=True)  → 自动标记cleaned
  p27-s0043 (status=stuck, DONE.md=False) → ⚠️ stuck session消失了，可能devin cli崩溃

tmux有但注册表无（孤儿session，需人工检查）:
  p27-s0099  → ⚠️ 未注册的session，可能是手动启动的
```

### A.7 Monitor Pipe的session检查项（扩展p27_monitor_spec.md的A类检查）

在 `p27_monitor_spec.md` 的A类自动检查中新增：

| 检查项 | 函数 | 检查内容 | alert_type |
|---|---|---|---|
| **A10** | `check_session_registry_consistency()` | 注册表 vs tmux实际session的一致性 | `session_registry_inconsistency` |
| **A11** | `check_stuck_sessions()` | stuck状态session的数量和时长 | `stuck_session_accumulated` |
| **A12** | `check_done_sessions_uncleaned()` | done状态但未清理的session数量（占tmux资源） | `done_session_uncleaned` |

**A10的alert标准**：任何不一致都写critical alert
**A11的alert标准**：stuck session > 5 个时写warning，> 10 个写critical
**A12的alert标准**：done未清理 > 20 个时写info（不紧急，但占tmux资源）

---

## §B. ~~Monitor Pipe执行devin架构规范~~（已废弃 2026-08-19）

> **废弃说明**：§B 定义的"Monitor Exec Devin"（独立 devin cli 做 AI 检查+修复）不再实现。由 **Master Agent SOP 流程控制机制**取代——Master Agent 自己通过 `scripts/sop/run.py` 的 7 步自驱动循环承载 C 类 AI 检查+修复工作。详见 `dev-docs/013-Master-Agent-SOP流程控制机制方案.md`。
>
> §A（Session 编号化管理）仍然有效且已实现。以下 §B 内容保留作为历史参考。

### B.0 设计起源与当前实现的背离

**用户原意**（Monitor Pipe最初提出时）：
- Master Agent监控整个系统运行时，有些检查可以通过Python程序完成，有些检查需要AI的智能性
- 把需要AI智能性的检查，放入Monitor Pipe
- **Monitor Pipe应该启动一个devin cli，替Master Agent对整个系统做智能性检查**

**当前实现的背离**（`monitor_continuation.py` 实际代码 + `MonitorPipe.md` §2.2"澄清"）：
- Monitor Pipe被实现为纯Python脚本
- C类"AI review"只写 `needs_ai_review=True` 标记到DB，没有启动devin cli，没有做任何AI判断
- 真正的AI智能性检查落到了Master Agent头上——Master Agent运行检查脚本，看行动清单第7条去人工做C类检查
- `MonitorPipe.md` §2.2甚至把"Monitor Pipe不是devin cli实例"写成了设计原则——这是对用户原意的降级

**本规范的修正**：
- Monitor Pipe的执行层恢复为**两层**：Python部分（A/B类，代码能做的）+ devin cli部分（C类，需要AI智能性的）
- devin cli部分不仅做C类AI检查，还做**发现问题的修复**——这是Monitor Pipe执行devin的自然延伸
- Master Agent退出这个检查+修复的循环——Master Agent只在用户主动询问时介入，或自愈循环长时间无法解决问题时介入

### B.1 角色定义

**Monitor Pipe执行devin**（Monitor Exec Devin）是Monitor Pipe执行层的AI部分，不是独立的新角色：

| 角色 | 职责 | 启动方式 | export保留 |
|---|---|---|---|
| Solver Devin | 做数学题 | launcher自动启动 | 是（DONE.md机制） |
| Handover Devin | 生成HANDOVER.md | launcher自动启动 | 是（DONE.md机制） |
| **Monitor Exec Devin** | **C类AI检查 + 发现问题 + 修复问题** | **Python定时启动** | **是（DONE.md机制）** |
| Master Agent | 用户主动询问时介入；自愈循环长时间无法解决时介入 | 用户session | - |

**Monitor Exec Devin不是Master Agent**：
- 不能spawn subagent（devin cli非交互模式本身不支持，prompt里也明确禁止）
- 不能决定系统架构方向（只修具体问题，不改规范）
- 不能push代码（只commit到本地，push需Master Agent在用户授意下做）
- 不能修改AGENTS.md/spec/MonitorPipe.md/AnalysisSystemDesign.md等规范文件

### B.2 工作循环——三位一体

Monitor Exec Devin的工作是**检查+判断+修复**三位一体，不是三个独立角色，不是一个只检测不修复的旁观者：

```
Python定时启动Monitor Exec Devin（每N分钟一轮，或Monitor Pipe Python部分发现新alert时启动）
  │
  ▼
Monitor Exec Devin执行（一个devin cli实例，非交互模式）:
  │
  ├── 1. 检查（运行检查脚本，获取系统状态）
  │     bash monitor_check_continuation.sh p27-full
  │     → 获取7项检查结果 + 所有未处理alert + 行动清单
  │
  ├── 2. 判断（AI智能性——C类检查在这里发生）
  │     ├── 逐个读alert，判断是代码bug还是数据问题还是基础设施问题
  │     ├── 对C类检查项做AI判断：
  │     │   - 读proof.md判断数学正确性（C1 proof_quality）
  │     │   - 读export判断方向正确性（C5 continuation_direction）
  │     │   - 判断是否有幻觉（C2 proof_hallucination）
  │     │   - 判断是否答案泄漏（C3 answer_leak）
  │     │   - 判断handover质量（C4 handover_quality）
  │     │   这些是Python做不了的，必须AI判断
  │     └── 综合判断：哪些问题需要修复，哪些只需要记录
  │
  ├── 3. 修复（发现问题就去修）
  │     ├── 代码bug → 读代码 → 定位根因 → 修复 → py_compile验证 → git commit
  │     ├── 数据问题（如proof_missing但题没做出来）→ 标记为模型能力问题，不修代码
  │     ├── 基础设施问题（如rate_limit）→ 不修，等恢复
  │     ├── 需要重跑的题 → 改DB status为prepared重新入队
  │     └── 需要重启的服务 → 重启launcher/monitor
  │
  ├── 4. 写MONITOR_EXEC_REPORT.md（本轮检查+修复的完整报告）
  │     - 检查了什么、发现了什么、判断了什么、修复了什么、验证结果
  │
  └── 5. 退出（DONE.md出现）
  │
  ▼
Python部分下一轮定时启动
```

**关键认知**：
- **检查不是只检测不修复**——发现问题和修复问题是一个连续动作，不是两个角色
- **判断由devin cli做，不由Python做**——Python不做"该不该修"的认知决策，devin cli自己判断
- **Master Agent不在这个循环里**——Master Agent不需要事后审计每一轮，自愈循环自己运行
- **C类检查在这里真正发生**——不再是写个标记等Master Agent来看，而是devin cli当场做AI判断

### B.3 启动机制

**Python部分**（`monitor_continuation.py` 的主循环）负责定时启动Monitor Exec Devin：

```python
# monitor_continuation.py 的主循环改动
while True:
    # A类 + B类检查（纯Python，不变）
    run_ab_checks(db, batch_id)  # 写alert到DB

    # ★ 新增：定时启动Monitor Exec Devin
    if should_launch_monitor_exec(db, batch_id):
        launch_monitor_exec(db, batch_id)

    # 检查上一轮Monitor Exec Devin是否完成（DONE.md出现）
    check_monitor_exec_completion(db, batch_id)

    # 退出条件（不变）
    if all_done(db, batch_id):
        break

    sleep(interval)
```

**`should_launch_monitor_exec(db, batch_id)` 的判断逻辑**：
- 注册表中没有 `type=monitor_exec, status=running` 的记录（上一轮还没完成就不启动新的）
- 距离上一轮Monitor Exec Devin完成已过 `MONITOR_EXEC_INTERVAL`（默认300秒）
- 或者：有新的critical alert且上一轮已完成

**不是由alert类型硬编码集合触发**——这是与之前Polish Devin设计的根本区别。Python不做"这个alert该不该修"的认知决策，只做"该不该启动一轮检查"的时序控制。修不修由devin cli自己判断。

### B.4 Monitor Exec Devin的启动命令与工作目录

**工作目录（cwd）**：在外部目录，不在worktree内——与Solver Devin相同的原因（避免worktree的AGENTS.md劫持devin cli行为）：

```
/Volumes/data/p27-monitor-exec/{exec_seq}/
  monitor_exec_prompt.txt     # 启动prompt
  conversation.json           # --export的产出（完整thinking）
  DONE.md                     # 退出标记
  MONITOR_EXEC_REPORT.md      # 本轮检查+修复报告
  tmux/tmux.log               # tmux日志
```

**启动命令**（在 `monitor_continuation.py` 或新的 `monitor_exec_launcher.py` 中）：

```bash
work_dir="/Volumes/data/p27-monitor-exec/{exec_seq}"
mkdir -p "$work_dir/tmux"

devin -p \
  --prompt-file "$work_dir/monitor_exec_prompt.txt" \
  --model glm-5-2-high \
  --respect-workspace-trust false \
  --permission-mode dangerous \
  --export "$work_dir/conversation.json"; \
  echo $? > "$work_dir/DONE.md"; \
  sleep 999999
```

**session命名**（进注册表，type=monitor_exec）：
```
p27-s{seq:04d}-monitor-exec-{exec_seq}
例: p27-s0042-monitor-exec-7
```

### B.5 Monitor Exec Devin的Prompt构造

**核心认知**：Monitor Exec Devin"就是未来的你"——它和Master Agent是同一个角色定位，都是管理这个系统的AI。它需要像Master Agent一样充分了解系统全貌，不是最小化认知。区别只是它运行在外部目录（避免worktree AGENTS.md工作系统规则劫持行为流程），按prompt+WORKLOG自主工作。

**Prompt模板**（落盘到 `templates/monitor_exec_prompt.md`）：

```markdown
# Monitor Pipe执行devin任务

你是POC-2.7续传系统的Monitor Pipe执行devin。你就是未来的Master Agent——管理这个系统的AI。你的任务是**检查系统状态 + 做AI智能性判断 + 修复发现的问题**。

## 你是第{exec_seq}次被唤醒

你的work_dir编号就是你的唤醒次数。从编号你知道自己的位置。

## 第0步：读WORKLOG.md（在你做任何事之前）

读你work_dir中的WORKLOG.md。它是从上一轮复制来的跨轮次连续工作日志——记录了之前每次唤醒做了什么、发现了什么、修了什么、想到了什么。读它你就知道之前发生了什么，不用从零开始。

如果WORKLOG.md为空或异常（第1次唤醒，或上一轮WORKLOG丢失），你是从零开始，但要意识到这一点。

## 然后加载认知资产（充分了解系统——像Master Agent一样）

你是这个系统的管理者，需要像Master Agent一样了解系统全貌。用绝对路径读取以下文档：

1. ../../docs/specs/p27_monitor_pipe_operations.md —— ★你的认知资产入口★（检查项目完整清单+self检查+工作流程）
2. ../../docs/specs/p27_monitor_spec.md —— A/B/C类检查详细标准
3. ../../docs/specs/p27_session_management_and_polish_spec.md —— session管理+你的工作规范
4. ../../docs/system/AnalysisSystemDesign.md —— 系统总索引（文档体系/规范/代码资产/设计原则/关键决策）
5. ../../docs/patterns/MonitorPipe.md —— Monitor Pipe三层架构设计范式
6. ../../docs/patterns/续传规范文档.md —— 续传机制标准规范

按需读取（遇到相关问题时）：
- docs/architecture/ 下的架构/优雅停止/运维关注点/框架检查清单等

## 你的工作循环

1. **读WORKLOG**——知道之前发生了什么（第0步已做）
2. **加载认知**——了解系统全貌（上面已做）
3. **检查**——运行检查脚本获取系统状态和所有未处理alert
4. **判断**——逐个读alert和产出文件，做AI智能性判断（C类检查）
5. **修复**——发现代码bug就修，发现数据问题就处理，发现基础设施问题就记录
6. **报告**——写MONITOR_EXEC_REPORT.md + 续写WORKLOG.md
7. **退出**

## 第一步：运行检查脚本

```bash
cd ../..
bash scripts/monitor_check_continuation.sh p27-full
```

读输出中的7项检查结果 + 所有未处理alert + 行动清单。

## 第二步：做AI智能性判断（C类检查）

对检查脚本输出中标记 `needs_ai_review` 的条目，逐个做AI判断：

- **C1 proof_quality**：读proof.md，判断数学正确性
- **C2 proof_hallucination**：判断proof是否有幻觉（编造定理/编造结果）
- **C3 answer_leak**：判断是否答案泄漏（prompt中泄露了答案）
- **C4 handover_quality**：读HANDOVER.md，判断交接文档质量
- **C5 continuation_direction**：读export，判断续传方向是否正确（是在上一轮基础上继续还是从头重复）

这些是Python做不了的判断，必须由你（AI）来做。

## 第三步：修复发现的问题

根据检查和判断的结果，分类处理：

### 代码bug（如export_missing/rounds_log_integrity/intermediate_product_uniqueness）
1. 读相关代码（用绝对路径）：
   - ../../src/continuation_launcher.py
   - ../../src/monitor_continuation.py
   - ../../monitoring/continuation_control.py
2. 定位根因（不是症状）
3. 修复
4. 验证：`python -m py_compile <修改的文件>`
5. git commit（见下方git规范）

### 数据问题（如proof_missing但题没做出来）
- 这是模型能力问题，不是代码bug——不修代码
- 在MONITOR_EXEC_REPORT.md中记录："X道题proof_missing，判定为模型能力问题，建议不重试"

### 基础设施问题（如rate_limit/failed_connection）
- 不修——等恢复
- 在MONITOR_EXEC_REPORT.md中记录

### 需要重跑的题
- 改DB中run的status为prepared，重新入Redis队列
- 命令：`&& .venv/bin/python3 -c "..."` （具体见续传规范）

### 需要重启的服务
- launcher挂了：`&& .venv/bin/python3 -m monitoring.continuation_control start --batch-id p27-full --concurrency 1`
- monitor挂了：同上（start命令会同时启动launcher和monitor）

## 严格约束

1. **不能spawn subagent**——你自己完成所有工作
2. **不能push代码**——只commit到本地
3. **文档同步分级**（详见p27_monitor_pipe_operations.md §4.5）：
   - **第一级（事实性文档）——你必须和代码同步修改，在同一个commit中**：
     - docs/architecture/ 下的所有模块文档（architecture/operational-concerns/graceful-shutdown/dynamic-concurrency/framework-checklist/monitor-pipe-pattern/solver-harness-borrowing）
     - AnalysisSystemDesign.md §4 代码资产索引
     - docs/specs/*.md 的§2/§3/§A/§B实现细节（检查项/检查标准/session管理/Exec Devin实现细节）
   - **第二级（架构级规范）——你不能改，只在REPORT和WORKLOG中记录建议**：
     - ../../AGENTS.md
     - ../../.devin/rules/*.md
     - ../../docs/patterns/MonitorPipe.md 的三层架构定义和设计原则
     - ../../docs/system/AnalysisSystemDesign.md 的§5设计原则和§6关键设计决策
   - **判定标准**：改的是"是什么"（事实→第一级，自己改）还是"应该是什么"（设计决策→第二级，记录建议）
4. **git操作规范**：
   - 禁止 `git add -A` / `git add .` / `git add -u`
   - 只 `git add <具体路径>`
   - git命令用 `-C ../..` 指定repo
   - commit message格式：`修复<alert_type或问题简述>: <一句话描述>`
   - commit message末尾加：
     ```
     Generated with [Devin](https://devin.ai)

     Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
     ```
5. **修完必须验证**——`python -m py_compile <修改的文件>` 确认无语法错误
6. **写MONITOR_EXEC_REPORT.md + 续写WORKLOG.md**——在work_dir中写本轮报告（见下方格式），并在WORKLOG.md末尾追加本轮记录（见下方WORKLOG格式）
7. **只修本轮发现的问题**——不要重构、不要改架构、不要"顺便"修其他问题

## 最近的代码修改（git log --oneline -10）

{git_log_recent}

## MONITOR_EXEC_REPORT.md格式（本轮正式报告）

```markdown
# Monitor Exec Report #{exec_seq}

**时间**: {timestamp}
**检查批次**: p27-full

## 检查结果摘要

- A类alert: X个
- B类alert: Y个
- C类AI判断: Z项（其中W项有问题）

## C类AI判断详情

### C1 proof_quality
- problem_id X: 判定PASS/FAIL，原因...
- problem_id Y: 判定PASS/FAIL，原因...

### C5 continuation_direction
- problem_id Z: 判定方向正确/方向错误，原因...

## 修复操作

### 修复1: {alert_type或问题简述}
- 根因: ...
- 修复: ...
- commit: {hash}
- 验证: py_compile通过

### 修复2: ...

## self-check结果

- S1-S14: 全部通过 / S5未通过（py_compile失败，已修复重试通过）

## 未修复的问题（及原因）

- {问题}: {为什么不修——模型能力问题/基础设施问题/需要用户决策}

## 下一轮建议

- {如果有的话}
```

## WORKLOG.md续写格式（追加到从上一轮复制来的WORKLOG末尾）

在WORKLOG.md的末尾追加以下内容（不覆盖已有内容）：

```markdown
---

## 唤醒 #{exec_seq} · {timestamp}

### 检查发现
- A类alert: X个（列举关键的）
- B类alert: Y个
- C类AI判断: Z项（W项PASS，V项FAIL）

### 修复操作
- {修复简述}: {根因一句话} → {方案一句话}. commit {hash}
- {修复简述}: ...

### 思考
- {你为什么这么修、发现了什么模式、对系统的观察——这是WORKLOG最宝贵的部分}
- {上一轮WORKLOG中提到的建议，本轮是否采纳、结果如何}

### self-check结果
- S1-S14: 全部通过 / {哪些未通过及处理}
```
```

**Prompt构造逻辑**（在 `monitor_continuation.py` 或 `monitor_exec_launcher.py` 中）：

```python
def build_monitor_exec_prompt(exec_seq, db):
    git_log = subprocess.run(
        ["git", "log", "--oneline", "-10"],
        capture_output=True, text=True,
        cwd="../.."
    ).stdout
    return render_template("templates/monitor_exec_prompt.md", {
        "exec_seq": exec_seq,
        "git_log_recent": git_log,
    })

def prepare_worklog(exec_seq, work_dir):
    """启动前准备WORKLOG.md——从上一轮复制，或第1次创建"""
    import shutil
    if exec_seq == 1:
        (work_dir / "WORKLOG.md").write_text("# Monitor Exec Devin Worklog\n\n")
    else:
        prev_worklog = Path(f"/Volumes/data/p27-monitor-exec/{exec_seq - 1}/WORKLOG.md")
        if prev_worklog.exists():
            shutil.copy2(prev_worklog, work_dir / "WORKLOG.md")
        else:
            # 向前找最近的WORKLOG
            for seq in range(exec_seq - 1, 0, -1):
                candidate = Path(f"/Volumes/data/p27-monitor-exec/{seq}/WORKLOG.md")
                if candidate.exists():
                    shutil.copy2(candidate, work_dir / "WORKLOG.md")
                    return
            # 全部丢失
            (work_dir / "WORKLOG.md").write_text(
                f"# Monitor Exec Devin Worklog\n\n"
                f"## 唤醒 #{exec_seq}\n\n"
                f"**⚠️ 异常**：未找到上一轮的WORKLOG.md，本轮从空开始。\n\n"
            )
```

**注意**：
- prompt不注入alert详情——Monitor Exec Devin自己运行检查脚本获取alert，自己做判断
- prompt不注入WORKLOG内容——Monitor Exec Devin自己读work_dir中的WORKLOG.md（Python部分已从上一轮复制好）
- Python不做任何认知层面的预筛选

### B.6 export保留与session管理

Monitor Exec Devin的export路径：

```
/Volumes/data/p27-monitor-exec/{exec_seq}/conversation.json
/Volumes/data/p27-monitor-exec/{exec_seq}/DONE.md
/Volumes/data/p27-monitor-exec/{exec_seq}/MONITOR_EXEC_REPORT.md
/Volumes/data/p27-monitor-exec/{exec_seq}/WORKLOG.md          ← 从上一轮复制+本轮续写
/Volumes/data/p27-monitor-exec/{exec_seq}/tmux/tmux.log
```

**保留铁律**：与Solver Devin相同——等DONE.md出现才处理，绝不主动kill无DONE.md的session（见§A.5）。**WORKLOG.md是跨轮连续记忆，必须保留**——下一轮启动时要从本轮复制。

**与Solver/Handover Devin的隔离**：
- 工作目录隔离：Monitor Exec Devin在 `/Volumes/data/p27-monitor-exec/{exec_seq}/`，Solver在 `/Volumes/data/.../p27-continuation/{run_key}/`
- tmux session命名隔离：`p27-s{seq}-monitor-exec-*` vs `p27-s{seq}-solve-*` vs `p27-s{seq}-handover-*`
- 并发槽隔离：Monitor Exec Devin不占Solver的并发槽（有独立的 `monitor_exec_concurrency` 配置，默认1）

**session注册表记录**（type=monitor_exec）：
```python
{
    "_key": "p27-s0042",
    "seq": 42,
    "session_name": "p27-s0042-monitor-exec-7",
    "type": "monitor_exec",
    "exec_seq": 7,                    # 第几轮Monitor Exec
    "batch_id": "p27-full",
    "started_at": "...",
    "done_md": False,
    "export_path": "/Volumes/data/p27-monitor-exec/7/conversation.json",
    "work_dir": "/Volumes/data/p27-monitor-exec/7/",
    "status": "running",              # running | done | stuck | cleaned
    "report_path": "/Volumes/data/p27-monitor-exec/7/MONITOR_EXEC_REPORT.md",
}
```

### B.7 并发控制

**默认并发=1**：同一时间最多1个Monitor Exec Devin在跑。理由：
- Monitor Exec Devin会commit代码，多个并发修改可能git冲突
- Monitor Exec Devin每轮做完整检查+修复，并发了会重复检查同样的问题
- 一轮检查+修复通常几分钟到十几分钟，串行足够

**防重复启动**：Python部分启动前查注册表，已有 `type=monitor_exec, status=running` 就不启动新的。

**配置**（`continuation_config.py`）：
```python
MONITOR_EXEC_CONCURRENCY = 1
MONITOR_EXEC_INTERVAL = 300          # 两轮之间的最小间隔（秒）
MONITOR_EXEC_EXPORT_BASE = Path("/Volumes/data/p27-monitor-exec")
MONITOR_EXEC_MAX_RUNTIME_SECONDS = 900  # 一轮最多15分钟
```

### B.8 Master Agent的职责（精简后）

Master Agent**退出检查+修复的日常循环**，只在以下情况介入：

1. **用户主动询问**——用户问"系统怎么样了"，Master Agent运行检查脚本汇报
2. **自愈循环长时间无法解决**——Monitor Exec Devin连续多轮修不好同一个问题，Master Agent介入手动处理
3. **需要push代码**——Monitor Exec Devin只commit，push需Master Agent在用户授意下做
4. **需要修改规范**——Monitor Exec Devin不能改AGENTS.md/spec，规范变更走Master Agent + 用户
5. **stuck session清理**——无DONE.md的session只有Master Agent在用户授意下才能kill（见§A.5）

**Master Agent不再做的事**：
- 不再每轮运行检查脚本看行动清单——Monitor Exec Devin在做
- 不再做C类AI判断——Monitor Exec Devin在做
- 不再修代码bug——Monitor Exec Devin在做
- 不再事后审计每个修复——自愈循环自己验证（下一轮检查会发现上一轮修的对不对）

**这个改变解决的核心问题**：Master Agent在长程打磨中上下文增长导致遗忘约定——现在打磨工作不在Master Agent的session里，而在Monitor Exec Devin的独立devin cli实例里，每个实例的prompt自包含，不受Master Agent session压缩影响。
---

## §C. 实施Checklist

### C.1 阶段1：Session编号化管理（必须先做）

这是地基——不做的话Polish Devin的session管理不起来，export保留铁律也无处落地。

#### C.1.1 DB schema

- [ ] `continuation_db_schema.py`：新增 `p27_sessions` collection定义
- [ ] `continuation_db_schema.py`：新增 `p27_session_counter` 文档（`_key=session_counter`, `seq=0`）
- [ ] `continuation_db_schema.py`：`ensure_schema()` 中创建collection + 索引（seq/session_name/status/batch_id+type/triggered_by_alert）
- [ ] `continuation_config.py`：新增 `SESSIONS_COLLECTION = "p27_sessions"` 等常量

#### C.1.2 序号分配与命名

- [ ] 新建 `src/session_registry.py`：
  - `allocate_seq(db) -> int`：原子递增seq（ArangoDB的transaction或update with precondition）
  - `create_session_record(db, seq, session_name, type, ...)`：创建注册表记录
  - `update_session_status(db, session_key, status, **fields)`：更新状态
  - `get_session(db, session_key)`：读取记录
  - `list_sessions(db, batch_id=None, status=None, type=None)`：查询列表
  - `find_orphaned_sessions(db)`：注册表有但tmux无
  - `find_unregistered_sessions(db)`：tmux有但注册表无
- [ ] `continuation_launcher.py`：`tmux_session_name()` 改为 `p27-s{seq:04d}-{type}-{run_key_short}-r{round}` 格式
- [ ] `continuation_launcher.py`：`launch_solve()` 和 `start_handover()` 启动前调 `allocate_seq` + `create_session_record`
- [ ] `continuation_launcher.py`：所有 `tmux_kill` 调用前检查注册表状态（done才能kill）

#### C.1.3 "绝不kill无DONE.md"的改动

- [ ] `continuation_launcher.py`：rate_limited分支——从 `tmux_kill` 改为 `update_session_status(stuck)` + 从running移除
- [ ] `continuation_launcher.py`：timeout分支——同上
- [ ] `continuation_launcher.py`：stall分支——同上
- [ ] `continuation_control.py`：`cmd_stop` 的 `--force` 模式——改为分类处理（done可kill，stuck/running留给用户）
- [ ] `continuation_launcher.py`：每轮检查时更新注册表的 `tmux_alive` 字段（对比tmux实际状态）

#### C.1.4 管理命令

- [ ] `continuation_control.py`：新增 `sessions` 子命令（--status/--type/--clean/--clean-done/--consistency-check）
- [ ] `continuation_control.py`：`sessions --clean <key>` 实现安全清理（检查status=done才kill）
- [ ] `continuation_control.py`：`sessions --clean-done` 批量清理done的
- [ ] `continuation_control.py`：`sessions --consistency-check` 对比注册表 vs tmux

#### C.1.5 Monitor Pipe检查项扩展

- [ ] `monitor_continuation.py`：新增 `check_session_registry_consistency()` (A10)
- [ ] `monitor_continuation.py`：新增 `check_stuck_sessions()` (A11)
- [ ] `monitor_continuation.py`：新增 `check_done_sessions_uncleaned()` (A12)
- [ ] `p27_monitor_spec.md`：A类检查从9项扩展为12项，新增A10/A11/A12的检查标准
- [ ] `monitor_check_continuation.sh`：第1项输出加入stuck session统计

#### C.1.6 验证

- [ ] 小批量测试（5道题）：验证seq递增、注册表记录、状态流转
- [ ] 模拟rate_limited：验证session标记stuck而非kill，export最终落盘
- [ ] 模拟stop --force：验证done的清理、stuck的保留
- [ ] `sessions --consistency-check`：验证能发现注册表/tmux不一致

### C.2 阶段2：Monitor Pipe执行devin架构（阶段1完成后做）

#### C.2.1 配置与模板

- [ ] `continuation_config.py`：新增 `MONITOR_EXEC_CONCURRENCY`/`MONITOR_EXEC_INTERVAL`/`MONITOR_EXEC_EXPORT_BASE`/`MONITOR_EXEC_MAX_RUNTIME_SECONDS`
- [ ] 新建 `templates/monitor_exec_prompt.md`：Monitor Exec Devin的prompt模板（见B.5）
- [ ] `continuation_db_schema.py`：`p27_sessions` 的type字段支持 `monitor_exec`（已在schema中，确认即可）

#### C.2.2 Monitor Exec Devin启动器

- [ ] 新建 `src/monitor_exec_launcher.py`：
  - `should_launch_monitor_exec(db, batch_id) -> bool`：判断是否启动新一轮（无running的monitor_exec + 距上次完成已过interval）
  - `build_monitor_exec_prompt(exec_seq, db) -> str`：构造prompt（见B.5的构造逻辑）
  - `launch_monitor_exec(db, batch_id) -> session_name`：分配seq + 创建注册表记录 + 启动devin cli到tmux
  - `check_monitor_exec_completion(db, batch_id) -> list[completed]`：检查哪些Monitor Exec Devin的DONE.md出现了
- [ ] `monitor_exec_launcher.py`：复用 `launch_solve` 的DONE.md机制和tmux log机制

#### C.2.3 Monitor Pipe集成

- [ ] `monitor_continuation.py`：主循环中加入Monitor Exec Devin启动逻辑——每轮A/B类检查后，调 `should_launch_monitor_exec`，True则调 `launch_monitor_exec`
- [ ] `monitor_continuation.py`：每轮检查Monitor Exec Devin的DONE.md，出现的写 `monitor_exec_completed` alert（含MONITOR_EXEC_REPORT.md路径）
- [ ] `monitor_continuation.py`：Monitor Exec Devin超时（`MONITOR_EXEC_MAX_RUNTIME_SECONDS`）标记stuck，不kill
- [ ] `monitor_continuation.py`：C类检查的 `flag_for_ai_review()` 改为只做抽样标记（Monitor Exec Devin会读这些标记做真正的AI判断），不再只写标记等Master Agent
- [ ] `p27_monitor_spec.md`：新增 §4 Monitor Exec Devin规范（引用本spec §B）
- [ ] `monitor_check_continuation.sh`：行动清单精简——去掉"AI_REVIEW抽样结果需Master Agent检查"（现在Monitor Exec Devin做），改为"有monitor_exec_completed alert时可选读REPORT了解本轮修复"

#### C.2.4 export与report查看支持

- [ ] `monitor_check_continuation.sh`：第2项alerts输出中，`monitor_exec_completed` 类型的alert显示MONITOR_EXEC_REPORT.md路径和commit hash（如有）
- [ ] `continuation_control.py`：新增 `view-exec <session_key>` 命令——一键展示Monitor Exec Devin的MONITOR_EXEC_REPORT.md + git log -3（最近修复）

#### C.2.5 验证

- [ ] 手动启动一轮Monitor Exec Devin，验证完整流程（检查→判断→修复→报告→退出）
- [ ] 验证Monitor Exec Devin的export被完整保留（DONE.md机制）
- [ ] 验证Monitor Exec Devin不能修改AGENTS.md/spec文件（prompt约束）
- [ ] 验证防重复启动（上一轮running时不启动新的）
- [ ] 验证C类AI判断真正发生（proof.md被读取并判断，不是只写标记）
- [ ] 验证Master Agent不介入时系统自愈（构造一个代码bug，Monitor Exec Devin自己修）

### C.3 阶段3：文档同步（阶段1和2完成后做）

- [ ] `AnalysisSystemDesign.md`：§2文档体系加入本spec；§5设计原则更新——Monitor Pipe执行层包含Python+devin cli两部分
- [ ] `AnalysisSystemDesign.md`：§4代码资产索引加入 `session_registry.py`/`monitor_exec_launcher.py`/`templates/monitor_exec_prompt.md`
- [ ] `MonitorPipe.md`：§2.2修正——去掉"Monitor Pipe不是devin cli实例"的错误澄清，改为执行层两层架构定义（Python A/B类 + devin cli C类+修复）；新增Monitor Exec Devin工作循环说明
- [ ] `AGENTS.md`：POC-2.7章节更新——加入session管理和Monitor Exec Devin的简要说明；Master Agent职责精简
- [ ] `docs/architecture.md`：加入session注册表和Monitor Exec Devin架构
- [ ] `docs/framework-checklist.md`：加入session管理和Monitor Exec Devin的检查项

---

## §D. 已知反模式（从最近30个commit提取）

这些是事实依据——本规范的每条设计都对应一个或多个已发生的bug。

### D.1 export丢失类

| 反模式 | 发生commit | 根因 | 本规范的对策 |
|---|---|---|---|
| **proof.md出现就kill session** | 34d05f4 | devin cli刚写完proof.md还没退出，export没写入就被kill | A.5铁律：等DONE.md才kill |
| **用pane文本检测退出** | 81bcbaf | tmux scrollback有限，DEVIN_CLI_EXITED标记被挤出窗口 | A.5：DONE.md文件检测（已修复，本规范固化） |
| **主动kill等超时后强制kill** | 87c60fe | 上一个修复方向不对——应该等自然退出不是超时后强杀 | A.5：stuck状态不kill，留给用户 |
| **rate_limited时kill session** | 当前代码 | devin可能还在写export，rate_limit是临时问题 | A.5：rate_limited改标记stuck |
| **timeout时kill session** | 当前代码 | 同上，timeout可能是thinking spin | A.5：timeout改标记stuck |
| **stop --force无脑kill所有** | 当前代码 | running的session可能正在写export | A.5：force分类处理，running/stuck留给用户 |

### D.2 session管理类

| 反模式 | 发生commit | 根因 | 本规范的对策 |
|---|---|---|---|
| **服务session混入devin cli计数** | 7f22460、3a85f6f | `list_p27_sessions` 没排除launcher/monitor/watchdog | A.2：命名前缀区分 + 注册表type字段 |
| **session名撞名** | 06cb5c7（proof.md被覆盖） | 同题同轮重跑，session名重复，kill旧的 | A.2：全局seq保证永不撞名 |
| **无注册表，死了的session无痕迹** | 7f22460 | tmux list-sessions只显示活着的 | A.3：DB注册表是source of truth |

### D.3 完成判定类

| 反模式 | 发生commit | 根因 | 本规范的对策 |
|---|---|---|---|
| **无proof.md被判定completed** | 5cbf027 | `is_completed`在有message输出但无proof.md时返回True | B.5：Monitor Exec Devin做C类检查时可发现此类问题并修复（检查脚本的B8 rounds_log_integrity会触发alert） |
| **中间产物路径互相覆盖** | 06cb5c7 | `generate_handover`路径计算错误，所有题共用同一文件 | A.3：注册表记录export_path，B9检查唯一性（已有，本规范强化） |
| **rounds_log字段名不匹配** | 06cb5c7 | 写入用"export"读取用"export_path" | B.5：Monitor Exec Devin读alert后修此类bug（rounds_log_integrity触发） |

### D.4 上下文漂移类

| 反模式 | 发生commit | 根因 | 本规范的对策 |
|---|---|---|---|
| **alert从未被resolve，堆积2327个** | 003e990 | 没有自动resolve机制，每次monitor轮次都创建新alert | B.2：Monitor Exec Devin每轮处理alert，修复后resolve原alert；未修复的保留供下一轮 |
| **检查脚本输出13235行** | 003e990 | pane捕获200行 + alert全量输出 | A.6：`sessions`命令有状态过滤，不全量输出 |
| **Master Agent遗忘打磨约定** | 30个commit的修复过程 | 约定散落在AGENTS.md/dev-docs/commit message | B.5：Monitor Exec Devin的prompt自包含SOP，不依赖Master Agent记忆；打磨工作不在Master Agent session里 |

---

## §E. 设计决策记录

### E.1 为什么用DB注册表而不是文件

- tmux list-sessions只显示活着的session，死了的没痕迹——注册表是source of truth
- 文件会和tmux实际状态不同步（launcher崩溃后文件残留）——DB的update有原子性
- 已有ArangoDB连接，加一个collection成本为零
- 注册表可以查询历史（"上周创建过多少session"），文件不行

### E.2 为什么Monitor Exec Devin并发=1

- Monitor Exec Devin会commit代码，多个并发修改可能git冲突
- 每轮做完整检查+修复，并发了会重复检查同样的问题
- 一轮通常几分钟到十几分钟，串行足够
- 不需要Master Agent事后审计每一轮——自愈循环自己验证（下一轮检查会发现上一轮修的对不对）

### E.3 为什么Monitor Exec Devin不能修改AGENTS.md/spec

- AGENTS.md和spec是规范，修改规范需要用户参与讨论
- Monitor Exec Devin只修代码bug，不修规范——规范变更走Master Agent + 用户
- 如果bug的根因确实是规范有问题，Monitor Exec Devin在MONITOR_EXEC_REPORT.md中提出，Master Agent决定是否启动规范变更流程

### E.4 为什么不把Monitor Exec Devin做成subagent

- devin cli非交互模式本身不支持subagent
- subagent的输出不直接保留——Monitor Exec Devin的export是完整thinking，可审计
- subagent由Master Agent的session承载，session压缩后subagent上下文丢失——Monitor Exec Devin是独立devin cli实例，不受Master Agent session影响
- 这正是解决"Master Agent上下文漂移"的关键：打磨工作在独立devin cli里，不在Master Agent session里

### E.5 为什么stuck session不自动kill

- 用户明确要求："必须等到DONE.md出现再kill，否则就一直留在那里，等到Master Agent在用户的授意之下再处理"
- stuck的session可能自己恢复（rate_limit解除后devin cli继续）或自然退出（写完export后退出）
- 自动kill会重蹈export丢失的覆辙——这是本规范要根治的问题
- stuck不占并发槽，不影响系统吞吐——只是占tmux资源，tmux能承载几百个session

---

## §F. 与现有规范的关系

| 现有规范 | 本规范的关系 |
|---|---|
| `p27_monitor_spec.md` | 本规范是其演进——后者定义"检查什么"，本规范定义"Monitor Pipe执行devin怎么工作"和"session怎么管" |
| `MonitorPipe.md` | 本规范的§B修正了MonitorPipe.md §2.2的错误澄清——Monitor Pipe执行层包含Python+devin cli两部分，不是纯Python |
| `续传规范文档.md` | 无直接关系——续传规范定义HANDOFF.md结构，本规范定义session管理和Monitor Exec Devin |
| `AnalysisSystemDesign.md` | 本规范加入其§2文档体系索引；其§5设计原则需更新 |
| `.devin/rules/code-doc-sync.md` | Monitor Exec Devin也需遵守——改代码后同步文档（但不能改AGENTS.md/spec，只能改docs/下的模块文档） |

---

## §G. 待决策问题

以下问题本规范暂不决定，留待实施时由用户确认：

1. **Monitor Exec Devin的model**：用 `glm-5-2-high`（与Solver相同）还是用其他model？——默认与Solver相同，但Monitor Exec Devin是代码修复+系统检查不是数学，可能其他model更合适
2. **Monitor Exec Devin的permission_mode**：用 `dangerous`（与Solver相同）？——Monitor Exec Devin需要exec（py_compile/检查脚本）和git操作，需要dangerous
3. **stuck session的自动清理阈值**：stuck超过多少个或多少时间后自动告警？——A11的标准（>5 warning, >10 critical）是初步值，需要运行中调整
4. **Monitor Exec Devin能否修改docs/下的模块文档**：当前规范允许（code-doc-sync rule要求），但docs/的修改也可能有争议——实施时观察
5. **Monitor Exec Devin的修复是否自动触发系统重启**：当前规范不自动重启（只commit，不重启launcher）——如果修复的bug需要重启才生效，Monitor Exec Devin在REPORT中建议，下一轮或Master Agent决定
6. **Monitor Exec Devin的启动间隔**：默认300秒（5分钟）是否合适？——太频繁浪费API配额，太慢问题修复不及时，需要运行中调整
7. **自愈循环的escalation机制**：Monitor Exec Devin连续多轮修不好同一个问题时，何时escalate给Master Agent？——需要定义"连续N轮同一alert未resolve"的阈值
