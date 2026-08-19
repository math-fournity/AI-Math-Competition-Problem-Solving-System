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
  tmux/tmux.log               # tmux pane日志
  tmux/tmux_pipe.log          # tmux pipe-pane日志
```

`exec_seq` 是单调递增的序号（从DB的session_counter读取），永不复用。

### 1.2 资产保留铁律

- **等DONE.md出现才处理**——绝不主动kill无DONE.md的session（见`p27_session_management_and_polish_spec.md` §A.5）
- **export是完整thinking**——conversation.json的reasoning_content记录Monitor Exec Devin的完整推理过程，事后可审计
- **MONITOR_EXEC_REPORT.md是自述报告**——本轮检查了什么、发现了什么、判断了什么、修复了什么
- **tmux.log是行为日志**——记录devin cli的TUI输出，包括工具调用和结果

### 1.3 session注册表记录

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
    "status": "running",  # running | done | stuck | cleaned
}
```

### 1.4 运行历史可查询

```bash
# 查看所有Monitor Exec Devin运行记录
cd analysis-devin-failure-system
.venv/bin/python3 -m monitoring.continuation_control sessions --type monitor_exec

# 查看特定运行的report
cat /Volumes/data/p27-monitor-exec/{exec_seq}/MONITOR_EXEC_REPORT.md

# 查看特定运行的thinking（export）
# 用read工具读 /Volumes/data/p27-monitor-exec/{exec_seq}/conversation.json
```

---

## §2. 认知资产加载清单

**Monitor Exec Devin启动后、正式工作前，必须加载以下认知资产**。这些资产保证Monitor Exec Devin了解系统架构、检查标准、修复规范。如果这些资产不是最新的，Monitor Exec Devin的工作可能基于过时信息。

### 2.1 必读资产（每次启动都读）

| 序号 | 文档 | 路径 | 用途 |
|---|---|---|---|
| 1 | **本文档** | `analysis-devin-failure-system/specs/p27_monitor_pipe_operations.md` | 认知资产入口+检查项目完整清单+self检查 |
| 2 | **检查规范详情** | `analysis-devin-failure-system/specs/p27_monitor_spec.md` | A/B/C类检查的详细标准（阈值/方法/通过条件） |
| 3 | **session管理+Exec Devin架构** | `analysis-devin-failure-system/specs/p27_session_management_and_polish_spec.md` | session注册表/DONE.md铁律/Monitor Exec Devin工作循环/prompt构造 |

### 2.2 按需读取资产（遇到相关问题时读）

| 序号 | 文档 | 路径 | 何时读 |
|---|---|---|---|
| 4 | 系统总索引 | `/Users/user/glm5.2-math-worktree/AnalysisSystemDesign.md` | 需要理解系统全貌、找代码资产位置时 |
| 5 | Monitor Pipe设计范式 | `/Users/user/glm5.2-math-worktree/MonitorPipe.md` | 需要理解Monitor Pipe三层架构设计时 |
| 6 | 续传规范 | `/Users/user/glm5.2-math-worktree/续传规范文档.md` | 修复续传相关bug时（HANDOFF.md结构/截断判定/prompt模板） |
| 7 | 系统架构 | `analysis-devin-failure-system/docs/architecture.md` | 需要理解4个Pipe的演进和目录结构时 |
| 8 | 优雅停止 | `analysis-devin-failure-system/docs/graceful-shutdown.md` | 修复停止/watchdog相关bug时 |
| 9 | 运维关注点 | `analysis-devin-failure-system/docs/operational-concerns.md` | 修复rate_limit/stall/zombie/多轮续传相关bug时 |
| 10 | 框架检查清单 | `analysis-devin-failure-system/docs/framework-checklist.md` | 检查自己是否遗漏框架级问题时 |

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
| S7. 未修改禁止文件 | 检查git diff --name-only | 不包含AGENTS.md/specs/*.md/MonitorPipe.md/AnalysisSystemDesign.md/.devin/rules/*.md | 如果误改了，git checkout还原 |
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

---

## §5. Monitor Exec Devin的完整工作流程

```
启动（Python部分定时启动，分配exec_seq，创建work_dir，写入注册表）
  │
  ▼
加载认知资产（读§2的必读资产）
  │
  ├── 1. 读本文档（p27_monitor_pipe_operations.md）—— 知道检查什么、怎么工作
  ├── 2. 读p27_monitor_spec.md —— 知道A/B/C类检查详细标准
  └── 3. 读p27_session_management_and_polish_spec.md —— 知道session管理和自己的工作规范
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
  │   ├── 修复
  │   ├── S5: py_compile验证
  │   ├── S7+S8: 检查未修改禁止文件 + git add规范
  │   └── git commit
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
  └── S13-S14: 循环检测
  │
  ▼
第五步：写MONITOR_EXEC_REPORT.md
  │
  ├── §检查结果摘要（A/B/C类alert统计）
  ├── §C类AI判断详情（每条抽样的判断结果+依据）
  ├── §修复操作（每个修复的根因+方案+commit+验证）
  ├── §self-check结果
  ├── §未修复的问题（及原因）
  └── §下一轮建议（如有）
  │
  ▼
第六步：resolve已处理的alert
  │
  ├── 修复了的代码bug → resolve对应alert
  ├── C类判定PASS的 → resolve对应needs_ai_review标记
  └── C类判定FAIL的 → 写新alert（ai_review_*）不resolve原标记
  │
  ▼
退出（DONE.md出现，Python部分下一轮定时启动）
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
