# checklist/README.md — 需求点清单索引

> **本目录是什么**：错题分析系统全部功能需求点的存放目录。每个需求点（checkpoint）一个独立文件，文件名即编号。本文件是所有 checkpoint 的索引。
>
> **不是什么**：不是实施计划（那是 `working-packages/` 的事），不是检查规范详情（那是 `docs/specs/` 的事），不是设计文档（那是 `docs/system/` 的事）。

---

## 用途

1. **开发前**——确认"要做哪些功能"没有遗漏
2. **开发中**——每个功能点有唯一编号，WP 和 commit message 可引用
3. **验收时**——逐项打勾判定系统是否完成
4. **跨 session**——新 AI 接手时一眼看清系统全貌
5. **研发管理**——用 checklist 推进和管理整个项目研发，每个 checkpoint 记录它涉及的文档和代码

---

## 编号规则

格式：`<门类代号>-<序号>`，如 `SESS-01`、`MON-A1`、`EXEC-03`。编号稳定，不随文档重组而变。

**已知问题编号**：`<门类>-!<序号>`，如 `MON-A!01`。文件名中 `!` 替换为 `-issue-`，如 `MON-A-issue-01.md`。

**编号稳定性**：编号一旦分配，不随文档重组而变。新增续接（如 MON-A 已有 A12，新增为 A13）。删除标记 `[-]` 不回收编号。

### 状态标记

`[ ]` 待做 · `[~]` 进行中 · `[x]` 已完成 · `[!]` 已知有问题待修 · `[-]` 决定不做

---

## 门类索引

| 门类代号 | 名称 | 需求点数 | 负责的 WP | 文件名前缀 |
|---|---|---|---|---|
| ENV | 环境与基础设施 | 7 | WP-01, WP-09 | `ENV-` |
| SESS | Session 编号化管理（阶段1） | 12 | WP-01 | `SESS-` |
| LAUNCH | Launcher 启动与续传控制 | 10 | WP-01, WP-02 | `LAUNCH-` |
| MON-A | Monitor Pipe A 类自动检查 | 14 | WP-02, WP-05 | `MON-A` |
| MON-B | Monitor Pipe B 类续传质量检查 | 9 | WP-02, WP-05 | `MON-B` |
| MON-C | Monitor Pipe C 类 AI 判断 | 5 | WP-05, WP-07 | `MON-C` |
| EXEC | ~~Monitor Exec Devin~~（已废弃[-]） | 28 | ~~WP-03~07~~ | `EXEC-` |
| SELF | Master Agent self-check | 22 | WP-13 | `SELF-` |
| CTRL | 控制命令与查看支持 | 9 | WP-01, WP-06 | `CTRL-` |
| RUN | POC-2.7 运行与监控 | 8 | WP-09 | `RUN-` |
| AUDIT | 系统审计 | 7 | WP-10 | `AUDIT-` |
| DOC | 文档同步（阶段3） | 8 | WP-08 | `DOC-` |
| HARD | 硬约束（贯穿全程） | 12 | 全部, WP-14 | `HARD-` |
| DECISION | ~~待决策问题~~（已废弃[-]，多数关于Exec Devin） | 7 | — | `DEC-` |

**合计**：14 个门类，143 个需求点。

---

## 如何查找 checkpoint

1. **按编号**——直接读 `checklist/<编号>.md`，如 `checklist/ENV-01.md`
2. **按门类**——用门类索引表找到前缀，`ls checklist/<前缀>*` 列出该门类所有文件
3. **按状态**——`grep -l '\[ \]' checklist/*.md` 找所有待做的 checkpoint

---

## 每个 checkpoint 文件的内容结构

每个 checkpoint 文件包含：

- **需求描述**——这个 checkpoint 要求什么
- **验证方法**——如何验证这个 checkpoint 已满足
- **涉及的文档和代码**——这个 checkpoint 关联哪些设计文档、规范、代码文件
- **状态**——`[ ]`/`[~]`/`[x]`/`[!]`/`[-]`
- **负责的 WP**——哪个工作包负责实现
- **来源**——这个 checkpoint 从哪个文档/规范中提取
- **变更记录**——修改历史

---

## 相关文件

- `checklist/MasterAgentCheck.md`——**Master Agent 检查工作清单**（Master Agent 接管 Monitor Pipe 检查工作后使用的检查清单，取代 ExecDevin.md 的角色）。当 Master Agent 需要检查系统状态时，运行 `./scripts/monitor_check_continuation.sh <batch_id>` 后全文加载本文件逐项处理。
- `checklist/ExecDevin.md`——Monitor Exec Devin 必读子集（约68个需求点）。**历史参考**——原来给独立 Monitor Pipe devin cli 用的，该角色已由 Master Agent 接管，但文件保留作为历史参考。
- `working-packages/`——工作包实施计划，WP 中引用 checkpoint 编号
- `docs/specs/`——检查规范详情，部分 checkpoint 的来源
- `docs/system/AnalysisSystemDesign.md` §6——**关键设计决策记录**（已决策+理由）。注意：本目录的 `DEC-` 门类是"待决策问题"（spec §G），和设计决策记录（spec §E）不同——后者是已经做出的决策及其理由，汇总在 AnalysisSystemDesign.md §6。

---

## 维护规则

- **新增 checkpoint**——分配编号，创建文件，更新门类索引表的需求数
- **状态变更**——直接改 checkpoint 文件中的状态标记
- **内容变更**——直接改 checkpoint 文件，在变更记录中追加一行
- **编号不回收**——删除的 checkpoint 标记 `[-]`，不删除文件，不回收编号
