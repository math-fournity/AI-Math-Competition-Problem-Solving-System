# WP-R — 审计 prompt 双份渲染修复（小包）

> **优先级**: 第二批（独立小包，随时可做）
> **依赖**: 无（但注意与 WP-J 的文件交集——先后皆可，merge 冲突由后做者处理）
> **预计规模**: proof_audit_launcher.py ~30 行 + 模板新增 1 个文件
> **性质**: 代码小修 + 模板

---

## 0. 给执行 AI 的第一句话

审计 devin cli 启动时，`--prompt-file` 传的是渲染后的 AGENTS.md 本身——而 devin cli
本来就会自动读 work_dir 下的 AGENTS.md。同一份几百行的审计指令被发送了两遍：浪费
token、双份指令可能互相干扰。你要拆开：AGENTS.md 留在 work_dir 作工作区引导，
`--prompt-file` 换成一个简短的任务启动指令文件。

## 1. 背景（为什么）

- 发现链：031 C5（032 验证属实）——`prepare_audit_work_dir()` 返回
  `(work_dir, agents_md_path)`，launcher 把 agents_md_path 直接当 prompt_file 传给
  `audit_launch()` 的 `--prompt-file`
- 设计本意（029 §5.1）：`templates/proof_audit_agents_md.md` 是审计 AI 的**工作区引导**
  （AGENTS.md 语义），不是一个好 prompt（太长、无任务聚焦）
- 优先级 P2：不致命（审计确实能跑——035 的实测都过了），但属浪费与混乱源

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `src/proof_audit_launcher.py` 的 `prepare_audit_work_dir`（~89-111 行） | 现状：渲染模板写 AGENTS.md + proof.txt，返回 agents_md_path |
| 2 | 同文件主循环调用处（搜 `prepare_audit_work_dir`） | `work_dir, prompt_file = prepare...`——prompt_file 就是 agents_md_path |
| 3 | `templates/proof_audit_agents_md.md` 前 30 行 | 模板结构（占位符风格 `{problem_text}` 等——replace 渲染，非 format） |
| 4 | `src/continuation_launcher.py` 的 `start_handover` 写 prompt 文件的姿势（prompt_file.write_text + 传入 launch） | 续传的做法参照：prompt 与工作区分离 |

## 3. 现场事实基线（2026-08-21 09:30）

- `audit_launch(audit_run_key, work_dir, prompt_file, export_path, ...)` 内
  `--prompt-file {prompt_file}`，prompt_file == work_dir/AGENTS.md
- 复核：`grep -n "prompt_file" src/proof_audit_launcher.py`
- devin cli 自动读 work_dir/AGENTS.md 的行为是平台特性（与续传 solve 一致——续传的
  work_dir 也有 AGENTS.md 而其 prompt 是独立 prompt.txt——这就是为什么续传没这个问题）

**基线漂移预期**：WP-J 改 running 检查段（无交集）；WP-H 改主循环退出路径（无交集）。
若 WP-A 已重写 audit_launch 的 docstring——你改的是函数体调用链，docstring 若提到
"prompt=AGENTS.md"需同步一句。

## 4. 任务分解

### 任务 1：新增启动指令模板 `templates/proof_audit_prompt.txt`

内容骨架（人话，~15 行）：

```
你的任务：审计一道数学题的 proof.md 是否真实、正确、完整。

工作区指引：完整读当前目录下的 AGENTS.md——里面有题目文本、标准答案、被审计的
proof 内容、以及 9 项审计维度（A1-E2）和输出格式要求。

输出要求：按 AGENTS.md 规定的 XML 格式（<proof_audit>...</proof_audit>）输出审计
报告，以 ### PROOF AUDIT COMPLETE 结尾。

problem_id: {problem_id}
```

（占位符 {problem_id} 用 replace 渲染——对齐现有模板机制。）

### 任务 2：改 `prepare_audit_work_dir`

- 渲染 prompt 模板写 `work_dir/audit_prompt.txt`（同一函数内完成，mkdir 已有）
- 返回值改为 `(work_dir, prompt_path)`——prompt_path 指向 audit_prompt.txt
- docstring 一句话注明：AGENTS.md=工作区引导（devin 自动读），audit_prompt.txt=
  任务启动指令（--prompt-file）——双份渲染修复（031 C5）

### 任务 3：验证 + commit

- py_compile
- 冒烟：跑一个审计任务（pending 有货时）或至少 dry 验证——`python -c` 调
  prepare_audit_work_dir（假参数）断言两个文件都生成、内容非空、audit_prompt.txt
  与 AGENTS.md 内容**不同**（防回归双份）
- 若能跑真审计：tmux 里看 devin 命令行的 --prompt-file 指向 audit_prompt.txt
- commit 显式路径（launcher + 新模板）

## 5. 禁止事项

- ❌ 不改 AGENTS.md 模板内容（它是审计维度的权威——WP-C 的 SOP 引用它）
- ❌ 不动 proof.txt 逻辑
- ❌ prompt 保持简短（<25 行）——它的职责是"启动+指向"，不是重复 AGENTS.md

## 6. 验收 checklist

- [ ] `templates/proof_audit_prompt.txt` 存在且 <30 行
- [ ] prepare_audit_work_dir 返回的 prompt 路径 != AGENTS.md 路径（代码+冒烟输出）
- [ ] 冒烟断言两文件内容不同
- [ ] （若有真审计跑）tmux pane/命令行证据：--prompt-file 指向 audit_prompt.txt
- [ ] py_compile；commit 显式路径

## 7. 完成汇报要求

执行记录：diff、冒烟输出、（若跑）真审计的启动证据。

## 8. 审计对照

1. 读 prepare 函数代码——返回值语义正确
2. audit_prompt.txt 内容没有复制 AGENTS.md 的大段（长度检查）
3. 模板占位符渲染无残留（冒烟输出 grep "{" 验证）
