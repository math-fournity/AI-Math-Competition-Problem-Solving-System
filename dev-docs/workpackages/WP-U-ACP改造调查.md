# WP-U — ACP 管线改造调查【已废止——由 U1~U8 系列取代】

> ⚠️ **本文档已于 2026-08-21 废止**：037（双 ACP 管线策略）将本包范围（034 的 8 项 +
> 036 的 3 项）与双管线新范围（037 的 9-13 项）重组为 **WP-U1~U8 八个包**（见总控
> README §二）。本文件保留作为历史痕迹（痕迹保留铁律），**不要再按本文档执行**。
> 本文档中仍然有效的内容（内容完整性前置实验设计、tmux 影响面方法、红线约束）已
> 分别并入 WP-U2 / WP-U3 / 各 U 包的禁止事项。

> **优先级**: 线 2（与线 1 全部 WP 并行；**不动任何生产代码**）
> **依赖**: 无（自包含；035 实测资产已就位）
> **预计规模**: 调查报告 1 份（dev-docs/041）+ 1 个前置实验脚本 + 可能的对比数据
> **性质**: 调查 + 实验。**本 WP 的红线：除实验产生的数据文件外，不改 src/monitoring/
> scripts 的任何生产代码**

---

## 0. 给执行 AI 的第一句话

ACP（Agent Client Protocol，`devin acp`，JSON-RPC over stdio）可能是本系统管线层的
下一次大升级：`agent_thought_chunk` 等信号实时流式推送，能解决 -p 模式下"thinking
期间无任何实时落盘数据"的死局（035 已实测信号存在性）。但 036 审计发现改造方案有
一个**未探明的分叉**：ACP 推送的 thinking 内容是否完整（实测样本只有 22 个单词级
分片，而 --export 的 reasoning_content 动辄几千字符）——它决定 ACP 是"全面替代 -p"
还是"只做检测层"。你的任务：先做前置实验探明分叉，再完成全面影响面调查，产出一份
用户可以直接据此做决策的报告。

## 1. 背景（为什么）

- 030 需求（034 §七承载）：用户提出 session.db 快照检测 thinking spin + 提示词等待
  标记——经 034 四轮实测两个方案都不可行（-p 模式 session.db 退出才落盘、pane 无
  TUI 渲染内容）→ 用户提出调研 ACP → 035 实测信号可行
- 036 审计对 035/034 的三个核心修正（你必须内化）：
  1. **检测 ≠ 采集**：信号存在性已验证（卡死检测够用）；内容完整性未验证
     （trajectory 采集/组装 conversation.json 存疑）——你的前置实验就是补这个
  2. **035 §六 是初版遗留**（"不建议推进、先做方案2"与 §四/§七"首选 ACP、放弃方案2"
     矛盾）——你以 §四/§七 为准
  3. **WP-U 范围补 3 项**（036 §四.2）：0.5 内容完整性前置实验、0 sim 适配、
     1 扩为 tmux 依赖体系全量影响面
- WP-T.1/T.4（ACP 信号检测、SOP 信号停滞检查）依赖本 WP 的结论——你的报告是它们
  的设计输入

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `dev-docs/035-ACP模式调研与检测方案对比.md` **全文** | ACP 协议要点（v1 差异/sessionCapabilities/自定义通知/权限响应格式）、实测数据、集成路线图、§六 矛盾段（知其弃用） |
| 2 | `scripts/test_acp_signals.py`（399 行，已验证） | ACP 客户端工作代码——你的前置实验基于它改 |
| 3 | `dev-docs/036-对034-035的审计.md` §三.3/§四.2（60 行） | 前置实验的设计要求；范围 3 补项的原文 |
| 4 | `src/continuation_launcher.py` + `src/proof_audit_launcher.py`（launcher 全貌） | 现有 -p+tmux 架构（你要逐点列改造影响） |
| 5 | `src/sim/` 目录 + `dev-docs/017`（选读使用节） | sim 发布门禁机制 + fake_devin 的结构（范围 0 的评估对象） |
| 6 | `src/session_registry.py`（465 行，重点 tmux_alive 相关）+ `monitoring/continuation_control.py`（sessions/stop 逻辑）+ `scripts/continuation_watchdog.sh` | 范围 1 的 tmux 依赖体系清单素材 |
| 7 | `scripts/sop/checks.py` 的 tmux 相关检查（grep tmux）+ `docs/specs/p27_monitor_spec.md` §A13 | A13 四源一致的 tmux 源——ACP 化后的重构对象 |
| 8 | `dev-docs/034` §七 WP-U 段 | 034 版的 8 点调查范围（你的 2-8 项来源） |
| 9 | `AGENTS.md` 资产保留铁律段 | 范围 7（tmux_pipe.log 地位变化）的约束 |
| 10 | `/tmp/acp_test*.jsonl`（5 个实测日志） | 实测数据原始形态（thought chunk 是单词级分片的证据） |

## 3. 现场事实基线（2026-08-21 09:30）

- `devin acp` 存在且实测通过（v1 协议、protocolVersion: 1、sessionCapabilities 无 close）
- `test_acp_signals.py` 399 行可跑；5 个 jsonl 日志在 /tmp
- √2 实测：22 个 thought_chunk（单词级，~1 秒）+ 754 message_chunk + 权限处理通过
- 本 repo 所有 devin 启动都是 `-p` 模式（continuation_launcher/proof_audit_launcher/
  平凡系统 solver_harness）+ tmux 承载
- ACP 模式的三个已知缺口（035）：无 --export（需组装）、权限需 client 处理、
  session/close 不支持（cancel+杀进程替代）
- 复核：`ls scripts/test_acp_signals.py /tmp/acp_test*.jsonl`

## 4. 任务分解

### 任务 0.5（第一步，分叉探明）：ACP 内容完整性前置实验

**设计**：
1. 选一道真实的、thinking 很长的数学题（从 problem_list.json 或已有续传题中选一道
   之前 rc（reasoning_content）很大的题——查 DB rounds_log 的截断 reason 或选难题）
2. 同题双跑：
   - A 路：`test_acp_signals.py` 改造版（或新脚本 `scripts/test_wp_u_acp_vs_export.py`）——
     ACP 模式跑同题，收集全部 agent_thought_chunk/agent_message_chunk，拼接，
     落盘 `tmp/wp_u_acp_run.jsonl`
   - B 路：同题用 `-p --export` 跑一次（prompt 一致），得到 conversation.json
3. 对比指标（全部落报告）：
   - thought 拼接总字符数 vs export 的 reasoning_content 字符数（每 agent step）
   - message 拼接 vs message 内容
   - thinking 时长覆盖：thought_chunk 的时间跨度 vs export 各 step 时间戳
   - 若 ACP 有 thinking level 配置（035 提到 opt+t cycle thinking levels——查
     `config_option_update` 通知里有无 thinking level 选项）：测高/低两档对比
4. **结论三分支**（写明数据支撑哪个）：
   - 完整（同量级 ≥80%）：全面 ACP 化可行（WP-U.4 组装成立）
   - 部分（20-80%）：ACP 做检测+实时状态，trajectory 仍靠 --export（混合架构）或
     查 devin cli 有无完整推送的开关
   - 碎片（<20%）：ACP 只做卡死检测层（WP-T.1 用），管线上全面改造不成立

**红线**：实验脚本是新文件（scripts/test_wp_u_*），不 import 进生产代码；B 路的 -p
跑放 tmux（长命令铁律）；实验消耗 API 配额——两路各一题，总开销可控（记录 token 用量）。

### 任务 0：sim 适配影响面（硬依赖评估）

- 读 `src/sim/` 的结构（fake_devin 的角色机制/剧本格式/断言器 assert_final.py）
- 评估：ACP 化后 fake_devin 需变成"ACP server 剧本演员"（stdin/stdout JSON-RPC 按剧
  本吐通知）——工作量估计、剧本可否复用、断言器改哪些
- 结论：sim 适配是 ACP 改造的前置门禁（铁律 12）还是可并行——给出判断依据

### 任务 1：tmux 依赖体系全量影响面清单

grep + 读代码，列出**所有依赖 tmux 存在性的代码点**（文件/函数/行为），逐点写 ACP 化
后的等价物或废弃方式：
- session_registry：tmux_alive/一致性检查
- A13 四源一致（tmux 源）→ ACP 后的新源集（ACP 进程数？subprocess 句柄表？）
- continuation_control：sessions 管理/stop 的 kill-session 语义
- watchdog 脚本的检查目标
- 门闸 resource="tmux" 的 kill_session（GATE-KILL-SESSION/GATE-AUDIT-KILL-SESSION）
- SOP 检查的 tmux has-session/孤儿对账（check_07 项 7）
- launcher 的 sleep 999999+DONE.md 模式 → ACP 的 session/prompt response+进程退出
- E2 的 pane 查看语义（ACP 后无 pane——调试入口变成通知日志）

### 任务 2-8：034 版调查范围（原文要点 + 036 修正）

2. ACP 客户端库设计（从 test_acp_signals.py 提取 acp_client.py 的设计：连接/重连/
   通知分发/超时——**只设计不实现**）
3. launcher 改造方案（continuation/proof_audit 逐个：subprocess 生命周期/并发模型
   ——多 ACP server 进程 vs 单 server 多 session，035 §5.4 有初步分析，验证之）
4. --export 替代（依赖任务 0.5 结论：组装格式对 ATIF 的一致性方案 / 或保留 -p 混跑）
5. 权限处理（对应 --permission-mode dangerous 的自动批准策略+按 kind 精细批准+日志）
6. noninteractive-solver-run rule 更新（找到该 rule 文件位置——grep .devin/rules/）
7. 资产保留影响（tmux_pipe.log 消失→ACP 通知日志是否成为新保留资产——对齐铁律表）
8. 渐进式 vs 一步到位（推荐顺序+每步回退方案——035 §4.3 路线图为基底，按 0.5 结论修订）

### 任务 9：写报告 `dev-docs/041-ACP管线改造调查报告.md`

结构：
```
0. 执行摘要（三分支结论 + 推荐 + 总工作量 + 风险 top3）
1. 前置实验（任务 0.5 全数据：双路对比表、结论分支判定）
2. sim 适配（任务 0）
3. tmux 依赖体系影响面清单（任务 1 全表）
4. 8 点调查（任务 2-8）
5. 工作量分解（按 035 路线图修订——每项行数估计+依赖）
6. 风险清单与回退方案
7. 推荐路径（渐进式顺序）与决策点清单（哪些要用户拍板）
```

### 任务 10：commit（实验脚本 + tmp 数据不 commit（tmp 已 ignore 则放 tmp/）+ 报告）

## 5. 禁止事项

- ❌ **不改任何生产代码**（src/monitoring/scripts 的现有文件——实验脚本是新文件）
- ❌ 前置实验不跑超过 2 题 ×2 路（配额纪律；题目选 thinking 长的）
- ❌ 报告不给"拍脑袋行数"——每个估计注明依据（035 路线图/实测/类比现有代码规模）
- ❌ 不把 035 §六 的弃用结论带进报告（以 §四/§七 为准——036 修正）
- ❌ 不在报告里替用户做"是否改造"的最终决策——给推荐+决策点

## 6. 验收 checklist

- [ ] 前置实验双路数据表存在（字符数/时长/覆盖率三个指标）+ 分支结论明确
- [ ] tmux 依赖体系清单 ≥8 个代码点（文件+函数+ACP 等价物）
- [ ] sim 适配有工作量估计与前置性判断
- [ ] 8 点调查逐点有内容（无"略"/"同上"）
- [ ] 工作量表（行数+依据）、风险表、回退方案、推荐顺序、决策点清单齐全
- [ ] `git status` 确认生产代码零改动（只有新实验脚本+报告）
- [ ] 041 报告 commit

## 7. 完成汇报要求

执行记录：实验的题目选择依据、token 消耗、双路原始数据文件路径、报告要点摘要
（三分支结论+推荐）。

## 8. 审计对照

1. 前置实验我会复算：读你的双路数据文件，核对字符数对比与结论分支自洽
   （这是整个 ACP 方向的地基——数据不扎实全盘皆输）
2. tmux 影响面清单我会 grep 抽查 3 个点（有没有漏——比如 watchdog/observability 的
   session_name 维度）
3. 生产代码零改动的 git 证据
4. 报告的推荐与 0.5 结论一致（不自相矛盾——035 犯过的错）
