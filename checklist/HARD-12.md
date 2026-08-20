# HARD-12: 检查体系完备性——数据库集合级完整性 + 跨题目模式 + 方向性判断

> **门类**: HARD · 硬约束
> **状态**: [x] 已完成
> **负责的WP**: WP-14
> **来源**: dev-docs/014-检查体系完备性盘点与缺口分析.md
> **所属章节**: §HARD · 硬约束（贯穿全程）

## 需求描述

检查体系必须覆盖三个层面，不能只有单run级别的文件存在性检查：

1. **数据库集合级完整性**——results集合是否为空、events是否完整、prepared是否堆积
2. **跨题目模式识别**——按题源分组的完成率差异、失败模式分布
3. **方向性判断**——策略是否有效、完成率是否可接受、系统产出是否有价值

## 验证方法

运行 `python -m scripts.sop.run` 执行完整SOP循环，确认：
- check_02 输出中包含 results集合检查、events完整性检查、prepared堆积检查
- check_02 输出中包含按题源完成率统计
- check_02 输出中包含标准文件检查和round编号连续性检查
- SOP_02 文档包含跨题目模式分析指令
- SOP_Z 文档包含方向性判断检查项
- SOP_04 文档包含export语义检查指令

## 关联文件

- `scripts/sop/checks.py` — 自动化检查逻辑（主要改动）
- `docs/sop/SOP_02_data_integrity.md` — 数据完整性SOP（新增跨题目模式指令）
- `docs/sop/SOP_04_ai_judgment.md` — AI判断SOP（新增C6 export语义检查）
- `docs/sop/SOP_Z_meta_system_review.md` — 元检查SOP（新增方向性判断检查项）
- `dev-docs/014-检查体系完备性盘点与缺口分析.md` — 缺口分析来源
- `dev-docs/015-检查体系缺口补全行动计划.md` — 行动计划

## 变更记录

- v1 · 2026-08-20 · 初始创建，对应WP-14
