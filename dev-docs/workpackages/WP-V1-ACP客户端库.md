# WP-V1 — ACP 客户端库实现（src/acp/：base + 双后端 + 组装器 + 检测）

> **优先级**: 实现系列之首（V2~V6 的共同依赖）
> **依赖**: **用户批准 049 总报告后启动**；WP-U4（接口）/U5（OpenCode 参数）/
> U7（Devin 规格）/U8（任务书修订版）
> **预计规模**: 【待 U8 实数化；框架估 500-800 行】src/acp/ 新模块 4-5 个文件 + 单测
> **性质**: 实现（新代码，不接 launcher——接入是 V3/V4）
> **⚠️ 本文档为框架版**：标 🔶 的规格槽位由 WP-U8 填实后方可执行

---

## ★ U8 任务书修订（2026-08-21 填实——049 §三，与本文冲突处以本块为准）

| 槽位 | 填实值 | 来源 |
|---|---|---|
| 通知日志格式 | 每行 `{ts, dir:"→\|←", msg}`（U1/U2/U5 探针同款） | 046§五 |
| comp 取数路径 | prompt response 的 usage.outputTokens（流内 usage_update 为空——043） | 043 |
| set_config 方法名 | 兼容探测 `session/set_config_option`(0.16.x) / `session/set_config`(新版) | skill§3.8 |
| export 兜底 | **文件重定向**（非管道捕获——64KB 管道限制实证）+ JSON 校验 + 重试 | 049§零 |
| start() 断言链 | model→断言回显→effort→断言回显，fail-fast（铁律15）；model/effort 从 DB batch 读 | 铁律15/045 |
| 截断检测语义修正 | finish_reason 仅信息性；成败分界=组装后 message 非空；comp 条件辅助（实测校准阈值） | 045§三/043 |
| **工作量实数** | **~800 行**（接口200+opencode后端150+devin后端150+组装器120+detection80+export兜底60+测试） | 049§三 |
| **启动条件** | 用户批准 049 决策点（D1-D7） | 红线 |

## 0. 给执行 AI 的第一句话

把 U 系列的设计变成代码：`src/acp/` 包——后端抽象基类、OpenCode/Devin 两个适配器、
通知→ATIF 组装器、thinking spin 检测。**本包不接 launcher**（纯库+单测），launcher
接入在 V3/V4——这让协议代码可独立充分测试（ACP 协议的坑在 U1/U5 都见过：权限响应
格式/静默窗口/mcpServers 必填）。

## 1. 背景

- U4 架构（执行后端抽象）的实现层；WP-T.1 的检测逻辑落在 base 层（037 §5.1：
  双管线通用）
- 独立成包的意义：协议代码与 launcher 解耦——sim（V2）可以 mock 这个库，单测不打
  真实 API

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **049 总报告的 V1 任务书节**（U8 修订版——本文档的权威覆盖者） | 槽位实值/工作量/启动条件确认 |
| 2 | `dev-docs/045`（U4 架构） | 接口定义全文——你的实现规格 |
| 3 | `dev-docs/046`（U5）+ `048`（U7） | 两后端的详细规格（窗口参数/权限细节/错误三层） |
| 4 | OpenCode + Devin 两份 skill | 协议细节速查（实现时随查） |
| 5 | `scripts/test_wp_u1_acp_smoke.py` + `test_acp_signals.py` | 已验证的客户端骨架——抽取复用（这两个脚本的经验直接迁移） |
| 6 | `src/continuation_launcher.py` 的 `is_truncated/is_completed` | 组装器的产物契约（ATIF 字段） |
| 7 | `src/observability.py` 的 log_flow 签名 | 后端事件接行为流水（设计要求：后端关键事件也进 flow） |

## 3. 规格（框架版——🔶 = U8 填实）

```
src/acp/__init__.py
src/acp/backend_base.py
  class BackendHandle: {backend, session_id, proc, work_dir, traj_path, started_at, last_signal_ts}
  class BackendStatus: {state: thinking|tool_running|message_out|done|failed,
                        detail, last_signal_ts, assembled_partial?}
  class AcpBackend(ABC):
      start(task) -> BackendHandle        # spawn 子进程+initialize+session/new
                                          # ★+ set_config_option 设 model/effort 并断言
                                          #   响应回显（铁律 15，fail-fast——OpenCode 后端；
                                          #   Devin 后端校验 --model 已传）
      poll(handle) -> BackendStatus       # 非阻塞读通知+更新 last_signal_ts+组装缓冲
      terminate(handle, reason)           # 🔶 每后端的终止序列（048/046）
      @property spin_window_seconds       # 5min（037 不变量）
      @property done_silence_seconds      # 🔶 OpenCode=046 实测值；Devin=N/A（response 驱动）
      health_probe() -> bool              # initialize+session/new 探测（5s 超时）
src/acp/opencode_backend.py   # 🔶 完成状态机按 046；权限零交互；close 语义
src/acp/devin_backend.py      # stopReason 驱动；权限自动响应 🔶（048 的 allow_session 决策）
src/acp/assembler.py          # 通知流→ATIF conversation.json；实时 jsonl 落盘（资产）
                              # + OpenCode 侧三层来源对接（038 §八）：export 兜底读取器
                              #   （opencode export 包装——进程崩溃后从 SQLite 捞回）
src/acp/detection.py          # spin 检测（poll 的 last_signal_ts > spin_window → alert 事件）
                              # + 截断检测分层（038 §九）：第一层消费 poll 的
                              #   finish_reason（协议原生，U2 任务 6 实测其截断值）；
                              #   第二层结构启发式 is_truncated（阈值读 backend.
                              #   trunc_comp_threshold）
                              # + 错误三层检测 🔶（046：通知文本 WP-I 模式/stderr/超时）
```

## 4. 任务分解（框架）

1. 按 045 接口实现 5 个模块（🔶 槽位以 049 为准）
2. 单测 `scripts/test_wp_v1_acp_lib.py`：
   - 组装器：喂 U2 的 jsonl 数据（tmp 里或重新构造 fixture）断言 ATIF 字段与
     is_truncated/is_completed 兼容
   - 状态机：mock 通知序列驱动 poll，断言状态转移（含 spin 触发/完成触发）
   - 错误检测：WP-I 模式对通知文本的匹配单测
   - 协议层：与真实后端的冒烟（各 1 次简单任务——复用 U1 冒烟任务）
3. 行为流水接线：backend 事件（start/done/failed/spin_detected）写 log_flow
4. py_compile + 全部测试 + commit（显式路径）

## 5. 禁止事项

- ❌ 不接 launcher（V3/V4 的事）；不建 tmux（ACP 无 tmux）
- ❌ 不写死并发数/静默窗口/模型名（配置从 DB batch 读——窗口参数 🔶 来源写清）
- ❌ 组装器不做"创造性补全"（通知里没有的字段标 null，不编造——判定函数要能处理）
- ❌ 协议实现不偏离 skill 文档（U1 踩过的坑：mcpServers 必填/权限响应嵌套格式）

## 6. 验收 checklist

- [ ] src/acp/ 五模块存在，接口与 045 一致（逐方法核对）
- [ ] 单测全过（组装器 fixture 用 U2 真实数据）；两后端真冒烟各 1 次通过
- [ ] spin 检测可单测触发（mock 时钟）
- [ ] log_flow 事件落盘抽查
- [ ] py_compile；grep 无写死窗口/模型/并发；commit

## 7. 完成汇报要求

执行记录：模块清单+行数、单测输出、冒烟结果、与 045/046/048 规格的偏差清单（若有）。

## 8. 审计对照

1. 接口逐方法对 045；槽位值对 049
2. 组装产物喂 is_truncated/is_completed 实跑（不崩+判定合理）
3. 无 tmux 依赖（grep）；无写死配置
4. 单测覆盖 spin/完成/错误三态
