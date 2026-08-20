# docs/ — 系统文档总目录

> **本目录是什么**：错题分析系统的全部文档存放处，按用途分为五个子目录。涵盖系统认知、设计范式、架构设计、检查规范、模板。当你需要查找某个方面的文档时，从本目录出发，根据子目录主题判断进入哪个子岛屿。
>
> **与根 README 的关系**：根 `README.md` 的分类法索引已覆盖本目录的文档（系统认知层、设计范式层、架构设计三节）。本 README 是**目录入口**（服务阶段0岛屿遍历），根 README 是**分类法索引**（服务阶段1+闭包迭代）。需要详细的覆盖场景和依赖关系时，加载根 README 对应章节或各子目录 README。

## 直接子目录

| 子目录 | 一句话说明 |
|---|---|
| `system/` | 系统认知层——新 AI 接手入口（AnalysisSystem/Design/Ops 三个文档） |
| `patterns/` | 设计范式层——跨项目元方法论（MonitorPipe 范式、HANDOFF 续传标准） |
| `architecture/` | 架构设计——9个设计方面文档（framework-checklist/architecture/shutdown/concurrency 等） |
| `specs/` | 检查规范——POC-2.7 Monitor Pipe 执行依据（3个 spec 文档） |
| `templates/` | 模板——各 Pipe 的 AGENTS.md 模板和 selfrun 任务模板（4个） |

## 本目录依赖关系

本目录被根 `README.md` 分类法索引覆盖。各子目录之间有交叉引用（如 architecture/ 引用 patterns/，specs/ 引用 patterns/）。本目录无直接文件，所有文档在子目录中。各子目录的详细入口见各自 README.md。
