# WP-U2 — 内容完整性三路对比实验（-p export vs Devin ACP vs OpenCode ACP）

> **优先级**: 线 2（U1 之后立即——**决定 V 系列方案分叉**）
> **依赖**: WP-U1（基线复验通过）
> **预计规模**: 实验脚本 1 个 + 三路原始数据 + 实验报告（043）
> **性质**: 调查实验。红线同 U1（不改生产代码；同题配额纪律）

---

## 0. 给执行 AI 的第一句话

036 审计的核心未决问题：**ACP 推送的 thinking 内容是否完整？**（Devin 侧实测 22 个
单词级 thought_chunk/1 秒 vs --export 的 reasoning_content 几千字符——不同任务不可比，
完整性未证）。这个答案决定整个 ACP 改造的方案分叉：完整→ACP 可全面替代（trajectory
从通知组装）；碎片→ACP 只做检测层（--export 仍是 trajectory 来源，架构变混合式）。
你要用**同一道真实数学题**跑三路对比，给出分叉判定。

## 1. 背景（为什么）

- 现有判定链（is_truncated/is_completed）吃的是 `--export` 的 conversation.json
  （ATIF 格式：steps[] 含 source=agent 的 reasoning_content/message/tool_calls/
  metrics.completion_tokens）。ACP 模式没有 --export——若 ACP 管线要复用全部判定逻辑，
  必须从通知流组装出**同结构**的 conversation.json
- 三路对比的意义：
  - A 路 `-p --export`（glm-5-2）：现状基准（reasoning_content 的权威来源）
  - B 路 Devin ACP（glm-5-2）：同模型跨模式——隔离"模式差异"（ACP 推送 vs export 落盘）
  - C 路 OpenCode ACP（Ox Alpha）：默认目标管线——但模型不同，thought 量差异含模型因素
  （B 路是关键的受控对照：同模型下 ACP 推送 vs export 的完整性）
- 037 §1.2 声称 OpenCode 823 thought_chunk"拼接后得到完整 thinking 内容"（skill §5.2）
  ——但那是工具任务的自述，未经 export 对照验证

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **WP-U1 基线报告**（dev-docs/042 "基线事实"节） | 双后端可用性 + 你的冒烟脚本（本实验直接扩展它） |
| 2 | `src/continuation_launcher.py` 的 `is_truncated()` + `is_completed()`（搜 def is_truncated） | **判定链吃的 JSON 结构**——实验的对照目标：三路的"可组装性"都按这两个函数的字段需求检验（steps/source=agent/reasoning_content/message/tool_calls/metrics.completion_tokens） |
| 3 | OpenCode skill §9（trajectory 组装）+ Devin skill 对应节 | 两家的组装方法（messageId 索引/chunk 拼接） |
| 4 | `dev-docs/036` §三.3（检测≠采集的区分，30 行） | 本实验要回答的问题的原始表述与三分支 |
| 5 | DB 或 problem_list 选题：找一道已有续传记录的题（`data/poc_2.7/problem_list.json` 任取 + 查 DB 该题历史） | 实验题要求：真实数学题、已知 glm-5-2 会产生较长 thinking（优先选历史 rc>5000 的题） |

## 3. 现场事实基线

- U1 冒烟已通（否则不做本包）
- `test_acp_signals.py` 的 Devin 客户端 + U1 的双后端冒烟脚本可复用
- is_truncated 的 comp 阈值 24000：glm-5-2 硬上限 25000（39 处实证）；**Ox Alpha 输出
  上限 131072**（037/skill §8.1）——C 路的 completion_tokens 语义不同（OpenRouter 计
  token 方式），本实验只记录不判定
- 配额：三路各 1 题 × 1 次（Devin/OpenRouter 均免费，但纪律仍限 3 次调用）

## 4. 任务分解

### 任务 1：实验脚本 `scripts/test_wp_u2_content_fidelity.py`

扩展 U1 脚本：
```
参数：--problem-file <题目文本文件> --work-dir tmp/wp_u2/
三路各一个子命令（--mode p_export / devin_acp / opencode_acp）

A 路（p_export）：
  devin -p --prompt-file <题> --model glm-5-2 --export tmp/wp_u2/a_export.json
  （放 tmux 跑——长命令铁律；等 DONE.md）
B 路（devin_acp）：U1 客户端 + session/prompt 发同题 → 全通知落盘 b_acp.jsonl
C 路（opencode_acp）：同上 → c_acp.jsonl
```

### 任务 2：组装器原型（脚本内函数，不进生产代码）

写 `assemble_conversation(jsonl_path) -> dict`：按 skill §9 的方法组装，输出结构**对齐
ATIF**：`{"steps": [{"source": "agent", "reasoning_content": <thought 拼接>,
"message": <message 拼接>, "tool_calls": [...], "metrics": {"completion_tokens":
<估算>}}]}`。Devin/OpenCode 各一版（差异：tool_call 首次通知格式/无 metrics——
completion_tokens 从 usage_update 取或标注缺失）。

### 任务 3：对比分析（报告核心）

对三路产出：
| 指标 | A 路（基准） | B 路（同模型对照） | C 路（目标管线） |
|---|---|---|---|
| reasoning_content 总字符数 | export 实测 | thought 拼接实测 | thought 拼接实测 |
| B/A 完整率 | — | 计算 | — |
| message 总字符数 | | | |
| tool_calls 数 | | | |
| thinking 时长（首末 chunk 时间戳跨度） | export 时间字段 | 通知 ts | 通知 ts |
| `is_truncated(assembled)` 可运行？ | ✅原生 | 试跑 | 试跑 |
| `is_completed(assembled, work_dir)` 可运行？ | ✅ | 试跑 | 试跑 |

**注意**：A 路与 B/C 路是独立运行——模型输出本身有随机性，字符数不会相等。完整性
判定的正确口径：**B 路的 thought 拼接量级是否与 A 路 reasoning_content 同量级**
（如 ≥50%——同模型同题，ACP 推送若只是摘要会差一个数量级）；C 路同理对照其自身
message 量（Ox Alpha 无 A 路基准——对照 C 路 message 与 thought 的比例合理性）。

### 任务 4：分叉判定（写进报告，V 系列依据）

```
分支判定（每后端一个）：
  完整（thought 拼接与基准同量级 ≥50% 且 is_truncated/is_completed 可运行）
    → 该后端 trajectory 可从通知组装（V4/V5 的组装方案成立）
  碎片（<50% 或字段缺失致判定不可运行）
    → 该后端 trajectory 需要补充来源（session/load replay？二次确认实验？）
    → 或该后端只做检测层（--export 并行保留）
记录 Devin 与 OpenCode 各自落在哪个分支——两者可以不同！
```

### 任务 5：报告 `dev-docs/043-ACP内容完整性三路实验报告.md` + commit

## 5. 禁止事项

- ❌ 配额纪律：三路各 1 题 1 次；失败重跑最多 1 次并记录原因
- ❌ 组装器只进实验脚本不进 src/（生产化是 V1 的事，先证明可行）
- ❌ 不因单题结果下绝对结论——报告中写明样本局限（1 题），V1 实现时保留回归验证点
- ❌ C 路（Ox Alpha）不做解题质量判断（那是 U6 的事——本包只看内容完整性）

## 6. 验收 checklist

- [ ] 三路原始数据落盘（a_export.json / b_acp.jsonl / c_acp.jsonl）+ 脚本存在
- [ ] 对比表完整（7 项指标×3 路）
- [ ] B/A 完整率有数字；两后端各自的分支判定明确
- [ ] is_truncated/is_completed 对组装产物的试跑结果记录（可运行/报错字段清单）
- [ ] 043 报告含"给 V1/V4/V5 的输入"小节
- [ ] 生产代码零改动；commit 只含脚本+报告

## 7. 完成汇报要求

执行记录：选题及理由（历史 rc 数据）、三路指标表、分支判定、异常（如 usage_update
缺失导致 completion_tokens 无源）。

## 8. 审计对照

1. 我会读三路原始数据亲自复算字符量（审计者守直接检查铁律——尤其 B/A 完整率）
2. 组装器对 is_truncated 的字段对齐逐字段核对（source/reasoning_content/metrics 路径）
3. 分支判定与数据自洽（不为"想让 ACP 成"而放宽 50% 口径——口径在数据出来前已定）
