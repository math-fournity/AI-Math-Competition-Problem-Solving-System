# WP-C — SOP_07 新 STEP：审计系统健康检查（9 步循环 + 资产 + 直接检查）

> **优先级**: 第三批之首（SOP 链的根）
> **依赖**: WP-B（直接检查铁律——检查项设计依据）；最好在 WP-N/H 之后（检查项引用
> mark_parse_error 与收尾即收集的语义）
> **预计规模**: sop_state.py ~5 行 + run.py ~3 行 + checks.py ~150 行 + SOP 文档
> ~200 行 + 模板 ~70 行 + SYSTEM_CLOSURE/AGENTS.md 同步
> **性质**: SOP 系统扩展（新步骤 + 新资产）

---

## 0. 给执行 AI 的第一句话

SOP 循环从 8 步变 9 步：在 06 与 Z 之间插入 **07 审计系统健康检查**。你要建全套资产：
状态机注册、检查函数、给 Master Agent 的提示词文档（SOP_07_audit_health.md）、报表
模板。检查项全部按**直接检查铁律**设计（WP-B 的 rule）——不只查 DB/Redis，必须抽查
硬盘 export/proof 实物。这一步是 030 需求 5 的核心交付（用户原文："甚至是新的SOP
STEP和对应的审计系统运行用的资产，比如说给Master Agent的提示词文件、新的报表模板"）。

## 1. 背景（为什么）

- 审计 Pipe 已上线（WP-1~9）且有本批工作包的大量改造（N/H/J/L…）——SOP 循环却只有
  适配续传的检查。审计是独立管线（独立队列/门闸/产出），需要独立检查步骤（031 D4
  裁定建 SOP_07；034 接受；用户原文支持）
- 本批事故的教训直接铸进检查项：孤儿审计 session 对账（本次 5 孤儿无人发现）、
  PARSE_ERROR 堆积（WP-N 修复后需要有人看）、审计通过题的实物交叉验证（028 教训）
- SOP 机制认知：run.py 每次执行一步（读 _state.json→打印 L0+L1 文档→跑检查函数→
  推进→打印 todo 指令）；文档自包含（认知闭包+执行指令+todo）；报表必填

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `scripts/sop/sop_state.py` **全文**（197 行） | SOP_STEPS/SOP_NAMES 结构、check_order/advance 的顺序逻辑——你插入 "07" 的位置（06 后 Z 前） |
| 2 | `scripts/sop/run.py`（117 行） | STEP_CHECKS 映射、报表生成调用——加一行映射 |
| 3 | `scripts/sop/checks.py` 的 `check_01_system_health` + `_check_audit_pipe_health`（现有 A15-A18） | ① 检查函数的风格（打印格式/异常包裹）② A16/A17 的实现——**WP-D 将移除，你先知道有什么**（你的 check_07 接管它们并升级直接化） |
| 4 | `docs/sop/SOP_04_ai_judgment.md` 全文（137 行） | SOP 文档的标准结构（认知闭包→执行指令→todo 指令）——你的 SOP_07 文档照此写 |
| 5 | `docs/sop/SYSTEM_CLOSURE.md` §6 审计段 + §"审计 Pipe 正常状态" | 正常工作的判定标准（你的检查项阈值来源） |
| 6 | `.devin/rules/direct-verification-ironlaw.md`（WP-B 产物） | 直接检查的判定表——你的 8 项检查的合规依据 |
| 7 | `docs/sop/templates/report_step_04.md`（86 行） | 模板结构（打勾项/表格/AI 填写区） |
| 8 | `scripts/sop/report.py` 的模板发现机制（搜 report_step / REPORT_BASE） | 模板文件命名规则——**确认 report_step_07.md 会被自动发现**（若是硬编码清单则要加） |
| 9 | `src/proof_audit_db_schema.py` + `src/proof_audit_redis_queue.py` 的查询 API | check_07 用的函数 |
| 10 | WP-N（mark_parse_error 语义）/ WP-H（收尾即收集语义）的执行记录 | 检查项 8/7 的语义依据 |

## 3. 现场事实基线（2026-08-21 09:30 + 前序 WP 后）

- 当前 SOP_STEPS = ["01","02","03","04","05","06","Z","OP"]（8 步，cycle=6 进行中）
- `_state.json` 的 last/next——你插入 07 后，状态机的顺序数组变了：已执行过的 cycle
  不受影响（next 推进按数组索引），但**执行本 WP 期间循环若在跑会乱序**——改代码
  前确认 SOP 循环没在跑（或改完立即验证顺序）
- checks.py 的 `_check_audit_pipe_health` 存在（A15-A18，简化版检查）
- 复核：`grep -n "SOP_STEPS" scripts/sop/sop_state.py`

**基线漂移预期**：WP-N/H/J/L/G/S 都可能已执行——你的检查项阈值按"改造后语义"设计
（下面 §4 已按最终态写）。report.py 的模板机制若是按 step 编号模式匹配（rglob）则
零改动；若硬编码则加 07。

## 4. 任务分解

### 任务 1：状态机与入口

- `sop_state.py`：`SOP_STEPS = ["01","02","03","04","05","06","07","Z","OP"]`；
  `SOP_NAMES["07"] = "审计系统健康检查"`
- `run.py`：`STEP_CHECKS["07"] = checks.check_07_audit_health`
- 验证顺序校验：`python -m scripts.sop._set_next status` 正常；`python -m scripts.sop.dry_run`
  若支持列出步骤则确认 07 在列

### 任务 2：`checks.py` 新增 `check_07_audit_health(batch_id)`

8 项检查（**1-3 层间接快照 + 4-8 层直接实物**，打印风格对齐现有函数）：

```
--- 1. 队列与状态快照（间接层，来自 A16/A17 升级接管）---
  Redis paudit 四队列数；DB p27_proof_audit_runs status 分布；
  p27_proof_audits 的 audit_status 分布 + 失败率（>20% 警告——阈值来源 SYSTEM_CLOSURE §6）

--- 2. 失败审计分析 ---
  paudit:failed 的 reason 分布（WP-J 后是 verdict 原词）；
  dead_session_no_export/max_runtime_exceeded 占比异常提示（>30% 警示模板问题/输入问题）

--- 3. 门闸 Y 通道（审计专属）---
  p27_step_gates 中 _key 含 AUDIT 且 waiting_for 非空——输出闭包（复用 extract_checklist，
  对齐 _check_pending_gates 的输出方式）；无 Y 打 ✅

--- 4. 【直接】审计产出实物验证 ---
  随机抽 5 个 p27_proof_audits 记录 → 读其 source_run_key 的 export_path →
  Path.exists() + 文件含 "<proof_audit>" 字符串 + audit_status 与 DB 一致
  （不一致=收集链断裂——critical 提示）

--- 5. 【直接】审计通过题交叉验证（028 教训）---
  随机抽 5 个 audit_passed=True 的 run → work_dir/proof.md（或 rounds_log 最后一条
  proof_path）→ 存在 + grep '\\boxed'——DB 说通过但盘上没证据=立即警示

--- 6. 【直接】作弊题证据复核（原 C9 移入）---
  FAIL_CHEATING/FAIL_CHEATING_DECLARED 且未复核（无 ai_review_done）的 ≤5 条：
  输出 cheating_analysis 全文供 Master Agent 判断证据充分性

--- 7. 【直接】孤儿审计 session 对账 ---
  tmux list-sessions 的 ^paudit- 前缀 session vs Redis paudit:running 的 key 集合
  （注意 session 名是 key 后 30 字符的映射规则）：
  - session 有 Redis 无 → 孤儿（launcher 死了？DONE.md 在就可建议清理）逐个输出
    DONE.md 状态【直接查文件】
  - Redis 有 session 无 → 状态漂移（DB/Redis 说在跑实际没了）

--- 8. PARSE_ERROR 堆积检查 ---
  p27_proof_audit_runs 中 audit_status==PARSE_ERROR 的计数与列表（WP-N 语义：待人工）；
  >0 则醒目输出"待人工复查清单" + 对应 alert 是否在 p27_monitor_alerts 且未 resolve
```

实现注意：随机抽样用 `SORT RAND() LIMIT 5`（对齐现有 C7/C8 查询）；每项独立
try/except（一项失败不拖垮整步）；直接检查项的输出必须含实际文件路径与判定结果。

### 任务 3：`docs/sop/SOP_07_audit_health.md`（给 Master Agent 的提示词文件）

结构对齐 SOP_04（认知闭包→执行指令→todo）。内容要点：
- 认知闭包：审计管线三段（collector→launcher→result_collector）+ 各段健康标准
  （引用 SYSTEM_CLOSURE §6 审计段——不重复，写"见上方 L0"）+ **completed 的真实语义
  （E1：devin 退出≠审计成功——SOP 判断时最易踩的坑）** + 收尾即收集语义（WP-H：
  审计完成即入库，p27_proof_audits 增长是健康信号）
- 执行指令：读上方自动检查输出的 8 项，逐项按"正常标准表"判断；异常时给处置指引表
  （孤儿→验证 DONE.md 后建议 kill 命令；PARSE_ERROR→人工读 export 复审流程；
  交叉验证失败→critical 上报并暂停审计批次建议）
- C6 语义检查（AI 判断部分，少量）：抽查 1 个 PASS 的 audit_summary 与 proof 内容
  匹配度（轻量版 C7）
- todo 指令（固定格式：填报表→最后一项执行 python -m scripts.sop.run）

### 任务 4：`docs/sop/templates/report_step_07.md`

对齐 report_step_04 风格：8 项检查的打勾表（含"直接检查"标记列）+ 孤儿 session
处置记录表 + PARSE_ERROR 复查记录表 + AI 判断（C6 轻量）记录 + 结论行。

### 任务 5：全量文档同步

- `AGENTS.md`：SOP 循环表（8 步→9 步，加 07 行：审计系统健康——8 项含 5 项直接检查）；
  "有效步骤编号"列表加 `07`
- `docs/sop/SYSTEM_CLOSURE.md`：循环结构图加 07；§6 审计段的检查归属注明"SOP_07 承载"
- `docs/sop/SOP_Z_meta_system_review.md` 的循环结构段（有 8 步列表——同步 9 步）
- `docs/sop/SOP_OP_operations_knowledge.md` 的 SOP 文档清单段（"8个"→"9个"+列名）
- README.md 若有 SOP 计数同步之（grep "8 步\|8步\|8 个 SOP"）

### 任务 6：端到端验证 + commit

```
python -m scripts.sop._set_next status
python -m scripts.sop.dry_run --step 07   （若 dry_run 支持；否则 _set_next 07 后真跑一步——
                                           注意真跑会把状态推进到 Z，用 _set_next 修正回来）
# 真跑一次：确认 L0+L1 文档打印、check_07 输出 8 项、报表目录生成（report_step_07.md
# 被发现并复制）、todo 指令打印
python -m scripts.sop._set_next <跑完后的正确下一步>   # 恢复循环秩序
```
commit 显式路径：sop_state.py / run.py / checks.py / SOP_07 文档 / 模板 / 同步的文档。

## 5. 禁止事项

- ❌ 检查项不做任何"写"操作（SOP 检查是只读+报告——处置是 Master Agent 的事，
  适度依赖原则）
- ❌ 不把 A15（队列停滞快速预警）从 SOP_01 移走（WP-D 只移 A16/A17——A15 留 01 做快速预警）
- ❌ 不在 check_07 里复制 C7/C8 逻辑（它们在 SOP_04 由 WP-E 升级——你的项 6 只接 C9）
- ❌ 文档不重复 SYSTEM_CLOSURE 的系统级内容（L1 只写本步骤增量——SOP 文档铁律）

## 6. 验收 checklist

- [ ] `grep -n '"07"' scripts/sop/sop_state.py scripts/sop/run.py` — 两处注册
- [ ] check_07 的 8 项在函数中逐项可辨（grep 项标题注释）；其中 4 项标"直接"且代码
      里真的读文件（grep Path( / read_text / exists）
- [ ] SOP_07 文档含：E1 语义警示 / 收尾即收集语义 / 处置指引表 / todo 指令
- [ ] 模板 report_step_07.md 存在且被 report.py 机制发现（真跑后报表目录里有）
- [ ] AGENTS.md/SYSTEM_CLOSURE/SOP_Z/SOP_OP 的循环描述全部 9 步（grep 验证无"8 步"残留）
- [ ] 端到端真跑一次的输出贴记录（8 项全出+报表生成+状态机秩序恢复）
- [ ] py_compile；commit 显式路径

## 7. 完成汇报要求

执行记录：check_07 真跑输出全文、报表路径、状态机恢复证明（_set_next status 前后）、
同步文档清单。

## 8. 审计对照

1. 我会真跑一次 `python -m scripts.sop.run`（当 next==07 时）——8 项输出完整、直接
   检查项含真实文件路径、异常包裹不崩
2. 交叉验证项（项 5）我会抽查它报"存在+boxed"的题亲手 ls 核对（审计者守直接检查铁律）
3. 9 步循环的全量文档一致性（grep "8 步" 零残留）
4. 报表模板的打勾项与 8 项检查一一对应
