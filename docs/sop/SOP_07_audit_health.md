# SOP_07 — 审计系统健康检查

> **本步定位**：审计 Pipe（collector→launcher→result_collector）的专属健康检查——
> 8 项检查中 4 项为直接实物检查（铁律：.devin/rules/direct-verification-ironlaw.md）。
> 系统级背景（审计管线三段架构/门闸清单/正常状态阈值）见上方 L0（SYSTEM_CLOSURE），
> 本文档只写本步骤增量。

## 认知增量（判断前必读的三条语义）

1. **completed 的真实语义（E1，最易踩的坑）**：DONE.md 存在 = devin cli 已退出，
   ≠ 审计成功。审计成败唯一权威 = p27_proof_audits.audit_status。看到"5 个
   completed"不要以为审计成功——可能全是 PARSE_ERROR 待人工。
2. **收尾即收集语义（WP-H）**：审计判定完成即入库（collect_one），p27_proof_audits
   持续增长是健康信号；launcher 退出前还有兜底收集。若 DB 有 completed 但
   p27_proof_audits 不涨 = 收集链断裂。
3. **PARSE_ERROR 的语义（WP-N）**：audit_status=PARSE_ERROR 表示"不知道对错"
   ——不是失败也不是通过，必须人工读 export 复审。堆积无人看是本步的重点排查对象。

## 执行指令

逐项阅读上方自动检查输出（8 项），按下方处置指引表判断：

| 检查项 | 正常标准 | 异常处置 |
|---|---|---|
| 1 队列与状态快照 | pending 持续下降、running≤并发、失败率<20% | 失败率>20%：抽读 export 判定是否系统性误判；pending 堆积查 launcher 存活 |
| 2 failed reason 分布 | 无单类占比 >30% | dead_session_no_export/max_runtime_exceeded 占比异常 → 排查审计模板或输入 |
| 3 门闸 Y 通道 | 无 AUDIT 闸 waiting | 有 → 按 checklist 核对后 --step 放行（附理由） |
| 4【直接】export 实物 | 抽样全部存在且含 XML | 缺失/无 XML → 收集链断裂嫌疑，critical 上报并暂停审计批次 |
| 5【直接】通过题交叉验证 | 抽样 proof 存在且含 boxed | DB 说通过但盘上无证据 → critical 上报（028 教训重现） |
| 6【直接】作弊题证据 | cheating_analysis 指明具体行为 | 证据空泛 → 转 SOP_04 C9 复核流程翻案或维持 |
| 7【直接】孤儿 session 对账 | tmux 与 Redis running 一致 | 孤儿（有 DONE.md）→ 建议 kill 命令：`tmux kill-session -t <名>`；漂移 → 查 launcher 死亡时间线 |
| 8 PARSE_ERROR 堆积 | 0 或全部有未 resolve alert 对应 | >0 → 按"人工复查清单"逐条读 export 复审（判 PASS/FAIL/重审），resolve 对应 alert |

### C6 轻量语义检查（AI 判断）

随机抽 1 个 audit_status=PASS 的题：对照 audit_summary 与 export 中证明内容——
summary 是否与证明实际结论一致？明显不符（如 summary 说 PASS 但证明答非所问）
→ 转人工复核并在报表记录。

## Todo 指令（固定格式）

1. [ ] 填写报表 `report_step_07`（docs/sop/templates/ 模板，含 8 项打勾+处置记录）
2. [ ] 异常项按处置指引表执行并在报表记录处置结果
3. [ ] 执行 `python -m scripts.sop.run`
