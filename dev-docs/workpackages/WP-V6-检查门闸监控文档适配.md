# WP-V6 — 检查/门闸/监控/文档全量适配（ACP 化的体系收口）

> **优先级**: 实现系列第六（V4/V5 后；V7 前——灰度前检查体系必须先对齐）
> **依赖**: WP-V3~V5、WP-U3（影响面清单的消费终 点）
> **预计规模: 【待 U8 实数化；框架估 15-25 个改动点，横跨 8+ 文件】
> **性质**: 实现（SOP/门闸/监控/文档——按 044 清单逐点落）
> **⚠️ 框架版**：🔶 槽位由 U8 填实

---

## ★ U8 任务书修订（2026-08-21）

| 槽位 | 填实值 |
|---|---|
| 四源重定义 | 044#22/23/35：tmux 源→launcher 进程表/注册表 acp 字段（solve/handover/audit 分型保留） |
| zombie 重定义 | 044#12："有进程零通知 N 分钟"替代空 pane 检测（复用 spin 数据源） |
| SOP_07 新检查项 | 后端健康概览（当前 backend/两后端健康态/最近 fallback 事件）——048§2.3 |
| rule 更新 | noninteractive-solver-run → 支持 ACP 模式（覆盖矩阵#6 的归属落地） |
| budget_starved 终态 | 状态机新增（049§零指纹定义），与 truncated_at_max 区分统计 |
| **工作量实数** | **~300 行** |
| **启动条件** | V4/V5 完成 |

---

## 0. 给执行 AI 的第一句话

044 影响面清单的每个"ACP 等价物"列，现在逐点落地：A13 四源一致的新源定义、门闸
docstring 的查法更新、monitor 的 tmux 数数改造、SOP 检查适配、资产保留表更新、
noninteractive rule 更新、SYSTEM_CLOSURE 全量同步。这是 ACP 化的"神经系统"适配——
launcher 会跑了，但检查体系还只会看 tmux 的话，系统等于失明。

## 1. 背景

- U3 影响面（044）逐行消费；036 §四.2b 的原话："ACP 化消灭的是整个 tmux 存在性体系"
- 双后端并存期的特殊性：-p 后端（过渡期）还有 tmux——**检查体系必须同时看两种
  后端**（按 backend 字段分派查法），这是本包最易漏的点

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **044 影响面清单** + **049 对本包的任务书**（🔶 逐点方案） | 施工清单 |
| 2 | `src/monitor_continuation.py` 的 A1/A13 检查 | 四源一致改造对象（ACP 源=🔶 后端进程表/注册表新字段——按 049） |
| 3 | `src/session_registry.py` | 🔶 tmux_alive 字段的兼容策略（改名/双字段/语义扩展） |
| 4 | 门闸 docstring 现状（WP-A 后的 4 审计闸 + 续传 9 闸） | 查法更新（tmux 命令 → 按 backend 分派的查法） |
| 5 | `scripts/sop/checks.py`（check_01/07 的 tmux 检查） | 孤儿对账的双后端版 |
| 6 | `AGENTS.md` 资产保留铁律段 + `.devin/rules/`（noninteractive-solver-run 位置——grep 找） | rule 与铁律表更新对象 |
| 7 | `docs/sop/SYSTEM_CLOSURE.md` | 全量同步（架构图/模块表/数据产出/alert 清单含 backend_* 两新类型） |

## 3. 规格（框架——按 044 四层组织）

```
列举层改造（最重）：
  A13/SOP 孤儿对账/control sessions 的"session 数数"→ 统一的新列举函数：
  list_active_agents() = ptmux 后端的 tmux 列举 + ACP 后端的进程/注册表列举
  （🔶 实现位置按 049——建议 session_registry 扩展为唯一权威列举点）
存活层：tmux_alive 的兼容（🔶 049 策略）+ ACP 的 proc.poll()
门闸层：4+9 闸 docstring 查法改双后端版（语义不变——kill 仍是 kill，查法分派）
  + GATE-KILL-SESSION 的 resource 标签语义说明更新
监控层：A1/A13 读新列举；backend_degraded/backend_down alert_type 登记
  SYSTEM_CLOSURE alert 清单（+2 或 🔶 048 全集）
资产层：铁律表加"ACP 通知日志 jsonl"行；tmux_pipe.log 标注"仅 ptmux 后端"
rule 层：noninteractive-solver-run 增 ACP 模式说明（-p 与 ACP 并存，🔶 按 049 措辞）
SOP 层：SOP_01 §8.5/检查项、SOP_07 项 7 的双后端版；报表模板微调
```

## 4. 任务分解（框架）

1. list_active_agents 统一列举（session_registry 扩展）+ 三消费方接入（monitor/
   checks/control）
2. 门闸 docstring 13 闸查法更新 + `--register` 刷新
3. alert 登记与 SYSTEM_CLOSURE 全量同步（架构/模块/数据/alert/判定框架的 ACP 段）
4. 铁律表/rule/SOP 文档/模板更新
5. 验证：双后端各跑 1 题 + SOP_01/07 真跑（检查输出对两种后端都正确）+ 门闸
   `--pending` 闭包输出
6. py_compile/commit

## 5. 禁止事项

- ❌ 不做只适配单后端的检查（所有改动的检查必须双后端可用——过渡期铁则）
- ❌ 门闸语义/门闸数量不变（13 个；只改查法）
- ❌ 不删 tmux 检查代码（ptmux 后端还活着）
- ❌ SYSTEM_CLOSURE 的更新等全部代码完成后一次做（不逐文件碎更）

## 6. 验收 checklist

- [ ] 044 清单的每个改造类型（重写/替换/源重定义/查法更新/消失）都有对应落地行
- [ ] list_active_agents 在三消费方的输出双后端正确（混合场景实测：ptmux 1 题 +
      acp 1 题同时跑，数数对）
- [ ] 13 门闸 docstring 双后端查法 + `--pending` 输出验证
- [ ] alert 清单/铁律表/rule/SOP/模板全部更新且互相一致
- [ ] SOP_01/07 真跑输出（双后端混合态）
- [ ] py_compile/commit

## 7. 完成汇报要求

执行记录：044 清单→落地行的对照表（全表）、混合场景验证数据、文档变更清单。

## 8. 审计对照

1. 044 对照表逐行核对（我持原始清单）
2. 混合场景我会亲手复跑数数
3. 门闸 13 个未增减（--list）
4. SYSTEM_CLOSURE 与代码的一致性抽查（alert/架构段）
