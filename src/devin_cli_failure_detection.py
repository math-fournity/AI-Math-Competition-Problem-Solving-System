"""devin_cli_failure_detection.py — devin cli 失败检测共享模块（续传+审计共用）

提取自平凡解题系统（solver_harness/pipe/collector.py）的可靠检测模式，
按 031 B 组修正 + 036 §四.2 裁定的范围实现。

设计准则（AGENTS.md"适度依赖 Master Agent 介入"边界判据：能否写成确定性函数
并单测覆盖？）：
- 进代码的：确定性文本模式匹配 / 集合判定——全部可单测覆盖（本模块如此）
- 不进代码的（及原因，036 §三.4 实证）：
  * is_thinking —— 平凡系统的 THINKING_PATTERNS 是 TUI 渲染产物，-p 模式不渲染、
    永不匹配；数学内容计数在 pane 无输出时也失效。thinking 检测交 ACP 方案
    （agent_thought_chunk 流，WP-U 系列已验证）
  * is_devin_waiting_api —— 依赖平凡系统代理端口 7897 假设，环境耦合
  * check_tool_use —— 平凡系统禁 AI 用工具；本系统 ANTI_CHEATING_CLAUSE 明确
    允许工具，政策相反（031 B3），该检测无适用场景

关键事实（供阈值参考）：本 repo 39 处截断案例 completion_tokens 恒=25000（036 §二
全量验证）——devin cli（glm-5-2）输出硬上限 25000，续传侧 TRUNC_COMP_TOKENS_MIN=24000
能覆盖全部输出上限型截断；若 devin cli 升级改上限需复核。
另（043/U6 实测）：ox-alpha 经 OpenRouter 的有效单轮输出上限观测值为 32000
（非模型卡宣称的 131072）——阈值必须以实测有效值校准。

模式来源与并集策略：
- AI_GAVE_UP_PATTERNS：平凡系统 collector.py 原样迁移（031 裁定）
- RATE_LIMIT / CONNECTION：以本 repo continuation_config 版为基底（比平凡版多
  message rate limit/http 429/status 429/network error/network request failed/
  ECONNRESET），平凡版模式已全部包含在本 repo 版内（并集=本 repo 版）
- TOKEN_LIMIT_PATTERNS：平凡系统原文——仅审计 pane 检测用（续传用 is_truncated
  结构化检测，更优，031 B2）
"""

# === 文本模式（pane/pipe/export 合并文本，大小写不敏感匹配）===

# AI 主动放弃（平凡系统 collector.py 原样迁移）
AI_GAVE_UP_PATTERNS = [
    "I CANNOT SOLVE", "I cannot solve", "i cannot solve",
    "无法解决", "无法做出", "做不出来",
    "I give up", "i give up", "I'm unable", "无法完成",
    "### I CANNOT SOLVE THIS",
]

# rate limit（本 repo 7 模式为基底，已含平凡系统全部 4 模式的并集）
RATE_LIMIT_PATTERNS = [
    "rate limit", "rate_limit", "429", "Too Many Requests",
    "message rate limit", "http 429", "status 429",
]

# 连接错误（本 repo 8 模式为基底，已含平凡系统全部 5 模式的并集）
CONNECTION_PATTERNS = [
    "connection error", "ECONNREFUSED", "ETIMEDOUT",
    "socket hang up", "fetch failed", "network error",
    "network request failed", "ECONNRESET",
]

# token/输出上限（仅审计 pane 检测用；续传用 is_truncated 结构化检测，031 B2）
TOKEN_LIMIT_PATTERNS = [
    "token limit", "context limit", "context_length", "maximum context",
    "Response truncated", "max output token", "Send a message to continue",
]


# === 失败分类集合 ===

# 基础设施失败（可重试）。含 crash_recovered——031 B7 裁定取平凡系统
# collector.py 的正确版（其 retry_infrastructure.py 版不含，属遗留不一致）；
# 续传系统目前把 tmux server 死亡合并入 dead_session，分类集合先统一备用。
INFRA_FAILURES = {
    "rate_limited", "failed_connection", "launch_error",
    "dead_session", "crash_recovered",
}

# 非基础设施结果（不做“同配置立即自动重试”，但题目仍可在未来显式继续）。
# truncated_at_max仅兼容历史failed队列；WP-01起新窗口用window_exhausted且不入
# failed队列。ai_gave_up防止无意义立即重试，不代表题目永久不可解。
MODEL_FAILURES = {
    "failed_timeout", "failed_stall", "failed_no_proof",
    "truncated_at_max", "ai_gave_up",
    "failed_token_limit", "max_runtime_exceeded",
}

# 重试配置（从 continuation_config 迁来集中；WP-L 的自动重试消费）
MAX_RETRIES = 3


def match_patterns(text, patterns):
    """通用文本匹配：小写化后返回首个命中的模式串；无命中返回 None。

    text 为 None/空时安全返回 None（调用方无需预判）。
    """
    if not text:
        return None
    lower = text.lower()
    for pat in patterns:
        if pat.lower() in lower:
            return pat
    return None


def check_ai_gave_up(text):
    """文本含 AI 放弃模式 → 返回命中的模式串；否则 None。

    确定性文本匹配，可单测覆盖（适度依赖边界判据的正面示例）。
    用途：防放弃题被误判 dead_session 后进入无意义重试（031 B6）。
    """
    return match_patterns(text, AI_GAVE_UP_PATTERNS)


def classify_failure(failure_type):
    """区分基础设施失败和模型能力失败。

    infra（可重试）：INFRA_FAILURES 集合成员（rate_limited/failed_connection/
        launch_error/dead_session/crash_recovered）
    model（不可重试，是数据）：其余一切——含未知串（非 INFRA 即 model，
        与迁移前 continuation_launcher.classify_failure 语义一致）

    参考：xishujuzhen/solver_harness/pipe/retry_infrastructure.py
    """
    if failure_type in INFRA_FAILURES:
        return "infra"
    return "model"
