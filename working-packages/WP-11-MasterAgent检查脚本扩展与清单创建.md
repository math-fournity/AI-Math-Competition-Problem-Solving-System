# WP-11: Master Agent 检查脚本扩展与清单创建

> **依据**：`dev-docs/005-Master-Agent接管Monitor-Pipe检查工作.md`（需求）+ `dev-docs/006-Master-Agent接管Monitor-Pipe检查工作方案.md`（方案）
> **优先级**：P1
> **前置条件**：无（独立工作包，不依赖 WP-01~WP-10）
> **性质**：Master Agent 接管 Monitor Pipe 检查工作的第一半——自动化检查脚本扩展 + AI 检查清单文件创建

---

## 目标

把原来由独立 Monitor Pipe devin cli 实例执行的检查工作，改造为"检查脚本（自动化）+ Master Agent（AI 判断）"的协作模式。本工作包负责：

1. 扩展 `scripts/monitor_check.sh`——整合 `runtime_health_check.py` 10维度检查 + 续传检查 + 末尾输出"AI 后续检查清单"
2. 新建 `checklist/MasterAgentCheck.md`——Master Agent 视角的检查清单（取代 ExecDevin.md 的角色）
3. 更新 `checklist/README.md` 索引 + 项目 `README.md` 引导地图

## 要读的文档（自包含认知加载）

**执行前必须用 trace.py 追溯本工作包涉及的元素**：
```bash
python3 scripts/trace.py query-prefix code scripts/monitor_check.sh
python3 scripts/trace.py query-prefix code monitoring/runtime_health_check.py
python3 scripts/trace.py query-prefix doc checklist/ExecDevin.md
python3 scripts/trace.py query-prefix doc checklist/README.md
```

**需要加载的文档**：
- `scripts/monitor_check.sh` — 现有检查脚本结构（要扩展它）
- `monitoring/runtime_health_check.py` — 10维度健康检查（要在脚本中调用它）
- `scripts/monitor_check_continuation.sh` — 续传检查脚本（要整合其核心逻辑）
- `checklist/ExecDevin.md` — 检查项来源（提取 Master Agent 需要的检查项）
- `checklist/README.md` — 需求点清单索引（要加入 MasterAgentCheck.md 索引）
- `docs/specs/p27_monitor_spec.md` — MON-A/B/C 详细标准（MasterAgentCheck 内容来源）
- 项目 `README.md` — 引导地图（要加入 MasterAgentCheck.md）
- 项目 `AGENTS.md` — 了解现有结构（WP-12 会改它，本 WP 只读不改）

**看法文件**：
- `views/idempotency.md` — 幂等追溯分类法（执行中维护 trace.csv 时参考）

## 任务清单

### 1. 扩展 `scripts/monitor_check.sh`

- [ ] 在现有4项检查后，新增第5项：调用 `python -m monitoring.runtime_health_check --batch-id <id>`，输出10维度健康检查结果（A-J）
- [ ] 新增第6项：续传检查（调用 `monitor_check_continuation.sh` 的核心逻辑，或直接 source 它）
- [ ] 修改末尾"行动清单"为"AI 后续检查清单"——明确列出需要 Master Agent 逐项处理的项目，指向 `checklist/MasterAgentCheck.md`
- [ ] 保持现有4项检查不变（向后兼容）
- [ ] 测试脚本可运行（`bash scripts/monitor_check.sh p27-full`，即使系统没运行也不应崩溃，只输出 NOT RUNNING）

### 2. 新建 `checklist/MasterAgentCheck.md`

- [ ] 从 `ExecDevin.md` 提取 Master Agent 需要执行的检查项，重新组织为"Master Agent 视角"
- [ ] 包含6个部分：
  1. **C类AI判断**（MON-C1~C5）——读 proof.md/HANDOVER.md 做判断
  2. **self-check**（SELF-S1~S17）——对自己的检查
  3. **新alert分类处理**——读自动化检查输出，逐个 recheck
  4. **已知问题诊断**——MON-A-issue-01~05 中未诊断的优先诊断
  5. **落盘完整性检查**——每个 round 的完整落盘验证
  6. **修复操作规范**——修复后同步更新文档 + commit
- [ ] 顶部写明使用场景："当你在做题系统工作中需要检查系统状态时，运行 `./scripts/monitor_check.sh <batch_id>` 后，全文加载本文件逐项处理"
- [ ] 每个 checkpoint 引用对应 `checklist/<编号>.md` 详情文件

### 3. 更新索引文档

- [ ] `checklist/README.md` — 加入 MasterAgentCheck.md 的索引行
- [ ] 项目 `README.md` — 在"四、需求点清单"章节加入 MasterAgentCheck.md 的引导地图条目
- [ ] 说明 MasterAgentCheck.md 和 ExecDevin.md 的关系（前者取代后者的角色，但后者暂不删除——历史参考）

## 验收标准

1. `scripts/monitor_check.sh` 扩展后包含6项自动化检查 + 末尾"AI 后续检查清单"
2. `checklist/MasterAgentCheck.md` 存在，包含6个部分，每个 checkpoint 有对应详情文件引用
3. `checklist/README.md` 和项目 `README.md` 都有 MasterAgentCheck.md 的索引
4. 脚本可运行（不崩溃）
5. 不膨胀 AGENTS.md（本 WP 不改 AGENTS.md，那是 WP-12 的事）

## AI 工作规范（幂等关系铁律）

**执行前利用幂等关系**：
- 用 `trace.py query/query-prefix` 追溯本工作包涉及的所有元素（脚本/代码/文档/checkpoint）
- 确认哪些资产是孤立的（无追溯关系）——这些在 WP-12 中补全

**执行中维护幂等关系**：
- 每完成一个逻辑单元就 commit
- 每次 commit 前维护 trace.csv——记录新文件（MasterAgentCheck.md）、变更文件（monitor_check.sh/README.md）的关系
- commit 同时包含 repo 变更和 trace.csv 变更

**执行后修复幂等关系**：
- 如发现孤立资产（无追溯关系的资产），主动补全 trace.csv
- 本 WP 产出的新文件（MasterAgentCheck.md）必须立即建立追溯关系：
  - `MasterAgentCheck.md → comes-from → ExecDevin.md`
  - `MasterAgentCheck.md → specified-by → p27_monitor_spec.md`
  - `monitor_check.sh（扩展后） → changed-in → <commit>`

## 需求引用

- 需求文档：`dev-docs/005-Master-Agent接管Monitor-Pipe检查工作.md`
- 方案文档：`dev-docs/006-Master-Agent接管Monitor-Pipe检查工作方案.md`（§2.2 检查脚本设计、§2.3 MasterAgentCheck.md、§5 工作包拆解预案 WP-A）
