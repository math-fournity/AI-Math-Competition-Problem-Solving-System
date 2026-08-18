# POC-2.7续传Pipe检查规范（系统资产）

**用途**：定义POC-2.7续传Pipe的Monitor Pipe应该检查什么、检查标准是什么。
Monitor Pipe代码（`monitor_continuation.py`）按本规范执行检查，查询脚本（`monitor_check_continuation.sh`）按本规范输出检查结果和行动清单。

**对应文档**：
- 方案文档：`Tell分类学研究过程文档/415-v0-2026-08-18-POC-2.7-截断vs思维错误.md`
- 续传规范：`续传规范文档.md`
- 参考实现：`analysis-devin-failure-system/src/monitor_selection.py`（Pipe 3的Monitor Pipe）

---

## 1. 模块职责

Monitor Pipe持续监控POC-2.7续传批次的运行健康，把**应该由Master AI智能检查的项目**全部自动执行并写alert到ArangoDB，让Master AI通过查询脚本发现这些alert并逐个处理。

**核心设计原则**（来自用户原话）：
- Monitor Pipe的目的是让应该由Master AI进行智能检查的项目全部放入这个Pipe
- 然后留下检查结果（alert），让Master AI的检查脚本可以查询到这些问题
- 然后让Master AI可以整改
- 查询脚本每次检查都要调用，它在输出结果的最后提醒Master AI去检查Monitor Pipe留下的检查结果

---

## 2. 检查项目分类

### 2.1 A类：自动检查（脚本判定，不需要AI）

这些是代码能机械判定的检查项，Monitor Pipe自动执行，发现问题写alert。

| 检查项 | alert_type | severity | 阈值 | 说明 |
|---|---|---|---|---|
| A1. session_health | session_health | critical | — | p27- session数 vs DB running数 vs 设定并发——不匹配说明launcher挂了 |
| A2. queue_progress | queue_stalled | critical | 15分钟无变化 | pending队列没在减少 |
| A3. queue_progress | no_completions | warning | 15分钟无变化 | completed没在增加 |
| A4. rate_limit_detection | rate_limit | critical | ≥3个 | 最近interval内rate_limited数量 |
| A5. zombie_sessions | zombie_sessions | warning | ≥2个 | 空pane僵尸session（devin cli退出后tmux残留） |
| A6. export_landing | export_missing | critical | 缺失率>10% | completed的run无export文件 |
| A7. failure_rate | failure_rate | warning | >15% | 最近interval失败率 |
| A8. launcher_dead | launcher_dead | critical | — | launcher进程消失但还有prepared/running任务 |
| A9. stall_detection | long_running | warning | 单轮>30分钟 | 单个续传轮次运行超时 |

### 2.2 B类：续传质量检查（POC-2.7特有，脚本判定）

这些是POC-2.7续传Pipe特有的质量检查，针对续传结果的结构化判定。

| 检查项 | alert_type | severity | 阈值 | 说明 |
|---|---|---|---|---|
| B1. proof_completeness | proof_missing | critical | — | COMPLETED的run无proof.md文件 |
| B2. proof_completeness | proof_no_boxed | warning | — | proof.md存在但无\boxed答案 |
| B3. proof_too_small | proof_too_small | warning | <1KB | proof.md太小，可能内容不完整 |
| B4. handover_completeness | handover_missing | critical | — | v2方案的round无HANDOVER.md |
| B5. handover_completeness | handover_too_small | warning | <500B | HANDOVER.md太小，可能不完整 |
| B6. truncation_pattern | all_rounds_truncated | warning | 5轮全截断 | 5轮全部TRUNCATED，可能是思维错误 |
| B7. final_status_distribution | status_anomaly | info | — | final_status分布异常（全TRUNCATED或全ERROR） |

### 2.3 C类：AI review抽样（需Master AI判断）

这些检查无法用代码完成，需要Master AI判断。Monitor Pipe每3轮抽样2条结果，标记为needs_ai_review，Master AI通过查询脚本发现后逐个检查。

| 检查项 | alert_type | severity | AI需要检查什么 |
|---|---|---|---|
| C1. proof_quality | ai_review_sample | info | proof.md的数学正确性——答案对不对、证明逻辑是否完整 |
| C2. proof_hallucination | ai_review_sample | info | proof.md是否有幻觉——编造的定理、不存在的引用、虚假的计算结果 |
| C3. answer_leak | ai_review_sample | info | proof.md是否答案泄漏——直接从题目描述中抄答案而非推导 |
| C4. handover_quality | ai_review_sample | info | HANDOVER.md是否准确总结了上一轮的思考——有没有遗漏关键结论、有没有编造内容 |
| C5. continuation_direction | ai_review_sample | info | 续传方向是否正确——AI是在上一轮的基础上继续，还是从头开始重复 |

---

## 3. 检查标准（详细）

### 3.1 A类自动检查标准

#### A1. session_health
- **检查方法**：`tmux list-sessions | grep "^p27-"` 获取实际session数，对比DB中`status='running'`的run数
- **critical条件**：tmux p27- session数=0 但DB running>0 → launcher可能挂了
- **warning条件**：tmux p27- session数 < 设定并发数 且 >0 → 并发不足

#### A2/A3. queue_progress
- **检查方法**：Redis `p27:pending`/`p27:completed` 计数，对比上一轮
- **critical条件**：pending>0 且15分钟内pending无变化 → queue_stalled
- **warning条件**：pending>0 且15分钟内completed无变化 → no_completions

#### A4. rate_limit_detection
- **检查方法**：DB中最近interval内`status='rate_limited'`的run数
- **critical条件**：≥3个rate_limited
- **warning条件**：>0个rate_limited

#### A5. zombie_sessions
- **检查方法**：`tmux list-sessions | grep "^p27-"`，对每个session用`tmux capture-pane`检查pane是否空白
- **warning条件**：≥2个空pane session（devin cli已退出但tmux session残留）

#### A6. export_landing
- **检查方法**：抽样5个`status='completed'`的run，检查export_path文件是否存在
- **critical条件**：缺失率>10%

#### A7. failure_rate
- **检查方法**：DB中最近interval内failed/finished的比例
- **warning条件**：失败率>15%

#### A8. launcher_dead
- **检查方法**：`pgrep -f "run_continuation_pipeline.*launch"` 检查launcher进程
- **critical条件**：进程不存在但还有prepared/running任务

#### A9. stall_detection
- **检查方法**：DB中`status='running'`的run的`started_at`时间
- **warning条件**：单个run运行>30分钟（DEFAULT_MAX_RUNTIME_SECONDS=1800）

### 3.2 B类续传质量检查标准

#### B1. proof_missing
- **检查方法**：`final_status='COMPLETED'`的run，检查work_dir/proof.md是否存在
- **critical条件**：COMPLETED但无proof.md

#### B2. proof_no_boxed
- **检查方法**：读proof.md内容，正则匹配`\\boxed`
- **warning条件**：proof.md存在但无boxed答案

#### B3. proof_too_small
- **检查方法**：proof.md文件大小
- **warning条件**：<1KB（proof内容不完整）

#### B4/B5. handover_completeness
- **检查方法**：v2方案的round目录下HANDOVER.md是否存在、大小是否>500B
- **critical条件**：v2方案但无HANDOVER.md
- **warning条件**：HANDOVER.md <500B

#### B6. all_rounds_truncated
- **检查方法**：`final_status='TRUNCATED_AT_MAX'`的run，检查rounds_log中每轮的truncated字段
- **warning条件**：5轮全部truncated=True → 可能是真正的思维错误（不是截断错误）

#### B7. status_anomaly
- **检查方法**：final_status分布统计
- **info条件**：全TRUNCATED_AT_MAX或全ERROR → 数据/机制问题

### 3.3 C类AI review抽样标准

#### 抽样频率
- 每3轮（约6-15分钟）抽样2条`final_status='COMPLETED'`的run

#### AI需要检查的5项（C1-C5）
对每条抽样结果，Master AI需要：

1. **C1. proof_quality**——读proof.md，检查数学正确性
   - 答案是否正确（对照标准答案，如果有的话）
   - 证明逻辑是否完整（有没有跳步、有没有未证明的断言）
   - 通过标准：答案正确且证明逻辑完整

2. **C2. proof_hallucination**——检查proof.md是否有幻觉
   - 是否引用了不存在的定理
   - 是否编造了计算结果
   - 是否声称用了某个方法但实际没有
   - 通过标准：无幻觉

3. **C3. answer_leak**——检查是否答案泄漏
   - 是否直接从题目描述中抄答案
   - 是否用"显然""易证"等逃避推导
   - 通过标准：答案是通过推导得到的，不是抄的

4. **C4. handover_quality**——读HANDOVER.md，检查交接文档质量
   - 是否准确总结了上一轮的思考
   - 有没有遗漏关键结论
   - 有没有编造内容
   - 通过标准：准确总结、无遗漏、无编造

5. **C5. continuation_direction**——对比本轮proof和上一轮thinking
   - AI是在上一轮的基础上继续，还是从头开始重复
   - 通过标准：在上一轮基础上继续

---

## 4. alert结构

```json
{
  "_key": "p27-alert-{timestamp}-{type}",
  "alert_type": "session_health | queue_stalled | rate_limit | ...",
  "severity": "critical | warning | info",
  "details": {
    "summary": "一句话描述",
    "problem_id": "相关题目ID（如适用）",
    "run_key": "相关run的key（如适用）",
    ...其他上下文字段
  },
  "status": "new | reviewing | fixed | wontfix",
  "created_at": "ISO timestamp",
  "resolved_at": null
}
```

**alert集合**：`p27_monitor_alerts`（独立于现有Pipe的`monitor_alerts`集合）

---

## 5. Monitor Pipe运行规范

### 5.1 运行方式
- 在独立tmux session中运行：`tmux new-session -d -s monitor-p27 "cd ... && python -m src.monitor_continuation --batch-id p27-full"`
- 检查间隔：120秒（2分钟）
- 所有任务完成后自动退出

### 5.2 检查顺序（每轮）
1. A1-A9自动检查（顺序执行）
2. B1-B7续传质量检查（从第2轮开始，需要有completed的run）
3. C1-C5 AI review抽样（每3轮一次）
4. 创建alerts
5. 状态报告
6. 检查退出条件（所有任务完成）

---

## 6. 查询脚本输出规范（monitor_check_continuation.sh）

### 6.1 输出6项检查
1. **Monitor Pipe pane输出**——最近5轮的ALERT/AI_REVIEW/status/progress
2. **alerts集合**——所有新alert的详情
3. **进程状态**——launcher + monitor_continuation + p27- session数
4. **进度**——DB状态分布 + final_status分布 + 通过率
5. **续传质量汇总**——proof.md统计 + HANDOVER.md统计 + 截断模式统计
6. **通过率判定**——对照415号§7.1的通过标准

### 6.2 行动清单（输出最后）
```
>> 行动清单（按顺序执行）：
   1. 仔细阅读第1项Monitor Pipe pane输出中的每轮ALERT和AI_REVIEW
   2. 有新alert时逐个recheck（第2项），处理完用--resolve-alert标记
   3. 进程NOT RUNNING时重启launcher/monitor（第3项）
   4. 有新增失败时重新入队（第4项）
   5. 进度停滞时检查launcher日志和rate_limit_pause状态
   6. 从alert的problem_ids字段获取需重跑的题，改status为prepared后重新launch
   7. AI_REVIEW抽样的结果——读proof.md和HANDOVER.md，按C1-C5标准逐项检查
   8. 对照第6项通过率判定——如果COMPLETED≥50%，POC-2.7通过
```

---

## 7. 和其他规则的关系

- **`six-dual-check-mechanism.md`**：本规范是双重检查机制在POC-2.7续传Pipe上的具体化。A类和B类是"代码能检查的"，C类是"AI需要检查的"。
- **`six-asset-grading.md`**：本规范是第2级资产（文件），Monitor Pipe代码和查询脚本都参照本规范实现。
- **`six-trace-preservation.md`**：alert写入ArangoDB是痕迹保留——Master AI处理后标记为fixed，全过程可审计。
