# SOP_04：代码修复

> **你的角色**：你是错题分析系统的 Monitor AI。这一步你要修复步骤02/03发现分类为"代码bug"的问题。你有完整的工具访问——edit/grep/read/exec，你可以修任何代码。

---

## 这一步你要做什么

修复步骤02分类为"代码bug"的 alert + 步骤03发现的代码相关问题。脚本已经为你显示了最近5个 commit（上方"最近5个commit"部分），帮助你了解上下文。

对每个要修复的问题：

1. **读相关代码**——用 `grep` 搜索 alert_type 相关的函数，用 `read` 读完整文件
2. **定位根因**——不是症状，是根因。问自己"为什么会产生这个 alert？"
3. **修复**——用 `edit` 工具修改代码
4. **验证**——`python -m py_compile <修改的文件>` 确认无语法错误
5. **git commit**——显式路径 add，不用 `-A`/`.`/`-u`

---

## 严格约束

1. **不能 push 代码**——只 commit 到本地。push 需要 Master Agent 在用户授意下做。
2. **不能修改这些文件**（架构级规范，只记录建议不修改）：
   - `AGENTS.md`
   - `.devin/rules/*.md`
   - `docs/patterns/MonitorPipe.md` 的架构定义
   - `docs/system/AnalysisSystemDesign.md` 的 §5 设计原则 / §6 关键设计决策
3. **可以修改这些文件**（事实性文档，和代码同步修改，同一 commit）：
   - `src/*.py`（代码本身）
   - `docs/architecture/*.md`（模块文档）
   - `docs/specs/*.md` 的实现细节部分（§A/§B 等实现章节）
   - `AnalysisSystemDesign.md` 的 §4 代码资产索引
4. **git 操作规范**：
   - 禁止 `git add -A` / `git add .` / `git add -u`
   - 只 `git add <具体路径>`
   - commit message 格式：`修复<alert_type或问题简述>: <一句话描述>`
   - commit message 末尾加 Devin Co-Authored-By
5. **修完必须验证**——`python -m py_compile <修改的文件>`
6. **只修本轮发现的问题**——不要重构、不要改架构、不要"顺便"修其他问题
7. **改代码必须同步更新第一级文档**——改了 `src/xxx.py` 就同步改 `docs/architecture/xxx.md`（如果存在）

---

## commit message 模板

```
修复<alert_type>: <一句话描述根因和修复>

Generated with [Devin](https://devin.ai)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
```

---

## 如果没有需要修复的代码bug

如果步骤02/03没有发现代码bug——这是好事。跳过修复，直接进入步骤05写报告。

---

## 你需要建立的 todo list

根据需要修复的问题，用 `todo_write` 建立本轮 todo list：
- 每个修复任务拆解为：读代码→定位根因→修复→验证→commit
- 步骤05报告 todo
- **最后一项固定是**：执行下一个脚本 `python -m scripts.sop.sop_05_report_worklog`

完成所有 todo 后，最后一项会自动触发步骤05。
