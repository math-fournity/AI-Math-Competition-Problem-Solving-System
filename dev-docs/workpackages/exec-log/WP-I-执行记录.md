# WP-I 执行记录 — 共享终态检测模块

> **执行时间**: 2026-08-21（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（模块 + 单测 39 PASS/0 FAIL + 迁移兼容层）

---

## 一、做了什么

1. **新建 `src/devin_cli_failure_detection.py`**（~150 行）：
   - AI_GAVE_UP_PATTERNS：平凡系统 collector.py 原样迁移（10 模式）
   - RATE_LIMIT_PATTERNS（7）/ CONNECTION_PATTERNS（8）：本 repo 版为基底——
     经比对本 repo 版已是平凡版超集（平凡 4+5 模式全含），并集=本 repo 版
   - TOKEN_LIMIT_PATTERNS（7）：平凡原文，仅审计 pane 用（续传 is_truncated 更优）
   - INFRA_FAILURES 含 crash_recovered（031 B7 取 collector.py 正确版）；
     MODEL_FAILURES 补 ai_gave_up + max_runtime_exceeded（WP-J/K 预留）
   - MAX_RETRIES=3 迁入集中（WP-L 消费）
   - match_patterns（大小写不敏感、None 安全）/ check_ai_gave_up / classify_failure
   - docstring 引用适度依赖边界判据 + 三项"不提取"原因 + 25000 硬上限与 32000
     实测（043/U6）

2. **单测** `scripts/test_wp_i_failure_detection.py`：39 PASS / 0 FAIL
   - ai_gave_up 正例 9 个（覆盖全部模式族）；负例 4 个
   - **误伤边界决策记录**："I cannot solve this specific sub-step, but continuing"
     会命中 "I cannot solve" 子串——裁定保持平凡系统原文不自创收紧（F1 漏判发现
     机制负责迭代），调用方需结合终态上下文判定。已作为已知宽匹配边界记录在测试中

3. **迁移兼容改造**：
   - continuation_config.py：五项定义删除 → re-export 共享模块（兼容层，
     新代码应直连共享模块）
   - continuation_launcher.py：本地 classify_failure def 删除 → 顶部直接 import；
     check_ai_gave_up 留给 WP-K 接线（暂不 import）

## 二、验收 checklist 对照

- [x] 模块存在；docstring 含边界判据引用/三项不提取及原因/25000 硬上限事实
      （另补 043 的 32000 实测）
- [x] `grep -n "crash_recovered"` 在 INFRA_FAILURES ✅
- [x] 单测全过 39 PASS（ai_gave_up 正例 9 覆盖全部模式族+负例含误伤边界决策）
- [x] `grep classify_failure src/continuation_launcher.py` = import(:70) + 6 处调用，
      无本地 def ✅
- [x] re-export 兼容层生效（from continuation_config import RATE_LIMIT_PATTERNS
      实测 OK：7 patterns / 5 infra）；launcher import 冒烟 OK
- [x] py_compile 四文件全过
- [x] commit 只含 4 个文件

## 三、模式并集取舍说明

| 模式组 | 平凡版 | 本 repo 版 | 并集结果 |
|---|---|---|---|
| RATE_LIMIT | 4 | 7 | 本 repo 版（超集） |
| CONNECTION | 5 | 8 | 本 repo 版（超集） |
| AI_GAVE_UP | 10 | 无 | 平凡版原样 |
| TOKEN_LIMIT | 7 | 无 | 平凡版原样（仅审计用） |

## 四、遗留

无。WP-J/WP-K/WP-L 按 045/任务书消费本模块。
