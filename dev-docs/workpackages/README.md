# 工作包总控 — 030~037 审计链收敛后的最终执行体系（v2）

> **历史工作包警示（2026-08-22）**：本目录记录 031~056 阶段的修复和 ACP 调查，已完成
> 资产继续有效；但用户随后更新了无限 Round、充分形式化验证、key capacity/lease、最大
> 并发30和 Master Agent stuck 监督等目标。未来实现不要继续从本目录领取未完成 V/R2 包，
> 应转到 `dev-docs/final-system-workpackages/README.md`。最终目标见 057~064；当前差距见064。

> **执行 AI 从这里开始**：`00-START-HERE-执行AI完整提示词.md`（本目录）是完整启动
> 提示词——含四阶段认知装载清单/执行纪律/工作记录规约（审计契约）/拍板闸门/红线。
> 本文档是它的第一节必读物（工作宪法）；两份配合使用。

> **创建**: 2026-08-21（036 审计完成后）；**v2**: 同日 037 双管线策略后的线 2 重构
> **读者**: 执行 AI（每个工作包开一个新会话执行，按本文档顺序领取）
> **审计**: 用户将在全部完成后指派 031/033/036 作者（审计链同一 AI）全盘审计执行结果
> **事实基线时间**: 2026-08-21 10:10。行号会随后续工作包改变代码而漂移——**一律以
> 函数名/关键字 grep 定位，行号仅供参考**。

---

## 一、这套工作包从哪来（30 秒背景，不加载其他文档也够用）

030（用户对审计系统 WP-1~9 实现的 8 条质疑）→ 031（核查修正方案）→ 032（对 031 审计
+ 用户新增两条硬约束：适度依赖 Master Agent 介入 / 资产保留铁律）→ 033（对 032 审计，
发现 partial proof 删除漏洞）→ 034（对 033 审计 + 用户 thinking 检测需求 → ACP）→
035（ACP 调研实测）→ 036（对 034/035 审计，最终裁定）→ **037（用户策略：双 ACP 管线
——OpenCode ACP 默认 + Devin ACP 备用，线 2 因此重构为 U/V 两系列）**。

**本目录每个 WP-*.md 是自包含执行文档**——不需要读审计链全文。需要的外部认知在每个
文档的"前置认知加载清单"里精确列出。

> **2026-08-21 补充（038 §八/§九）**：OpenCode 有原生 export 机制（ACP session
> 落盘 SQLite 同构可导，实测）；截断检测按"协议原生主信号 + 结构启发式兜底"分层。
> 已落入 WP-U2（任务 6 + export 对照）/U4（接口 finish_reason + 适配层 7/8 点）/
> U5/V1/V3——执行这些包的 AI 以更新后的文档为准。

> **2026-08-21 用户裁定（执行顺序与并发）**：
> ① **后续所有工作包 OpenCode ACP 优先**——先让未来的系统在 OpenCode ACP 侧跑起来，
>   Devin 侧推后（U 系列内 U5 先于 U7、V 系列 V4 先于 V5；U2 的 C 路先于 B 路出数据）。
> ② **并发数值由用户定**——AI 不做推荐实验（WP-G 任务 3 据此提前终止，见 dev-docs/051）；
>   系统解决问题能力优先于参数寻优，无论数值多少，异常处置能力是前提。

## 二、执行顺序与依赖图（v2）

> 编号说明：线 1 沿用 031~036 的最终裁定（无 WP-M/O/T 独立包——M 并入 WP-J，O 未占用，
> T.1 检测逻辑已并入 V1/V4，T.2/T.3 降级可选见 036 §四.1）。原《WP-U-ACP改造调查.md》
> **已废止**（文件保留加废止头，痕迹保留），由 U1~U8 取代。

```
━━━ 线 1：-p 模式修复与治理（与线 2 完全并行，不等任何 U/V 包）━━━

第一批（机制修正，串行）：
  WP-N（PARSE_ERROR 修复）──→ WP-P（现场补救）
                              └→ WP-H（审计优雅停止+收尾即收集）
                              └→ WP-G（并发治理；实验项在 WP-P 后跑）

第二批（可并行）：
  WP-A（审计门控 docstring）  WP-B（直接检查铁律 rule）  WP-S（资产保留，项1优先）
  WP-I（共享终态检测模块）──┬→ WP-J（审计终态补全）
                           └→ WP-K（续传终态补全）
                              WP-J+K ──→ WP-L（自动重试，dry-run 先行）
  WP-R（审计 prompt 双份渲染，独立小包）

第三批（SOP 链，依赖一二批）：
  WP-C（SOP_07 新 STEP）──→ WP-D（SOP_01 精简）
                        └→ WP-E（SOP_04 升级）
  WP-N ──→ WP-Q（审计 alert 清单对齐）
  最后：WP-F（线 1 全量文档同步）

━━━ 线 2：双 ACP 管线（U 调查系列 → 用户批准 049 → V 实现系列）━━━

U 系列（调查，不动生产代码；U2~U7 在 U1 后可部分并行）：
  WP-U1（ACP 能力基线复验）
    ├→ WP-U2（内容完整性三路对比——分叉判定）──┐
    ├→ WP-U3（tmux 影响面 + sim 适配）─────────┤
    │    WP-U2+U3 ──→ WP-U4（双管线架构设计）──┤（U4 消费 U2/U3）
    ├→ WP-U5（OpenCode 管线详设）←── U4 参数位协同
    ├→ WP-U6（Ox Alpha 数学能力评估）
    └→ WP-U7（Devin 备用管线 + 切换回退）
         U1~U7 全部 ──→ WP-U8（总报告 049 + V 系列任务书 + 决策点清单）

  ★ 用户拍板 049 的决策点（≥5 项：Ox Alpha 默认与否/分叉跟随/auto-fallback/-p 存续期/
    V 系列投入节奏）——V 系列不得在此之前启动

V 系列（实现；顺序即依赖链）：
  WP-V1（ACP 客户端库）──→ WP-V2（sim ACP 化·门禁前置）──→ WP-V3（launcher 后端抽象
  重构·行为零变化）──→ WP-V4（OpenCode 后端接入·不切默认）──→ WP-V5（Devin 备用
  + 回退机制）──→ WP-V6（检查/门闸/监控/文档全量适配）──→ WP-V7（端到端验证 +
  灰度阶梯 + 默认切换[需再次拍板] + 回退演练）
```

**线间关系**：线 2 的 V3 重构基于线 1 完成后的 launcher 形态（WP-H/J/K/L/S 已落地）——
**V3 启动前核对线 1 相关包全部完成**；U 系列与线 1 无依赖可先行。

**单会话领取规则**：一次只做一个 WP。做完 → 勾本文档 §四状态表 → 写执行记录 →
git commit（显式路径 add）→ 领下一个。

## 三、全局铁律（每个工作包都适用，违反=审计不通过）

1. **git 显式路径 add**——禁止 `git add -A` / `.` / `-u`
2. **改代码必须同步更新第一级文档**（docs/architecture / docs/specs / docs/sop/
   SYSTEM_CLOSURE.md）——各 WP 文档的"文档同步"节列了具体清单
3. **绝不 kill 无 DONE.md 的 session**（dead_session 判定分支是唯一例外；ACP 后端的
   等价物语义见 V3/V4）
4. **长时间命令用 tmux**——ACP 时代的长命令（灰度批次/长实验）同样适用
5. **禁止 inline 脚本**——超过 3 行的逻辑写成文件放 scripts/
6. **人话铁律**——文档/回复/注释/commit message 用人话
7. **DB-文件双向可追溯 / 痕迹保留**——操作写 WORKLOG.md，alert 入 ArangoDB
8. **改调度/判定逻辑后跑 sim 发布门禁**（线 2 的门禁在 V2 就位，V3 起强制）
9. **禁止代码写死并发数**（V 系列扩展：静默窗口/模型名/backend 同样从 DB/配置读，
   不写死——WP-G 是本条的第一批落地）
10. **适度依赖 Master Agent 介入**——可靠判定（确定性函数可单测）进代码；语义判断
    标"待人工"+alert。边界判据："能否写成确定性函数并单测覆盖？"
11. **解题运行结果资产保留**——任何 round 产出不删（唯一例外见 WP-S 的 partial
    归档逻辑）；ACP 时代新增的**通知日志 jsonl 同为资产**（V1/V4 落地）
12. **py_compile 每个改动的 .py**；测试脚本放 scripts/test_*.py
13. **判断系统状态必须直接查证**（硬盘/tmux/进程/通知日志实物），不能只看 DB/Redis
14. **线 2 红线**：U 系列（U1~U8）不动任何生产代码；V 系列的默认后端切换（V7）与
    auto-fallback 启用（V5）都是用户拍板项——AI 只准备数据与机制
15. **opencode acp 必须显式设置模型与推理强度，并经 ACP 接口回显确认（脚本执行，
    fail-fast）**——session/new 后立即 `session/set_config_option` 两步：
    configId:"model" → 断言响应回显 currentValue == 目标模型；configId:"effort"
    → 设 max 并断言。实测依据：不显式选择落到内建 big-pickle、ox-alpha effort
    默认 low（opencode-acp-protocol skill §3.8 / 042 勘误节 /
    scripts/probe_acp_model_config.py）。devin 侧对应：启动必须 `--model`
    （强度无开关——工具事实，见 ~/.devin/rules/explicit-model-and-effort.md）

## 四、状态跟踪表（执行 AI 填写，审计依据之一）

| WP | 文档 | 状态 | 执行者 | 完成时间 | commit | 执行记录 |
|---|---|---|---|---|---|---|
| **线 1** | | | | | | |
| WP-N | WP-N-PARSE-ERROR修复.md | ✅ 完成 | Devin | 2026-08-21 | d9c59f0 | exec-log/WP-N-执行记录.md |
| WP-P | WP-P-现场补救.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | a4c436b+见exec-log | exec-log/WP-P-执行记录.md（含收集器解析bug修复+差1根因报告） |
| WP-H | WP-H-审计优雅停止.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-H-执行记录.md（集成测试五断言全过） |
| WP-G | WP-G-并发治理.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-G-执行记录.md（实验按用户裁定终止，051留档） |
| WP-A | WP-A-门控docstring重写.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-A-执行记录.md（4门闸5/5段标识+DB注册验证通过） |
| WP-B | WP-B-直接检查铁律rule.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 9c37209 | exec-log/WP-B-执行记录.md（rule 46行+AGENTS.md双rule引用） |
| WP-S | WP-S-资产保留.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-S-执行记录.md（六项全做；盘点报告050：export缺45%/handover缺92%） |
| WP-I | WP-I-共享终态检测模块.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-I-执行记录.md（模块+单测39PASS+re-export兼容层） |
| WP-J | WP-J-审计终态补全.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-J-执行记录.md（四类检测+超时改名+误伤检查10样本零命中） |
| WP-K | WP-K-续传终态补全.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 0d32dbb | exec-log/WP-K-执行记录.md（ai_gave_up分支+sim门禁8断言过） |
| WP-L | WP-L-基础设施失败自动重试.md | ✅ 完成（dry-run阶段；--once待批准） | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-L-执行记录.md（报告052：7 infra候选+23 model留存） |
| WP-C | WP-C-SOP07新STEP.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-C-执行记录.md（9步循环上线；端到端真跑8项全绿+PARSE_ERROR=1待人工） |
| WP-D | WP-D-SOP01精简.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | d7e2c7e | exec-log/WP-D-执行记录.md（A16/A17移交+completed抽样直接检查落地） |
| WP-E | WP-E-SOP04升级.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-E-执行记录.md（四步复核法+回退链+--scope audit实测；C7-C8文档补全） |
| WP-Q | WP-Q-审计alert清单对齐.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | dc044ab | exec-log/WP-Q-执行记录.md（6种→2 DB alert+3 SOP提示+删1） |
| WP-F | WP-F-文档同步.md | ☐ 未开始 | | | | |
| WP-R | WP-R-审计prompt双份渲染.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-R-执行记录.md（audit_prompt.txt分离+冒烟全过） |
| **线 2·U 系列（调查）** | | | | | | |
| WP-U1 | WP-U1-ACP能力基线复验.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | c310171/b211945 | exec-log/WP-U1-执行记录.md（含跑错模型勘误弧线，042 勘误节为准） |
| WP-U2 | WP-U2-内容完整性三路对比.md | ✅ 完成（B路推迟） | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-U2-执行记录.md（C路组装100%无损；报告043） |
| WP-U3 | WP-U3-tmux依赖影响面与sim适配.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-U3-执行记录.md（报告044：35行影响面清单+sim 470行评估） |
| WP-U4 | WP-U4-双管线架构设计.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-U4-执行记录.md（045：接口+8点适配+切换机制+三方案对比） |
| WP-U5 | WP-U5-OpenCode管线详细设计.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-U5-执行记录.md（报告046：response驱动完成检测+注入实测+错误三层；配额2/3） |
| WP-U6 | WP-U6-OxAlpha数学能力评估.md | ✅ 完成 | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-U6-执行记录.md（报告047：续传收敛实证，有条件可作默认） |
| WP-U7 | WP-U7-Devin备用管线与切换回退.md | ✅ 完成（纯设计） | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-U7-执行记录.md（报告048：三态健康+事件表+演练设计） |
| WP-U8 | WP-U8-双管线调查总报告.md | ✅ 完成（停等拍板049） | Claude(ox-alpha) | 2026-08-21 | 见exec-log | exec-log/WP-U8-执行记录.md（049+决策点D1-D7待拍板） |
| ★ 用户拍板 049 决策点 | （V 系列启动闸门） | ☐ 待用户 | — | — | — | 用户回复记录 |
| **线 2·V 系列（实现，框架版文档·待 U8 填实槽位）** | | | | | | |
| WP-V1 | WP-V1-【U8任务书已填实】ACP客户端库.md | ☐ 未开始 | | | | |
| WP-V2 | WP-V2-【U8任务书已填实】sim-ACP化.md | ☐ 未开始 | | | | |
| WP-V3 | WP-V3-【U8任务书已填实】执行后端抽象重构.md | ☐ 未开始 | | | | |
| WP-V4 | WP-V4-【U8任务书已填实】OpenCode后端接入.md | ☐ 未开始 | | | | |
| WP-V5 | WP-V5-【U8任务书已填实】Devin备用与回退机制.md | ☐ 未开始 | | | | |
| WP-V6 | WP-V6-【U8任务书已填实】检查门闸监控文档适配.md | ☐ 未开始 | | | | |
| WP-V7 | WP-V7-【U8任务书已填实】端到端验证与灰度切换.md | ☐ 未开始 | | | | |
| ~~WP-U（旧）~~ | WP-U-ACP改造调查.md | **已废止**（U1~U8 取代） | — | — | — | — |

执行记录统一写到 `dev-docs/workpackages/exec-log/WP-{X}-执行记录.md`（模板：
做了什么/改了哪些文件/验证结果/遗留问题）。


> **🔴 当前状态：线 2 调查全部完成（U1-U8），停在 049 决策点闸门——等待用户对 D1-D7 拍板后方可启动 V 系列。**

## 五、执行 AI 的会话启动 checklist（每个 WP 通用）

```
1. 读 dev-docs/workpackages/README.md（本文档）
2. 读自己的 WP-*.md 全文（V 系列注意"框架版"说明——先确认 U8 已填实槽位）
3. 按 WP 文档"前置认知加载清单"逐项加载（文档/代码/DB 查询）
4. 复核"现场事实基线"——用文档给的命令重新查一遍；若基线已变（前序 WP 改动所致），
   按 WP 文档"基线漂移预期"节调整理解；若出现文档没预期的漂移，停下来报告用户
5. 按"任务分解"执行，逐项对照"禁止事项"
6. 填"验收 checklist"（逐项勾选+贴验证输出）
7. 写执行记录 + 填总控状态表 + git commit（显式路径）
8. 汇报：本 WP 完成、验收结果、下一 WP 是什么
```

## 六、设计者留给审计的话（执行 AI 也应读——这是验收标准的精神）

这批工作包的设计遵循三条用户级洞察（030~037 链的收敛结论）：

1. **直接检查**——所有 SOP/监控检查必须看到最底层（028 教训）。本批工作包多处要求
   "查 DB + 查文件交叉验证"。
2. **适度依赖 Master Agent**——代码只做可靠判定（确定性模式匹配/超时/存在性），
   不可靠的标记待人工（PARSE_ERROR 语义、C7-C9 复核、**ACP 灰度门槛的达标判断**）。
3. **资产保留**——每个 round 的所有产出是资产；ACP 时代通知日志 jsonl 同为资产。

**037 双管线的三条设计立场**（V 系列的实现主线，执行 AI 不得偏离）：
- **执行后端抽象**——launcher 业务逻辑不动，-p/OpenCode ACP/Devin ACP 三后端插同一
  接口（U4 验证此立场，V3 落地）
- **判定链复用**——ACP 后端必须产出 ATIF 同构 conversation.json 喂原生
  is_truncated/is_completed（U2 实验先行，V1 组装器落地）——不为 ACP 重写判定
- **切换的人机分工**——自动回退可代码化（默认关），切回与默认切换永远人工拍板

审计将按每个 WP 文档的"验收 checklist"逐项核对，并额外检查：有没有做文档没让做的
事（scope 蔓延）、有没有违反 §三全局铁律、commit 是否干净、V 系列是否越过了拍板
闸门（U8 前启动 V / V7 前无拍板切默认——**这两条是红线中的红线**）。
