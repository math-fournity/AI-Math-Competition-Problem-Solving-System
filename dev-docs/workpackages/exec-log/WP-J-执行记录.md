# WP-J 执行记录 — 审计系统终态检测补全

> **执行时间**: 2026-08-21（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（单测 16 PASS/0 FAIL；误伤检查 10 样本零命中）

---

## 一、做了什么

### 检测段（proof_audit_launcher.py running 检查段插入，位置=完成检查之后、session 消失之前）
1. **数据源**：pane 300 行 + pipe log 尾部 5KB 合并（`tail_file()` 新辅助——pane
   scrollback 会滚走早期错误）；add_running 元数据补 `tmux_pipe_path`
2. **判定辅助函数** `detect_terminal_verdict(detect_text)`（模块级便于单测）：
   检测顺序 rate_limited → failed_connection → failed_token_limit → ai_gave_up
   （先环境性，续传同序）
3. **kill 策略两类**（KILL_POLICY 模块级 dict）：
   - `rate_limited` / `failed_connection`：**不 kill** session 留观（devin 可能
     自恢复，对齐续传"标记不 kill"哲学）
   - `ai_gave_up` / `failed_token_limit`：kill（过门闸 reason=verdict）
4. 失败写入统一带 `failure_category: classify_failure(verdict)`（WP-L 消费）
5. **rate_limited 全局暂停**：`audit_rate_paused_until = now + 1200`（20 分钟，
   照抄续传模式）；主循环顶部检查（暂停中 sleep+continue 跳过整轮）+ 补充并发
   while 条件加闸

### 超时语义修正 + 死代码删除
- `stall_timeout` → **`max_runtime_exceeded`**（reason/error_message/日志三处；
  名实一致——这是总时长超时不是无活动检测）
- `detect_stall()` 死代码整体删除（031 B5：定义后从未被调用）；`stall_since`
  字段删除
- 超时失败写入补 failure_category=model

## 二、误伤检查（零配额方案——用既有产物验证）

对 10 个**已成功完成**审计的 tmux_pipe.log 全量 grep 检测模式（大小写不敏感）：
**全部 0 命中**——正常完成的审计不含任何检测模式词，无误伤风险。
样本：622/632/174/550/130/258/295/amo8 等。

## 三、单测输出（16 PASS / 0 FAIL）

- 五类场景判定各 1 例 ✅（含正常完成文本判 None）
- KILL_POLICY 四映射断言 ✅
- classify_failure 五 verdict 分类 ✅
- tail_file 辅助 ✅（5120 字节尾部读取+不存在路径安全）

## 四、验收 checklist 对照

- [x] `grep detect_stall|stall_since` → 0 ✅
- [x] `grep stall_timeout` → 0 ✅（注释同步清理）
- [x] `grep max_runtime_exceeded` ≥1（6 处）
- [x] 共享模块 import + 使用（:50 import，:322-324 判定调用）
- [x] rate_limit 全局暂停：`+ 1200` 与主循环顶部检查均在
- [x] kill 策略两类分明（KILL_POLICY 注释+单测断言）
- [x] failure_category 字段设计就位（下次真实失败发生时入 DB——当前无失败样本可抽，
      单测覆盖分类正确性）
- [x] 单测过 + 误伤观察记录
- [x] py_compile 过

## 五、文档同步

- operational-concerns.md §1："审计 Pipe 同款已接入"块（数据源/暂停机制）
- SYSTEM_CLOSURE §4 proof_audit_launcher 行：加终态检测描述

## 六、遗留

无阻塞项。failure_category 的 DB 抽查待下一次真实失败发生后补样（当前批次全部成功）。
