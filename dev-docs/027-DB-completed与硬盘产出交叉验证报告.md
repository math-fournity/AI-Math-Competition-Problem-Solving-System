# 027 - DB completed 与硬盘产出交叉验证报告

> **日期**：2026-08-21
> **触发**：用户质疑"你的统计是不够扎实的，你确定数据库中的结果，能和硬盘上的解题目录中的结果对应上吗？"
> **结论**：DB 说 completed 138 题，但只有 **14 题**有硬盘 proof.md 产出。124 题是 018 事故受害者，产出永久丢失。

---

## 1. 交叉验证方法

### 1.1 DB 侧

```sql
FOR r IN p27_continuation_runs
  FILTER r.status == "completed"
  RETURN {pid: r.problem_id, work_dir: r.work_dir, ended_at: r.ended_at}
```

### 1.2 硬盘侧

对每条 completed 记录，检查 `work_dir/proof.md` 是否存在：
- 存在 → 真正有产出
- 不存在但 work_dir 存在 → work_dir 在但 proof.md 丢失
- work_dir 不存在 → 整个目录已删

### 1.3 脚本

`scripts/query_progress.py --detail`（默认做硬盘验证）

---

## 2. 验证结果

### 2.1 总览

| 指标 | 题数 | 说明 |
|---|---|---|
| DB completed 总数 | 138 | DB 说完成了 |
| 有 proof.md（真正有产出） | **14** | 硬盘验证通过 |
| 无 proof.md 但 work_dir 存在 | 0 | — |
| 无 proof.md 且 work_dir 已删 | **124** | 018 事故受害者 |

**真正成功解出且有硬盘证据的只有 14 题，不是 138 题。**

### 2.2 14 题有 proof.md 的明细

| problem_id | proof.md 大小 | boxed answer | PROOF COMPLETE |
|---|---|---|---|
| deepmath_103k_00000130 | 5903B | ✓ | ✗ |
| amo_bench_00000006 | 5327B | ✓ | ✗ |
| amo_bench_00000008 | 5557B | ✓ | ✓ |
| deepmath_103k_00000174 | 6732B | ✓ | ✗ |
| deepmath_103k_00000521 | 6723B | ✓ | ✗ |
| deepmath_103k_00000571 | 4839B | ✓ | ✗ |
| deepmath_103k_00000688 | 10791B | ✓ | ✗ |
| deepmath_103k_00000716 | 6235B | ✓ | ✓ |
| deepmath_103k_00000773 | 7250B | ✓ | ✓ |
| deepmath_103k_00000939 | 9420B | ✓ | ✓ |
| deepmath_103k_00001035 | 5463B | ✓ | ✗ |
| deepmath_103k_00001066 | 2936B | ✓ | ✗ |
| deepmath_103k_00001285 | 3948B | ✓ | ✗ |
| deepmath_103k_00001365 | 2385B | ✓ | ✗ |

14 题全部有 boxed answer。4 题有 PROOF COMPLETE 标记，10 题没有（但 DB final_status=COMPLETED 且有 proof.md 产出，说明 launcher 判定为完成）。

### 2.3 124 题无 proof.md 的 ended_at 分布

| 日期 | 题数 | 说明 |
|---|---|---|
| 2026-08-18 | 39 | 018 事故当天 |
| 2026-08-19 | 82 | 018 事故次日 |
| 2026-08-20 | 3 | 018 事故第三天 |

124 题全部集中在 2026-08-18~20，这正是 018 事故（teardown 误删生产目录）的时间窗口。work_dir 路径为 `/Volumes/data/math-agent-glm5.2-tmux-agents-dir/p27-continuation/p27-full-<pid>`，这些目录已被删除，proof.md 永久丢失。

---

## 3. 根因分析

### 3.1 018 事故

2026-08-18 的 018 事故中，teardown 脚本误删了 `/Volumes/data/math-agent-glm5.2-tmux-agents-dir/p27-continuation/` 下的生产目录。DB 中的 run 记录保留了 completed 状态，但硬盘上的 proof.md 产出随目录一起被删。

### 3.2 DB 与硬盘不一致

DB 的 `status=completed` 只反映 launcher 的判定结果，不保证硬盘产出存在。这是一个已知的设计缺陷——launcher 在 finalize 步骤更新 DB status 时，没有同时验证 proof.md 是否落盘。

### 3.3 影响评估

- **124 题的解题产出永久丢失**——无法恢复，需要重新做题
- **DB 中的 124 题 status=completed 是虚假的**——没有硬盘证据支撑
- **真实成功率 = 14/10,069 = 0.14%**（不是 138/10,069 = 1.37%）

---

## 4. 修复建议

### 4.1 短期：修正 DB 状态

将 124 题 status=completed 但无 proof.md 的记录改回 status=prepared，让它们重新进入做题队列。

**注意**：按 `db-delete-backup-first` rule，修改前必须先备份这 124 条记录。

### 4.2 中期：launcher finalize 加硬盘验证

在 `continuation_launcher.py` 的 finalize 步骤中，更新 DB status=completed 之前，先验证 `work_dir/proof.md` 是否存在。如果不存在，标记为 `failed_no_proof` 而非 `completed`。

### 4.3 长期：proof.md 落盘到安全位置

proof.md 不应只存在 work_dir 中（会被 teardown 删）。应该同步落盘到一个安全的归档目录，如 `/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-continuation-proofs/`。

---

## 5. 查询方法

```bash
# 基础进度（含硬盘验证汇总）
python -m scripts.query_progress

# 硬盘验证明细（列出有/无 proof.md 的题）
python -m scripts.query_progress --verify-disk

# 全部维度
python -m scripts.query_progress --detail
```

---

## 变更记录

- v1 · 2026-08-21 · 初始创建，DB completed 138 题中只有 14 题有硬盘 proof.md，124 题是 018 事故受害者
