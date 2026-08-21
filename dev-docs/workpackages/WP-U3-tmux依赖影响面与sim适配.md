# WP-U3 — tmux 依赖体系全量影响面 + sim 适配评估

> **优先级**: 线 2（U1 之后；与 U2 可并行）
> **依赖**: WP-U1（基线）
> **预计规模**: 影响面清单报告（044）——纯代码调查，无实验
> **性质**: 调查。**只读代码，零改动**

---

## 0. 给执行 AI 的第一句话

ACP 化消灭的不只是"devin -p 启动命令"，而是**整个 tmux 存在性体系**：A13 四源一致、
session 注册表的 tmux_alive、门闸 resource=tmux、watchdog、SOP 的孤儿对账、监控的
session 数数……设计者已 grep 出 70+ 调用点的分布底料，你要把它变成逐点的"ACP 化后
等价物"清单，并评估 sim（发布门禁）的适配——这是 V 系列所有包的公共输入。

## 1. 背景（为什么）

- 036 §四.2b 指出 034 版 WP-U 范围 1（只列"devin -p 启动位置"）严重低估影响面——
  tmux 是本系统的**进程管理底座**，不是启动参数
- sim 适配是硬依赖（铁律 12：改调度逻辑必须过 sim 发布门禁）——ACP 化是最大的调度
  改动，fake_devin 不 ACP 化则门禁无法跑（036 §四.2a）

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | 设计者底料（2026-08-21 grep，复核后可用）：tmux 调用点分布 = continuation_launcher(27)/continuation_control(16)/proof_audit_launcher(11)/session_registry(4)/monitor_check_continuation.sh(4)/continuation_watchdog.sh(4)/monitor_continuation(3+)/sim×5 | 影响面的量级地图——你的起点 |
| 2 | `src/session_registry.py`（465 行，重点 create_session_record/update_tmux_alive_status/check_done_md） | 注册表字段（tmux_alive/session_name/status）与 tmux 的耦合点 |
| 3 | `src/monitor_continuation.py` 的 A1/A13 检查（搜 `_tmux_p27_sessions`） | **四源一致的 tmux 源**——ACP 后源集合怎么重定义（注意 :284-288 的勘误注释：按 session 类型拆分对比——这个思路 ACP 后要保留） |
| 4 | `monitoring/continuation_control.py`（750 行，重点 sessions/stop/start） | kill-session 语义/一致性检查/服务管理 |
| 5 | `src/step_gate.py` + 续传 launcher 的 `@gated(resource="tmux")` 两个闸 | 门闸语义（kill 动作）在 ACP 下的等价物（杀 subprocess） |
| 6 | `src/sim/` 全目录（fake_devin.py/run_sim.py/setup.py/assert_final.py/teardown.py） | sim 架构：剧本演员如何被 tmux 启动/断言器吃什么产物/隔离旋钮 |
| 7 | `dev-docs/017-全流程模拟系统设计方案.md`（选读使用节） | sim 的设计意图与跑法 |
| 8 | `src/observability.py`（271 行） | flow 事件的 session_name 维度（ACP 后=acp 会话标识，字段兼容性） |
| 9 | `dev-docs/037` §五（对现有工作包影响）+ 036 §四.2 | 影响面评估的范围定义 |

## 3. 现场事实基线（设计者 grep 底料——复核命令同 §2.1）

tmux 依赖分四层（你的清单按此组织）：
1. **启动层**：new-session/pipe-pane（continuation/proof_audit launcher）
2. **存活层**：has-session/tmux_running/capture-pane（判定+注册表+检查）
3. **清理层**：kill-session（门闸 kill_session/audit_kill_session/control 的 stop/clean）
4. **列举层**：list-sessions（monitor A1/A13、control sessions、check 脚本、watchdog）

## 4. 任务分解

### 任务 1：逐点影响面清单（044 报告核心表）

对底料中每个文件逐个读代码，输出清单表（预计 25-35 行）：
```
| 文件:函数 | tmux 用法 | 业务语义 | ACP 等价物 | 改造类型 |
例：
| continuation_launcher:launch_solve | new-session+pipe-pane | 启动解题进程+日志管道 | subprocess.Popen(acp)+通知日志 jsonl 落盘 | 重写启动层 |
| session_registry:update_tmux_alive_status | has-session | 注册表存活心跳 | subprocess.poll() is None | 字段语义改名或兼容保留 |
| monitor_continuation:_tmux_p27_sessions | list-sessions 计数 | A1/A13 的 tmux 源 | ACP 进程表（launcher 内存/注册表新字段） | 源重定义 |
| kill_session@GATE | kill-session | 不可逆终止 | proc.terminate()+grace | 门闸查法更新（语义不变） |
| ...（每个真实点一行）
```
改造类型分类：**重写**（启动/监控循环内）/**等价替换**（tmux 命令→subprocess 等价）/
**源重定义**（A13/SOP 检查）/**语义保留+查法更新**（门闸 docstring）/**消失**
（pipe-pane、E2 的 sleep 999999+DONE.md 模式）。

### 任务 2：DONE.md/export/pane 三件套的 ACP 等价物专节

现有判定的三个物理依据在 ACP 下的替身：
- DONE.md（devin 退出标记）→ prompt response（Devin）/静默窗口+进程存活（OpenCode）
- export conversation.json → 通知组装（引 U2 结论）+实时落盘 jsonl（资产保留新形态）
- pane 文本（WP-J 的错误模式检测源）→ 通知流（tool_call kind/错误内容在 message/
  thought 中？——标注：**错误模式在 ACP 通知里长什么样是 U5 的实测点**，本节只留接口）

### 任务 3：sim 适配评估

- fake_devin 现状：跑在 tmux 里的 python 剧本演员（SIM_MODE 替换 devin 命令）
- ACP 化需求：fake 变成"ACP server 演员"（stdin/stdout JSON-RPC 按剧本吐通知）——
  评估：剧本格式改造量 / 能否复用现有 7 剧本语义 / assert_final 断言的产物路径变化 /
  setup/teardown 的 tmux 假环境是否还需要
- 结论：sim ACP 化的工作量估计 + 是否 V 系列的前置门禁（预期：是——写成明确判断）
- **额外注意**：ACP 化后 -p 模式（PtmuxDevinBackend）仍在（过渡期/回退），sim 要能
  同时测两种后端——评估双后端剧本的组织方式

### 任务 4：报告 `dev-docs/044-tmux依赖体系影响面与sim适配评估.md` + commit

报告含 §任务 1 清单全表 / §任务 2 三件套专节 / §任务 3 sim 评估 / "给 V 系列的
输入"小节（哪些 V 包消费哪些行）。

## 5. 禁止事项

- ❌ 只读调查——零代码改动（报告+可能的注释级建议都在报告里，不动代码）
- ❌ 清单不许有"等等/类似"——每个点真实读到函数（设计者底料只是起点，你逐点验证）
- ❌ 不要在本包设计解决方案细节（"等价物"写到位即可，实现方案是 U4/V 系列的）

## 6. 验收 checklist

- [ ] 影响面清单 ≥25 行，每行五列齐全（抽查 3 行我能对到代码）
- [ ] 四层分类（启动/存活/清理/列举）各有归属
- [ ] 三件套等价物专节存在，错误模式检测留 U5 接口标注
- [ ] sim 评估有工作量估计+前置性判断+双后端测试组织建议
- [ ] 044 报告 + "给 V 系列输入"小节
- [ ] 零代码改动（git status 证据）

## 7. 完成汇报要求

执行记录：清单行数统计、与设计者底料的差异（漏了/多出的点）、sim 结论。

## 8. 审计对照

1. 我会随机抽清单 5 行对到源码验证（文件:函数:行为三对）
2. 底料里 70+ 调用点 vs 你的清单行数——遗漏检查（如 watchdog 脚本/control 的
   clean-done 是否入表）
3. sim 评估的"前置门禁"判断与铁律 12 一致
