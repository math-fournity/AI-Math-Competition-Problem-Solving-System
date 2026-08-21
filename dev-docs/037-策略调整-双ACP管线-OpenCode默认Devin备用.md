# 037 — 策略调整：双 ACP 管线（OpenCode ACP 默认 + Devin ACP 备用）

> **创建时间**: 2026-08-21
> **性质**: 用户需求更新——系统未来要同时实现基于 Devin ACP 和基于 OpenCode ACP 的解题管线，默认使用 OpenCode ACP，Devin ACP 是备用管线
> **触发**: OpenRouter 上线 Ox Alpha（智谱下一代多模态 GLM stealth，1M context，完全免费，无限量），且实测确认 OpenCode 支持 ACP 且信号完备
> **关联**: 035（ACP 调研）→ 036（审计）→ 本文（策略调整）→ WP-U（改造调查，需更新范围）
> **前置文档**: 执行 AI 必须先读 034（WP-U 定义）、035（ACP 实测）、036（审计修正）再读本文

---

## 一、需求来源

### 1.1 OpenRouter Ox Alpha 上线

2026-08-21，OpenRouter 上线 stealth 模型 `stealth/ox-alpha`（社区指纹确认是智谱下一代多模态 GLM）：

- **1,048,576 tokens 上下文**（1M，是 glm-5-2 的 5 倍）
- **131,072 tokens 最大输出**
- **原生支持 text + image + video 输入**
- **支持 tool calling + reasoning**
- **完全免费**（pricing prompt=0 completion=0）
- **无限量**（实测 20 次连续请求全部成功，零限速——账户 `is_free_tier: false`，`limit: null`）

### 1.2 OpenCode 支持 ACP 且实测完备

OpenCode v1.18.19 的 `opencode acp` 子命令支持 ACP v1 协议，实测验证：

| 信号 | 实测结果 |
|---|---|
| `agent_thought_chunk` | ✅ 823 个（thinking 实时流式推送） |
| `agent_message_chunk` | ✅ 378 个（message 流式推送） |
| `tool_call` | ✅ 3 个（edit + read + read） |
| `tool_call_update` | ✅ 6 个（pending → in_progress → completed） |
| `session/request_permission` | ✅ 0 个（配置 allow 后自动批准） |
| 文件写入 + 读取 | ✅ 成功 |

### 1.3 OpenCode ACP vs Devin ACP 的关键差异

完整对比见 skill 文件（§三给出路径），此处列影响管线设计的核心差异：

| 维度 | Devin ACP | OpenCode ACP | 对管线设计的影响 |
|---|---|---|---|
| **session/prompt response** | ✅ 返回 `{stopReason, usage}` | ⚠️ 可能不返回 | OpenCode 管线需静默检测完成 |
| **权限处理** | 每次发 `request_permission`，需手动回复 | 配置 `allow` 后自动批准 | OpenCode 管线权限更简单 |
| **session/close/fork/resume** | ❌ 不支持 | ✅ 支持 | OpenCode 管线 session 管理更灵活 |
| **自定义通知** | `_cognition.ai/thinking_complete` / `_cognition.ai/agent_stopped` | 未观察到 | OpenCode 管线 thinking 结束检测靠通知流转变 |
| **免费模型** | glm-5-2（200K context，free） | Ox Alpha（1M context，free，无限量） | OpenCode + Ox Alpha 上下文大 5 倍 |
| **模型指定方式** | `--model` 命令行参数 | `opencode.json` provider 配置 | OpenCode 管线配置方式不同 |

---

## 二、用户决策

### 2.1 双管线策略

**系统未来要同时实现两套 ACP 解题管线：**

1. **OpenCode ACP 管线（默认）**——基于 `opencode acp` + OpenRouter Ox Alpha
2. **Devin ACP 管线（备用）**——基于 `devin acp` + glm-5-2

**默认使用 OpenCode ACP，Devin ACP 是备用管线。**

### 2.2 决策理由

1. **Ox Alpha 免费无限量**——1M context 完全免费，不限速，比 glm-5-2 的 200K 更适合长程 agent 任务
2. **OpenCode ACP 权限更简单**——配置 `allow` 后自动批准，不需要 client 手动处理每个权限请求
3. **OpenCode ACP session 管理更完整**——支持 close/fork/resume，比 Devin 的只能 cancel + 进程终止更灵活
4. **Devin ACP 作为备用**——Devin ACP 有精确的 `stopReason` 完成信号和 `_cognition.ai/thinking_complete` 显式标记，在需要精确完成检测的场景仍有价值
5. **双管线降低单点依赖**——不把所有鸡蛋放在一个篮子里，OpenRouter/Ox Alpha 或 Devin/glm-5-2 任一出问题时另一条管线可顶替

### 2.3 不变的部分

- **ACP 协议本身**——两者都用 v1，`session/update` 通知格式相同，`agent_thought_chunk` / `agent_message_chunk` / `tool_call` / `tool_call_update` 信号相同
- **thinking spin 检测逻辑**——5 分钟无任何信号 = 疑似卡住，两者通用
- **trajectory 组装**——从 `session/update` 通知组装，两者通用（格式相同）
- **max_runtime 兜底**——两者都保留 max_runtime 作为最终兜底

---

## 三、执行 AI 必读文档

### 3.1 ACP 完整知识（skill 文件路径）

执行 AI 必须加载以下 skill 文件获取 ACP 的完整协议、实测数据、参考代码：

**OpenCode ACP 完整指南**：
- skill 触发器：`~/.config/opencode/skills/opencode-acp-protocol/SKILL.md`
- 完整内容：`~/.config/opencode/skills/opencode-acp-protocol/references/full-sop.md`
- devin 侧镜像：`/Users/user/skills-devin/opencode-acp-protocol.md`

**Devin ACP 完整指南**：
- skill 触发器：`~/.config/devin/skills/devin-acp-protocol/SKILL.md`
- 完整内容：`/Users/user/skills-devin/devin-acp-protocol.md`

**两者对比**：
- Devin skill 中 §十·补 有速查表和选方案建议
- OpenCode skill 中 §七（full-sop.md）有完整 11 维度对比表和 4 个关键差异详解

### 3.2 现有管线文档

执行 AI 必须读取以下文档了解现有管线和改造背景：

| 文档 | 用途 |
|---|---|
| `dev-docs/029-Pipe5-proof审计系统设计方案.md` | Pipe 5 设计方案 |
| `dev-docs/034-对033审计报告的审计.md` | WP-T/WP-U 定义（§WP-T 修订 + §WP-U 调查范围） |
| `dev-docs/035-ACP模式调研与检测方案对比.md` | ACP 协议调研 + 实测验证 + 集成路线图 |
| `dev-docs/036-对034-035的审计.md` | 审计修正（WP-U 范围补充 0/0.5 + 执行结构建议） |
| `AGENTS.md` | 项目认知资产表 |
| `src/continuation_launcher.py` | 现有 launcher 代码 |
| `src/proof_audit_launcher.py` | 现有审计 launcher 代码 |
| `scripts/test_acp_signals.py` | 已验证的 Devin ACP 客户端代码（约 300 行） |

### 3.3 OpenCode 配置（已就绪）

OpenCode 的 ACP + Ox Alpha 配置已经完成并实测通过：

- `~/.config/opencode/opencode.json`——已添加 `openrouter` provider + `stealth/ox-alpha` 模型定义
- `~/.local/share/opencode/auth.json`——已添加 OpenRouter API key
- `~/.config/opencode/AGENTS.md`——opencode 全局工作规范（已存在）

---

## 四、WP-U 范围更新

### 4.1 原 WP-U 范围（034 定义 + 036 补充）

034 定义了 8 项调查范围，036 补充了 3 项（0. sim 适配 / 0.5. 内容完整性前置实验 / 1 扩大为 tmux 依赖体系全量影响面）。

### 4.2 本文新增范围

在 036 补充后的 WP-U 范围基础上，本文新增以下调查项：

**9. 双管线架构设计**

设计同时支持 OpenCode ACP 和 Devin ACP 的双管线架构：
- 共同抽象层——两者共享的 ACP 客户端基类（`session/update` 通知处理、trajectory 组装、thinking spin 检测）
- 差异适配层——两者的差异部分（完成检测、权限处理、session 管理、模型指定）
- 管线选择机制——如何根据配置/参数选择使用 OpenCode ACP 还是 Devin ACP
- 默认值——OpenCode ACP 为默认，Devin ACP 为备用

**10. OpenCode ACP 管线设计**

基于 `opencode acp` 的解题管线设计：
- 启动方式——`opencode acp --cwd <work_dir>` 作为子进程
- 模型配置——通过 `opencode.json` 的 provider 配置 Ox Alpha（已就绪）
- 完成检测——通知流静默检测（30 秒无新通知 = 完成）+ max_runtime 兜底
- 权限处理——`opencode.json` 配置 `"*": "allow"` 自动批准（已就绪）
- trajectory 组装——从 `session/update` 通知组装（与 Devin 相同的信号格式）
- session 管理——利用 OpenCode 的 close/fork/resume 能力
- AGENTS.md 注入——OpenCode 自动加载项目 AGENTS.md，需确认解题提示词如何注入（通过 `session/prompt` 的 prompt 参数还是 AGENTS.md）

**11. OpenCode ACP 完成检测方案细化**

OpenCode ACP 的 `session/prompt` 可能不返回 response，这是与 Devin ACP 最大的行为差异。需要设计可靠的完成检测方案：
- 静默窗口选择——30 秒？60 秒？需要实测不同任务类型的 thinking + message 间隔
- 误判风险——静默检测可能在 AI 暂停思考（如 rate limit 短暂暂停）时误判为完成
- 与 thinking spin 检测的关系——thinking spin 是"5 分钟无信号 = 卡住"，完成检测是"30 秒无信号 = 完成"，两者窗口不同需协调
- 备选方案——是否可以用 `session/list` 查询 session 状态来判断完成

**12. Ox Alpha 模型适配评估**

评估 Ox Alpha 作为解题 AI 的适配性：
- 数学解题能力——Ox Alpha 主打 coding + agentic work，数学解题能力需实测验证
- reasoning 质量——`agent_thought_chunk` 的 thinking 内容质量与 glm-5-2 对比
- 1M context 利用——长程 agent 任务（如复杂证明）是否能有效利用 1M context
- 与现有提示词的兼容性——现有解题提示词（`--prompt-file` 注入的题目+脉络+卡点）是否需要调整
- tool calling 行为——Ox Alpha 的工具调用模式与 glm-5-2 是否一致

**13. 双管线切换和回退机制**

设计 OpenCode ACP → Devin ACP 的自动切换和回退机制：
- 切换触发条件——OpenCode ACP 不可用（Ox Alpha 限速/下线/OpenRouter 故障）时自动切换到 Devin ACP
- 健康检查——管线启动时的健康检查（ACP server 能否 initialize + session/new）
- 回退条件——Devin ACP 作为备用，在 OpenCode ACP 恢复后是否自动切回
- 配置方式——通过 `continuation_config.py` 的配置项控制默认管线和切换策略

### 4.3 WP-U 产出要求更新

在 034 的产出要求基础上，增加：

- 双管线架构设计文档（共同抽象层 + 差异适配层 + 管线选择机制）
- OpenCode ACP 管线设计文档（启动/完成检测/权限/trajectory/session 管理）
- Ox Alpha 适配评估报告（数学解题能力/reasoning 质量/提示词兼容性）
- 双管线切换和回退机制设计
- 两条管线的改造工作量分别估计（OpenCode ACP 管线 / Devin ACP 管线）

### 4.4 WP-U 仍然不执行改造

WP-U 只做调查和方案设计。改造执行在方案批准后另起工作包。

---

## 五、对现有工作包的影响

### 5.1 WP-T（thinking spin 检测）

WP-T 的检测机制改为 ACP 信号检测（034 已修订），本文不改变这个决策。但需要补充：

- **检测逻辑双管线通用**——`agent_thought_chunk` / `agent_message_chunk` / `tool_call_update` 信号在 OpenCode ACP 和 Devin ACP 中格式相同，检测逻辑可以共用
- **差异**——Devin ACP 有 `_cognition.ai/thinking_complete` 显式标记，OpenCode ACP 没有。检测逻辑需要兼容两者（有标记时用标记，无标记时靠通知流转变）
- **实现建议**——检测逻辑放在共同抽象层，差异适配层处理有无 `_cognition.ai/*` 标记的差异

### 5.2 WP-U（ACP 管线全面改造调查）

WP-U 范围扩大（新增 9-13 项），但性质不变——仍然是调查和方案设计，不执行改造。

### 5.3 线1（-p 模式继续跑）不受影响

036 §五的"两线并行"执行结构仍然成立——线1（WP-P~S，-p 模式继续跑）不等 ACP。双管线策略只影响线2（WP-U 调查）。

### 5.4 `noninteractive-solver-run` rule 的未来

当前 `noninteractive-solver-run` rule 要求用 `devin -p` 模式。双管线上线后，这个 rule 需要更新为支持 ACP 模式（OpenCode ACP 和 Devin ACP）。但这是改造执行阶段的事，WP-U 调查阶段不动 rule。

---

## 六、认知闭包与 checklist 影响分析

```
=== 认知闭包与 checklist 影响分析 ===
认知闭包（SYSTEM_CLOSURE.md）：
  - [需更新] §2 架构/数据流：新增 OpenCode ACP 管线和 Devin ACP 管线两条数据流
  - [需更新] §4 模块职责：新增 ACP 客户端抽象层（如果改造方案确定）
  - [需更新] §5 数据产出：ACP 模式下 trajectory 来源从 --export 变为 session/update 通知组装
  - [暂不更新] 等 WP-U 产出方案后再更新——现在是需求调整阶段，不是实现阶段
checklist/：
  - [暂不更新] 原因：WP-U 调查阶段不改变现有检查项，改造执行阶段再更新
```

---

## 七、给执行 AI 的交接 prompt 要点

执行 AI 收到本文后，需要：

1. **加载 ACP 知识**——读取 §三.1 列出的 skill 文件，掌握 OpenCode ACP 和 Devin ACP 的完整协议、实测数据、差异对比

2. **加载现有管线知识**——读取 §三.2 列出的文档和代码，了解现有 `-p` 模式管线的架构

3. **执行 WP-U 调查（范围扩大版）**——按 034 的 8 项 + 036 的 3 项 + 本文的 5 项（共 16 项）进行调查

4. **产出方案文档**——包含双管线架构设计、OpenCode ACP 管线设计、Devin ACP 管线设计、Ox Alpha 适配评估、切换回退机制、工作量估计

5. **不执行改造**——WP-U 只调查不改造，方案批准后另起工作包

6. **关键约束**：
   - 默认管线是 OpenCode ACP，Devin ACP 是备用
   - 两者共享 ACP 协议核心（v1 + session/update 通知），差异通过适配层处理
   - thinking spin 检测逻辑双管线通用
   - max_runtime 兜底双管线都保留
   - 线1（-p 模式）不等 WP-U

---

**最终执行版 = 031 方案 + 032 修正 + 033 修订 + 034 F1/WP-T/WP-U + 035 实测 + 036 审计修正 + 037 双管线策略调整。** WP-U 范围扩大为 16 项调查，默认 OpenCode ACP + 备用 Devin ACP。线1 不等 WP-U。
