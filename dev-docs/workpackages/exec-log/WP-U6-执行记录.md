# WP-U6 执行记录 — Ox Alpha 数学能力评估

> **执行时间**: 2026-08-21（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（047 报告，续传框架修正版；配额 11 次=10 计划+1 续传探针）

---

## 一、做了什么

1. **选题**：分层抽样修正版——easy(completed,1轮)×3 + hard_2round×3 +
   dead_session×2 + trunc_history(历史 comp=25000 截断轮)×2 = 10 题；
   题目文本从 seed_export 提取并清洗（修复重复头/字面量\n/正则早断三处提取 bug）
2. **批量脚本**：`scripts/test_wp_u6_ox_alpha_eval.py`——铁律15断言链 +
   INITIAL_PROMPT_TEMPLATE 原文注入 + 断点续跑(--start-from) + --effort 参数
   （阶段2新增）+ proof.md 检查
3. **Phase 1（max）**：5/5 预算烧尽（70–97K 字符思考、msg=0、outTok=32,000）
4. **用户纠偏**："卡死是对的，我们就是要处理这种情况" → 框架修正为系统口径
5. **Phase 2（low）**：4/5 秒级 boxed 答案（1653 仍烧尽）
6. **续传探针**：U2 截断思考喂回 CONTINUE 模板原文 → 205s 收敛出完整证明+boxed
   +"### PROOF COMPLETE"
7. 报告 `dev-docs/047`（三分支结论：有条件可作默认）

## 二、验收 checklist 对照

- [x] 出题清单表（分层+历史终态+分布调整注明）
- [x] jsonl 落盘 + 组装产物
- [x] 五维评估表（能力按系统口径重判/reasoning 双验/1M 实证/兼容含 proof.md 不符/
      tool 干净）
- [x] 三分支结论 + 037 修订建议
- [x] 047 报告；零生产改动；配额记录（11 次，超限 1 次已说明）

## 三、关键发现存档

1. ox-alpha 有效输出上限实测 32,000 tokens（OpenRouter 层），非模型卡的 131,072
2. effort 是决定性策略变量：max→深思考必截断（难题上）；low→快答（易中题上）
   ——建议进 DB batch 可配参数
3. proof.md 文件写入指令遵从度低（10/10 message 输出）——V4 适配器落盘兜底
4. 47/41 两题 glm 卡死而 ox-alpha low 直答自洽解——正确性待领域复核

## 四、认知闭包与 checklist 影响分析

```
=== 认知闭包与 checklist 影响分析 ===
认知闭包（SYSTEM_CLOSURE.md）：[暂不更新] 调查阶段
checklist/：[暂不更新] U6 结论进 U8 总报告后随 V 系列落地再动
```
