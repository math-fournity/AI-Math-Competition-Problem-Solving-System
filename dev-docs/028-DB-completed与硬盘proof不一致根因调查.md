# 028 - DB completed 与硬盘 proof.md 不一致根因调查报告

> **日期**：2026-08-21
> **触发**：027 报告发现 138 题 DB completed 中只有 14 题有 proof.md，用户要求调查"为什么会在没有 proof.md 的情况下，DB 记录就被造假了"
> **结论**：DB 不是"造假"——124 题在 018 事故前确实有 proof.md，launcher 正确标记了 completed。018 事故删了 work_dir 导致 proof.md 永久丢失，DB 与硬盘不一致是**数据丢失**，不是**数据造假**。但 018 事故前的设计缺陷（proof 单点存储）是根本问题。

---

## 1. 调查问题

027 报告发现：138 题 DB status=completed，但只有 14 题有硬盘 proof.md。124 题既没有 proof.md 也没有 work_dir。

用户质疑：为什么会在没有 proof.md 的情况下，DB 记录就被标记为 completed？DB 是否"造假"？

## 2. 调查方法

### 2.1 审查 launcher finalize 逻辑

审查 `src/continuation_launcher.py` 中 `finalize_run_completed` 函数的调用链，确认标记 completed 的前置条件。

### 2.2 交叉验证 DB 与硬盘

对 138 题 completed 记录，检查：
- `work_dir/proof.md` 是否存在
- `p27_continuation_results` 集合中是否有对应记录（018 加固后的 proof 入库）
- `ended_at` 时间分布

### 2.3 追溯 018 事故

查阅 `dev-docs/018-teardown误删生产目录事故报告.md`，确认事故时间、影响范围、丢失内容。

### 2.4 追溯 018 加固代码

查 git log，确认 proof 入库加固代码的 commit 时间。

## 3. 调查结果

### 3.1 launcher finalize 逻辑——不可能在无 proof.md 时标记 completed

`continuation_launcher.py` 的完成判定逻辑（第 1442-1565 行）：

```
proof_found = False  # 初始值

# 步骤1：预检 proof.md
proof_path = work_dir / "proof.md"
if proof_path.exists():
    if proof_path.stat().st_mtime >= started_at:  # 产物归属校验
        if re.search(PROOF_COMPLETE_MARKER, proof_text):  # 有 boxed 答案
            proof_found = True

# 步骤2：devin cli 退出后
if devin_exited:
    if proof_found:
        is_done = True  # 标记完成
    else:
        # 调用 is_completed() 二次检查
        comp, comp_reason = is_completed(export_path, work_dir, since_ts=started_at)
        if comp:
            is_done = True
            proof_found = PROOF_FILE_NAME in comp_reason

# 步骤3：只有 proof_found=True 才调用 finalize_run_completed
if proof_found:
    finalize_run_completed(...)  # 写 DB status=completed
```

`is_completed()` 函数（第 257-289 行）的返回 True 的唯一路径：
- proof.md 存在 + mtime >= since_ts + 有 boxed 答案 → return True

**结论：launcher 不可能在 proof.md 不存在的情况下标记 completed。** 逻辑链中有两道检查（预检 + is_completed），都要求 proof.md 存在且有 boxed 答案。

### 3.2 交叉验证——14 题有 proof 入库，124 题没有

| 分类 | 题数 | 有 proof.md | 有 p27_continuation_results | ended_at |
|---|---|---|---|---|
| 018 加固后完成 | 14 | ✓ | ✓（14/14） | 2026-08-21 |
| 018 事故前完成 | 124 | ✗（被删） | ✗（0/124） | 2026-08-18~20 |

14 题全部有 `p27_continuation_results` 记录（含 proof_text），ended_at 全部在 2026-08-21。
124 题全部没有 `p27_continuation_results` 记录，ended_at 全部在 2026-08-18~20。

### 3.3 018 事故——2026-08-20，删了 5958 个 work_dir

018 事故报告（`dev-docs/018-teardown误删生产目录事故报告.md`）记录：

- **事故时间**：2026-08-20
- **事故原因**：017 全流程模拟系统收尾清理时，手动 export 隔离环境漏设 `SOLVER_BASE`/`TRAJECTORY_BASE`，teardown 的 `shutil.rmtree` 删除了生产 D 盘目录
- **删除内容**：
  - `/Volumes/data/math-agent-glm5.2-tmux-agents-dir/p27-continuation/`（5958 个题目的工作目录）
  - `/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-continuation/`（trajectory 根）
- **丢失数据**：124 个 completed run 的 proof.md 文本（永久丢失，DB 只存路径不存内容，rmtree 不进废纸篓，D 盘 APFS 无快照）

### 3.4 018 加固代码——2026-08-20 10:25 commit

`f5d89e7` commit（2026-08-20 10:25 -0400）加了 proof 入库加固：

```python
# 018事故加固：proof文本入库（continuation_results）。此前只存路径——
# 文件是单点，盘上丢失即永久丢失（018实证：124份proof不可恢复）。
# 入库后DB自身成为proof的第二份存档，选题/复核不再依赖盘上文件。
try:
    insert_result(db, {
        "run_key": run_key,
        "proof_text": archived_proof.read_text(errors="replace")[:100000],
        ...
    })
```

14 题有 `p27_continuation_results` 记录，说明它们是在加固代码之后完成的。

## 4. 根因判定

### 4.1 不是 DB 造假

DB 不是"造假"——124 题在 018 事故之前完成时，proof.md 确实存在，launcher 的 `is_completed` 检查通过了（proof.md 存在 + mtime >= started_at + 有 boxed 答案），DB 标记 completed 是**正确的判定**。

### 4.2 是 018 事故导致的数据丢失

018 事故的 `shutil.rmtree` 删了整个 `p27-continuation/` 目录，包括 124 题的 work_dir 和 proof.md。DB 中的 completed 记录保留了，但硬盘上的证据丢失了。这是**数据丢失**，不是**数据造假**。

### 4.3 根本原因是设计缺陷——proof 单点存储

018 事故报告第 51 行已经指出："proof 是解题成果的唯一凭证，却是'盘上单点文件 + DB 只存路径'——单点丢失。**重要成果必须入库双写**。"

018 事故前的数据架构：
- proof.md 只存在 work_dir 中（单点）
- DB 只存 proof_path（路径），不存 proof_text（内容）
- work_dir 被 rmtree → proof.md 永久丢失，DB completed 变成"无证据的声明"

018 事故后的加固：
- finalize_run_completed 现在把 proof_text 写入 `p27_continuation_results`（≤100KB）
- DB 自身成为 proof 的第二份存档
- 14 题（018 加固后完成）都有 `p27_continuation_results` 记录，验证加固有效

## 5. 时间线

| 时间 | 事件 | 影响 |
|---|---|---|
| 2026-08-18 19:56 ~ 2026-08-20 06:xx | 124 题陆续完成 | proof.md 存在 work_dir 中，DB 标记 completed（正确） |
| 2026-08-20 | 018 事故发生 | shutil.rmtree 删了 p27-continuation/ 目录，124 题 proof.md 永久丢失 |
| 2026-08-20 10:25 | 018 加固代码 commit (f5d89e7) | finalize_run_completed 加 proof_text 入库到 p27_continuation_results |
| 2026-08-21 05:56 ~ 10:39 | 14 题完成 | proof.md 存在 work_dir 中，同时入库到 p27_continuation_results（加固生效） |
| 2026-08-21 | 027 报告发现 DB 与硬盘不一致 | 138 completed 中只有 14 题有 proof.md |

## 6. 当前状态

| 指标 | 值 | 说明 |
|---|---|---|
| DB completed 总数 | 138 | DB 记录 |
| 有 proof.md（硬盘验证） | 14 | 018 加固后完成，proof.md 存在 |
| 有 p27_continuation_results 记录 | 14 | 018 加固后完成，proof_text 入库 |
| 无 proof.md 且无 continuation_results | 124 | 018 事故前完成，proof.md 被删，无入库备份 |
| 真实有证据的成功数 | **14** | 只有这 14 题有硬盘 + DB 双重证据 |

## 7. 修复建议

### 7.1 短期：修正 124 题的 DB 状态

124 题的 proof.md 已永久丢失，无法验证解题结果是否正确。建议：

1. **按 `db-delete-backup-first` rule，先备份这 124 条记录**
2. 将 status 从 `completed` 改为 `prepared`，让它们重新进入做题队列
3. 重新做题后会生成新的 proof.md，同时入库到 p27_continuation_results

**注意**：这 124 题中可能有些确实解出了正确答案（018 事故前 launcher 判定正确），但因为 proof 已丢失无法验证，必须重做。

### 7.2 中期：launcher finalize 加硬盘验证（已在 018 加固中部分实现）

018 加固已经加了 proof_text 入库。但还可以进一步加固：

- finalize_run_completed 中 `insert_result` 失败时（第 907 行 catch），目前只 log warning 不阻断。建议改为：入库失败则不标记 completed（防止再次出现"DB completed 但无证据"的情况）。

### 7.3 长期：proof 多副本存储

- proof.md 不仅存 work_dir，同时入库（已实现）
- 考虑将 proof.md 同步到安全的归档目录（如 `/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-continuation-proofs/`）
- 归档目录不受 teardown 影响

## 8. 与 027 报告的关系

| 报告 | 关注点 | 结论 |
|---|---|---|
| 027 | DB completed 与硬盘 proof.md 的交叉验证 | 138 题只有 14 题有 proof.md，124 题无证据 |
| 028（本报告） | 为什么会这样？DB 是否造假？ | 不是造假，是 018 事故数据丢失 + 018 事故前 proof 单点存储的设计缺陷 |

## 变更记录

- v1 · 2026-08-21 · 初始创建，根因调查完成：不是 DB 造假，是 018 事故数据丢失 + 018 事故前 proof 单点存储设计缺陷
