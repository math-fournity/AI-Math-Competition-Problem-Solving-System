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
- `seq`（unique）——序号唯一
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

## §B. 打磨devin架构规范

### B.1 角色定义

**打磨devin**（Polish Devin）是POC-2.7系统的新角色：

| 角色 | 职责 | 启动方式 | export保留 |
|---|---|---|---|
| Solver Devin | 做数学题 | launcher自动启动 | 是（DONE.md机制） |
| Handover Devin | 生成HANDOFF.md | launcher自动启动 | 是（DONE.md机制） |
| **Polish Devin** | **修复系统代码bug** | **Monitor Pipe触发** | **是（DONE.md机制）** |
| Master Agent | 检查系统健康、审计产出、决定是否接受Polish Devin的修复 | 用户session | - |

**Polish Devin不是Master Agent**：
- 不能spawn subagent（devin cli非交互模式本身就不支持subagent，但prompt里也要明确禁止）
- 不能决定系统架构方向（只修alert指出的具体问题）
- 不能push代码（只commit到本地，push需Master Agent在用户授意下做）
- 不能修改AGENTS.md或spec文件（这些是规范，不是代码bug）

### B.2 触发条件

Polish Devin由Monitor Pipe的alert触发。不是所有alert都触发Polish Devin——只有**代码可修复的alert**才触发：

| alert类型 | 触发Polish Devin？ | 理由 |
|---|---|---|
| `export_missing` | ✅ | 代码bug——launcher的kill逻辑或DONE.md检测有问题 |
| `proof_missing` | ❌ | 模型能力问题——AI没做出来，不是代码bug |
| `rate_limit` | ❌ | 基础设施问题——等恢复即可，不是代码bug |
| `session_registry_inconsistency` (A10) | ✅ | 代码bug——注册表同步逻辑有问题 |
| `stuck_session_accumulated` (A11) | ❌ | 需要Master Agent判断——可能是devin cli真的卡了，需要人工kill |
| `done_session_uncleaned` (A12) | ❌ | 不是bug——只是需要清理，Master Agent跑 `--clean-done` 即可 |
| `rounds_log_integrity` (B8) | ✅ | 代码bug——rounds_log写入逻辑有问题 |
| `intermediate_product_uniqueness` (B9) | ✅ | 代码bug——中间产物路径计算有问题 |
| `proof_quality` (C1) | ❌ | 需要AI判断——不是代码bug |
| `continuation_direction` (C5) | ❌ | 需要AI判断——不是代码bug |

**判定规则**：alert的 `alert_type` 在 `POLISH_TRIGGERABLE_ALERTS` 集合中 → 触发Polish Devin。

**`POLISH_TRIGGERABLE_ALERTS`**（定义在 `continuation_config.py`）：
```python
POLISH_TRIGGERABLE_ALERTS = {
    "export_missing",
    "session_registry_inconsistency",
    "rounds_log_integrity",
    "intermediate_product_uniqueness",
    # 后续可扩展
}
```

### B.3 触发流程

```
Monitor Pipe发现alert (alert_type in POLISH_TRIGGERABLE_ALERTS)
  │
  ▼
检查是否已有Polish Devin在处理同类型alert
  │ (防止重复触发——同一alert_type最多1个Polish Devin并发)
  ├── 已有 → 跳过，等现有的完成
  └── 无 → 继续
  │
  ▼
构造Polish Devin的prompt（见B.4）
  │
  ▼
分配seq，创建注册表记录（type=polish, triggered_by_alert=alert_key）
  │
  ▼
启动devin cli到tmux session:
  devin -p --prompt-file {polish_prompt} --model glm-5-2-high \
    --permission-mode dangerous --export {polish_export_path}; \
    echo $? > {done_marker}; sleep 999999
  │
  ▼
Polish Devin执行:
  1. 读prompt中的alert详情和相关代码路径
  2. 读git log --oneline -10了解最近修改
  3. 定位bug → 修复 → compile验证
  4. git add 具体路径 → git commit
  5. 写POLISH_REPORT.md（修复了什么、怎么修的、验证结果）
  6. 退出（DONE.md出现）
  │
  ▼
Monitor Pipe下一轮检查发现Polish Devin的DONE.md
  │
  ▼
写alert: polish_completed (severity=info, 含commit hash和POLISH_REPORT.md路径)
  │
  ▼
Master Agent审:
  1. 读Polish Devin的export（thinking过程）—— 看它怎么分析的
  2. 读git diff —— 看它改了什么
  3. 读POLISH_REPORT.md —— 看它的自述
  4. 决定: 接受 / 回滚 / 手动修正
```

### B.4 Polish Devin的Prompt构造

**核心原则**：prompt必须自包含——Polish Devin不需要读AGENTS.md（4216行），不需要了解整个系统架构，只需要知道这个alert、相关代码、打磨SOP。

**Prompt模板**（落盘到 `templates/polish_devin_prompt.md`）：

```markdown
# 打磨任务

你是POC-2.7续传系统的代码修复devin。你的任务是修复一个具体的bug。

## 严格约束

1. **只修这个bug**——不要重构、不要改架构、不要"顺便"修其他问题
2. **不能spawn subagent**——你自己完成所有工作
3. **不能push代码**——只commit到本地
4. **不能修改以下文件**——它们是规范，不是代码bug：
   - AGENTS.md
   - specs/*.md
   - MonitorPipe.md
   - AnalysisSystemDesign.md
   - .devin/rules/*.md
5. **git操作规范**：
   - 禁止 `git add -A` / `git add .` / `git add -u`
   - 只 `git add <具体路径>`
   - commit message格式：`修复<alert_type>: <一句话描述>`
   - commit message末尾加：
     ```
     Generated with [Devin](https://devin.ai)

     Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
     ```
6. **修完必须验证**——运行 `python -m py_compile <修改的文件>` 确认无语法错误
7. **写POLISH_REPORT.md**——在work_dir中写一份修复报告（见下方格式）

## 最近的代码修改（git log --oneline -10）

{git_log_recent}

## 你要修的bug

**alert类型**: {alert_type}
**alert详情**: {alert_details}
**相关代码文件**: {relevant_code_paths}
**相关代码片段**:

{relevant_code_snippets}

## 修复步骤

1. 读相关代码文件，理解当前逻辑
2. 定位bug的根因（不是症状）
3. 修复bug
4. 运行 `python -m py_compile <修改的文件>` 验证语法
5. `git add <具体路径>` + `git commit`
6. 写POLISH_REPORT.md

## POLISH_REPORT.md格式

```markdown
# Polish Report

**alert**: {alert_key}
**alert_type**: {alert_type}
**commit**: {commit_hash}

## 问题根因

（bug的根本原因，不是症状）

## 修复方案

（怎么修的，为什么这么修）

## 验证

- [ ] py_compile通过
- [ ] git commit成功

## 可能的副作用

（这次修改可能影响什么，如果不确定就写"不确定"）
```
```

**Prompt构造逻辑**（在 `monitor_continuation.py` 或新的 `polish_launcher.py` 中）：

```python
def build_polish_prompt(alert, db):
    # 1. 从alert的details获取相关代码路径
    relevant_paths = identify_relevant_code(alert["alert_type"], alert["details"])
    # 2. 读取相关代码片段（每个文件最多200行，避免prompt过大）
    snippets = {p: read_code_snippet(p, max_lines=200) for p in relevant_paths}
    # 3. 获取最近git log
    git_log = subprocess.run(
        ["git", "log", "--oneline", "-10"],
        capture_output=True, text=True, cwd=PROJECT_ROOT
    ).stdout
    # 4. 填充模板
    return render_template("templates/polish_devin_prompt.md", {
        "alert_type": alert["alert_type"],
        "alert_details": json.dumps(alert["details"], ensure_ascii=False, indent=2),
        "relevant_code_paths": "\n".join(relevant_paths),
        "relevant_code_snippets": "\n\n".join(
            f"### {p}\n```\n{s}\n```" for p, s in snippets.items()
        ),
        "git_log_recent": git_log,
    })
```

**`identify_relevant_code(alert_type, details)`** 的映射规则：

| alert_type | 相关代码 |
|---|---|
| `export_missing` | `src/continuation_launcher.py`（kill逻辑、DONE.md检测） |
| `session_registry_inconsistency` | `src/continuation_launcher.py` + `monitoring/continuation_control.py`（注册表同步） |
| `rounds_log_integrity` | `src/continuation_launcher.py`（`make_round_log_entry`、所有写rounds_log的地方） |
| `intermediate_product_uniqueness` | `src/continuation_launcher.py`（路径计算逻辑） |

### B.5 Polish Devin的export保留

Polish Devin的export路径：

```
/Volumes/data/p27-polish/{alert_key}/conversation.json
/Volumes/data/p27-polish/{alert_key}/DONE.md
/Volumes/data/p27-polish/{alert_key}/POLISH_REPORT.md
/Volumes/data/p27-polish/{alert_key}/tmux/tmux.log
```

**保留铁律**：与Solver Devin相同——等DONE.md出现才处理，绝不主动kill无DONE.md的session。

**与Solver Devin的隔离**：
- 工作目录隔离：Polish Devin在 `/Volumes/data/p27-polish/{alert_key}/`，Solver在 `/Volumes/data/p27-trajectories/{run_key}/`
- tmux session命名隔离：`p27-s{seq}-polish-*` vs `p27-s{seq}-solve-*`
- 并发槽隔离：Polish Devin不占Solver的并发槽（有独立的 `polish_concurrency` 配置，默认1）

### B.6 Polish Devin的并发控制

**默认并发=1**：同一时间最多1个Polish Devin在跑。理由：
- Polish Devin会commit代码，多个并发修改可能冲突
- Polish Devin的修复需要Master Agent事后审计，并发多了审计不过来

**防重复触发**：Monitor Pipe每轮检查时，先查注册表是否已有 `type=polish, status=running, triggered_by_alert_type=X` 的记录。有则跳过，无则触发。

**配置**（`continuation_config.py`）：
```python
POLISH_CONCURRENCY = 1
POLISH_TRIGGERABLE_ALERTS = {
    "export_missing",
    "session_registry_inconsistency",
    "rounds_log_integrity",
    "intermediate_product_uniqueness",
}
POLISH_EXPORT_BASE = Path("/Volumes/data/p27-polish")
POLISH_MAX_RUNTIME_SECONDS = 600  # Polish Devin最多跑10分钟
```

### B.7 Master Agent的审计职责

Polish Devin完成后，Master Agent必须审计：

1. **读export的thinking**——Polish Devin是怎么分析bug的？逻辑对不对？
2. **读git diff**——实际改了什么？是不是只改了该改的？
3. **读POLISH_REPORT.md**——自述的根因和修复方案对不对？
4. **决定**：
   - **接受**：修复正确，继续运行系统
   - **回滚**：`git revert <commit>`，修复错误，重新触发或手动修
   - **手动修正**：Polish Devin方向对但不完整，Master Agent在它的基础上继续修

**审计的触发**：Monitor Pipe写 `polish_completed` alert后，Master Agent在下次循环监控时通过检查脚本看到这个alert，执行审计。

**审计的SOP**（加到 `monitor_check_continuation.sh` 的行动清单）：
```
   9. 有polish_completed alert时——读Polish Devin的export和git diff，决定接受/回滚/手动修正
```

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

### C.2 阶段2：打磨devin架构（阶段1完成后做）

#### C.2.1 配置与模板

- [ ] `continuation_config.py`：新增 `POLISH_CONCURRENCY`/`POLISH_TRIGGERABLE_ALERTS`/`POLISH_EXPORT_BASE`/`POLISH_MAX_RUNTIME_SECONDS`
- [ ] 新建 `templates/polish_devin_prompt.md`：Polish Devin的prompt模板（见B.4）
- [ ] `continuation_db_schema.py`：`p27_sessions` 的type字段支持 `polish`（已在schema中，确认即可）

#### C.2.2 Polish Devin启动器

- [ ] 新建 `src/polish_launcher.py`：
  - `should_trigger_polish(alert, db) -> bool`：判断是否触发（alert_type在POLISH_TRIGGERABLE_ALERTS中 + 无同类型Polish Devin在跑）
  - `build_polish_prompt(alert, db) -> str`：构造prompt（见B.4的构造逻辑）
  - `identify_relevant_code(alert_type, details) -> list[Path]`：alert_type到代码路径的映射
  - `launch_polish(alert, db) -> session_name`：分配seq + 创建注册表记录 + 启动devin cli到tmux
  - `check_polish_completion(db) -> list[completed_polish]`：检查哪些Polish Devin的DONE.md出现了
- [ ] `polish_launcher.py`：复用 `launch_solve` 的DONE.md机制和tmux log机制

#### C.2.3 Monitor Pipe集成

- [ ] `monitor_continuation.py`：主循环中加入Polish Devin触发逻辑——每轮检查完A/B/C类后，扫描new alert中是否有 `POLISH_TRIGGERABLE_ALERTS`，有则调 `launch_polish`
- [ ] `monitor_continuation.py`：每轮检查Polish Devin的DONE.md，出现的写 `polish_completed` alert
- [ ] `monitor_continuation.py`：Polish Devin超时（`POLISH_MAX_RUNTIME_SECONDS`）标记stuck，不kill
- [ ] `p27_monitor_spec.md`：新增 §4 Polish Devin触发规范
- [ ] `monitor_check_continuation.sh`：行动清单加入第9项"有polish_completed alert时审计"

#### C.2.4 Master Agent审计支持

- [ ] `monitor_check_continuation.sh`：第2项alerts输出中，`polish_completed` 类型的alert显示commit hash和POLISH_REPORT.md路径
- [ ] `continuation_control.py`：新增 `audit-polish <session_key>` 命令——一键展示Polish Devin的export thinking + git diff + POLISH_REPORT.md

#### C.2.5 验证

- [ ] 手动构造一个 `export_missing` alert，触发Polish Devin，验证完整流程
- [ ] 验证Polish Devin的export被完整保留（DONE.md机制）
- [ ] 验证Polish Devin不能修改AGENTS.md/spec文件（prompt约束 + 事后审计）
- [ ] 验证防重复触发（同类型alert不会启动第二个Polish Devin）
- [ ] 验证Master Agent的审计命令 `audit-polish` 输出正确

### C.3 阶段3：文档同步（阶段1和2完成后做）

- [ ] `AnalysisSystemDesign.md`：§2文档体系加入本spec
- [ ] `AnalysisSystemDesign.md`：§4代码资产索引加入 `session_registry.py`/`polish_launcher.py`
- [ ] `MonitorPipe.md`：新增 §7 "Polish Devin闭环"（如果认定为范式演进）
- [ ] `AGENTS.md`：POC-2.7章节更新——加入session管理和Polish Devin的简要说明
- [ ] `docs/architecture.md`：加入session注册表和Polish Devin架构
- [ ] `docs/framework-checklist.md`：加入session管理和Polish Devin的检查项

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
| **无proof.md被判定completed** | 5cbf027 | `is_completed`在有message输出但无proof.md时返回True | B.4：Polish Devin可修此类bug（alert_type=proof_missing不触发Polish Devin，但rounds_log_integrity会触发检查） |
| **中间产物路径互相覆盖** | 06cb5c7 | `generate_handover`路径计算错误，所有题共用同一文件 | A.3：注册表记录export_path，B9检查唯一性（已有，本规范强化） |
| **rounds_log字段名不匹配** | 06cb5c7 | 写入用"export"读取用"export_path" | B.4：Polish Devin可修此类bug（alert_type=rounds_log_integrity触发） |

### D.4 上下文漂移类

| 反模式 | 发生commit | 根因 | 本规范的对策 |
|---|---|---|---|
| **alert从未被resolve，堆积2327个** | 003e990 | 没有自动resolve机制，每次monitor轮次都创建新alert | B.3：Polish Devin完成后自动写polish_completed alert，Master Agent审计后resolve原alert |
| **检查脚本输出13235行** | 003e990 | pane捕获200行 + alert全量输出 | A.6：`sessions`命令有状态过滤，不全量输出 |
| **Master Agent遗忘打磨约定** | 30个commit的修复过程 | 约定散落在AGENTS.md/dev-docs/commit message | B.4：Polish Devin的prompt自包含SOP，不依赖Master Agent记忆 |

---

## §E. 设计决策记录

### E.1 为什么用DB注册表而不是文件

- tmux list-sessions只显示活着的session，死了的没痕迹——注册表是source of truth
- 文件会和tmux实际状态不同步（launcher崩溃后文件残留）——DB的update有原子性
- 已有ArangoDB连接，加一个collection成本为零
- 注册表可以查询历史（"上周创建过多少session"），文件不行

### E.2 为什么Polish Devin并发=1

- Polish Devin会commit代码，多个并发修改可能git冲突
- Polish Devin的修复需要Master Agent事后审计，并发多了审计不过来
- 代码bug不像数学题那样需要大规模并行——一个一个修更安全

### E.3 为什么Polish Devin不能修改AGENTS.md/spec

- AGENTS.md和spec是规范，修改规范需要用户参与讨论
- Polish Devin只修代码bug，不修规范——规范变更走Master Agent + 用户
- 如果bug的根因确实是规范有问题，Polish Devin在POLISH_REPORT.md中提出，Master Agent决定是否启动规范变更流程

### E.4 为什么不把Polish Devin做成subagent

- devin cli非交互模式本身不支持subagent
- subagent的输出不直接保留——Polish Devin的export是完整thinking，可审计
- subagent由Master Agent的session承载，session压缩后subagent上下文丢失——Polish Devin是独立devin cli实例，不受Master Agent session影响

### E.5 为什么stuck session不自动kill

- 用户明确要求："必须等到DONE.md出现再kill，否则就一直留在那里，等到Master Agent在用户的授意之下再处理"
- stuck的session可能自己恢复（rate_limit解除后devin cli继续）或自然退出（写完export后退出）
- 自动kill会重蹈export丢失的覆辙——这是本规范要根治的问题
- stuck不占并发槽，不影响系统吞吐——只是占tmux资源，tmux能承载几百个session

---

## §F. 与现有规范的关系

| 现有规范 | 本规范的关系 |
|---|---|
| `p27_monitor_spec.md` | 本规范是其演进——后者定义"检查什么"，本规范定义"检查发现问题后怎么自动修复"和"session怎么管" |
| `MonitorPipe.md` | 本规范的§B可能成为MonitorPipe.md的新章节"Polish Devin闭环"——如果认定为跨项目范式 |
| `续传规范文档.md` | 无直接关系——续传规范定义HANDOFF.md结构，本规范定义session管理和Polish Devin |
| `AnalysisSystemDesign.md` | 本规范加入其§2文档体系索引 |
| `.devin/rules/code-doc-sync.md` | 本规范的Polish Devin也需遵守——改代码后同步文档（但Polish Devin不能改AGENTS.md/spec，只能改docs/下的模块文档） |

---

## §G. 待决策问题

以下问题本规范暂不决定，留待实施时由用户确认：

1. **Polish Devin的model**：用 `glm-5-2-high`（与Solver相同）还是用其他model？——默认与Solver相同，但Polish Devin是代码修复不是数学，可能其他model更合适
2. **Polish Devin的permission_mode**：用 `dangerous`（与Solver相同）？——Polish Devin需要exec（py_compile）和git操作，需要dangerous
3. **stuck session的自动清理阈值**：stuck超过多少个或多少时间后自动告警？——A11的标准（>5 warning, >10 critical）是初步值，需要运行中调整
4. **Polish Devin能否修改docs/下的模块文档**：当前规范允许（code-doc-sync rule要求），但docs/的修改也可能有争议——实施时观察
5. **Polish Devin的修复是否自动触发系统重启**：当前规范不自动重启（Polish Devin只commit，不重启launcher）——Master Agent审计后决定是否重启
