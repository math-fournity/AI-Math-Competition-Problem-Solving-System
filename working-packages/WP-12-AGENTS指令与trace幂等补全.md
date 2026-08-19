# WP-12: AGENTS.md 检查指令 + trace.csv 幂等补全

> **依据**：`dev-docs/005-Master-Agent接管Monitor-Pipe检查工作.md`（需求）+ `dev-docs/006-Master-Agent接管Monitor-Pipe检查工作方案.md`（方案）
> **优先级**：P1
> **前置条件**：WP-11 完成（需要 WP-11 产出的 `MasterAgentCheck.md` 路径才能写 AGENTS.md 指令和 trace.csv 关系）
> **性质**：Master Agent 接管 Monitor Pipe 检查工作的第二半——AGENTS.md 最前面放指令 + trace.csv 孤立资产补全

---

## 目标

1. 在项目 `AGENTS.md` 的**最前面**（在所有其他内容之前）加入"Master Agent 检查工作指令"——确保连续运行中不被截断
2. 补全 `trace.csv` 中孤立资产的追溯关系——方案文档 §1.3 发现的5个孤立资产 + WP-11 产出的新资产

## 要读的文档（自包含认知加载）

**执行前必须用 trace.py 追溯本工作包涉及的元素**：
```bash
python3 scripts/trace.py query-prefix code scripts/monitor_check_continuation.sh
python3 scripts/trace.py query-prefix code scripts/monitor_check_selection.sh
python3 scripts/trace.py query-prefix code monitoring/runtime_health_check.py
python3 scripts/trace.py query-prefix doc checklist/ExecDevin.md
python3 scripts/trace.py query-prefix doc docs/specs/p27_monitor_pipe_operations.md
python3 scripts/trace.py query-prefix doc checklist/MasterAgentCheck.md  # WP-11产出后
python3 scripts/trace.py stats  # 查看当前幂等关系总量
```

**需要加载的文档**：
- 项目 `AGENTS.md` — 要在最前面加指令（先读了解现有结构）
- `dev-docs/006-...方案.md` §1.3 — 孤立资产清单 + §4 元数据更新计划
- `views/idempotency.md` — 幂等追溯分类法（确定关系类型时参考）
- WP-11 产出的 `checklist/MasterAgentCheck.md` — 确认路径正确

**看法文件**：
- `views/idempotency.md` — 幂等追溯分类法

## 任务清单

### 1. 项目 AGENTS.md 最前面加检查工作指令

- [ ] 在 `AGENTS.md` 的**最前面**（在 `# AGENTS.md — 错题分析系统` 标题之后、`> **强制声明**` 之前）加入"Master Agent 检查工作指令"章节
- [ ] 指令内容（约10行，精简）：
  ```
  ## ⚠️ Master Agent 检查工作指令（最前面，不可截断）

  **当你在做题系统工作中需要检查系统状态时**：
  1. 运行检查脚本：`./scripts/monitor_check.sh <batch_id>`
  2. 仔细阅读脚本输出的"AI后续检查清单"部分
  3. 全文加载 `checklist/MasterAgentCheck.md`
  4. 逐项处理清单中的每一项
  5. 每完成一项立即 commit（含 trace.csv 同步）
  6. 全部处理完后写执行结果记录

  **这个指令放在最前面是因为**：连续运行中 AGENTS.md 后部可能被截断，这个指令必须始终可见。
  ```
- [ ] 确认指令放在最前面（用 `head -20 AGENTS.md` 验证）
- [ ] 确认 AGENTS.md 没有膨胀（指令约10行，检查项在 MasterAgentCheck.md 中）

### 2. 补全 trace.csv 孤立资产追溯关系

按方案 §1.3 和 §4 的清单补全：

- [ ] `scripts/monitor_check_continuation.sh` — 建立 implements 关系（追溯它实现的检查功能对应的 checkpoint）
- [ ] `scripts/monitor_check_selection.sh` — 建立 implements 关系
- [ ] `monitoring/runtime_health_check.py` — 建立 implements 关系（10维度对应 MON-A* 检查）
- [ ] `checklist/ExecDevin.md` — 建立 specified-by 关系（指向 p27_monitor_spec.md）
- [ ] `docs/specs/p27_monitor_pipe_operations.md` — 建立 specified-by 关系（指向 MON-A*/B*/C*）
- [ ] MON-A2~A12、MON-B1~B9、MON-C1~C5 — 补全 implements 关系（不只 part-of WP-09）

### 3. 记录新资产到 trace.csv

- [ ] `checklist/MasterAgentCheck.md`（WP-11 产出）— 建立关系：
  - `MasterAgentCheck.md → comes-from → ExecDevin.md`
  - `MasterAgentCheck.md → specified-by → p27_monitor_spec.md`
- [ ] `scripts/monitor_check.sh`（扩展后）— 建立 changed-in 关系（指向本批 commit）
- [ ] `AGENTS.md`（修改后）— 建立 changed-in 关系（指向本批 commit）
- [ ] WP-11 和 WP-12 自身 — 建立 comes-from 关系（指向 dev-docs/006 方案）

### 4. 更新 INDEX.md

- [ ] 在 `working-packages/INDEX.md` 的工作包清单中加入 WP-11 和 WP-12

## 验收标准

1. `head -20 AGENTS.md` 能看到"Master Agent 检查工作指令"在最前面
2. `python3 scripts/trace.py query-prefix code scripts/monitor_check_continuation.sh` 不再返回"没有关系"
3. `python3 scripts/trace.py query-prefix doc checklist/ExecDevin.md` 不再返回"没有关系"
4. `python3 scripts/trace.py stats` 显示关系总数增加
5. INDEX.md 包含 WP-11 和 WP-12

## AI 工作规范（幂等关系铁律）

**执行前利用幂等关系**：
- 用 `trace.py query-prefix` 追溯每个要补全的孤立资产，确认它确实没有关系
- 用 `trace.py stats` 记录补全前的关系总数（补全后对比）

**执行中维护幂等关系**：
- 每补全一个孤立资产就 commit（含 trace.csv 变更）
- AGENTS.md 修改单独 commit
- commit 同时包含 repo 变更和 trace.csv 变更

**执行后修复幂等关系**：
- 补全后用 `trace.py query-prefix` 验证每个原孤立资产现在有关系
- 用 `trace.py stats` 对比补全前后关系总数
- 检查是否有新产生的孤立资产（WP-11/WP-12 产出的文件是否都建立了关系）

## 需求引用

- 需求文档：`dev-docs/005-Master-Agent接管Monitor-Pipe检查工作.md`
- 方案文档：`dev-docs/006-Master-Agent接管Monitor-Pipe检查工作方案.md`（§2.4 AGENTS.md 指令、§4 元数据更新计划、§5 工作包拆解预案 WP-B）
