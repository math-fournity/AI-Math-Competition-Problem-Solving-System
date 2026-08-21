# WP-U1 — ACP 能力基线复验（双后端冒烟 + Ox Alpha 确认）

> **优先级**: 线 2 之首（U2~U8 的共同前置）
> **依赖**: 无（037 核查已确认资产就绪：skill×5 / opencode 1.18.20 / openrouter 配置 / auth）
> **预计规模**: 冒烟脚本 1 个 + 冒烟数据文件 + 基线报告
> **性质**: 调查（动手实验但**不改生产代码**）。红线：新文件只放 scripts/test_* 或 tmp/

---

## 0. 给执行 AI 的第一句话

U 系列的一切结论都建立在"双 ACP 后端在本机可用"之上。037 的实测是别人做的——你要
**亲手复验**一遍（直接检查铁律：别人说测试过了不算数）：Devin ACP 复跑 035 的测试、
OpenCode ACP 跑通全信号、Ox Alpha 免费可用性确认。半天内完成，产出基线报告，后续
U 包引用你的基线而不是 037 的声称。

## 1. 背景（为什么）

- 037 §一/§三声称：OpenCode v1.18.19 `opencode acp` 信号完备（823 thought_chunk 实测）、
  Ox Alpha 免费无限量、配置已就绪——这些是**外部条件**，会随版本/服务变化
- 037 核查（设计者已做）：skill 文件 5 个存在、opencode 实为 **1.18.20**（比 037 写的
  19 新一个小版本）、opencode.json 有 openrouter/stealth/ox-alpha + permission
  `"*": "allow"`、auth.json 有 openrouter 条目——**静态核查通过，但动态行为未复验**
- 你复验后，后续 U 包的认知加载清单可以直接引用你的基线报告（一个事实源）

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `dev-docs/037-策略调整-双ACP管线-OpenCode默认Devin备用.md` **全文** | 双管线决策与理由 / 差异表 / U 系列范围定义（§四）/ 交接要点（§七） |
| 2 | `~/.config/opencode/skills/opencode-acp-protocol/references/full-sop.md` **全文**（21918B，≈650 行） | OpenCode ACP 全部协议细节：§4 通信流程 / §5 通知格式 / §6 完成检测（**核心差异：prompt response 可能不返回**）/ §7 权限 / §8 模型配置 / §10 参考 80 行客户端 |
| 3 | `/Users/user/skills-devin/devin-acp-protocol.md` **全文**（19618B） | Devin ACP 全部细节（v1 协议/权限响应格式/sessionCapabilities 无 close/_cognition.ai 自定义通知/实测数据） |
| 4 | `scripts/test_acp_signals.py`（399 行，已验证的 Devin 客户端） | 可复用的客户端骨架（select 循环/通知分发/权限响应） |
| 5 | `dev-docs/035`（选读 §二·补 实测节） | Devin 侧的历史实测数据（对照用） |
| 6 | `/tmp/acp_test*.jsonl`（5 个文件，若仍在） | Devin 实测原始数据形态 |

## 3. 现场事实基线（2026-08-21 09:55 设计者核查——你复核）

| 事实 | 值 | 复核命令 |
|---|---|---|
| opencode 版本 | 1.18.20（037 写 1.18.19——小版本更新） | `opencode --version` |
| opencode 路径 | ~/.opencode/bin/opencode | `which opencode` |
| opencode.json openrouter | provider openrouter，models: ["stealth/ox-alpha"] | 读配置 |
| permission | `"*": "allow"` + bash 白名单（git push/gh deny） | 读配置 |
| auth.json | 含 openrouter 条目 | `python3 -c "import json; print(list(json.load(open('/Users/user/.local/share/opencode/auth.json')).keys()))"` |
| skill 文件 | 5 个全部存在（09:17-09:44 创建） | ls 037 §三.1 的路径 |
| devin 版本 | （待你查）`devin --version` | — |

## 4. 任务分解

### 任务 1：写双后端冒烟脚本 `scripts/test_wp_u1_acp_smoke.py`

基于 `test_acp_signals.py` 的骨架，参数化后端：
```
--backend devin     → subprocess: devin acp
--backend opencode  → subprocess: opencode acp --cwd <tmp workdir>

流程（两个后端同一套）：
  initialize → 断言 protocolVersion==1
  session/new（mcpServers: []）→ 记录 sessionId
  session/prompt（简单任务："Write 'U1 smoke ok' to /tmp/wp_u1_<backend>.txt then read it back."）
  收集全部通知到 tmp/wp_u1_<backend>.jsonl（ts + 原始 JSON 每行）
  记录：各 sessionUpdate 类型的计数 / prompt response 是否返回（及内容）/ 静默时长
  （OpenCode 后端等静默 30 秒收尾；Devin 后端等 prompt response）
  终止进程（OpenCode 试 session/close；Devin cancel+terminate）
```

### 任务 2：跑双后端冒烟 + 记录差异

- 两后端各跑一次；输出对照表：信号计数（thought/message/tool_call/tool_call_update/
  request_permission）/ prompt response 有无 / 文件是否真的写出（`ls /tmp/wp_u1_*.txt`）
- **断言 OpenCode 侧 thought_chunk > 0**（037 声称 823——你的任务量不同数字会不同，
  >0 即证明 thinking 流式可用）；断言两后端都完成了文件写读任务

### 任务 3：Ox Alpha 免费可用性确认

- 冒烟中 OpenCode 后端用的模型就是 ox-alpha（opencode.json 单模型配置）——任务 2 成功
  即证明模型可用
- 免费性确认（可选增强）：用 OpenRouter API 查 `https://openrouter.ai/api/v1/key`
  （auth.json 的 key）返回的 usage/limit 信息，或查模型页 pricing——记录一条证据即可
  （"完全免费无限量"是 037 的关键决策依据，值得一条独立证据）
- **不读 auth.json 的 key 内容到日志/报告**（敏感——只记录查询结果）

### 任务 4：写基线报告 `dev-docs/042-ACP双后端基线复验报告.md`

内容：两后端冒烟对照表 / 与 037+035 声称的差异清单（版本漂移/信号计数差异/新发现）/
Ox Alpha 可用性证据 / "U 系列后续包可引用的基线事实"小节（一页内，供 U2-U8 认知加载）。

### 任务 5：commit

`scripts/test_wp_u1_acp_smoke.py` + 报告（jsonl 数据在 tmp/ 不提交）。

## 5. 禁止事项

- ❌ 不改生产代码（src/ monitoring/ 的现有文件）
- ❌ 不把 API key 写进任何日志/报告/commit
- ❌ 冒烟任务不用真实数学题（用简单写读任务——数学题留给 U2/U6 的正式实验）
- ❌ OpenCode 后端不依赖 prompt response（代码里对它 timeout 处理——它可能不返回）

## 6. 验收 checklist

- [ ] 冒烟脚本存在且 `--backend devin` / `--backend opencode` 各跑通一次（输出贴记录）
- [ ] 两份 jsonl 落盘 tmp/，信号计数表在报告中
- [ ] OpenCode thought_chunk > 0 有数据；两后端文件写读任务成功（ls 证据）
- [ ] prompt response 行为记录（Devin=返回+stopReason；OpenCode=记录实际行为）
- [ ] Ox Alpha 免费性证据一条
- [ ] 042 报告存在，含"基线事实"小节
- [ ] `git status` 生产代码零改动；commit 只含脚本+报告

## 7. 完成汇报要求

执行记录：两后端原始计数、与 037/035 的差异清单、版本漂移记录、任何异常（如 OpenCode
通知格式与 skill 文档不符——这正是复验的价值）。

## 8. 审计对照

1. 我会重跑一次 `--backend opencode` 冒烟核对计数数量级
2. jsonl 原始数据抽查（格式与 skill 文档的 §5 一致性）
3. 生产代码零改动的 git 证据
4. 042 的"基线事实"小节会被 U2-U8 引用——检查它是否自包含且无未验证声称
