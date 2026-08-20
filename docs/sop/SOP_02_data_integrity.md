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

### rounds_log 的 7 个路径字段

每个 run 的 DB 记录中有 `rounds_log` 数组，每条记录对应一轮：

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

**7个路径字段**：export / handover_path / map_path / prompt_path / prev_export / proof_path + work_dir（在run记录顶层）

### DB 集合

- `p27_continuation_runs` — 每道题的续传记录（含 rounds_log、status、final_status）
- `p27_continuation_events` — 事件流（7种事件类型）
- `p27_continuation_results` — 最终结果
- `p27_sessions` — session 注册表（含 export_path、work_dir、status）

### 本步骤检查什么

上方"自动化检查结果"已经抽查了 10 个 run 的数据完整性。你需要：

---

## 执行指令

### 1. 阅读自动化抽查结果

上方 checks.py 已经抽查了最近 10 个有 rounds_log 的 run，检查了：
- rounds_log 中 7 个路径字段指向的文件是否存在
- export 文件是否过小（<100字节）
- **proof.md 质量统计（RUN-05）**——全量统计 COMPLETED 数 / proof.md 存在数 / 有 boxed 数，计算存在率和 boxed 率

重点关注：
- COMPLETED 的 run 缺少 proof.md → 数据丢失风险（critical）
- proof.md 存在但没有 `\boxed` → 未完成的证明（warning）

如果发现问题，逐个确认是否是真实问题（不是路径格式变化导致的误报）。

### 2. 深度检查（你需要手动执行）

#### 2a. DB 记录和文件状态一致性

抽查几个 completed 的 run，确认：
- DB 中 `final_status = "COMPLETED"` 的 run，`proof_path` 指向的文件确实存在
- DB 中 `status = "running"` 的 run，对应的 tmux session 确实在运行
- DB 中 `status = "prepared"` 的 run，work_dir 存在且 problem.txt 存在

#### 2b. Redis 队列和 DB status 一致性

```python
from src.continuation_redis_queue import get_redis, pending_count, running_count
r = get_redis()
print(f"Redis pending: {pending_count(r)}")
print(f"Redis running: {running_count(r)}")
```

对比 DB 中 `status=prepared` 的数量和 Redis pending 数量——应该接近（prepared 的题被 feeder 入队后变成 pending）。

#### 2c. session 注册表数据完整性

```python
from src.continuation_db_schema import connect_db
from src.session_registry import list_sessions
db = connect_db()
sessions = list_sessions(db, status="running", limit=20)
for s in sessions:
    export_path = s.get("export_path", "")
    work_dir = s.get("work_dir", "")
    # 检查路径是否存在
```

检查项：
- `running` 状态的 session，`export_path` 的父目录是否存在
- `done` 状态的 session，`done_md` 是否为 True
- `stuck` 状态的 session，notes 字段是否记录了原因

#### 2d. 事件流完整性

每个 run 的事件流应该包含：
- `continuation_launched`（每轮启动时）
- `continuation_completed` 或 `continuation_failed`（每轮结束时）

抽查几个 run，确认事件流完整——没有"启动了但没有完成/失败事件"的轮次（除非还在 running）。

### 3. 记录发现的问题

每个数据完整性问题记录：
- 哪个 run（problem_id）
- 哪个字段/文件
- 什么问题（文件不存在/字段缺失/不一致）
- 严重程度（critical=数据丢失 / warning=字段缺失 / info=不一致但不影响运行）

---

## 你需要建立的 todo list

- 阅读自动化抽查结果
- 深度检查 2a-2d（每个一个 todo）
- 记录发现的问题
- **最后一项固定是**：`执行下一个脚本: python -m scripts.sop.run`

完成所有 todo 后，自动触发步骤03（alert分类）。
