# Formal verification report

复制本模板为当前 Round 的 `formal_verification.md`，填写所有标记。不得删除标记；
它们是 WP-04/WP-05 的稳定机器入口。未知或未覆盖应如实写，不得留空后宣称充分。

<!-- FORMAL_STATEMENT -->
## 1. 原题形式化主命题

说明量词、定义域、假设、目标和最终答案如何对应原题。

<!-- CLAIM_COVERAGE -->
## 2. Proof claim / lemma 覆盖映射

逐项列 `proof.md` 关键 claim，以及对应 formal theorem、程序或尚未覆盖。

<!-- TOOLCHAIN -->
## 3. 工具、版本与可信边界

列工具、版本、库和哪些部分进入可信内核；外部 oracle/库边界必须说明。

<!-- REPRODUCE -->
## 4. 精确重跑命令

命令必须以 Round 目录为 cwd，只引用归档相对路径，不得依赖 `/tmp`。

<!-- RESULTS_AND_LOGS -->
## 5. 结果与日志

列每次运行的 `.run.json`、stdout、stderr、exit code；退出 0 不自动等于充分。

<!-- ESCAPE_HATCHES -->
## 6. Escape hatch 检查

列 `sorry`、`admit`、额外 `axiom`、过强假设、弱化命题；没有也必须明确写“未发现”。

<!-- FINITE_SEARCH_BOUNDARY -->
## 7. Python/Sage/有限搜索边界

写明范围和作用。若承担完备性，给出把无限问题归约到该有限范围的 proof claim。

<!-- UNCOVERED -->
## 8. 尚未覆盖或失败的部分

列失败日志、原因和下一 Round 可执行任务。形式化不足不是永久数学失败。

<!-- SUFFICIENCY_ARGUMENT -->
## 9. 解题 AI 的充分性论证

解释为何上述映射覆盖所有决定正确性与完备性的关键步骤；该自述仍需独立审计。
