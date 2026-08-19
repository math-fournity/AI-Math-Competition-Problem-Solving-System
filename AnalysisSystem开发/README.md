# AnalysisSystem开发 目录说明

> **本目录是什么**：错题分析系统（`analysis-devin-failure-system/`）后续开发的工作包、需求点清单、检查点详情的存放目录。
> **不是什么**：不是代码目录（代码在 `analysis-devin-failure-system/src/`），不是设计文档目录（设计文档在项目根目录和 `analysis-devin-failure-system/specs/`）。

---

## 目录结构

```
AnalysisSystem开发/
  README.md                    ← 本文件——目录结构说明+使用指南（静态，很少改）
  INDEX.md                     ← 工作包跟踪表——WP清单+依赖图+执行顺序+当前状态（动态，经常改）
  CheckList.md                 ← 需求点全集——13门类127+个需求点，编号+状态标记
  CheckList-ExecDevin.md       ← Exec Devin必读子集——约68个需求点
  CheckPoints/                 ← 检查点详情——每个需求点一个文件，可独立追踪
    ENV/                       ← 环境与基础设施
    SESS/                      ← Session编号化管理
    LAUNCH/                    ← Launcher启动与续传控制
    MON-A/                     ← Monitor Pipe A类自动检查
    MON-B/                     ← Monitor Pipe B类续传质量检查
    MON-C/                     ← Monitor Pipe C类AI判断
    EXEC/                      ← Monitor Exec Devin
    SELF/                      ← Exec Devin self-check
    CTRL/                      ← 控制命令与查看支持
    RUN/                       ← POC-2.7运行与监控
    AUDIT/                     ← 系统审计
    DOC/                       ← 文档同步
    HARD/                      ← 硬约束
    DECISION/                  ← 待决策问题
  WP-01-阶段1真实运行验证.md
  WP-02-已知bug修复.md
  WP-03-阶段2配置与模板.md
  WP-04-阶段2MonitorExecDevin启动器.md
  WP-05-阶段2MonitorPipe集成.md
  WP-06-阶段2export与report查看支持.md
  WP-07-阶段2端到端验证.md
  WP-08-阶段3文档同步.md
  WP-09-POC-2.7并发1运行和监控.md
  WP-10-系统审计.md
  scripts/                     ← 本目录的辅助脚本
    generate_checkpoints.py    ← 从CheckList.md生成CheckPoints/下所有文件
```

---

## 文件类型说明

| 文件类型 | 文件 | 用途 | 读者 |
|---|---|---|---|
| 目录说明 | `README.md` | 目录结构+使用指南——"这里有什么、怎么导航" | 第一次进目录的人 |
| 工作包跟踪 | `INDEX.md` | WP清单+状态+依赖+执行顺序——"现在做到哪了" | 每次工作的人 |
| 需求点全集 | `CheckList.md` | 13门类127+个需求点的清单——编号+状态标记 | Master Agent / 开发者 |
| 需求点子集 | `CheckList-ExecDevin.md` | Exec Devin必读的约68个需求点 | Monitor Exec Devin |
| 检查点详情 | `CheckPoints/<门类>/<编号>.md` | 每个需求点的详细文件——描述+验证方法+关联文件+变更记录 | 需要了解某个需求点详情时 |
| 工作包 | `WP-XX-*.md` | 每个工作包的实施计划——要读什么+任务清单+验证标准 | 执行该WP时 |

---

## README.md 和 INDEX.md 的关系

| 维度 | README.md | INDEX.md |
|---|---|---|
| 性质 | **静态**的目录结构说明 | **动态**的状态跟踪表 |
| 改的频率 | 很少改——目录结构变化时才改 | 经常改——WP状态/系统状态变化时改 |
| 内容 | 目录结构、编号规则、文件类型、阅读顺序、维护规则 | WP清单+状态、依赖图、执行顺序、当前系统状态 |
| 读者 | 第一次进目录的人——了解"这里有什么" | 每次工作的人——了解"现在什么状态" |
| 比喻 | 地图 | 进度板 |

**关系**：README 指向 INDEX（"要了解当前进度，读 INDEX.md"），INDEX 不重复 README 的内容（不解释目录结构）。两者互补不重叠。

---

## 编号规则

### 需求点编号

格式：`<门类代号>-<序号>`

| 门类代号 | 名称 | 示例 |
|---|---|---|
| ENV | 环境与基础设施 | `ENV-01` |
| SESS | Session编号化管理 | `SESS-01` |
| LAUNCH | Launcher启动与续传控制 | `LAUNCH-01` |
| MON-A | A类自动检查 | `MON-A1` |
| MON-B | B类续传质量检查 | `MON-B1` |
| MON-C | C类AI判断 | `MON-C1` |
| EXEC | Monitor Exec Devin | `EXEC-01` |
| SELF | Exec Devin self-check | `SELF-S1` |
| CTRL | 控制命令与查看支持 | `CTRL-01` |
| RUN | POC-2.7运行与监控 | `RUN-01` |
| AUDIT | 系统审计 | `AUDIT-01` |
| DOC | 文档同步 | `DOC-01` |
| HARD | 硬约束 | `HARD-01` |
| DECISION | 待决策问题 | `DEC-01` |

**已知问题编号**：`<门类>-!<序号>`，如 `MON-A!01`。文件名中 `!` 替换为 `-issue-`，如 `MON-A-issue-01.md`。

**编号稳定性**：编号一旦分配，不随文档重组而变。新增续接（如 MON-A 已有 A12，新增为 A13）。删除标记 `[-]` 不回收编号。

### 工作包编号

格式：`WP-<序号>`，如 `WP-01`。编号稳定，不重排。

---

## 新 AI 接手时的阅读顺序

```
第1步：读本文件（README.md）——了解目录结构和文件关系
  │
第2步：读 INDEX.md——了解当前工作包状态和执行顺序
  │
第3步：读 CheckList.md——了解系统全部需求点和状态
  │
第4步：根据要做的WP，读对应的 WP-XX-*.md
  │
第5步：根据WP中引用的需求点编号，读 CheckPoints/<门类>/<编号>.md 了解详情
```

---

## 维护规则

### 什么时候改 README.md
- 目录结构变化时（加新子目录、加新文件类型）
- 编号规则变化时
- 文件类型说明需要更新时

### 什么时候改 INDEX.md
- WP状态变化时（待执行→进行中→完成）
- 新增WP时
- 当前系统状态变化时
- 依赖关系调整时

### 什么时候改 CheckList.md
- 见 CheckList.md "维护规则"节——系统需求变化时和 check points 变化时的更新链条

### 什么时候改 CheckPoints/ 下的文件
- 需求点状态变化时（`[ ]`→`[x]` 等）
- 需求点定义修改时
- 发现新的验证方法或关联文件时
- 需求点有变更记录时

### 什么时候改 WP-XX-*.md
- WP任务清单中的项目完成时（打勾）
- WP验证记录需要填写时
- WP发现新问题需要转入其他WP时

---

## 版本记录

- **v1 · 2026-08-19** · 初始版本——目录结构说明+文件类型+编号规则+README与INDEX关系+阅读顺序+维护规则。
