# 046 — OpenCode ACP 管线详细设计（WP-U5 产出）

> **创建时间**: 2026-08-21
> **执行者**: Claude (ox-alpha, opencode)
> **数据来源**: U2 c_acp.jsonl（16min 数学题）/ U1 v2 冒烟 / 本包实测 2 次
> （agents 注入探针 + giveup 形态探针，配额 ≤3 用了 2）+ session/list 探测（零配额）
> **原始数据**: `tmp/wp_u5/*.jsonl`、`tmp/wp_u2/c_acp.jsonl`

---

## 一、完成检测设计（任务 1）

### 1.1 实测间隔数据

| 窗口 | 值 | 数据源 |
|---|---|---|
| 流内 chunk 间隔 | p50=0.07s / p95=0.15s / p99=0.24s | U2 C 路（16min，N=12064） |
| 运行中最大停顿 | **13.2s** | 同上 |
| 发题→首内容信号 | 4.25s（冒烟）/ 10.60s（数学题） | 两数据集 |
| **末信号→response** | **0.00s** | 两数据集一致——response 与流末紧耦合 |

### 1.2 设计裁定：response 驱动为主，静默窗口为兜底

```
完成判定状态机：
  session/prompt 已发送 → 等 response（上限 = max_runtime）
    ├─ response 到达 → done（finish_reason 记录，成败交组装后结构检查）
    └─ 超时未达 → 静默检测：120s 无新通知 → 视为完成类收尾（再查 response 一次）
                   → 仍无 → failed(timeout) + alert

参数依据：
  - 静默窗口 120s：运行中实测最大停顿 13.2s 的 ~9 倍余量；比 skill 初稿的
    30s 保守一倍以上（防工具长执行误判）
  - 防误判条件：静默判"完成"仅在 response 缺席的兜底分支生效；
    主路径 response 到达即结束，与静默无关
  - spin 检测窗口 300s（037 不变量）独立运行，两窗口数量级分离不冲突
```

### 1.3 备选方案 D 实测结论：session/list 不可用于完成检测

`session/list`（需带 `{"cwd":...}` 对象参数）返回 `{sessionId, cwd, title,
updatedAt}`——**无任何 state/status 字段**。价值重定位：**崩溃恢复**（launcher
重启后按 cwd 过滤找回 sessionId，配合 `opencode export` 捞回 trajectory）。

## 二、提示词注入设计（任务 2）

### 实测证据

work_dir 放强制标记 AGENTS.md → acp 会话（--cwd 指向该目录）→ AI 在实质回答前
**逐字输出标记行** ✅（31s，BANANA-CONFIRM-7391 先于答案出现）。全局
~/.config/opencode/AGENTS.md 叠加未见干扰（回答未被全局规范污染）。

### 注入设计（与现双轨对齐）

| 现有轨道 | OpenCode 后端映射 |
|---|---|
| --prompt-file（题目+任务指令） | `session/prompt` 的 text block 全文 |
| work_dir/AGENTS.md（工作区引导/防作弊条款） | 原样放 work_dir，OpenCode 自动加载（实测遵守）；模板无需改写 |

**V1/V4 实现要点**：work_dir 组装逻辑复用现有 prepare 函数；prompt 参数 =
prompt_file 内容原样注入。

## 三、错误信号形态（任务 3）

### ai_gave_up 实测（146s，end_turn）

放弃声明出现在 **agent_message_chunk 文本末尾**（"### CANNOT COMPLETE"位于
message 尾部，位置 2912/2927）——WP-I 的 `AI_GAVE_UP_PATTERNS` 直接跑在组装后的
message 文本上即可命中，**模式匹配方案跨后端成立**。

### rate_limit 形态（设计推演——免费模型难主动触发）

三层检测方案定稿：

```
L1 通知文本层：WP-I PATTERNS（rate limit/429/connection 等）跑在组装后的
   message/thought 文本上（ai_gave_up 同通道）
L2 进程层：proc.poll() 非零退出 + stderr 关键词（stderr 由客户端单独捕获线程收集）
L3 时序层：spin 检测（300s 无信号）+ max_runtime 兜底
任一层命中 → BackendStatus(failed, detail=...) → launcher 走既有失败处置
```

## 四、trajectory 来源三层（038 §八 + 043 落地形态）

| 层 | 机制 | 可靠性注记 |
|---|---|---|
| 1 通知 jsonl | 客户端实时追加写（每通知一行 {ts,dir,msg}） | 主来源；U2 证组装无损 |
| 2 `opencode export <sid>` | 进程死后可捞回 | **必须 JSON 校验+重试**（U2 首次调用曾产出截断 JSON，exit=0） |
| 3 SQLite 直读 | opencode.db | 不作主路径（schema 耦合风险） |

崩溃恢复流程：launcher 重启 → `session/list {"cwd": work_dir}` 找回 sessionId →
export 校验性读取 → 有则续用、无则按失败重入队。

## 五、给 V1/V4 的输入清单

1. start() 序列：initialize → session/new(cwd) → set model(断言) → set effort(断言)
   → prompt —— 045 §二契约的实现细节全部确定
2. 完成状态机见 §1.2；done_silence_seconds = 120（🔶 转 U8 确认）
3. 错误三层见 §三；AI_GAVE_UP_PATTERNS/RATE_LIMIT_PATTERNS 数据源 = 组装文本
4. 通知 jsonl 格式：`{ts, dir:"→|←", msg}` 每行一条（U1/U2/U5 探针同款，资产保留新形态）
5. session/list 用于崩溃恢复而非完成检测

## 六、验收对照

- [x] 间隔分布统计表（p50/p95/p99/max，含两数据集）
- [x] 完成窗口与 spin 窗口协调条件写清（response 主路径 vs 静默兜底 vs 300s spin）
- [x] session/list 状态探测结果记录（无状态字段→不可用于完成检测）
- [x] AGENTS.md 加载行为实测（标记法行为证据）
- [x] ai_gave_up 通知形态实测记录（message 尾部+thought 中均有）
- [x] 046 报告 + "给 V1/V4 输入"小节；生产代码零改动
