# WP-V4 — OpenCode ACP 后端接入（默认管线上线的第一步）

> **优先级**: 实现系列第四（V3 重构完成后）
> **依赖**: WP-V1/V2/V3、WP-U5（OpenCode 规格）、WP-U8（含 U6 能力结论的裁决）
> **预计规模**: 【待 U8 实数化；框架估 200-400 行（薄接入——重活在 V1 已做）】
> **性质**: 实现（接入+启用路径，但**不切默认**——默认切换在 V7 灰度后）
> **⚠️ 框架版**：🔶 槽位由 U8 填实；**若 U2 判 OpenCode 组装碎片**，本包按 049 裁决
> 降级为"检测层接入"（组装走混合方案）——执行前先读 049 对本包的修订

---

## 0. 给执行 AI 的第一句话

把 V1 的 OpenCodeAcpBackend 接进重构后的 launcher：set-backend opencode_acp 可选、
backend 字段驱动、sim 剧本在真 launcher 上过、真实灰度单题验证。完成后 OpenCode
管线**可用但非默认**——默认切换是 V7 的灰度决策。

## 1. 背景

- U5 已定 OpenCode 的全部细节（静默窗口/注入/错误三层）；V1 已实现后端；V3 已抽象
- **★ 接入验收必查（铁律 15）**：OpenCode 后端的 start() 必须已完成"set model +
  set effort=max + 双断言回显"链路（V1 实现、本包验证）——未设模型会静默跑在
  内建 big-pickle 上（U1 勘误实证），灰度验证数据全部无效
  接入——本包是"组装"性质，薄但责任重：第一次让真实解题走 ACP
- 判定链的第一次真实消费：assembler 产物喂 is_truncated/is_completed——U2 已在实验
  脚本验证，本包在生产路径复验

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **049 对本包的任务书**（含 U2 分叉/U6 能力结论的跟随裁决） | 🔶 一切以它为准 |
| 2 | `dev-docs/046`（U5） | 窗口参数/注入映射/错误三层——接入配置 |
| 3 | `src/acp/`（V1）+ `src/backends/` 或 acp 内的 ptmux（V3 后的 launcher 结构） | 接入点 |
| 4 | WP-G 后的并发/配置机制 | backend 字段的 set-backend 命令实现参照（U4/U7 设计） |
| 5 | 线 1 的 WP-A 门控 docstring（GATE-LAUNCH-SOLVE 现状） | 接入后门闸 docstring 的"查法"更新素材（本包只做后端相关查法——全量门闸适配在 V6） |

## 3. 规格（框架）

```
接入点：
  launcher 的 backend 工厂（V3 建）：backend 字段（DB batch）→ 实例化对应后端
  set-backend 命令（continuation_control）：--batch-id X --backend opencode_acp|devin_acp|ptmux
OpenCode 特有配置（🔶 从 DB batch 读）：
  静默窗口/模型（openrouter/stealth/ox-alpha 的引用方式）/work_dir 的 AGENTS.md
  模板（🔶 U5 注入设计的模板文件）
资产新增：通知日志 jsonl（assembler 实时落盘）→ rounds_log/审计 run 记录其路径
  （🔶 字段名按 049；资产保留铁律覆盖它）
SOP 暂不改（V6 统一）——但 check_07 的孤儿对账会看不到 ACP session：本包先加一个
  兼容提示（ACP 后端 session 不在 tmux——检查输出注明 backend 类型），全量在 V6
```

## 4. 任务分解（框架）

1. backend 工厂 + set-backend 命令 + DB 字段迁移（batch 记录加 backend 列，默认
   ptmux——不动现值）
2. OpenCode 后端接入两 launcher（continuation + proof_audit 的审计 Pipe——审计也
   ACP 化，🔶 若 049 裁决审计先行则审计先接）
3. sim：OpenCode 剧本（V2 的 fake）在真 launcher 上全流程（solve/handover/审计/
   spin/静默完成五场景）
4. 真实灰度：set-backend opencode_acp + 1 道题真实跑（continuation 1 题；🔶 审计
   是否同批灰度按 049）——判定链/资产/flow 事件全链验证
5. 回退验证：set-backend ptmux 切回，1 题验证
6. py_compile/测试/commit

## 5. 禁止事项

- ❌ 不切默认（默认值仍 ptmux——V7 灰度后用户拍板）
- ❌ 灰度题数 ≤2（本包是接入验证不是批量——批量在 V7）
- ❌ 判定链不为本包加特例（assembler 产物必须走原生 is_truncated/is_completed；
   字段缺失的兜底方案 🔶 按 049，不许现场发明）
- ❌ 配置不写死（窗口/模型/backend 全 DB）

## 6. 验收 checklist

- [ ] set-backend 三值可切换（三后端 health_probe 实测输出）
- [ ] sim 五场景过（输出贴记录）
- [ ] 真实灰度 1 题：判定/产物（conversation.json+通知 jsonl）/flow 全链记录
- [ ] 切回 ptmux 验证过
- [ ] DB batch 的 backend 字段存在且默认 ptmux；无写死配置
- [ ] py_compile/commit

## 7. 完成汇报要求

执行记录：接入 diff、灰度题的全链数据（含 assembler 产物 vs 判定结果的字段级记录）、
回退证据、发现的问题清单。

## 8. 审计对照

1. 灰度题我亲手复核（conversation.json 字段/proof/通知 jsonl 三件对齐）
2. 默认值未变（DB 实查）
3. sim 五场景输出完整
4. 无判定特例（grep is_truncated 调用点无 backend 分支特判）
