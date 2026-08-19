# POC-2.7 Monitor Pipe操作规范（认知资产入口）

**用途**：这份文档是Monitor Pipe执行devin（Monitor Exec Devin）的**认知资产入口**。Monitor Exec Devin启动时读这一份文档，就能找到所有它需要的认知资产、知道要检查什么（系统+self）、知道自己的运行资产怎么保留。

**为什么有这份文档**：认知资产曾经散落在6个位置（worktree根目录的MonitorPipe.md/AnalysisSystemDesign.md/续传规范文档.md + analysis-devin-failure-system内的specs/和docs/）。Monitor Exec Devin不知道该读哪些、读了过时的会出错。本文档把所有认知资产的入口归集在一处，并完整记录检查项目（系统检查+self检查）。这份文档会持续迭代。

**对应文档**：
- 检查规范详情：`specs/p27_monitor_spec.md`（A/B/C类检查的详细标准）
- session管理+Monitor Exec Devin架构：`specs/p27_session_management_and_polish_spec.md`
- 系统总索引：`/Users/user/glm5.2-math-worktree/AnalysisSystemDesign.md`
- Monitor Pipe设计范式：`/Users/user/glm5.2-math-worktree/MonitorPipe.md`

---

## §1. 可追溯性规范

### 1.1 每次运行在独立work_dir

Monitor Exec Devin每次被Python部分启动，都在一个新的、编号化的work_dir中运行：

```
/Volumes/data/p27-monitor-exec/{exec_seq}/
  monitor_exec_prompt.txt     # 启动prompt（含git log -10）
  conversation.json           # --export的产出（完整thinking，可审计）
  DONE.md                     # 退出标记（echo $? > DONE.md）
  MONITOR_EXEC_REPORT.md      # 本轮检查+修复的完整报告
  WORKLOG.md                  # ★跨轮次连续工作日志★（从上一轮复制+本轮续写）
  tmux/tmux.log               # tmux pane日志
  tmux/tmux_pipe.log          # tmux pipe-pane日志
```

`exec_seq` 是单调递增的序号（从DB的session_counter读取），永不复用。`exec_seq`就是"第几次被唤醒"——Monitor Exec Devin从自己work_dir的编号就知道自己是第几次运行。

### 1.2 WORKLOG.md——跨轮次连续工作日志

**核心设计**：WORKLOG.md是Monitor Exec Devin的**跨轮次连续记忆**。每次运行不是从零开始，而是续写一个不断增长的工作日记。

**跨目录传递机制**：
```
/Volumes/data/p27-monitor-exec/1/WORKLOG.md    —— 第1次唤醒：创建WORKLOG，记录本轮
/Volumes/data/p27-monitor-exec/2/WORKLOG.md    —— 第2次唤醒：从1/复制WORKLOG，续写本轮
/Volumes/data/p27-monitor-exec/3/WORKLOG.md    —— 第3次唤醒：从2/复制WORKLOG，续写本轮
...
/Volumes/data/p27-monitor-exec/N/WORKLOG.md    —— 第N次唤醒：从N-1/复制WORKLOG，续写本轮
```

**Python部分启动时的复制逻辑**（在`monitor_exec_launcher.py`中）：
```python
def prepare_worklog(exec_seq, work_dir):
    if exec_seq == 1:
        # 第1次唤醒——创建空WORKLOG.md
        (work_dir / "WORKLOG.md").write_text("# Monitor Exec Devin Worklog\n\n")
    else:
        # 从上一轮复制WORKLOG.md
        prev_worklog = Path(f"/Volumes/data/p27-monitor-exec/{exec_seq - 1}/WORKLOG.md")
        if prev_worklog.exists():
            shutil.copy2(prev_worklog, work_dir / "WORKLOG.md")
        else:
            # 上一轮的WORKLOG丢失了——从更早的最近一轮找
            for seq in range(exec_seq - 1, 0, -1):
                candidate = Path(f"/Volumes/data/p27-monitor-exec/{seq}/WORKLOG.md")
                if candidate.exists():
                    shutil.copy2(candidate, work_dir / "WORKLOG.md")
                    break
            else:
                # 全部丢失——创建空WORKLOG，在开头记录这个异常
                (work_dir / "WORKLOG.md").write_text(
                    "# Monitor Exec Devin Worklog\n\n"
                    "## 唤醒 #{exec_seq}\n\n"
                    "**⚠️ 异常**：未找到上一轮的WORKLOG.md，本轮从空开始。\n\n"
                )
```

**WORKLOG.md的格式**：
```markdown
# Monitor Exec Devin Worklog

## 唤醒 #1 · {timestamp}

### 检查发现
- A类alert: 3个（session_health warning, rate_limit critical, ...）
- B类alert: 1个（proof_missing critical, problem_id=CC-103_bare）
- C类AI判断: 抽样2条，1条PASS，1条FAIL（CC-103_bare proof有幻觉）

### 修复操作
- 修复export_missing: launcher的kill逻辑在rate_limited时主动kill，
  改为标记stuck不kill。commit abc123
- CC-103_bare proof幻觉: 判定为模型能力问题，不修代码，标记需重跑

### 思考
- rate_limited的session可能还在写export，不应该kill——这个根因
  和之前34d05f4修复的proof.md出现就kill是同一类问题
- 下轮应该关注：改完rate_limited不kill后，这些stuck session的
  export是否最终落盘

### self-check结果
- S1-S14全部通过
- S13循环检测: 无重复修复

---

## 唤醒 #2 · {timestamp}

### 检查发现
- A类alert: 1个（done_session_uncleaned info, 8个done未清理）
- B类alert: 0个
- C类AI判断: 抽样2条，全部PASS

### 修复操作
- 运行 sessions --clean-done 清理了8个done session
- 无代码bug需修复

### 思考
- 上轮改的rate_limited不kill生效了——之前3个stuck session中2个
  的export已落盘（DONE.md出现），1个还在跑
- 系统趋于稳定，下轮可以减少检查频率

### self-check结果
- S1-S14全部通过

---

## 唤醒 #3 · {timestamp}
...
```

**WORKLOG.md的内容要求**：
- **检查发现**：本轮A/B/C类alert的摘要（不需要全部详情，详情在DB的alert集合里）
- **修复操作**：每个修复的简述（根因+方案+commit hash），不需要完整代码diff
- **思考**：Monitor Exec Devin的推理和判断——为什么这么修、发现了什么模式、对系统的观察。**这是WORKLOG最宝贵的部分**——它记录了AI的思考演进，是export的thinking的结构化提炼
- **self-check结果**：S1-S14的结果摘要

**WORKLOG.md vs MONITOR_EXEC_REPORT.md vs conversation.json**：

| 资产 | 范围 | 内容 | 用途 |
|---|---|---|---|
| conversation.json | 本轮 | 完整thinking（raw，含所有tool_call和推理） | 事后审计本轮的完整推理过程 |
| MONITOR_EXEC_REPORT.md | 本轮 | 本轮的结构化报告（检查/判断/修复/self-check） | 本轮工作的正式产出 |
| WORKLOG.md | 跨轮 | 累积的工作日记（每轮的摘要+思考） | **下一轮的连续记忆**——读它知道之前发生了什么 |

**为什么需要WORKLOG.md（不能只靠DB的alert和git log）**：
- DB的alert只记录问题，不记录AI的思考和判断
- git log只记录代码修改，不记录为什么这么改、发现了什么模式
- conversation.json是本轮的完整thinking，但下一轮的Monitor Exec Devin不会读上一轮的conversation.json（太大、太raw）
- WORKLOG.md是**结构化的、精炼的、跨轮次的**——下一轮读它就能快速恢复上下文

### 1.3 资产保留铁律

- **等DONE.md出现才处理**——绝不主动kill无DONE.md的session（见`p27_session_management_and_polish_spec.md` §A.5）
- **export是完整thinking**——conversation.json的reasoning_content记录Monitor Exec Devin的完整推理过程，事后可审计
- **MONITOR_EXEC_REPORT.md是本轮自述报告**——本轮检查了什么、发现了什么、判断了什么、修复了什么
- **WORKLOG.md是跨轮连续记忆**——从上一轮复制+本轮续写，是下一轮恢复上下文的依据
- **tmux.log是行为日志**——记录devin cli的TUI输出，包括工具调用和结果

### 1.4 session注册表记录

每次启动在DB的`p27_sessions`集合中创建记录（见`p27_session_management_and_polish_spec.md` §A.3）：

```python
{
    "_key": "p27-s{seq}",
    "seq": {seq},
    "session_name": "p27-s{seq}-monitor-exec-{exec_seq}",
    "type": "monitor_exec",
    "exec_seq": {exec_seq},
    "batch_id": "p27-full",
    "started_at": "...",
    "done_md": False,
    "export_path": "/Volumes/data/p27-monitor-exec/{exec_seq}/conversation.json",
    "work_dir": "/Volumes/data/p27-monitor-exec/{exec_seq}/",
    "report_path": "/Volumes/data/p27-monitor-exec/{exec_seq}/MONITOR_EXEC_REPORT.md",
    "worklog_path": "/Volumes/data/p27-monitor-exec/{exec_seq}/WORKLOG.md",
    "prev_worklog_path": "/Volumes/data/p27-monitor-exec/{exec_seq-1}/WORKLOG.md",
    "status": "running",  # running | done | stuck | cleaned
}
```

### 1.5 运行历史可查询

```bash
# 查看所有Monitor Exec Devin运行记录
cd analysis-devin-failure-system
.venv/bin/python3 -m monitoring.continuation_control sessions --type monitor_exec

# 查看最新一轮的WORKLOG（跨轮次连续记忆）
cat /Volumes/data/p27-monitor-exec/{latest_exec_seq}/WORKLOG.md

# 查看特定运行的report
cat /Volumes/data/p27-monitor-exec/{exec_seq}/MONITOR_EXEC_REPORT.md

# 查看特定运行的thinking（export）
# 用read工具读 /Volumes/data/p27-monitor-exec/{exec_seq}/conversation.json
```

---

## §2. 认知资产加载清单

**核心认知**：Monitor Exec Devin"就是未来的你"——它和Master Agent是同一个角色定位，都是管理这个系统的AI。区别只是Master Agent在用户session里有用户实时指导，Monitor Exec Devin在独立devin cli里按prompt+WORKLOG自主工作。**它们需要知道的东西是一样的**——整个错题分析系统和POC-2.7的所有设计。

因此，Monitor Exec Devin的认资源加载不是"最小化"（只读3份spec），而是**充分加载**——像Master Agent一样了解系统全貌。只是它的运行在外部目录，避免worktree的AGENTS.md工作系统规则劫持它的行为流程。

### 2.0 第0步：读WORKLOG.md（跨轮次连续记忆）

**在加载任何认知资产之前，先读自己work_dir中的WORKLOG.md**（由Python部分从上一轮复制过来）。

WORKLOG.md告诉Monitor Exec Devin：
- 自己是第几次被唤醒（从work_dir编号exec_seq也知道）
- 之前每次唤醒做了什么、发现了什么、修了什么、想到了什么
- 系统从开始到现在的完整演进
- 上一轮留下的"下一轮建议"

**如果WORKLOG.md为空或异常**（第1次唤醒，或上一轮WORKLOG丢失）——从零开始，但要意识到自己是首次或异常状态。

### 2.1 必读资产（每次启动都读——充分了解系统）

| 序号 | 文档 | 路径 | 用途 |
|---|---|---|---|
| 0 | **WORKLOG.md** | 自己work_dir中 | 跨轮次连续记忆——之前发生了什么 |
| 1 | **本文档** | `analysis-devin-failure-system/specs/p27_monitor_pipe_operations.md` | 认知资产入口+检查项目完整清单+self检查 |
| 2 | **检查规范详情** | `analysis-devin-failure-system/specs/p27_monitor_spec.md` | A/B/C类检查的详细标准（阈值/方法/通过条件） |
| 3 | **session管理+Exec Devin架构** | `analysis-devin-failure-system/specs/p27_session_management_and_polish_spec.md` | session注册表/DONE.md铁律/Monitor Exec Devin工作循环/prompt构造 |
| 4 | **系统总索引** | `/Users/user/glm5.2-math-worktree/AnalysisSystemDesign.md` | 错题分析系统设计总索引——文档体系/规范/代码资产/设计原则/关键决策 |
| 5 | **Monitor Pipe设计范式** | `/Users/user/glm5.2-math-worktree/MonitorPipe.md` | Monitor Pipe三层架构设计范式（跨项目） |
| 6 | **续传规范** | `/Users/user/glm5.2-math-worktree/续传规范文档.md` | 续传机制标准规范——HANDOFF.md结构/截断判定/prompt模板 |

### 2.2 按需读取资产（遇到相关问题时读）

| 序号 | 文档 | 路径 | 何时读 |
|---|---|---|---|
| 7 | 系统架构 | `analysis-devin-failure-system/docs/architecture.md` | 需要理解4个Pipe的演进和目录结构时 |
| 8 | 优雅停止 | `analysis-devin-failure-system/docs/graceful-shutdown.md` | 修复停止/watchdog相关bug时 |
| 9 | 运维关注点 | `analysis-devin-failure-system/docs/operational-concerns.md` | 修复rate_limit/stall/zombie/多轮续传相关bug时 |
| 10 | 框架检查清单 | `analysis-devin-failure-system/docs/framework-checklist.md` | 检查自己是否遗漏框架级问题时 |
| 11 | 动态并发 | `analysis-devin-failure-system/docs/dynamic-concurrency.md` | 修复并发相关bug时 |
| 12 | 解题系统借鉴 | `analysis-devin-failure-system/docs/solver-harness-borrowing.md` | 需要理解与解题系统的关系时 |

### 2.3 代码资产（修复bug时读）

| 代码文件 | 路径 | 何时读 |
|---|---|---|
| `continuation_launcher.py` | `analysis-devin-failure-system/src/continuation_launcher.py` | 修复launch/kill/stall/rate_limit/完成判定/续传逻辑bug时 |
| `monitor_continuation.py` | `analysis-devin-failure-system/src/monitor_continuation.py` | 修复Monitor Pipe Python部分bug时 |
| `continuation_control.py` | `analysis-devin-failure-system/monitoring/continuation_control.py` | 修复start/stop/status/sessions管理bug时 |
| `continuation_config.py` | `analysis-devin-failure-system/src/continuation_config.py` | 修复配置常量/路径/阈值bug时 |
| `continuation_db_schema.py` | `analysis-devin-failure-system/src/continuation_db_schema.py` | 修复DB集合/索引/CRUD bug时 |
| `continuation_redis_queue.py` | `analysis-devin-failure-system/src/continuation_redis_queue.py` | 修复Redis队列操作bug时 |
| `session_registry.py` | `analysis-devin-failure-system/src/session_registry.py` | 修复session注册表bug时 |
| `monitor_check_continuation.sh` | `analysis-devin-failure-system/scripts/monitor_check_continuation.sh` | 修复检查脚本bug时 |

### 2.4 认知资产"最新"的保证

- Monitor Exec Devin每次启动都是新的devin cli实例，读文档时读的是磁盘上的最新版本——不存在缓存旧版本问题
- **内容最新**靠本规范的持续迭代保证——系统演进时同步更新本规范和相关文档
- **如果发现认知资产与实际代码不一致**——以代码为准，在MONITOR_EXEC_REPORT.md中记录"认知资产X与代码不一致，建议更新文档"

---

## §3. 系统检查项目（Monitor Exec Devin检查被监控系统）

### 3.1 A类：自动检查（Python部分做，Monitor Exec Devin读结果）

这些由`monitor_continuation.py`的Python部分每120秒自动执行，结果写成alert。Monitor Exec Devin运行检查脚本时获取这些alert。

| 检查项 | alert_type | severity | 阈值 | 说明 |
|---|---|---|---|---|
| A1. session_health | session_health | critical | — | p27- session数 vs DB running数 vs 设定并发——不匹配说明launcher挂了 |
| A2. queue_progress | queue_stalled | critical | 15分钟无变化 | pending队列没在减少 |
| A3. queue_progress | no_completions | warning | 15分钟无变化 | completed没在增加 |
| A4. rate_limit_detection | rate_limit | critical | ≥3个 | 最近interval内rate_limited数量 |
| A5. zombie_sessions | zombie_sessions | warning | ≥2个 | 空pane僵尸session |
| A6. export_landing | export_missing | critical | 缺失率>10% | completed的run无export文件 |
| A7. failure_rate | failure_rate | warning | >15% | 最近interval失败率 |
| A8. launcher_dead | launcher_dead | critical | — | launcher进程消失但还有prepared/running任务 |
| A9. stall_detection | long_running | warning | 单轮>30分钟 | 单个续传轮次运行超时 |
| **A10. session_registry_consistency** | session_registry_inconsistency | critical | — | 注册表 vs tmux实际session不一致（见`p27_session_management_and_polish_spec.md` §A.7） |
| **A11. stuck_sessions** | stuck_session_accumulated | warning/critical | >5 warning, >10 critical | stuck状态session数量（无DONE.md但超时/rate_limit的session） |
| **A12. done_sessions_uncleaned** | done_session_uncleaned | info | >20个 | done状态但未清理的session（占tmux资源） |

**详细检查标准**：见`p27_monitor_spec.md` §3.1（A1-A9）和`p27_session_management_and_polish_spec.md` §A.7（A10-A12）。

### 3.2 B类：续传质量检查（Python部分做，Monitor Exec Devin读结果）

| 检查项 | alert_type | severity | 阈值 | 说明 |
|---|---|---|---|---|
| B1. proof_completeness | proof_missing | critical | — | COMPLETED的run无proof.md |
| B2. proof_completeness | proof_no_boxed | warning | — | proof.md无\boxed答案 |
| B3. proof_too_small | proof_too_small | warning | <1KB | proof.md太小 |
| B4. handover_completeness | handover_missing | critical | — | v2方案的round无HANDOVER.md |
| B5. handover_completeness | handover_too_small | warning | <500B | HANDOVER.md太小 |
| B6. truncation_pattern | all_rounds_truncated | warning | 5轮全截断 | 可能是思维错误不是截断错误 |
| B7. final_status_distribution | status_anomaly | info | — | final_status分布异常 |
| B8. rounds_log_integrity | rounds_log_* | warning/critical | — | rounds_log字段完整性+路径有效性+round编号连续性 |
| B9. intermediate_product_uniqueness | intermediate_product_collision | critical | — | 中间产物路径重复 |

**详细检查标准**：见`p27_monitor_spec.md` §3.2。

### 3.3 C类：AI智能性检查（Monitor Exec Devin自己做）

**这些是Python做不了的，必须由Monitor Exec Devin做AI判断**。Python部分只做抽样标记（`needs_ai_review=True`），Monitor Exec Devin读标记后做真正的AI判断。

| 检查项 | alert_type | AI需要检查什么 | 通过标准 |
|---|---|---|---|
| C1. proof_quality | ai_review_proof_quality | 读proof.md，检查数学正确性——答案对不对、证明逻辑是否完整 | 答案正确且证明逻辑完整 |
| C2. proof_hallucination | ai_review_hallucination | proof.md是否有幻觉——编造的定理、不存在的引用、虚假的计算结果 | 无幻觉 |
| C3. answer_leak | ai_review_answer_leak | proof.md是否答案泄漏——直接从题目描述抄答案而非推导 | 答案是通过推导得到的 |
| C4. handover_quality | ai_review_handover_quality | HANDOVER.md是否准确总结了上一轮思考——有没有遗漏关键结论、有没有编造 | 准确总结、无遗漏、无编造 |
| C5. continuation_direction | ai_review_continuation_direction | 续传方向是否正确——AI是在上一轮基础上继续还是从头重复 | 在上一轮基础上继续 |

**C类检查的输入**：
- proof.md路径（从rounds_log的proof_path字段获取）
- HANDOVER.md路径（从rounds_log的handover_path字段获取）
- export路径（从rounds_log的export字段获取，用于判断continuation_direction）

**C类检查的输出**：
- 在MONITOR_EXEC_REPORT.md中记录每条抽样的判断结果
- 判定FAIL的，写alert到DB（alert_type=ai_review_*，severity根据问题严重程度定）
- 判定PASS的，resolve对应的needs_ai_review标记

---

## §4. Self检查项目（Monitor Exec Devin检查自己）

**这些是Monitor Exec Devin对自己的检查**——确保自己的运行是正确的、不引入新问题。这是新的检查类别，不属于A/B/C类（那些是检查被监控系统的）。

### 4.1 运行完整性self-check

| 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
|---|---|---|---|
| S1. export完整性 | 检查自己的conversation.json是否存在且非空 | 文件存在且>1KB | 在REPORT中记录"export可能不完整"；不影响本轮工作 |
| S2. DONE.md写入 | 检查自己的work_dir中DONE.md是否会在退出时写入 | 退出前确认echo命令正确 | 这是自动的（prompt中的exit命令），无需检查 |
| S3. REPORT完整性 | 检查MONITOR_EXEC_REPORT.md是否包含必需章节 | 包含§检查结果摘要/§C类AI判断详情/§修复操作/§未修复问题 | 补全缺失章节 |
| S4. session注册 | 检查自己的session是否在p27_sessions集合中 | type=monitor_exec的记录存在 | 记录"session未注册，可能Python部分启动逻辑有问题" |

### 4.2 修复正确性self-check

| 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
|---|---|---|---|
| S5. py_compile通过 | 修复代码后运行`python -m py_compile <修改的文件>` | 无语法错误 | 继续修直到通过 |
| S6. git commit成功 | 修复后git add + git commit | commit成功 | 记录"commit失败，原因..." |
| S7. 未修改第二级架构级规范 | 检查git diff --name-only | 不包含AGENTS.md/.devin/rules/*.md/MonitorPipe.md/AnalysisSystemDesign.md的§5§6段落 | 如果误改了，git checkout还原；详见§4.5文档同步分级 |
| S8. git add规范 | 检查git diff --cached --name-only | 只add了具体路径，没有git add -A/. /-u | 如果误add了，git reset HEAD <路径>后重新add |

### 4.3 行为正确性self-check

| 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
|---|---|---|---|
| S9. 只修本轮发现的问题 | 回顾自己的修复操作 | 没有重构/改架构/顺便修其他问题 | 如果做了额外修改，在REPORT中说明原因 |
| S10. 未spawn subagent | 回顾自己的工具调用 | 没有run_subagent调用 | — |
| S11. 未push代码 | 回顾自己的git操作 | 没有git push | 如果误push了，在REPORT中记录（需Master Agent评估是否回滚） |
| S12. C类判断有依据 | 回顾自己的C类判断 | 每个判断都有读了proof.md/HANDOVER.md的记录 | 如果判断没有依据，标记为"不确定" |

### 4.4 循环检测self-check

| 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
|---|---|---|---|
| S13. 是否陷入重复修复 | 读最近3轮的MONITOR_EXEC_REPORT.md（从/Volumes/data/p27-monitor-exec/{exec_seq-1}/{exec_seq-2}/{exec_seq-3}/） | 同一个问题没有连续3轮修 | 如果陷入循环，在REPORT中写"⚠️ 同一问题已连续N轮未修好，建议escalate给Master Agent"，不再尝试修复该问题 |
| S14. 同一alert是否反复出现 | 查DB中同一alert_type的alert创建历史 | 同一alert_type没有在最近5轮中反复创建 | 如果反复出现，说明根因没找到，在REPORT中写"⚠️ alert_type X反复出现，可能需要系统级重构" |

### 4.5 文档同步self-check

**背景问题**：如果Monitor Exec Devin改了代码但不改描述这段代码的文档，下一轮它读的认知资产就是过时的——按过时认知工作，可能改错或重复踩坑。这是自己方案里的死循环。

**解决**：文档分两级，不是分两类。Monitor Exec Devin必须同步修改第一级（事实性文档），不能改第二级（架构级规范）。

**第一级：事实性文档**（描述代码实际怎么工作的）——Monitor Exec Devin **必须**和代码同步修改，在同一个commit中：

| 文档 | 位置 | 何时同步修改 |
|---|---|---|
| `docs/architecture.md` | `analysis-devin-failure-system/docs/` | 修改了架构/目录结构/4个Pipe的演进 |
| `docs/operational-concerns.md` | `analysis-devin-failure-system/docs/` | 修改了rate_limit/stall/zombie/多轮续传的运维逻辑 |
| `docs/graceful-shutdown.md` | `analysis-devin-failure-system/docs/` | 修改了停止/watchdog/信号处理逻辑 |
| `docs/dynamic-concurrency.md` | `analysis-devin-failure-system/docs/` | 修改了动态并发逻辑 |
| `docs/framework-checklist.md` | `analysis-devin-failure-system/docs/` | 修改了框架检查清单相关逻辑 |
| `docs/monitor-pipe-pattern.md` | `analysis-devin-failure-system/docs/` | 修改了Monitor Pipe本地实现细节 |
| `docs/solver-harness-borrowing.md` | `analysis-devin-failure-system/docs/` | 修改了与解题系统的借鉴关系 |
| `AnalysisSystemDesign.md` §4 代码资产索引 | 项目repo根目录 | 新增/删除/重命名了代码文件 |
| `specs/p27_monitor_spec.md` §2/§3 检查项和检查标准 | `analysis-devin-failure-system/specs/` | 修改了A/B/C类检查项或阈值 |
| `specs/p27_monitor_pipe_operations.md` §3/§4 检查项目和self-check | `analysis-devin-failure-system/specs/` | 修改了检查项目或self-check项 |
| `specs/p27_session_management_and_polish_spec.md` §A/§B 实现细节 | `analysis-devin-failure-system/specs/` | 修改了session管理或Exec Devin的实现细节 |

**第二级：架构级规范**（定义系统应该怎么设计的）——Monitor Exec Devin **不能**改，只在REPORT和WORKLOG中记录建议：

| 文档 | 位置 | 为什么不能改 |
|---|---|---|
| `AGENTS.md` | 项目repo根目录 | 项目级硬约束，变更需用户参与讨论 |
| `.devin/rules/*.md` | 项目rule目录 | 工作纪律rule，变更需用户参与讨论 |
| `MonitorPipe.md` 三层架构定义/设计原则 | 项目repo根目录 | 跨项目范式定义，变更需用户参与讨论 |
| `AnalysisSystemDesign.md` §5 设计原则/§6 关键设计决策 | 项目repo根目录 | 架构级决策记录，变更需用户参与讨论 |

**判定标准**：改的是"是什么"（事实）还是"应该是什么"（设计决策）。
- "launcher的rate_limited分支从kill改为标记stuck" → 事实性变更 → 同步改`docs/operational-concerns.md`（第一级，自己改）
- "Monitor Pipe应该从纯Python改为Python+devin cli两层" → 架构级变更 → 只在REPORT+WORKLOG记录建议（第二级，Master Agent改）

| 检查项 | 检查方法 | 通过标准 | 不通过时怎么办 |
|---|---|---|---|
| **S15. 第一级文档同步** | 如果修改了代码，检查git diff中是否包含对应的第一级文档修改 | 改了代码就改了对应文档（在同一个commit中） | 补充修改文档，重新commit；如果确实不需要同步（如纯cosmetic改动），在REPORT中说明 |
| **S16. 第二级规范建议记录** | 如果代码变更涉及第二级规范需更新 | 在REPORT和WORKLOG中记录"建议Master Agent同步更新X的Y段落" | 补充记录 |
| **S17. 同步清单完整性** | 对照§4.5的第一级文档清单，检查所有相关文档 | 该改的都改了 | 补充遗漏的文档 |

---

## §5. Monitor Exec Devin的完整工作流程

```
启动（Python部分定时启动，分配exec_seq，创建work_dir，从上一轮复制WORKLOG.md，写入注册表）
  │
  ▼
第0步：读WORKLOG.md（跨轮次连续记忆）
  │
  ├── 读自己work_dir中的WORKLOG.md
  ├── 知道自己是第{exec_seq}次被唤醒
  ├── 了解之前每次唤醒做了什么、发现了什么、修了什么、想到了什么
  └── 读上一轮留下的"下一轮建议"
  │
  ▼
加载认知资产（充分了解系统——像Master Agent一样）
  │
  ├── 1. 读本文档（p27_monitor_pipe_operations.md）—— 知道检查什么、怎么工作
  ├── 2. 读p27_monitor_spec.md —— 知道A/B/C类检查详细标准
  ├── 3. 读p27_session_management_and_polish_spec.md —— 知道session管理和自己的工作规范
  ├── 4. 读AnalysisSystemDesign.md —— 系统总索引（文档体系/规范/代码资产/设计原则/关键决策）
  ├── 5. 读MonitorPipe.md —— Monitor Pipe三层架构设计范式
  └── 6. 续传规范文档.md —— 续传机制标准规范（如本轮涉及续传问题）
  │
  ▼
第一步：检查系统状态
  │
  ├── 运行检查脚本：bash monitor_check_continuation.sh p27-full
  ├── 读输出中的7项检查结果 + 所有未处理alert + 行动清单
  └── 获取needs_ai_review标记的抽样列表
  │
  ▼
第二步：做C类AI智能性判断
  │
  ├── 对每个needs_ai_review的抽样：
  │   ├── C1: 读proof.md，判断数学正确性
  │   ├── C2: 判断是否有幻觉
  │   ├── C3: 判断是否答案泄漏
  │   ├── C4: 读HANDOVER.md，判断交接质量
  │   └── C5: 读export，判断续传方向
  └── 记录每个判断的结果和依据
  │
  ▼
第三步：综合判断 + 分类处理
  │
  ├── 代码bug（如export_missing/rounds_log_integrity/session_registry_inconsistency等）
  │   ├── 读相关代码（§2.3的代码资产）
  │   ├── 定位根因
  │   ├── 修复代码
  │   ├── S5: py_compile验证
  │   ├── ★同步修改第一级文档（§4.5清单——改了什么代码就改对应文档）★
  │   ├── S7+S8: 检查未修改第二级架构级规范 + git add规范
  │   ├── S16: 如果涉及第二级规范需更新，在REPORT+WORKLOG记录建议
  │   └── git commit（代码+文档在同一个commit中）
  │
  ├── 数据问题（如proof_missing但题没做出来——C1判定FAIL且非代码bug）
  │   └── 记录为模型能力问题，不修代码
  │
  ├── 基础设施问题（如rate_limit/failed_connection）
  │   └── 记录，等恢复
  │
  ├── 需要重跑的题
  │   └── 改DB status为prepared，重新入Redis队列
  │
  ├── 需要重启的服务（launcher_dead）
  │   └── 重启launcher/monitor
  │
  └── 需要清理的session（A12 done_sessions_uncleaned）
      └── 运行 sessions --clean-done
  │
  ▼
第四步：self-check
  │
  ├── S1-S4: 运行完整性
  ├── S5-S8: 修复正确性
  ├── S9-S12: 行为正确性
  ├── S13-S14: 循环检测
  └── S15-S17: 文档同步（§4.5——第一级文档是否同步改了/第二级建议是否记录了/清单是否完整）
  │
  ▼
第五步：写MONITOR_EXEC_REPORT.md + 续写WORKLOG.md
  │
  ├── MONITOR_EXEC_REPORT.md（本轮正式报告）：
  │   ├── §检查结果摘要（A/B/C类alert统计）
  │   ├── §C类AI判断详情（每条抽样的判断结果+依据）
  │   ├── §修复操作（每个修复的根因+方案+commit+验证）
  │   ├── §self-check结果
  │   ├── §未修复的问题（及原因）
  │   └── §下一轮建议（如有）
  │
  └── WORKLOG.md续写（追加到从上一轮复制来的WORKLOG末尾）：
      ├── ## 唤醒 #{exec_seq} · {timestamp}
      ├── ### 检查发现（A/B/C类alert摘要）
      ├── ### 修复操作（每个修复简述+commit hash）
      ├── ### 思考（推理和判断——为什么这么修、发现了什么模式、对系统的观察）
      └── ### self-check结果
  │
  ▼
第六步：resolve已处理的alert
  │
  ├── 修复了的代码bug → resolve对应alert
  ├── C类判定PASS的 → resolve对应needs_ai_review标记
  └── C类判定FAIL的 → 写新alert（ai_review_*）不resolve原标记
  │
  ▼
退出（DONE.md出现，Python部分下一轮定时启动——下一轮会复制本轮的WORKLOG.md）
```

---

## §6. 持续迭代记录

本规范会持续迭代。每次修改记录在此节。

### v1 · 2026-08-19 · 初始版本

- 创建本规范，归集Monitor Exec Devin的认知资产入口
- 完整记录系统检查项目（A类12项+B类9项+C类5项）
- 新增self检查项目（S1-S14，14项）
- 定义可追溯性规范（work_dir结构/资产保留/session注册）
- 定义认知资产加载清单（必读3份+按需7份+代码8份）

### v2 · 2026-08-19 · WORKLOG.md+充分认知加载

- §1新增WORKLOG.md——跨轮次连续工作日志（从上一轮复制+本轮续写）
- §1.2定义WORKLOG.md的格式/内容要求/跨目录传递机制/Python复制逻辑
- §1.2定义WORKLOG vs REPORT vs conversation.json三者关系
- §2认知资产加载从"最小化"改为"充分加载"——Monitor Exec Devin"就是未来的你"，像Master Agent一样了解系统全貌
- §2.0新增第0步：读WORKLOG.md（在加载任何认知资产之前先读）
- §2.1必读资产从3份扩展为7份（加入AnalysisSystemDesign.md/MonitorPipe.md/续传规范文档.md）
- §5工作流程加入第0步读WORKLOG，第五步改为写REPORT+续写WORKLOG
- §5启动描述加入"从上一轮复制WORKLOG.md"

### v3 · 2026-08-19 · 文档同步分级（解决认知过时死循环）

- §4.5新增文档同步self-check——文档分两级不是分两类
  · 第一级（事实性文档）：docs/*.md + AnalysisSystemDesign.md §4 + specs/*.md的§2/§3/§A/§B实现细节
    Monitor Exec Devin必须和代码同步修改，在同一个commit中
  · 第二级（架构级规范）：AGENTS.md + .devin/rules/*.md + MonitorPipe.md架构定义 + AnalysisSystemDesign.md §5§6
    Monitor Exec Devin不能改，只在REPORT+WORKLOG记录建议
  · 判定标准：改的是"是什么"（事实）还是"应该是什么"（设计决策）
- S7从"未修改禁止文件"修正为"未修改第二级架构级规范"
- 新增S15（第一级文档同步）/S16（第二级规范建议记录）/S17（同步清单完整性）
- §5工作流程第三步加入"同步修改第一级文档"和S16，第四步加入S15-S17
- 解决的核心问题：改代码不改文档→下一轮认知过时→按过时认知工作→死循环

### 迭代规则

- **系统检查项目变更时**（新增/修改/删除A/B/C类检查项）→ 更新§3 + 更新`p27_monitor_spec.md`
- **self检查项目变更时**（新增/修改/删除S类检查项）→ 更新§4
- **认知资产变更时**（新增/修改/删除文档）→ 更新§2
- **Monitor Exec Devin工作流程变更时** → 更新§5
- **每次修改都记录在§6** —— 版本号+日期+修改内容摘要

---

## §7. 与其他规范的关系

| 规范 | 关系 |
|---|---|
| `p27_monitor_spec.md` | 本规范引用其A/B/C类检查详细标准。本规范是入口，p27_monitor_spec.md是详情 |
| `p27_session_management_and_polish_spec.md` | 本规范引用其session管理和Monitor Exec Devin架构。本规范补充了self检查项目 |
| `MonitorPipe.md` | 本规范是MonitorPipe.md范式在POC-2.7上的具体化。MonitorPipe.md定义跨项目范式，本规范定义POC-2.7的具体操作 |
| `AnalysisSystemDesign.md` | 本规范被其§2文档体系索引。AnalysisSystemDesign.md是系统总索引，本规范是Monitor Exec Devin的专属入口 |
