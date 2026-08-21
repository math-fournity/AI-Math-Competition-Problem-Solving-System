# SOP_02：数据完整性检查

## 认知闭包（执行前必读）

### 每道题的续传过程产生什么数据

每道题（一个 run）经过多轮续传，每轮产生以下文件：

| 产出文件 | 位置 | 内容 | 谁写 |
|---|---|---|---|
| `conversation.json` | `{trajectory_dir}/round{N}/exports/` | devin cli 的完整 thinking（export） | devin cli `--export` |
| `proof.md` | `{work_dir}/` | 解题产出（含 `\boxed` 答案） | devin cli |
| `round{N}_HANDOVER.md` | `{work_dir}/` | 交接文档（v2方案 Pipe A 产出） | handover devin cli |
| `round{N}_conversation_map.md` | `{work_dir}/` | 面包屑地图 | conversation_mapper.py |
| `round{N}_prompt.txt` | `{work_dir}/` | 发给 devin cli 的 prompt | continuation_launcher.py |
| `DONE.md` | `{export_dir}/` | 退出标记（含 exit code） | devin cli 退出时 |
| `tmux.log` | `{trajectory_dir}/tmux/` | tmux 日志 | tmux capture |

### rounds_log 的字段结构

每个 run 的 DB 记录中有 `rounds_log` 数组，每条记录对应一轮：

**round=1 是 seed 预检轮**（2026-08-20 起补录——017 sim 实证的 off-by-one
修复）：launcher 取件时对 seed export 重判截断/完成，结果补录为 round-1
条目。它没有自己的 prompt/handover/proof（那是 R2 起才有的），唯一产物是
`round1_export.json`（seed 镜像），所以只有 5 个基础字段。checks.py 对
round-1 只必查 export。R2 起的条目才是完整结构（5基础字段 + method/
handover_success + 6 个路径字段）。

> **WP-S 双位置说明（2026-08-21 起）**：round1 的 seed 镜像现在双写——
> work_dir 的 `round1_export.json`（rounds_log export 字段仍指向此处，兼容既有
> 检查）+ traj 的 `round1/exports/conversation.json`（与 R2+ 目录结构一致）。
> 旧 run 双位置可能皆缺（早于 WP-S），checks.py 对缺失只提示不计 issue。

```python
{
    "round": 2,
    "export": ".../round2/exports/conversation.json",
    "truncated": False,
    "completed": True,
    "reason": "proof.md有boxed",
    "method": "v2",
    "handover_path": ".../round1_HANDOVER.md",
    "map_path": ".../round1_conversation_map.md",
    "prompt_path": ".../round2_prompt.txt",
    "prev_export": ".../round1_export.json",
    "proof_path": ".../round2_proof.md",  # 归档路径
}
```

**6个路径字段**：export / handover_path / map_path / prompt_path / prev_export / proof_path（work_dir 在 run 记录顶层，不在 rounds_log 条目内）

> DB 集合全景见上方 SYSTEM_CLOSURE（L0）§5。本步骤检查 rounds_log 的字段完整性（下方）。

### 本步骤检查什么

上方"自动化检查结果"已经全量检查了最多 200 个 run 的每轮输入/输出文件完整性。你需要：

---

## 执行指令

### 1. 阅读自动化全量检查结果

上方 checks.py 已经全量检查了最多 200 个有 rounds_log 的 run，对每个 run 的每一轮检查了：
- **6 个路径字段**（export/prompt_path/proof_path/handover_path/map_path/prev_export）指向的文件是否存在
- **必需字段**（export/prompt_path）为空 → 标记为问题；**可选字段**为空 → 跳过
- 文件过小（<100字节）→ 标记为问题
- **内容质量检查**：
  - export 是否为有效 JSON 格式
  - proof.md 内容是否过短（<50字符）
  - HANDOVER.md 内容是否过短（<200字符）
  - prompt 内容是否过短（<100字符）
- **proof.md 质量统计（RUN-05）**——全量统计 COMPLETED 数 / proof.md 存在数 / 有 boxed 数，计算存在率和 boxed 率

自动化检查还包含以下**数据库集合级和跨题目级别**的检查：

- **results 集合检查**——results 集合文档数 vs runs 中 COMPLETED 数。results < COMPLETED → 结果未归档（critical）
- **events 完整性检查**——有 launched 但无 completed/failed 的 run。可能是还在运行或崩溃未写完成事件（warning）
- **prepared 堆积检查**——prepared 状态的 run 数 vs Redis pending 数。prepared > 0 但 pending = 0 → feeder 没在入队（critical）
- **按题源完成率统计**——按 problem_id 前缀分组统计完成率。完成率 = 0% 的题源 → 系统性问题（critical）
- **标准文件检查**——problem.txt / proof.md / round1 export 是否存在（rounds_log 之外的文件）
- **round 编号连续性检查**——rounds_log 的 round 字段是否连续。
  ~~当前全部从 round=2 开始——需确认是否 by design~~
  **已确认不是 by design**（2026-08-20，017 sim 实证 off-by-one）：round-1
  曾不补录导致 R2 被重跑。已修复——正常轮序为 `[1, 2, 3, ...]` 连续；
  出现重复轮号（如 `[2,2,3]`）= 旧数据或 bug 复发，应排查

重点关注：
- COMPLETED 的 run 缺少 proof.md → 数据丢失风险（critical）
- proof.md 存在但没有 `\boxed` → 未完成的证明（warning）
- results 集合为空但有 COMPLETED → 结果未归档（critical）
- 某些题源完成率全 0% → 系统性问题，需诊断原因（critical）
- prepared 堆积但 pending=0 → feeder 没在入队（critical）

如果发现问题，逐个确认是否是真实问题（不是路径格式变化导致的误报）。

### 2. 深度检查（你需要手动执行）

#### 2a-2c. 持久化深度检查脚本

2a（DB记录和文件状态一致性）、2b（Redis队列和DB status一致性）、2c（session注册表数据完整性）已提取成持久化脚本，避免 inline 代码在上下文压缩后丢失：

```
python -m scripts.sop.deep_checks_02 --batch-id p27-full
```

脚本输出包含：
- **2a**：抽查 COMPLETED run 的 proof_path 存在性 / running run 的 tmux session 活跃性 / prepared run 的 work_dir+problem.txt
- **2b**：Redis pending/running 数 vs DB prepared 数，比例异常时告警
- **2c**：running session 的 export_path 父目录 / done session 的 done_md / stuck session 的 notes 记录

#### 2d. 事件流完整性

每个 run 的事件流应该包含：
- `continuation_launched`（每轮启动时）
- `continuation_completed` 或 `continuation_failed`（每轮结束时）

自动化检查已输出有 launched 无 completed/failed 的 run 列表。确认这些 run：
- 如果 status=running → 正常（还在跑）
- 如果 status=completed/dead_session → 异常（事件丢失）

#### 2e. 跨题目模式分析（AI 必须做）

自动化检查已输出按题源分组的完成率统计。这是**脚本给数据、AI 看趋势**的检查项：

1. **完成率全 0% 的题源**——诊断原因：
   - 这些题源的 run 是否都是 prepared？（还没跑到）
   - 还是跑了但都失败了？（prompt 不适用？model 不胜任？）
   - 还是跑了但都 truncated？（token 不够？题太难？）
   - 用 AQL 按题源分组查 status 和 final_status 分布

2. **完成率差异大的题源**——分析是否有共同特征：
   - 题目类型（几何/代数/数论/组合）
   - 题目难度
   - 题目来源（竞赛题/教材题/生成题）

3. **失败模式分布**——统计 truncated / no_proof / timeout / stall 各占多少：
   - 全截断（5轮全 truncated）→ 可能是 token 不够
   - 有 proof 但无 boxed → 可能是能力不足
   - dead_session → 可能是基础设施问题

**这是 AI 的核心价值**——脚本能统计分组数据，但只有 AI 能判断"为什么 oda 和 polymath 全 0%"是系统性问题还是还没跑到。

### 3. 填写报表（必须做）

脚本运行时已自动在D盘生成报表目录，并把报表模板复制过去：

```
/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-sop-reports/cycle_{NNN}/step_02/{timestamp}/
  report.md           ← 从模板复制过来，你必须填写这个文件
  snapshot.json       ← 系统快照（聚合统计）
  snapshot_runs.json  ← 全量per-run数据（919条）
  check_output.txt    ← 脚本输出原文
```

**报表模板是项目运行期资产**，存放在 `docs/sop/templates/report_step_02.md`。模板中包含：
- 检查项清单（每个检查项的编号、名称、类型、检查方法、填写位置）
- 系统快照摘要的填写格式
- 发现的问题/执行的操作/未修复的问题/下一轮建议的填写位置

**你必须**：
1. 用 read 工具加载D盘报表目录中的 `report.md`（路径在脚本输出末尾已打印）
2. 先读 `snapshot.json` 和 `check_output.txt`，获取系统快照和脚本输出
3. 按模板中每个检查项的"检查方法"逐项检查，在"结果"列打勾：`[x]` 通过 / `[!]` 有问题 / `[ ]` 待检查 / `[-]` 不适用
4. 在"详情"列填写每个检查项的发现
5. 填写"发现的问题"——按 Critical / Warning / Info 分级
6. 填写"执行的操作"——做了什么修复/重启/重跑
7. 填写"未修复的问题及原因"
8. 填写"下一轮建议"
9. 用 edit 工具写回同一文件

**报表是审计痕迹**——回头可以 grep 到某一轮检查、某个step中、AI的报表文件到底是什么、查了什么、结果是什么。不填写报表 = 检查没有完成。

### 4. 记录发现的问题

每个数据完整性问题记录在 report.md 的"发现的问题"节中：
- 哪个 run（problem_id）
- 哪个字段/文件
- 什么问题（文件不存在/字段缺失/不一致）
- 严重程度（critical=数据丢失 / warning=字段缺失 / info=不一致但不影响运行）

---

## 你需要建立的 todo list

- 阅读自动化全量检查结果
- 深度检查 2a-2e（每个一个 todo）
- **填写 report.md 报表**（read加载→打勾填发现→edit写回）
- **最后一项固定是**：`执行下一个脚本: python -m scripts.sop.run`

完成所有 todo 后，自动触发步骤03（alert分类）。

### 3. 日志观察（数据完整性相关的日志事件）

```
# 查看 session 创建/状态变更日志
python -m scripts.sop.log_search --event create_session_record --tail 30
python -m scripts.sop.log_search --event update_session_status --tail 30
python -m scripts.sop.log_search --event check_done_md --tail 30

# 查看 DB 操作日志
python -m scripts.sop.log_search --event insert_run --tail 20
python -m scripts.sop.log_search --event update_run --tail 20

# 查看 Redis 队列操作日志
python -m scripts.sop.log_search --event enqueue_pending --tail 20
python -m scripts.sop.log_search --event add_completed --tail 20
python -m scripts.sop.log_search --event add_failed --tail 20

# 查看某道题的完整生命周期
python -m scripts.sop.log_search --problem-id <problem_id>
```
