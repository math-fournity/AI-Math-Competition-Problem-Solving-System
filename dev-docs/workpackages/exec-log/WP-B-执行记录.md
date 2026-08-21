# WP-B 执行记录 — 直接检查铁律 rule

> **执行时间**: 2026-08-21（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（rule 文件 + AGENTS.md 引用点同步）

---

## 一、做了什么

1. 新建 `.devin/rules/direct-verification-ironlaw.md`（46 行，always-on）：
   - 判定对照表 6 行（题目完成/审计完成/审计收集/进程存活/队列/session 实干活）
     ——每行 ❌ 间接转述 vs ✅ 直接实物
   - 028 教训引用（138 vs 14 proof，124 被删）
   - 与 verify-with-logs 三层法的互补关系（结果→过程→实物三层叠加，非冲突）
   - 与"适度依赖 Master Agent"的衔接（事实层不做分工妥协）
   - 附录：SOP 间接→直接升级清单（交接给 WP-C/D/E）
2. AGENTS.md 硬约束段同步：标题改为"查过程证据 + 直接检查"，双 rule 引用，
   正文补最底层实物要求与 028 教训

## 二、验收 checklist 对照

- [x] rule 存在，含判定表（6 行≥5）/028 引用/verify-with-logs 关系/适度依赖关系/
      升级清单附录
- [x] `grep -c "间接\|直接"` = 11（>10 ✅）
- [x] 格式对齐 verify-with-logs.md（frontmatter trigger: always_on + 触发场景说明）
- [x] 引用点已更新（AGENTS.md:147 区域双 rule 引用）
- [x] commit 只含本 WP 文件（rule + AGENTS.md）

## 三、偏差

无。长度 46 行 <120（always-on 负担达标）。
