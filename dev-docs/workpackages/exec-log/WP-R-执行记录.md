# WP-R 执行记录 — 审计 prompt 双份渲染修复

> **执行时间**: 2026-08-21（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（冒烟验证全过）

---

## 一、做了什么

1. 新增 `templates/proof_audit_prompt.txt`（9 行）：任务启动指令——指向 work_dir 的
   AGENTS.md（工作区引导），含 {problem_id} 占位符（replace 渲染，对齐现有模板机制）
2. `prepare_audit_work_dir` 改造：渲染 prompt 模板写 `work_dir/audit_prompt.txt`；
   返回值从 agents_md_path 改为 audit_prompt.txt 路径；docstring 注明双份渲染修复
   （031 C5）
3. 调用链无需改动——launch_batch 解包 `work_dir, prompt_file = prepare...`，
   prompt_file 自然指向新文件，`--prompt-file` 语义不变

## 二、冒烟验证输出

```
prompt != AGENTS.md 路径: True
内容不同（防双份回归）: True
prompt 行数: 9 (<30 ✅)
占位符残留: False （应为 False）
proof.txt 存在: True
```

## 三、验收 checklist 对照

- [x] 模板存在且 9 行 <30
- [x] 返回的 prompt 路径 != AGENTS.md 路径
- [x] 两文件内容不同
- [x] py_compile 过；commit 显式路径
- 真审计启动证据：暂无新审计批次运行——下次审计启动时 tmux 命令行的 --prompt-file
  将指向 audit_prompt.txt（代码路径已由冒烟覆盖）

## 四、文档影响

WP-A 重写的 GATE-AUDIT-LAUNCH docstring 未提及 "prompt=AGENTS.md"（检查的是
proof.txt 与模板渲染），无同步需求。
