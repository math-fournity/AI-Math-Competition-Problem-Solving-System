# WP-D 执行记录 — SOP_01 精简

> **执行时间**: 2026-08-21（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（真跑验证：A16/A17 清零、抽样 5 全绿）

---

## 一、做了什么

1. **_check_audit_pipe_health 瘦身**：删 A16（完成数）/A17（失败率与分布）——
   SOP_07 项 1 接管且升级为完整快照；保留 A15 队列停滞快速预警（01 视角最先看到）
   与 A18 计数式门闸（闭包详单移交步骤07项3/--pending）；段尾加"详查见步骤 07"指针
2. **completed 抽样直接检查**：新增 `_check_completed_sample_files()` 抽 5 个
   completed 直接验证 proof 存在+boxed，接入 check_01 调用链——WP-B 附录清单
   第一项落地（028 教训的 SOP_01 防线）
3. **SOP_01 文档同步**：§8.5 "9 个语义动作"→"13 个（续传 9+审计 4）"；数字口径段按
   改后代码重写（约 13 项）；§2.1 新增 completed 抽样异常的 028 处置行

## 二、验收 checklist 对照

- [x] `grep A16|A17|audit_failure_rate` 在 SOP_01 路径清零 ✅
- [x] check_01 真跑：审计快速概览（A15 告警 pending=122/running=0 正确触发+A18 计数）
      + completed 抽样 5 行全绿（贴记录于执行过程）
- [x] §8.5 写 13 个；数字口径段与代码一致
- [x] 判断表新增 2.1 处置行
- [x] py_compile 过；commit 显式路径

## 三、偏差说明

- StepGate.md 的"9 个"未顺手改（禁止事项允许——归 WP-F 全量文档同步），已记录
