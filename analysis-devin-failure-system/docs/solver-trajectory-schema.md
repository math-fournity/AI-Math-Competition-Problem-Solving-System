# 解题AI Trajectory文件Schema文档

> **基于50题采样（10个批次各5题）统计**。2026-08-15调查。
> 采样覆盖 dpb-20260812 的10个批次，共23911个trajectory目录。

## 目录结构

每个解题AI实验（exp_id）对应一个trajectory目录，包含以下文件：

```
{trajectory_base}/{exp_id}/
├── session_info.json              # 元数据（100%存在）
├── exports/
│   └── conversation.json          # ATIF格式export（58%存在）
├── sessions_db/
│   └── trajectory.jsonl           # SQLite导出的trajectory（82%存在）
├── mitm/                           # MITM截获数据（38%存在，仅早期批次）
│   ├── thinking_live.jsonl        # 实时thinking chunks
│   ├── thinking_live.txt          # 实时thinking文本
│   ├── thinking_readable.txt      # 可读格式thinking
│   └── trajectory.jsonl           # MITM解码的完整trajectory
└── tmux/
    ├── tmux_pipe.log              # tmux pipe-pane输出（90%存在）
    ├── tmux.log                   # tmux日志（90%存在）
    └── thinking_capture.txt       # thinking截获（部分后期批次，常为空）
```

### 文件存在率（50题采样）

| 文件 | 存在率 | 平均大小 | 最小 | 最大 |
|---|---|---|---|---|
| session_info.json | 50/50 (100%) | 1,095 B | 1,026 B | 1,151 B |
| exports/conversation.json | 29/50 (58%) | 154,795 B | 115,804 B | 332,067 B |
| sessions_db/trajectory.jsonl | 41/50 (82%) | 50,280 B | 272 B | 163,432 B |
| mitm/thinking_live.jsonl | 19/50 (38%) | 1,450,713 B | 12,827 B | 3,260,650 B |
| mitm/thinking_live.txt | 19/50 (38%) | 347,372 B | 2,103 B | 793,545 B |
| mitm/thinking_readable.txt | 19/50 (38%) | 30,168 B | 469 B | 79,032 B |
| mitm/trajectory.jsonl | 18/50 (36%) | 140,617 B | 2,313 B | 326,200 B |
| tmux/tmux_pipe.log | 45/50 (90%) | 741,975 B | 0 B | 17,544,586 B |
| tmux/tmux.log | 45/50 (90%) | 742,471 B | 0 B | 17,544,586 B |

### MITM按批次分布

| 批次前缀 | MITM存在率 |
|---|---|
| dpb-20260812-021956 | 5/5 (100%) |
| dpb-20260812-023218 | 4/5 (80%) |
| dpb-20260812-030508 | 3/5 (60%) |
| dpb-20260812-033649 | 5/5 (100%) |
| dpb-20260812-041914 | 2/5 (40%) |
| dpb-20260812-063817 | 0/5 (0%) |
| dpb-20260812-065425 | 0/5 (0%) |
| dpb-20260812-070744 | 0/5 (0%) |
| dpb-20260812-080658 | 0/5 (0%) |
| dpb-20260812-manual | 0/5 (0%) |

**结论**：早期批次（021956-041914）有MITM，后期批次（063817起）没有MITM。session_info.json中`mitm_enabled`字段为True/False各50%。

---

## 1. session_info.json

元数据文件，100%存在。

### Schema

```json
{
  "exp_id": "string — 实验ID",
  "model": "string — 模型名，如'glm-5-2'",
  "prompt": "string — 给解题AI的初始prompt",
  "problem_file": "string — 题目文件路径",
  "solver_dir": "string — 解题AI工作目录路径",
  "trajectory_dir": "string — trajectory目录路径",
  "tmux_session": "string — tmux session名",
  "mitm_port": "int — MITM代理端口",
  "mitm_enabled": "bool — 是否启用MITM",
  "devin_session_id": "string — Devin CLI的session ID",
  "start_timestamp": "string — ISO格式开始时间",
  "status": "string — 状态（如'stopped'）",
  "interactive": "bool — 是否交互模式",
  "updated_at": "string — ISO格式更新时间"
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| exp_id | string | 唯一实验标识符 |
| model | string | 模型名，采样中全部为`glm-5-2` |
| prompt | string | 给AI的初始指令，如"请读取当前目录下的problem.txt文件，解答其中的数学题。" |
| problem_file | string | 题目文件路径 |
| solver_dir | string | 解题AI的工作目录 |
| trajectory_dir | string | trajectory存储目录 |
| tmux_session | string | tmux session名称 |
| mitm_port | int | MITM代理端口号 |
| mitm_enabled | bool | 是否启用MITM截获 |
| devin_session_id | string | Devin CLI分配的session ID |
| start_timestamp | string | ISO 8601格式 |
| status | string | 实验状态 |
| interactive | bool | 是否交互模式 |
| updated_at | string | 最后更新时间 |

---

## 2. exports/conversation.json

ATIF格式export，58%存在。这是最完整的数据源。

### 顶层Schema

```json
{
  "schema_version": "string — 如'ATIF-v1.7'",
  "session_id": "string — Devin CLI的session ID",
  "agent": {
    "name": "string — 如'devin'",
    "version": "string — 如'3000.4.16'",
    "model_name": "string — 如'GLM-5.2 High'",
    "tool_definitions": "list[29] — 工具定义列表",
    "extra": {
      "backend": "string",
      "permission_mode": "string"
    }
  },
  "steps": "list[Step] — 步骤列表",
  "final_metrics": {
    "total_prompt_tokens": "int",
    "total_completion_tokens": "int",
    "total_cached_tokens": "int",
    "total_steps": "int"
  }
}
```

### Step类型

steps列表中有3种source类型的step：

#### 2.1 system step

```json
{
  "step_id": "int",
  "timestamp": "string — ISO格式",
  "source": "system",
  "message": "string — 系统消息内容",
  "extra": {
    "telemetry": {
      "source": "string — 如'sysprompt'",
      "operation": "string — 如'normal'"
    }
  }
}
```

system step的message内容分类（50题采样）：
- **system_prompt** (29个): 含"You are Devin"的系统提示词，约18653 chars
- **tool_related** (58个): 工具相关说明
- **short** (29个): 短消息（<100 chars）
- **other** (57个): 其他系统消息

#### 2.2 user step

```json
{
  "step_id": "int",
  "timestamp": "string",
  "source": "user",
  "message": "string — 用户输入",
  "extra": {
    "telemetry": {
      "source": "user",
      "operation": "unknown"
    }
  }
}
```

user step的message通常是解题指令，如"请按AGENTS.md中的题目直接解答"。

#### 2.3 agent step（最关键）

```json
{
  "step_id": "int",
  "timestamp": "string",
  "source": "agent",
  "message": "string — TUI输出内容",
  "model_name": "string — 如'glm-5-2'",
  "reasoning_content": "string — thinking内容（78%的agent step有）",
  "tool_calls": "list[ToolCall] — 工具调用（67%有）",
  "observation": {
    "results": [
      {
        "source_call_id": "string — 对应的tool_call_id",
        "content": "string — 工具返回结果"
      }
    ]
  },
  "metrics": {
    "prompt_tokens": "int",
    "completion_tokens": "int",
    "cached_tokens": "int"
  },
  "extra": {
    "generation_model": "string — 如'glm-5-2'",
    "telemetry": {
      "source": "assistant",
      "operation": "inference"
    }
  }
}
```

### agent step字段统计（89个agent step采样）

| 字段 | 存在率 | 说明 |
|---|---|---|
| step_id | 89/89 (100%) | 步骤ID |
| timestamp | 89/89 (100%) | 时间戳 |
| source | 89/89 (100%) | 固定为"agent" |
| message | 89/89 (100%) | TUI输出，长度0-5670 chars，avg=508 |
| model_name | 89/89 (100%) | 模型名 |
| reasoning_content | 69/89 (78%) | thinking内容，长度0-78128 chars，avg=11170 |
| tool_calls | 89/89 (100%) | 工具调用列表（可能为空） |
| observation | 60/89 (67%) | 工具返回结果（有tool_call时才有） |
| metrics | 89/89 (100%) | token统计 |
| extra | 89/89 (100%) | 额外信息 |

### ToolCall结构

```json
{
  "tool_call_id": "string — 如'chatcmpl-tool-a97adccc6e64f331'",
  "function_name": "string — 工具名",
  "arguments": {
    "command": "string — 命令内容（exec工具）",
    "file_path": "string — 文件路径（read/write/edit工具）",
    "content": "string — 文件内容（write工具）",
    "shell_id": "string — shell ID（get_output工具）",
    "timeout": "int — 超时（get_output工具）"
  }
}
```

### tool_call的function_name分布（60个tool_call）

| 工具名 | 次数 | 说明 |
|---|---|---|
| exec | 32 | 执行命令 |
| read | 11 | 读取文件 |
| write | 10 | 写入文件 |
| edit | 4 | 编辑文件 |
| get_output | 3 | 获取shell输出 |

**每个agent step最多1个tool_call**（min=1, max=1, avg=1.0）。

### observation结构

```json
{
  "results": [
    {
      "source_call_id": "string — 对应tool_call_id",
      "content": "string — 工具返回结果"
    }
  ]
}
```

- 每个observation有1个result（min=1, max=1, avg=1.0）
- result的content长度：42-1542 chars，avg=417
- **observation是tool_call返回结果的存储位置**——在conversation.json中，tool_results放在agent step的observation字段中，不在单独的tool step中

### steps数量分布

| 指标 | min | max | avg |
|---|---|---|---|
| steps总数 | 8 | 48 | 10 |
| agent_steps数 | 1 | 43 | 3 |

- 大部分题只有1个agent step（单轮thinking spin）
- 少数题有多达43个agent step（多轮thinking spin + 工具调用）

### final_metrics

```json
{
  "total_prompt_tokens": "int — 总prompt token数",
  "total_completion_tokens": "int — 总completion token数",
  "total_cached_tokens": "int — 缓存token数",
  "total_steps": "int — 总step数"
}
```

---

## 3. sessions_db/trajectory.jsonl

SQLite导出的trajectory，82%存在。每行一个JSON对象。

### Schema

```json
{
  "type": "string — 'step'",
  "node_id": "int — 节点ID",
  "parent_node_id": "int — 父节点ID",
  "role": "string — 'user'/'assistant'/'tool'",
  "content": "string — 消息内容",
  "thinking": "string — thinking内容（assistant角色有）",
  "tool_calls": "list — 工具调用列表",
  "created_at": "int — Unix时间戳"
}
```

### 行数分布

| 指标 | min | max | avg |
|---|---|---|---|
| 行数 | 1 | 22 | 4 |

### (type, role)分布

| (type, role) | 出现次数 | 说明 |
|---|---|---|
| (step, user) | 129 | 用户输入 |
| (step, assistant) | 111 | AI回复（含thinking） |
| (step, tool) | 27 | **工具返回结果** |

### tool行结构

```json
{
  "type": "step",
  "node_id": "int",
  "parent_node_id": "int",
  "role": "tool",
  "content": "string — 工具返回结果，105-1341 chars",
  "thinking": "string — 空字符串",
  "tool_calls": "list[0] — 空列表",
  "created_at": "int — Unix时间戳"
}
```

**关键**：sessions_db/trajectory.jsonl中的tool行`content`字段就是tool_call的返回结果。这是与conversation.json的不同之处——conversation.json把tool_results放在agent step的observation字段中，trajectory.jsonl把tool_results放在单独的tool行中。

---

## 4. mitm/thinking_live.jsonl

MITM实时截获的thinking chunks，38%存在（仅早期批次）。

### Schema

```json
{
  "timestamp": "string — ISO格式时间戳",
  "counter": "int — 计数器",
  "chunk_index": "int — chunk索引",
  "type": "string — 'thinking_chunk'",
  "content": "string — thinking文本片段"
}
```

### 行数分布

| 指标 | min | max | avg |
|---|---|---|---|
| 行数 | 68 | 25,072 | 11,196 |

- 每行是一个thinking chunk（流式截获的token片段）
- type全部为`thinking_chunk`
- 文件大小很大（avg 1.4MB），因为包含所有流式chunk

---

## 5. mitm/thinking_live.txt

MITM实时截获的thinking文本（拼接后），38%存在。

纯文本格式，是thinking_live.jsonl中所有chunk的content拼接。avg 347KB。

---

## 6. mitm/thinking_readable.txt

MITM可读格式thinking，38%存在。

纯文本格式，包含轮次标记：
```
============================================================
[02:22:50] === Thinking Round 1128 START ===
============================================================
Let me read the problem file.

--- [Tool Call: read] [02:22:50] ---

============================================================
[02:22:50] === Thinking Round 1128 END ===
  thinking: 29 chars, 7 chunks
  tool_calls: 1
  elapsed: 0.1s
============================================================
```

**特点**：
- 有轮次标记（Thinking Round N START/END）
- 有tool_call记录（`--- [Tool Call: read] ---`）
- **没有tool_call返回结果**（Tool Result）
- avg 30KB

---

## 7. mitm/trajectory.jsonl

MITM解码的完整trajectory，36%存在。

### Schema

```json
{
  "source_file": "string — 原始bin文件名",
  "session_id": "string — session UUID",
  "matched_exp": "string — 匹配的exp_id",
  "decoded_at": "float — 解码时间戳",
  "total_messages": "int — 总消息数",
  "content_thinking": "string — thinking内容",
  "content_chunks_count": "int — chunk数",
  "tool_calls": "dict — 工具调用"
}
```

### 行数分布

| 指标 | min | max | avg |
|---|---|---|---|
| 行数 | 3 | 33 | 16 |

每行对应一个完整的API响应（包含完整的thinking内容）。

---

## 8. tmux/tmux_pipe.log

tmux pipe-pane输出，90%存在。

纯文本格式，是tmux pane的完整输出（包括TUI渲染、ANSI转义码等）。大小变化大（0-17MB），取决于AI输出的长度和TUI渲染的复杂度。

---

## 9. tmux/tmux.log

tmux日志，90%存在。内容与tmux_pipe.log几乎相同。

---

## 数据源对比与选择建议

| 数据源 | 完整性 | 存在率 | thinking | tool_calls | tool_results | 轮次标记 |
|---|---|---|---|---|---|---|
| conversation.json | ★★★★★ | 58% | ✅ reasoning_content | ✅ tool_calls | ✅ observation | ❌ |
| sessions_db/trajectory.jsonl | ★★★★ | 82% | ✅ thinking | ✅ tool_calls | ✅ tool行content | ❌ |
| mitm/thinking_readable.txt | ★★★ | 38% | ✅ | ✅ 标记 | ❌ | ✅ |
| mitm/thinking_live.jsonl | ★★ | 38% | ✅ chunks | ❌ | ❌ | ❌ |
| mitm/trajectory.jsonl | ★★★ | 36% | ✅ content_thinking | ✅ | ❌ | ❌ |
| tmux/tmux_pipe.log | ★★ | 90% | ❌ TUI输出 | ❌ | ❌ | ❌ |

### 推荐数据源优先级（用于错题分析）

1. **exports/conversation.json** — 最完整，有reasoning_content + tool_calls + observation(tool_results)。但只有58%存在。
2. **sessions_db/trajectory.jsonl** — 82%存在，有thinking + tool_calls + tool行content(tool_results)。是conversation.json的最佳替代。
3. **mitm/thinking_readable.txt** — 38%存在，有轮次标记但无tool_results。仅在1和2都不存在时使用。
4. **tmux/tmux_pipe.log** — 90%存在，但只有TUI输出，无thinking。最后兜底。

### 关键发现

1. **conversation.json的observation字段是tool_results的存储位置**——不是在单独的tool step中，而是在agent step的observation.results[].content中。
2. **sessions_db/trajectory.jsonl把tool_results放在单独的tool行中**——role="tool"的行，content字段是工具返回结果。
3. **MITM文件只有早期批次存在**（dpb-20260812-021956到041914），后期批次没有MITM。
4. **42%的题没有conversation.json**——这些题只有sessions_db/trajectory.jsonl或tmux文件。
5. **大部分题只有1个agent step**（单轮thinking spin），少数题有多达43个agent step（多轮thinking spin + 工具调用）。
6. **reasoning_content不是所有agent step都有**（78%）——有些agent step只有tool_call没有thinking（如执行命令后的等待步骤）。
