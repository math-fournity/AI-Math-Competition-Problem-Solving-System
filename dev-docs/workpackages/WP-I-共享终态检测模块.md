# WP-I — 共享终态检测模块 src/devin_cli_failure_detection.py

> **优先级**: 第二批（WP-J/WP-K/WP-L 的共同前置）
> **依赖**: 无
> **预计规模**: 新模块 ~150 行 + 单测 ~100 行 + 2 个文件的 import 改造
> **性质**: 新代码（提取平凡系统模式，非照搬）+ 单测

---

## 0. 给执行 AI 的第一句话

续传和审计两个 launcher 各自维护（或不维护）devin cli 失败检测的文本模式——审计系统
几乎没有。你要建一个共享模块，把**可靠的确定性检测**集中：AI 放弃模式、rate limit
模式、连接错误模式、token limit 模式（审计用）、失败分类函数。**不提取** thinking
检测（036 裁定：平凡系统自己的 is_thinking 在 -p 模式下都系统性失效）。

## 1. 背景（为什么）

- 030 需求 8：续传/审计系统没有应对平凡解题系统已踩过的 devin cli 问题（限流/token/
  放弃）的完整策略。031~036 收敛后的提取范围（036 §四.2 裁定）：
  - ✅ AI_GAVE_UP_PATTERNS + check_ai_gave_up ——最高价值（防放弃题被误判 dead_session
    后进入无意义重试，031 B6）
  - ✅ RATE_LIMIT_PATTERNS / CONNECTION_PATTERNS——续传已有，迁移集中（消除双份维护）
  - ✅ TOKEN_LIMIT_PATTERNS——**仅审计用**（续传的 is_truncated 结构化检测已覆盖且更优，
    031 B2）
  - ✅ classify_failure——统一 INFRA_FAILURES **含 crash_recovered**（031 B7 裁定：
    平凡系统两处定义不一致，取 collector.py 的正确版）
  - ❌ is_thinking / is_devin_waiting_api——不提取（036 §三.4：-p 模式下 pane 无 TUI
    渲染，THINKING_PATTERNS 永不匹配；代理端口检测环境依赖）
  - ❌ check_tool_use——不提取（031 B3：两系统工具政策与平凡系统相反）
- "可靠判定进代码"边界判据（033/034 接受）：以上提取项全部是确定性文本模式匹配或
  集合判定——可单测覆盖

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `/Users/user/AI-Math-Normal-Solver/xishujuzhen/solver_harness/pipe/collector.py` 第 80-115 行 | AI_GAVE_UP_PATTERNS（7 模式）/RATE_LIMIT（4）/TOKEN_LIMIT（6）/CONNECTION（5）/INFRA/MODEL_FAILURES 集合原文 |
| 2 | `src/continuation_config.py` 第 89-101 行 | 本 repo 现有的 RATE_LIMIT_PATTERNS（7 模式，比平凡多 3 个——**取并集，以本 repo 版为基底**）/CONNECTION（8 个）/INFRA_FAILURES（4 个，**不含 crash_recovered——你要加**）/MAX_RETRIES |
| 3 | `src/continuation_launcher.py` 的 `classify_failure()`（搜 def classify_failure） | 迁移对象（迁移后原处改为 re-export 或直接改 import，见任务 3） |
| 4 | `AGENTS.md` 搜"适度依赖"的 4 条设计准则 + 边界判据 | 模块 docstring 要引用它（为什么这些检测进代码、thinking 不进） |
| 5 | `dev-docs/036` §三.4（选读 30 行） | "平凡系统 is_thinking 在 -p 下失效"的证据链——写进模块 docstring 的"不提取"依据 |
| 6 | 硬上限证据：`grep -rn "comp=25000" 的意识`——本 repo 39 处 comp 恒 25000（036 §二） | 写进 docstring：24000 阈值与 25000 硬上限的关系（WP-J 的 token_limit 检测参考） |

## 3. 现场事实基线（2026-08-21 09:30）

- 本 repo src/ 无 is_thinking/check_ai_gave_up/check_tool_use/TOKEN_LIMIT（复核：
  `grep -rn "is_thinking\|check_ai_gave_up\|TOKEN_LIMIT" src/ scripts/ monitoring/` → 仅
  asset_inventory.csv 的历史记录）
- `continuation_launcher.py` 的 `classify_failure` 被 4 处调用（1562/1747/1793/1830 行
  附近的 failure_category 写入）——迁移不能破坏这些调用
- `continuation_config.py` 的 RATE_LIMIT_PATTERNS/CONNECTION_PATTERNS 被 launcher 的
  主循环检测段 import（搜 `from src.continuation_config import` 的导入清单）
- `INFRA_FAILURES` 当前 = {rate_limited, failed_connection, launch_error, dead_session}；
  `MAX_RETRIES = 3` 定义未使用（WP-L 会用）

**基线漂移预期**：WP-H 改过审计 launcher 主循环；WP-G 删过并发常量——与本 WP 无交集。
若 WP-J/K 已被人先做（不该——依赖你），以现状报告。

## 4. 任务分解

### 任务 1：新建 `src/devin_cli_failure_detection.py`

模块骨架与内容规格：

```python
"""devin_cli_failure_detection.py — devin cli 失败检测共享模块（续传+审计）

提取自平凡解题系统（solver_harness/pipe/collector.py）的可靠检测模式，
按 031 B 组修正 + 036 §四.2 裁定的范围实现。

设计准则（AGENTS.md "适度依赖 Master Agent 介入"边界判据）：
- 进代码的：确定性文本模式匹配/集合判定——可单测覆盖（本模块全部如此）
- 不进代码的（及原因，036 §三.4）：
  * is_thinking —— 平凡系统的 THINKING_PATTERNS 是 TUI 渲染产物，-p 模式不渲染，
    永不匹配；数学内容计数在 pane 无输出时也失效。thinking 检测交 ACP 方案（WP-U）
  * is_devin_waiting_api —— 依赖平凡系统代理端口 7897 假设，环境耦合
  * check_tool_use —— 平凡系统禁 AI 用工具；本系统 ANTI_CHEATING_CLAUSE 明确允许，
    政策相反（031 B3）

关键事实（供阈值参考）：本 repo 39 处截断案例 completion_tokens 恒=25000——
devin cli（glm-5-2）输出硬上限 25000，TRUNC_COMP_TOKENS_MIN=24000 阈值能覆盖全部
输出上限型截断（036 §二验证）。若 devin cli 升级改上限，需复核。
"""

# === 文本模式（pane/pipe 合并文本，大小写不敏感匹配）===
# AI 主动放弃（平凡系统 collector.py:80-85 原样迁移）
AI_GAVE_UP_PATTERNS = [...]
# rate limit（以本 repo continuation_config 7 模式为基底并平凡 4 模式并集去重）
RATE_LIMIT_PATTERNS = [...]
# 连接错误（同法：本 repo 8 模式基底）
CONNECTION_PATTERNS = [...]
# token/输出上限（仅审计 pane 检测用；续传用 is_truncated 结构化检测，031 B2）
TOKEN_LIMIT_PATTERNS = [...]

# === 失败分类 ===
# 含 crash_recovered（031 B7：平凡系统 collector.py:105 正确版 vs retry_infrastructure.py:37
# 不含——取前者；续传系统目前合并入 dead_session，不单独判定，但分类集合先统一）
INFRA_FAILURES = {"rate_limited", "failed_connection", "launch_error", "dead_session", "crash_recovered"}
MODEL_FAILURES = {"failed_timeout", "failed_stall", "failed_no_proof", "truncated_at_max", "ai_gave_up", "failed_token_limit", "max_runtime_exceeded"}

MAX_RETRIES = 3  # 从 continuation_config 迁来（WP-L 消费；含义：infra 失败重试上限）

def check_ai_gave_up(text: str) -> str | None:
    """文本含放弃模式 → 返回命中的模式串；否则 None。确定性，可单测。"""

def match_patterns(text: str, patterns) -> str | None:
    """通用：小写匹配，返回首个命中模式。供 rate_limit/connection/token_limit 复用。"""

def classify_failure(failure_type: str) -> str:
    """infra | model（从 continuation_launcher.classify_failure 迁移，语义不变）"""
```

要点：
- `MODEL_FAILURES` 补入 `ai_gave_up` 与 `max_runtime_exceeded`（WP-J 引入的审计超时
  名——分类要能接住它）
- `match_patterns` 大小写不敏感（平凡系统 detect_lower 的做法）

### 任务 2：单测 `scripts/test_wp_i_failure_detection.py`

至少覆盖：
1. check_ai_gave_up：7 模式逐个正例 + 3 个负例（含"无法解决"中文正例；负例如
   "I cannot solve this **specific sub-step**, but continuing"——注意误伤控制：
   若某负例命中，评估该模式是否过宽并记录决策）
2. match_patterns 三组模式各 2 正例 1 负例
3. classify_failure：INFRA 5 项全 "infra"（含 crash_recovered）、MODEL 项全 "model"、
   未知串 → "model"（与现有函数语义一致：非 INFRA 即 model）
4. 空文本/None 安全

### 任务 3：迁移与兼容改造

- `continuation_launcher.py`：删除本地 `classify_failure` 定义，改为
  `from src.devin_cli_failure_detection import classify_failure, check_ai_gave_up`
  （后者 WP-K 用，先 import 备用或留给 WP-K 加——选后者则本 WP 只迁 classify_failure）
- `continuation_config.py`：删除 RATE_LIMIT_PATTERNS/CONNECTION_PATTERNS/INFRA_FAILURES/
  MODEL_FAILURES/MAX_RETRIES 定义，改为**从共享模块 re-export**：
  `from src.devin_cli_failure_detection import RATE_LIMIT_PATTERNS, ...`
  （保持 `continuation_launcher` 等现有 import 路径不破——最小改动策略；执行记录注明
  re-export 是兼容层，新代码应直接 import 共享模块）
- `grep -rn "RATE_LIMIT_PATTERNS\|CONNECTION_PATTERNS\|INFRA_FAILURES\|classify_failure" src/`
  确认无 broken import；py_compile 全部涉及文件

### 任务 4：commit + 记录

显式路径：`src/devin_cli_failure_detection.py scripts/test_wp_i_failure_detection.py
src/continuation_launcher.py src/continuation_config.py`。

## 5. 禁止事项

- ❌ 不提取 is_thinking/is_devin_waiting_api/check_tool_use/has_real_proof（036 裁定，
  docstring 里写了原因——别"好心"补全）
- ❌ 不改任何 launcher 的检测调用逻辑（接线是 WP-J/WP-K 的事）
- ❌ 模式串保持平凡系统/本 repo 的原文（不要自创模式——模式完备性靠 F1 机制
  （SOP 漏判发现）迭代，不靠一次写全）
- ❌ 不引入 thinking/pane 解析类依赖（纯文本+集合，零外部依赖）

## 6. 验收 checklist

- [ ] 模块存在，docstring 含：边界判据引用 / 三项"不提取"及原因 / 25000 硬上限事实
- [ ] `grep -n "crash_recovered" src/devin_cli_failure_detection.py` — 在 INFRA_FAILURES
- [ ] 单测全过（输出贴记录），含 ai_gave_up 7 正例 3 负例
- [ ] `grep -rn "classify_failure" src/continuation_launcher.py` — 只剩 import + 调用（无 def）
- [ ] `grep -rn "from src.continuation_config import" src/ | grep -i pattern` — 现有
      import 仍工作（re-export 兼容层生效）
- [ ] py_compile 涉及文件全过；续传 launcher 可正常 `python -c "import src.continuation_launcher"`
- [ ] commit 只含 4 个文件

## 7. 完成汇报要求

执行记录：模式并集的取舍说明（平凡 vs 本 repo 差异如何合并）、单测输出全文、
兼容层策略说明。

## 8. 审计对照

1. 我会逐条核对模式串与平凡系统 collector.py:80-92 + continuation_config:90-98 的
   原文（并集完整性）
2. 单测的负例设计是否真的测了误伤控制
3. re-export 兼容层没破任何现有 import（我会 py_compile + import 冒烟）
4. 模块没有夹带"好心"的 thinking 检测
