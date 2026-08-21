# 044 — tmux 依赖体系影响面与 sim 适配评估（WP-U3）

> **创建时间**: 2026-08-21
> **执行者**: Claude (ox-alpha, opencode)
> **性质**: 只读调查，零代码改动。V 系列所有包的公共输入。
> **复核口径**: 设计者底料（70+ 提及）经全量 grep 复核为 **28 个文件、~250 处提及、
> 功能性调用点 40 处**——本报告逐点入表（含底料遗漏的 6 个文件）。

---

## 一、影响面总览

tmux 在本系统是**进程管理底座**：启动、存活判定、日志管道、清理、并发计数、
一致性审计全部踩在上面。ACP 化后其角色由 **subprocess 句柄（Popen）+ 通知流 +
注册表新字段** 接管。以下清单按四层组织，改造类型分类：
**重写** / **等价替换** / **源重定义** / **语义保留+查法更新** / **消失**。

### 1.1 启动层（new-session / pipe-pane）

| # | 文件:函数 | tmux 用法 | 业务语义 | ACP 等价物 | 改造类型 |
|---|---|---|---|---|---|
| 1 | continuation_launcher:start_handover :593 | new-session -d | 启动 handover 进程（SIM_MODE 时换 fake_devin） | backend.start() → Popen(acp server) | 重写 |
| 2 | continuation_launcher:launch_solve :729 | new-session -d | 启动解题进程 | 同上 | 重写 |
| 3 | continuation_launcher:launch_solve :733 | pipe-pane | stdout 实时落盘 tmux_pipe.log | 通知流实时写 jsonl（铁律11 资产） | 消失→新形态 |
| 4 | proof_audit_launcher:audit_launch :167 | new-session -d | 启动审计进程 | backend.start() | 重写 |
| 5 | proof_audit_launcher:audit_launch :171 | pipe-pane | 审计日志管道 | 同 #3 | 消失→新形态 |
| 6 | continuation_control:start_service :159 | new-session -d | 启动 launcher/monitor 服务进程 | **保留**（服务编排仍用 tmux，非 agent 会话） | 语义保留 |

### 1.2 存活层（has-session / capture-pane）

| # | 文件:函数 | tmux 用法 | 业务语义 | ACP 等价物 | 改造类型 |
|---|---|---|---|---|---|
| 7 | continuation_launcher:tmux_running :110 | has-session | 进程存活判定 | handle.proc.poll() is None | 等价替换 |
| 8 | continuation_launcher:pane_text :119 | capture-pane | pane 文本（错误模式/stall 检测源） | 通知流内容（错误形态实测=U5 接口位） | 源重定义 |
| 9 | proof_audit_launcher:tmux_running :64 | has-session | 审计存活 | proc.poll() | 等价替换 |
| 10 | proof_audit_launcher:tmux_pane_text :85 | capture-pane | 审计完成标记辅助检查 | COMPLETE 标记在通知流/export 中查 | 源重定义 |
| 11 | session_registry:_tmux_has_session :43 | has-session | 注册表 alive 心跳底层 | 注册表新增 acp_alive 字段或 poll 句柄引用 | 字段语义改名 |
| 12 | monitor_continuation:check_zombie_sessions :454-463 | list-sessions + capture-pane | 空 pane 僵尸检测（<3 行输出） | ACP 后无 pane——等价物="有进程但 N 分钟零通知"（复用 spin 检测） | 源重定义 |

### 1.3 清理层（kill-session）

| # | 文件:函数 | tmux 用法 | 业务语义 | ACP 等价物 | 改造类型 |
|---|---|---|---|---|---|
| 13 | continuation_launcher:kill_session(GATE-KILL-SESSION) :128 | kill-session | 不可逆终止（过门闸） | proc.terminate()→宽限→kill()（门闸 resource 名改 process 或兼容保留） | 语义保留+查法更新 |
| 14 | continuation_launcher:stop_batch(force) :1955-1959 | list+kill 全部 p27- | 强制清场 | 遍历 BackendHandle 表 terminate；服务 tmux 不在此列 | 等价替换 |
| 15 | proof_audit_launcher:tmux_kill/audit_kill_session :75 | kill-session | 审计终止门闸 | 同 #13 | 语义保留+查法更新 |
| 16 | proof_audit_launcher:stop_audit_batch(force) :554 | list+kill paudit- | 审计强制清场 | 同 #14 | 等价替换 |
| 17 | session_registry:clean_session :399 | kill-session | Master Agent 清 stuck/done | terminate（经后端句柄；跨进程重启后句柄丢失→需 PID 记录进注册表） | 等价替换+注册表加字段 |
| 18 | continuation_control:stop_service :192 | kill-session | 停服务 tmux | **保留**（服务层） | 语义保留 |
| 19 | continuation_control:force 清场循环 :309 | list+kill p27- | --force 清 agent session | 同 #14 | 等价替换 |
| 20 | continuation_control:stop_watchdog :129 | kill-session | 停 watchdog 服务 | **保留**（服务层） | 语义保留 |
| 21 | sim/teardown :53 | kill-session 含 batch_id | 清 sim 残留 | ACP 后端模式：无 session 可杀→改为检查并 terminate 残留子进程（或断言本就无残留） | 等价替换（双后端条件化） |

### 1.4 列举层（list-sessions）

| # | 文件:函数 | tmux 用法 | 业务语义 | ACP 等价物 | 改造类型 |
|---|---|---|---|---|---|
| 22 | session_registry:_list_tmux_p27_sessions :57 | list-sessions 过滤 p27- | 孤儿/未注册对账的数据源 | 注册表自身成为唯一事实源（ACP 会话由 launcher 创建即注册）；孤儿=注册表有但进程表无 | 源重定义 |
| 23 | monitor_continuation:_tmux_p27_sessions :203 | list-sessions | A1/A13 的 tmux 实际数 | 四源重定义：tmux 源→**launcher 进程表/注册表 acp 字段**（按 solve/handover/audit 类型拆分的思路保留） | 源重定义 |
| 24 | monitor_check_continuation.sh :110,269 | list-sessions 计数/grep | 外部巡检脚本 | 同上（脚本版同步改） | 源重定义 |
| 25 | continuation_control:sessions cmd :81(+capture :94) | list+capture | sessions 管理/一致性检查 | 读注册表 acp 字段；capture 改读通知 jsonl 尾部 | 源重定义 |
| 26 | sim/assert_final:check_tmux :160 | tmux ls 查残留 | sim 断言#4 | 双后端条件化：ptmux 模式查 session 残留；acp 模式查子进程/端口残留 | 等价替换（双后端） |
| 27 | continuation_watchdog.sh :52-54,76 | has/new/list | 服务自动重启守护 | **保留**（守护的是服务 session，非 agent 会话）；:76 的 p27- 计数改读注册表 | 部分保留+源重定义 |
| 28 | sop/deep_checks_02.py :72 | list-sessions | SOP 深检的会话盘点 | 同 #23 口径 | 源重定义 |

### 1.5 语义耦合（无直接命令但强绑定 tmux 存在性）

| # | 位置 | 耦合点 | ACP 等价物 | 改造类型 |
|---|---|---|---|---|
| 29 | 两 launcher 的 E2 设计（sleep 999999 保 pane 可查） | devin 退出后靠 tmux session 留尸体 | **消失**——ACP 子进程随退出消亡，尸检靠 jsonl+export | 消失 |
| 30 | stall 检测 pane_hash 追踪（running 检查段） | capture-pane 内容哈希判无活动 | last_signal_ts（poll 维护）——U2 已实证 chunk 流的可用性 | 源重定义 |
| 31 | session_name 截断规则（paudit-{后30}） | 名字=进程身份 | backend 自生 sessionId（Devin 短名/OpenCode ses_长名）入注册表 | 字段语义改名 |
| 32 | observability log_flow 的 session_name 维度 | flow 按 session 名关联 | 新增 acp_session_id 维度（字段向后兼容：旧名仍在） | 兼容扩展 |
| 33 | DONE.md 三件套之一 | devin 退出标记文件 | prompt response 到达（Devin）/response 或静默窗口（OpenCode，end_turn≠成功见 043） | 源重定义 |
| 34 | export conversation.json | 判定链数据源 | 通知组装（U2 已证无损）+实时 jsonl+原生 export 兜底（须校验重试） | 源重定义 |
| 35 | A13 四源一致（tmux vs DB vs Redis vs 设定） | 失控检测核心 | 源集合变为：launcher 进程表 vs DB vs Redis vs 设定——**四源结构保留，换一个源** | 源重定义 |

## 二、DONE.md / export / pane 三件套专节（任务 2）

| 物理依据 | 现行语义 | ACP 等价物 | 备注 |
|---|---|---|---|
| DONE.md | devin 退出标记（exit code），completed≠成功（E1） | Devin：prompt response 到达即退出；OpenCode：response 或静默窗口兜底。**退出码语义由 stopReason 替代**——但 end_turn≠解出（043），成败分界移到组装后结构检查 | 049 决策点：是否保留 DONE.md 形态做跨后端统一标记（建议：保留为 launcher 写的派生标记，物理依据换源） |
| export conversation.json | 判定链权威数据源（ATIF） | 三层来源：通知组装（主，U2 证 100% 无损）/ opencode export（兜底，须 JSON 校验+重试）/ SQLite 直读（不作主路径）。**is_truncated/is_completed 吃同构 ATIF——判定链复用成立**（037 立场验证 ✅） | comp 取数路径变化：A 路 final_metrics / B 路 usage_update / C 路 response.usage.outputTokens |
| pane 文本 | 错误模式检测源（WP-J rate_limit 等）+ stall pane_hash + zombie 空pane | 通知流内容匹配（WP-I 模式跑在 message/thought 文本上）+ last_signal_ts + "有进程零通知"。**错误模式在 ACP 通知里的真实形态是 U5 实测点**——本表只锁接口 | WP-I 的 PATTERNS 直接复用，数据源换 |

## 三、sim 适配评估（任务 3，硬依赖判断）

### 3.1 现状架构

fake_devin 是被 launcher 在 tmux 里启动的**剧本演员**（SIM_MODE=1 时整体替换
devin 命令）：读 work_dir/sim_scenario.json → sleep(delay) → 按动作写真文件
（truncated_export/completed_export/proof.md/HANDOVER）→ 退出。下游一切判定
逻辑面对与生产相同的产物形态——这是 sim 的设计精髓：**演员只造产物，不改判定**。

### 3.2 ACP 化需求

fake_devin → **fake_acp_server**：stdin/stdout JSON-RPC 演员，按同一份剧本吐通知：

| 现行动作 | ACP 演员行为 |
|---|---|
| truncate（写截断态 export） | 流式推 N 个 thought_chunk（拼出 rc>阈值、msg=0）→ prompt response（stopReason=end_turn，复现 043 发现的真实形态） |
| complete | 流式推 thought+message（含 boxed）→ response(end_turn) |
| dead_session | 收到 prompt 后进程直接消失（模拟崩溃） |
| stall/spin | 流几个 chunk 后长时间静默（测 spin 检测） |
| handover:ok | 写 HANDOVER 文件后正常结束 |

关键优势：**ACP 演员能覆盖 -p 演员无法覆盖的场景**（真实截断信号形态、静默时序、
权限请求流）——sim 覆盖率反而提升。

### 3.3 工作量估计与前置性判断

| 项 | 估计 |
|---|---|
| fake_acp_server.py（JSON-RPC 骨架+5 动作） | ~250 行 |
| 剧本映射扩展（scenarios.py 双语义） | ~80 行 |
| assert_final 双后端条件化（tmux/子进程两套残留断言） | ~60 行 |
| teardown/setup 条件化 + run_sim 双后端接线 | ~80 行 |
| **合计** | **~470 行（框架估，U8 实数化）** |

**前置性判断：是硬前置（与铁律 12 一致）**——V3 重构的行为等价验证必须跑 sim 全剧本；
不先有 ACP 演员，V3/V4/V5/V7 的任何调度改动都无法过门禁。故 V2（sim ACP 化）
排在 V3 前（现依赖图已如此，本次评估确认该排序正确）。

### 3.4 双后端测试组织建议

- 剧本文件保持单一（sim_scenario.json 不分叉）——同一剧本喂两种演员
- run_sim 加 `--backend ptmux|acp` 旋钮（默认各跑一遍=全量门禁）
- assert_final 按 backend 选择残留断言集；DB/Redis/flow 断言双后端共用
- 隔离旋钮不变（ARANGO_DB 测试库 + PAUDIT/P27_REDIS_PREFIX）

## 四、给 V 系列的输入

| V 包 | 消费本报告哪些行 |
|---|---|
| V1（客户端库） | #29/32/33/34（E2 消失、jsonl 资产、DONE.md→response、export 三层）|
| V2（sim ACP 化） | §三全部（工作量基线 470 行 + 双后端组织）|
| V3（-p 抽象重构） | #1/2/7/8/13/14（启动与清理层的迁移边界）；#30（stall 检测去 pane_hash 化的接口位）|
| V4（OpenCode 接入） | #3/5（pipe-pane→jsonl）、#12（zombie 重定义）、§二三件套专节 |
| V5（Devin 备用） | #15/16、#33 的 Devin 分支（response 驱动）|
| V6（检查/监控适配） | #22/23/24/25/28/35（四源重定义全家桶）+ SOP_07 设计时引用 |
| V7（端到端） | §三双后端组织（灰度按 backend 分组断言）|

## 五、与设计者底料的差异

| 项 | 底料 | 复核实际 |
|---|---|---|
| continuation_launcher | 27 处提及 | 70 处提及/功能点约 12 个（多数是注释与 docstring 引用） |
| session_registry | 4 | 47 提及/功能点 4 个 ✓ |
| monitor_continuation | 3+ | 40 提及/功能点 4 个（A1/A13/zombie/A5 相邻）✓ |
| continuation_control | 16 | 40 提及/功能点 7 个 ✓ |
| **未入底料的文件** | — | deep_checks_02.py、export_new_problems.py、diag 脚本、test_016（测试/诊断类，前两个入表 #28，其余标注为非生产路径）|
