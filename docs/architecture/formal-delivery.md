# 解题侧形式化交付与运行记录

> **状态**：WP-04 已实现的解题侧能力。
> **边界**：这里只判断交付包结构和命令事实，不判断数学/形式化覆盖充分性；独立审计与最终
> Gate 属于 WP-05。`exit_code=0`、`structurally_complete=true` 都不是最终 PASS。

## 一、为什么需要这一层

旧系统把 `proof.md` 含 `\boxed` 当完成，1962 R6 的机器验证脚本还留在临时目录。最终系统
需要把 proof、形式化源码、可重跑命令、版本、日志和诚实覆盖说明一起保存，让下一 Round
和独立审计能直接复验。本实现复用 WP-03 的 Round 目录合同，不建立新 Gate、SOP、队列或
证明助手。

## 二、实现入口

- Python API：`src/formal_verification.py`
- 报告模板：`templates/formal_verification_TEMPLATE.md`
- 目录总合同：`docs/architecture/round-artifact-contract.md`

主要 API：

```python
archive_artifact(source, round_dir, category="formal")
run_formal_command(round_dir, run_name=..., command=[...], coverage_kind=...)
inspect_formal_package(round_dir)
formal_round_log_fields(round_dir)
```

模块不连接 DB/Redis；WP-02 在候选 proof 收尾时调用 `formal_round_log_fields` 登记路径。

## 三、命令运行与证据

命令必须使用 argv，不经过 shell，并以 Round 目录为 cwd：

```bash
python -m src.formal_verification run \
  --round-dir /configured/run/rounds/round8 \
  --run-name lean_main \
  --coverage-kind trusted_kernel \
  -- lean formal/Main.lean
```

支持的 `coverage_kind`：

- `trusted_kernel`：Lean/Coq/Isabelle 等可信内核；仍需审计命题等价性和覆盖；
- `finite_computation`：有限枚举/扫描，默认不能证明无限普遍命题；
- `symbolic_check`：CAS/符号恒等式检查；
- `other`：其他工具，必须在报告说明可信边界。

每次运行生成独立且拒绝覆盖的：

```text
formal_logs/<run_name>.run.json
formal_logs/<run_name>.stdout.log
formal_logs/<run_name>.stderr.log
```

run JSON 保存 argv、cwd=`.`、tool version、开始/结束时间、timeout、exit code、日志路径、
覆盖类型和 `mathematical_sufficiency_decided=false`。环境中的 key/token/secret/password 变量
不会传给子进程；输出若命中 secret 形态会先脱敏并记 `secret_redacted=true`。

为保证归档后可重跑：

- executable 通过 PATH 调用；
- 资产参数必须是 Round 内相对路径；
- 拒绝绝对路径、`..`、临时目录依赖、命令参数中的疑似 secret；
- 同名 run/log/source 不覆盖。

## 四、临时脚本归档

临时或外部生成的单个源码/验证脚本先归档：

```bash
python -m src.formal_verification archive \
  --round-dir /configured/run/rounds/round8 \
  --source /temporary/location/check.py \
  --category verification \
  --target-name check.py
```

归档 helper 要求源文件真实存在、不是 symlink、内容无疑似 secret，复制后记录 hash/字节数和
“来源是否是临时目录”。目标存在时拒绝覆盖。缺失临时脚本直接报错，不能虚构验证通过。

## 五、`formal_verification.md` 稳定标记

报告模板有九个 HTML marker，供 WP-04/WP-05 稳定读取：

```text
FORMAL_STATEMENT
CLAIM_COVERAGE
TOOLCHAIN
REPRODUCE
RESULTS_AND_LOGS
ESCAPE_HATCHES
FINITE_SEARCH_BOUNDARY
UNCOVERED
SUFFICIENCY_ARGUMENT
```

它们分别承载原题形式化命题、proof claim 映射、工具可信边界、精确命令、运行证据、
`sorry/admit/axiom`、有限搜索边界、未覆盖项和解题 AI 的充分性论证。最后一项仍是待审计
自述，不是自动 PASS。

## 六、结构检查语义

```bash
python -m src.formal_verification inspect --round-dir <round_dir>
```

检查直接事实：最小目录存在、proof 有 boxed、九 marker 完整、formal/verification 源码、run
记录及日志存在、symlink/secret/外部绝对路径、明显 `sorry/admit/axiom`、coverage kind 和各
命令成功状态。

特别注意：

- `structurally_complete=true` 只说明包的必需结构可审计；
- `all_runs_succeeded=true` 只说明命令都退出 0；
- `escape_hatches` 可在结构完整时仍非空，Lean `sorry` 正例就是这种情况；
- 所有检查结果始终带 `mathematical_sufficiency_decided=false` 和
  `requires_independent_audit=true`。

这种分层允许保存不充分但有价值的候选包，并把缺口交下一 Round，而不会误删 proof 或把题
永久判死。

## 七、rounds_log 接口

`formal_round_log_fields(round_dir)` 返回：

```text
formal_dir
formal_verification_path
formal_logs_dir
verification_dir
formal_source_paths
formal_run_record_paths
formal_structurally_complete
formal_all_runs_succeeded
formal_escape_hatches
formal_coverage_kinds
formal_requires_independent_audit=true
```

WP-02 把这些字段合并进当前数学 Round 的 `rounds_log`；不得据此直接写最终正确。WP-05 从
这些路径复制/重跑资产，检查命题等价性、关键 claim 覆盖和逃逸口。

## 八、当前验证样本

- 干净 Lean 4 theorem：命令成功、可信内核覆盖类型、无逃逸口；
- Lean `sorry`：命令成功但 scanner 报 escape hatch，证明不能只信 exit code；
- Python 有限区间：明确 `finite_computation`，不冒充普遍证明；
- 临时脚本归档/缺失/secret/绝对路径/覆盖保护；
- 跨 Round：前轮 Lean 失败日志保留，后轮修复成功且不覆盖旧证据。

这些是解题侧交付测试，不是 WP-05 的最终数学审计正反样本全集。
