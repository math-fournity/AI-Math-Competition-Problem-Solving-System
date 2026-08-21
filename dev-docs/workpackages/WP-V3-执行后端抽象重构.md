# WP-V3 — launcher 执行后端抽象重构（-p 后端化，行为不变的纯重构）

> **优先级**: 实现系列第三（V2 门禁就位后）
> **依赖**: WP-V1、WP-V2、WP-U3/U4/U8
> **预计规模**: 【待 U8 实数化；框架估 300-500 行重构，continuation+proof_audit 两 launcher】
> **性质**: 实现（**重构**——本包完成后系统行为与重构前完全一致，-p 模式跑，ACP
> 后端已就位但未启用）
> **⚠️ 框架版**：🔶 槽位由 U8 填实

---

## 0. 给执行 AI 的第一句话

把现有 -p+tmux 启动路径**原样搬进** PtmuxDevinBackend（U4 接口的第三个实现），launcher
主循环改为通过后端接口调用。**铁律：行为零变化**——本包是纯重构，改完跑 sim 全剧本
+ 真实小批次，产物与重构前逐字段一致。这一步让 V4/V5 的接入变成"换个后端类"，不再
碰业务逻辑。

## 1. 背景

- U4 的分界：业务逻辑（调度/判定/门闸/续传/优雅停止）留在 launcher；引擎逻辑
  （进程/协议/产物落地）进后端。-p 后端是"零行为变化"的对照组——它证明抽象没丢语义
- 风险：continuation_launcher 的启动/监控段与判定段交织（pane 预检/DONE.md 检查/
  stall 检测的 pane_hash 追踪都在 running 检查循环里）——U3 影响面清单是切分地图

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **049 的 V3 任务书**（🔶 切分方案——哪些行进后端哪些留） | 本包的施工图 |
| 2 | `src/continuation_launcher.py` 全文 + `src/proof_audit_launcher.py` 全文 | 重构对象（注意线 1 WP-H/J/K/L/S 已落地的形态——以当前代码为准） |
| 3 | `src/acp/backend_base.py`（V1） | 接口——PtmuxDevinBackend 实现它 |
| 4 | **044 影响面清单**（U3） | 启动/存活/清理/列举四层的切分依据 |
| 5 | `src/sim/`（V2 后） | 回归门禁（全剧本） |
| 6 | `scripts/test_wp_v1_acp_lib.py` 的 mock 模式 | -p 后端的单测方式（mock tmux 命令） |

## 3. 规格（框架）

```
src/backends/ptmux_devin.py   —— 或并入 src/acp/（🔶 按 U8 定夺目录）：
    start(task): 现有 launch_solve/start_handover 的 tmux 启动段（new-session/
                 pipe-pane/DONE.md 清理/sleep 999999 命令）原样迁入
    poll(handle): tmux_running + DONE.md 存在性 + pane_text 抓取 + pane_hash 追踪
                  （stall 检测的状态留在 handle）——返回 BackendStatus（映射：
                  tmux 活+无 DONE=thinking/tool_running；DONE=done）
    terminate(handle, reason): kill-session（过 GATE-KILL-SESSION——门闸在 launcher
                  层还是后端层？🔶 U8 定夺：建议门闸留 launcher（语义动作归业务），
                  后端提供原语）
launcher 改造：launch_solve 等函数变薄（组装 task → backend.start）；
              running 检查段消费 backend.poll 的状态——**判定逻辑
              （is_truncated/is_completed/proof 检查）不动**（消费后端产物路径）
```

## 4. 任务分解（框架）

1. PtmuxDevinBackend 实现（迁移而非重写——diff 可逐行对照）
2. 两 launcher 接入（continuation + proof_audit；SOP/门闸/监控调用点不变）
3. **行为等价验证**（本包的命门）：
   - sim 全剧本（017 七剧本）通过
   - 真实小批次（每 launcher 2-3 题）跑通，rounds_log 字段/flow 事件序列/产物文件
     与重构前模式逐项对照（抽 1 题全字段 diff）
   - 优雅停止回归（SIGINT 流程，WP-H 的验收断言重跑）
4. py_compile + 单测（mock tmux 的 backend 单测）+ commit

## 5. 禁止事项

- ❌ **零行为变化**——任何"顺手优化"都是 scope 蔓延（发现 bug 记录另立，不在重构里修）
- ❌ 判定逻辑/门闸语义/资产落盘格式不动（产物路径可变由后端管理但内容不变）
- ❌ 不启用 ACP 后端（backend 字段仍 -p——切换是 V7）
- ❌ 线 1 的 WP 若未全完成（总控表核对），先报告依赖状态再动

## 6. 验收 checklist

- [ ] launcher 中 tmux 命令直接调用清零（grep new-session/pipe-pane/kill-session 在
      launcher → 都在后端模块）
- [ ] sim 七剧本 + 2 ACP 剧本全过（ACP 剧本用 fake 后端跑 launcher——V2 门禁的首次
      全流程使用）
- [ ] 真实小批次等价性 diff 记录
- [ ] SIGINT 优雅停止回归通过
- [ ] py_compile/单测/commit；`--status`/SOP 检查无异常

## 7. 完成汇报要求

执行记录：迁移对照表（原行→新位置）、等价性验证数据、遗留（发现未修的 bug 清单）。

## 8. 审计对照

1. 等价性我会抽 1 题亲核 rounds_log 全字段 + flow 事件序列
2. grep 验证 launcher 无直接 tmux
3. sim 全过输出
4. backend 字段未变（-p）
