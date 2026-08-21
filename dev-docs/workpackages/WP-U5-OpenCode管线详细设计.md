# WP-U5 — OpenCode ACP 管线详细设计（完成检测实测 + 提示词注入 + 错误信号形态）

> **优先级**: 线 2（U1/U2 之后；与 U4 协同——U4 留了本包的参数位）
> **依赖**: WP-U1（基线）、WP-U2（组装可行性）
> **预计规模**: 实测脚本 1-2 个 + 设计文档（046）
> **性质**: 调查实验+设计。红线：不改生产代码

---

## 0. 给执行 AI 的第一句话

OpenCode ACP 是默认管线，但有三个未定问题必须实测才能设计：①**完成检测的静默窗口
设多少**（prompt response 可能不返回——窗口太短误判、太长浪费时间）；②**解题提示词
怎么注入**（OpenCode 自动读 work_dir/AGENTS.md，与 session/prompt 的分工）；③**错误
模式在通知流里长什么样**（-p 模式的 rate_limit 靠 pane 文本——ACP 后看什么）。你要
用真实数学题实测这三个问题，产出 OpenCode 后端的详细设计。

## 1. 背景（为什么）

- 037 §4.2.10/11 列了本包的调查点（原文要求）；skill §6 给了方案 A-D 但窗口值
  "需要实测不同任务类型的 thinking + message 间隔"
- ③ 是 U3 三件套专节留下的接口（"错误模式在 ACP 通知里长什么样是 U5 的实测点"）
  ——WP-I 的 RATE_LIMIT/CONNECTION 模式检测在 ACP 后端的数据源取决于此

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **WP-U1 基线**（042） | 可用性 + 冒烟脚本 |
| 2 | OpenCode skill **§6（完成检测）+ §5（通知格式）+ §2（--cwd/AGENTS.md 语义）** | 方案 A-D / 通知字段 / 工作目录行为 |
| 3 | `src/continuation_launcher.py` 的三个 prompt 模板（INITIAL/CONTINUE/v2 build）+ `proof_audit_launcher.py` 的 prepare_audit_work_dir（WP-R 后形态） | 现有提示词注入方式（--prompt-file + work_dir AGENTS.md 双轨）——OpenCode 后端怎么对齐 |
| 4 | `templates/proof_audit_agents_md.md`（若 WP-R 已加 audit_prompt.txt 也读） | 审计注入的模板结构 |
| 5 | `src/devin_cli_failure_detection.py`（WP-I 后） | 错误模式清单（rate_limit/connection/token_limit/ai_gave_up 的具体模式串——你实测它们的 ACP 形态） |
| 6 | **WP-U2 数据**（c_acp.jsonl） | 复用：通知时间戳间隔分布的第一手材料（静默窗口分析的起点） |

## 3. 现场事实基线

- U2 的 C 路数据已含同题的完整通知流（ts 逐条）——静默窗口分析可先从它开始，再补
  1-2 次针对性实测
- opencode.json 已配 openrouter/ox-alpha 单模型 + permission allow
- OpenCode 的 `--cwd` 决定工作目录与 AGENTS.md 自动加载范围
- **OpenCode 有原生 export 机制**（038 §八实测，v1.18.20）：`opencode export [sessionID]`
  官方命令；session 全量持久化于 `~/.local/share/opencode/opencode.db`（SQLite）；
  **ACP 创建的 session 与 TUI/run 存储同构可导出**（含 thinking 实文/逐消息 tokens/
  step-finish.reason）——你的 trajectory 落盘设计与崩溃恢复方案要把它纳入（三层来源：
  通知 jsonl 主 / export 兜底 / SQLite 直读不作主路径）
- **★ 模型与强度必须显式设置**（铁律 15）：所有实测/设计前提 = session/new 后
  set_config_option 设 model+effort=max 并断言回显——否则实际跑在 big-pickle 上，
  一切观察失效。静默窗口数据也必须采自正确模型
- 配额纪律：本包新增实测 ≤3 次（每次一题）

## 4. 任务分解

### 任务 1：静默窗口实测（完成检测参数化）

- 从 U2 的 c_acp.jsonl 统计：**题内通知间隔分布**（chunk 间正常间隔 p50/p95/p99、
  thinking→message 转变处的间隔、任务结束前最后通知的时间戳）
- 补测 1-2 次：①一道长 thinking 题（观察思考中的最长 chunk 间隔）②一次人为静默
  （任务结束后进程挂着不动——观察"真完成后的静默"长什么样）
- 产出：**窗口参数建议**——完成静默窗口（如 30s/60s，依据 p99×安全系数）与
  thinking spin 窗口（5 分钟，037 不变量）的协调说明（两窗口数量级不同不冲突，
  完成检测在"收到了足够内容"前提下才生效——写清条件防止把卡住误判成完成）
- 备选信号实测：`session/list` 返回里有无 session 状态字段（skill 方案 D——值得一次
  实测，若状态可用则比静默窗口可靠）

### 任务 2：提示词注入设计实测

现有双轨（--prompt-file 任务指令 + work_dir/AGENTS.md 工作区引导）在 OpenCode 后端
的映射：
- OpenCode 无 --prompt-file——任务指令走 `session/prompt` 的 text block
- AGENTS.md 自动加载（work_dir 即 --cwd）——**验证点**：session/new 的 cwd 与
  AGENTS.md 加载的关系（放 tmp work_dir 写一份测试 AGENTS.md，实测 AI 是否遵守其中
  指令）；`~/.config/opencode/AGENTS.md` 全局规范与项目 AGENTS.md 的叠加顺序（全局
  已存在——解题 AI 会不会被全局规范干扰？实测一道题观察行为）
- 产出：注入设计（prompt=题目+任务指令 / AGENTS.md=work_dir 的解题规范模板）——
  与现有模板的映射表

### 任务 3：错误信号形态实测

- rate limit 形态：难以主动触发（免费无限量）——**设计推演**为主：OpenRouter 出错时
  OpenCode 的通知流/进程行为（查 OpenCode 源码/文档的错误处理——skill §12 或 GitHub
  issues；错误大概率出现在 message 内容或进程 stderr），给出"ACP 后端的错误检测
  方案"：通知流内容匹配（WP-I 模式对 message/thought 文本跑）+ 进程 stderr 捕获 +
  poll 超时三层
- ai_gave_up 形态：实测 1 次——给一道极难题（或直接 prompt "如果无法解出请明确说明
  放弃"），观察放弃声明出现在哪个通知（message_chunk？）——验证 WP-I 的
  AI_GAVE_UP_PATTERNS 对 ACP message 文本可用
- 产出：ACP 后端错误检测方案（数据源分层：通知文本/进程 stderr/超时）

### 任务 4：设计文档 `dev-docs/046-OpenCode-ACP管线详细设计.md`

含：静默窗口参数+依据 / 完成状态机（running→thinking→…→done 的判定流程含双窗口
协调）/ 提示词注入设计+映射表 / 错误检测三层方案 / 通知日志落盘设计（实时 jsonl
追加——skill §9.2，资产保留新形态）/ **trajectory 来源三层小节**（通知 jsonl 主 /
`opencode export` 崩溃恢复兜底——含"launcher 死后如何从 sessionID 捞回"的操作设计，
引 038 §八与 U2 的 export 对照结论）/ "给 V1/V4 的输入"小节。

### 任务 5：commit（脚本+报告）

## 5. 禁止事项

- ❌ 配额 ≤3 次新增实测（复用 U2 数据优先）
- ❌ 不改生产代码（含 opencode.json——若实验需要改配置，用临时 OPENCODE_CONFIG
  环境变量或独立配置文件方案，不动全局配置；确需动则在执行记录写明并征得用户同意）
- ❌ 静默窗口不给"拍脑袋值"——每个参数附 p99 数据或实测时间戳依据（030 教训）
- ❌ 错误检测方案不过度设计（三层足够；四层以上需给场景依据）

## 6. 验收 checklist

- [ ] 间隔分布统计表（来自 U2 数据+补测，含 p50/p95/p99）
- [ ] 完成窗口与 spin 窗口（5min）的协调条件写清（防"卡住误判为完成"）
- [ ] session/list 状态实测结果记录（可用/不可用+格式）
- [ ] AGENTS.md 加载行为实测（项目级生效证据）；全局 AGENTS.md 叠加影响记录
- [ ] ai_gave_up 在通知流的形态实测记录（哪个通知类型+文本样例）
- [ ] 046 报告 + "给 V1/V4 输入"小节；零生产改动

## 7. 完成汇报要求

执行记录：实测次数清单（含复用 U2 的说明）、每个参数的数据依据、异常发现。

## 8. 审计对照

1. 窗口参数我会用 U2/U5 的 jsonl 原始时间戳复算 p99
2. AGENTS.md 实测证据（AI 确实读了 work_dir 的 AGENTS.md——行为证据不是猜测）
3. 错误检测三层与 WP-I 模式的衔接清晰（V4 按此实现）
