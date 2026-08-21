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
| 3 | OpenCode skill §9（trajectory 组装与导出，**含 §9.3–9.6 的原生 export 实测与三层来源**）+ Devin skill 对应节 | 两家的组装方法（messageId 索引/chunk 拼接）+ OpenCode 原生 export 命令与格式 |
| 4 | `dev-docs/036` §三.3（检测≠采集的区分，30 行）+ **`dev-docs/038` §八/§九（export 实测 + 检测信号分层）** | 本实验要回答的问题的原始表述与三分支；任务 6 截断信号探测的设计依据 |
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

**C 路追加（零调用成本）：原生 export 对照**——C 路跑完后立即执行
`opencode export <sessionID>`（sessionID 从通知流或 `opencode session list` 取），
对比三个来源：①通知流组装产物 ②原生 export JSON ③两者与 B 路口径的量级一致性。
验证点：export 是否含 thinking 实文（`reasoning` part）、逐消息 tokens、
`step-finish.reason` 值；组装器漏了什么 export 有（反之亦然）。038 §八已实测
"ACP session 可导出"，本对照验证**内容层面**组装器无损失。

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

### 任务 6：截断信号探测（038 §九分层检测的主信号验证，配额 +2）

**背景**：038 §九裁定检测信号分层——协议原生信号为主、结构启发式兜底。但"协议在
截断时给什么信号"从未实测。本任务用专门设计的任务触发 output 上限，记录协议响应。

```
对 Devin ACP 与 OpenCode ACP 各跑 1 次（配额 +2，独立于任务 1-3 的 3 次基线配额）：
  触发任务设计：要求 AI "穷举/逐条详述"型 prompt（如"从 1 数到 100000 并对每个数
  写一句注释"或超长枚举证明）——目标是让单轮输出撞后端上限
  记录：
    Devin：session/prompt response 的 stopReason 值（预期 max_tokens 类？）
           + usage_update 的 token 曲线 + 流终止形态
    OpenCode：step-finish.reason 的值（新值出现？）+ 最后几个通知的形态
              + 进程是否存活 + 随后 opencode export 能否捞回部分内容
  判定：
    显式信号存在（stopReason/reason 出现非 end_turn/stop 的新值且语义=截断）
      → 第一层主信号成立，V1 detection.py 优先消费它
    无显式信号（静默断流/仍是 stop）
      → 该后端截断检测只能靠第二层结构启发式（is_truncated 后端化阈值），
        报告中写明并给 V4/V5 标注
```

## 5. 禁止事项

- ❌ 配额纪律：任务 1-3 三路各 1 题 1 次；失败重跑最多 1 次并记录原因；任务 6 另有
  +2 配额（每后端 1 次），同样失败最多重跑 1 次
- ❌ 组装器只进实验脚本不进 src/（生产化是 V1 的事，先证明可行）
- ❌ 不因单题结果下绝对结论——报告中写明样本局限（1 题），V1 实现时保留回归验证点
- ❌ C 路（Ox Alpha）不做解题质量判断（那是 U6 的事——本包只看内容完整性）

## 6. 验收 checklist

- [ ] 三路原始数据落盘（a_export.json / b_acp.jsonl / c_acp.jsonl）+ 脚本存在
- [ ] 对比表完整（7 项指标×3 路）
- [ ] B/A 完整率有数字；两后端各自的分支判定明确
- [ ] **C 路原生 export 对照完成**（export JSON 落盘 + 与组装产物的差异清单）
- [ ] is_truncated/is_completed 对组装产物的试跑结果记录（可运行/报错字段清单）
- [ ] **任务 6 截断信号探测记录**（两后端各自的 stopReason/reason 实测值 + 分层检测
      判定：主信号成立/不成立）
- [ ] 043 报告含"给 V1/V4/V5 的输入"小节（**含分层检测的信号源结论**）
- [ ] 生产代码零改动；commit 只含脚本+报告

## 7. 完成汇报要求

执行记录：选题及理由（历史 rc 数据）、三路指标表、分支判定、异常（如 usage_update
缺失导致 completion_tokens 无源）。

## 8. 审计对照

1. 我会读三路原始数据亲自复算字符量（审计者守直接检查铁律——尤其 B/A 完整率）
2. 组装器对 is_truncated 的字段对齐逐字段核对（source/reasoning_content/metrics 路径）
3. 分支判定与数据自洽（不为"想让 ACP 成"而放宽 50% 口径——口径在数据出来前已定）
