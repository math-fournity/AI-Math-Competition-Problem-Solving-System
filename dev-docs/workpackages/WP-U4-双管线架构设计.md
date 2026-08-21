# WP-U4 — 双管线架构设计（执行后端抽象 + 差异适配 + 选择机制）

> **优先级**: 线 2 核心（U2/U3 之后——消费两包结论）
> **依赖**: WP-U2（内容完整性分叉）、WP-U3（影响面清单）
> **预计规模**: 架构设计文档（045）
> **性质**: 设计（文档产出，零代码）

---

## 0. 给执行 AI 的第一句话

把 037 的双管线决策落成可实施的架构：**launcher 的业务逻辑不动，把"启动一个 agent
干活并产出可判定的 trajectory"抽象成执行后端（Execution Backend）接口**，三个实现
（-p+tmux 现有 / OpenCode ACP 默认 / Devin ACP 备用）插在同一接口下。你要定义接口、
适配层边界、选择与切换机制，并给出设计者预埋立场的验证或反驳。

## 1. 背景（为什么）

- 037 §2.1：双管线（OpenCode 默认 + Devin 备用）+ §5.3 线 1（-p 模式）过渡期继续跑
  ——实质是**三种执行后端并存**的架构问题
- 不抽象的直接改法（每个 launcher 写 if backend==opencode…）会让 2031 行的
  continuation_launcher 膨胀成不可维护的状态——差异点（完成检测/权限/session 管理/
  模型指定/错误信号）必须收敛在适配层
- 设计者预埋立场（036 §四.2 + 本批 U3）：业务逻辑（队列调度/并发槽/多轮续传/判定/
  门闸/优雅停止/收尾收集）与执行引擎（进程管理/协议交互/产物落地）解耦——**你要
  独立验证这个立场**，若有更优结构（如更彻底的管线重写）如实提出并给依据

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **WP-U2 报告 043**（分叉结论） | 两后端各自：trajectory 组装可行性 / 判定函数可运行性 |
| 2 | **WP-U3 报告 044**（影响面清单 + 三件套等价物 + sim 结论） | 后端接口要覆盖的全部差异点 |
| 3 | `src/continuation_launcher.py` **主循环通读**（launch_batch 的调度骨架 + launch_solve/start_handover 的启动 + running 检查段的判定） | 哪些是业务逻辑（保留）哪些是引擎逻辑（抽走）——分界的原始材料 |
| 4 | `src/proof_audit_launcher.py` 通读 | 第二个消费方——接口必须同时适配两个 launcher（避免为续传过拟合） |
| 5 | `dev-docs/037` §2.3（不变的部分）+ §四.9（双管线架构设计要求原文） | 用户决策已定死的不变量：ACP v1 信号同构/检测逻辑通用/max_runtime 兜底/默认 OpenCode |
| 6 | OpenCode skill §6（完成检测方案 A-D）+ Devin skill 的 response 语义 | 适配层最大的差异点素材 |
| 7 | `dev-docs/036` §四.2c（分叉对方案的影响） | 完整性分叉如何改变 V4/V5 的设计 |

## 3. 现场事实基线

- 判定链（is_truncated/is_completed/proof 检查）吃 ATIF 结构 steps[]——后端接口的
  产物契约 = conversation.json（ATIF）
- 并发模型不变：管线并发=agent 实例数（用户 030 需求 2 的模型，ACP 后是 ACP 子进程数）
- WP-G 后并发数唯一来源 DB batch——后端选择/切换的配置也应同源（DB batch 记录，
  不写死——硬约束 8）
- Ox Alpha 输出上限 131072 vs glm-5-2 的 25000：**TRUNC_COMP_TOKENS_MIN=24000 阈值
  的后端相关性**——glm-5-2 截断 comp≈25000（>24000 ✓）；Ox Alpha 若截断 comp≈131072
  （>24000 ✓ 仍捕获）但**正常长输出也常 >24000**——幸好截断判定还需 msg==0 且 rc>1000，
  正常完成 msg>0 不误判。设计时把"判定阈值是否该按后端参数化"作为一个显式决策点
  （推荐：阈值常量共享，判定逻辑不变，理由写清）

## 4. 任务分解

### 任务 1：后端接口设计（045 报告核心）

```
设计 src/acp/（或 src/backends/）的模块结构：
  backend_base.py   —— 抽象接口：
      start(task) -> BackendHandle      # task: prompt/work_dir/traject_dir/超时
      poll(handle) -> BackendStatus     # running/thinking/tool_running/
                                       # done(result)/failed(reason) + 最近信号时间戳
      terminate(handle, reason)         # 不可逆终止（过门闸语义）
      done_marker_semantics()           # 该后端"完成"的定义（E1 语义澄清的后端版）
  opencode_backend.py / devin_backend.py / （-p 后端在 V3 从现有代码抽出）
  trajectory_assembler.py               # 通知→ATIF conversation.json（U2 结论落地）

接口设计的检验标准（写进报告）：
  a. continuation/proof_audit 两个 launcher 的全部现有语义都能表达
  b. 三后端在接口下行为等价性表（同一业务事件三后端各怎么产生）
  c. WP-T.1 的 thinking spin 检测落在 base 层（poll 的最近信号时间戳——双管线通用，
     037 §5.1 的要求）
```

### 任务 2：差异适配层逐点设计

按 037 §一.3 的差异表 + U3 清单，逐差异点写适配方案：
1. 完成检测：Devin=prompt response / OpenCode=静默窗口（窗口值是 U5 实测量——本包
   留参数位）+ max_runtime 兜底（两后端共同最终兜底）
2. 权限：Devin=必须实现 request_permission 响应 / OpenCode=配置 allow 零交互（适配
   层对 base 暴露统一的 permission_event）
3. session 管理：Devin=cancel+terminate / OpenCode=close（能力差异封装）
4. 模型指定：Devin=--model 参数 / OpenCode=opencode.json 配置（后端构造参数不同）
5. 自定义通知：Devin 有 _cognition.ai/*（thinking_complete 可用）/ OpenCode 无——
   base 的状态推断统一"靠通知流转变，有显式标记时加速"
6. 错误模式信号：-p 后端=pane 文本模式（WP-J）/ ACP 后端=通知流中的什么形态
   （**引 U5 的实测结论**——rate limit 在 ACP 通知里长什么样）

### 任务 3：管线选择与切换机制设计（037 §四.13）

```
配置：DB batch 记录加 backend 字段（"opencode_acp" 默认 / "devin_acp" / "ptmux"）——
  与 concurrency 同源（WP-G 模式：DB 唯一来源，set-backend 命令，launcher 每轮可刷）
切换：
  手动：set-backend（Master Agent 操作面）
  自动回退（设计但标注"默认关闭，用户批准后启用"）：启动健康检查失败（initialize+
    session/new 不通）N 次 → 该题切备用后端重试 + alert
  切回：Master Agent 决策（不过度自动化——适度依赖原则：自动回退是"可靠的确定性
    触发"可进代码；切回时机是系统级判断留人）
健康检查：每后端启动前的 probe（initialize 握手 5s 超时）
```

### 任务 4：架构验证（对预埋立场的检验）

写专节："执行后端抽象 vs 备选结构"——至少对比一条备选（如"新建独立 ACP launcher
复制业务逻辑"），给保留/否决理由（预埋立场预期成立：判定/门闸/多轮续传逻辑复用
价值 > 抽象成本；但你必须用 U3 清单的工作量数据说话，不照抄结论）。

### 任务 5：报告 `dev-docs/045-双管线执行后端架构设计.md` + commit

含：接口定义/差异适配表/选择切换机制/阈值参数化决策/架构对比/"给 V1-V7 的任务
分解输入"（每个 V 包从本报告拿什么）。

## 5. 禁止事项

- ❌ 不写代码（设计文档——伪代码/接口签名可以，import 级实现是 V1）
- ❌ 不推翻 037 用户决策（默认 OpenCode/备用 Devin/检测通用/max_runtime 兜底是定死
  的不变量——架构在不变量内设计；若发现不变量内部矛盾，报告里列出交用户，不自作主张）
- ❌ 接口不为单一 launcher 过拟合（两个 launcher 的语义都要覆盖——检验标准 a）
- ❌ 切换机制不做"全自动切回"（适度依赖边界）

## 6. 验收 checklist

- [ ] 接口定义完整（start/poll/terminate/完成语义）+ 伪代码签名
- [ ] 行为等价性表（≥8 个业务事件 × 3 后端）
- [ ] 差异适配 6 点逐一有方案（完成检测留 U5 参数位已标注）
- [ ] 选择/切换机制含 DB 配置源/set-backend/健康检查/回退策略（自动回退默认关）
- [ ] 阈值参数化决策有明确结论与理由
- [ ] 架构对比专节（含工作量数据引用 U3）
- [ ] 045 报告 + "给 V 系列输入"小节；零代码改动

## 7. 完成汇报要求

执行记录：设计要点摘要、对预埋立场的验证结论、发现的不变量矛盾（若有）。

## 8. 审计对照

1. 接口我会做"两个 launcher 语义覆盖"抽查（拿 proof_audit 的收尾即收集语义问：
   接口怎么表达？）
2. 等价性表的每行能对到 U3 清单的真实差异点
3. 切换机制不越适度依赖边界（自动切回不存在）
4. V 系列任务分解输入与 V1-V7 文档的对齐（我总控时会核）
