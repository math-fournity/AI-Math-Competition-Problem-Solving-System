# WP-D — SOP_01 精简（A16/A17 移交 SOP_07 + 门闸数修正 + 抽样直接检查）

> **优先级**: 第三批（WP-C 之后）
> **依赖**: WP-C（SOP_07 已接管 A16/A17）
> **预计规模**: checks.py ~40 行删改 + SOP_01 文档 ~20 行 + 直接检查抽样 ~25 行
> **性质**: SOP 调整 + 检查升级

---

## 0. 给执行 AI 的第一句话

SOP_01 的审计健康段（A15-A18）是 WP-7 时代加的简化版——现在 SOP_07 专门承载审计
检查（WP-C），SOP_01 要瘦身去重：A16/A17（审计完成数/失败率）移走、A15（队列停滞
快速预警）和 A18（门闸等待）按归属精简，同时把 §8.5 的过时门闸数（9 个，实际 13 个）
修正，并给进度检查加"直接检查"抽样（028 教训的 SOP_01 落地——WP-B 附录清单第一项）。

## 1. 背景（为什么）

- 去重：A16/A17 与 SOP_07 的项 1 完全重复（同一数据源同一统计）——SOP_01 已经很重
  （11 检查项+门闸+流水+全景），这正是 031 建 SOP_07 的理由之一
- 文档漂移：SYSTEM_CLOSURE 已是 13 门闸（9 续传+4 审计），SOP_01 §8.5 仍写"9 个
  语义动作（launcher 8 + feeder 1）"（031 C4，032/034 验证）
- 直接检查升级：SOP_01 的进度检查只看 DB status 分布（间接）——028 事故（DB 138
  completed 硬盘 14 proof）本可在第一轮就被"抽样 ls proof.md"抓住（WP-B rule 的
  核心案例）

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | **确认 WP-C 完成**（SOP_07 上线+真跑过） | A16/A17 的接管者已就位——你才能删 |
| 2 | `scripts/sop/checks.py` 的 `_check_audit_pipe_health`（全文） | 现状 A15-A18 实现——你的删改对象 |
| 3 | `docs/sop/SOP_01_system_health.md` §8.5（门闸段）+ §1 检查清单段 | "9 个语义动作"的位置；检查项数字口径说明段（"8 项基础检查+门闸Y通道+行为流水=10 项"那段也要顺一遍） |
| 4 | `.devin/rules/direct-verification-ironlaw.md` 附录（WP-B） | 你是"附录清单第一项"（SOP_01 进度检查抽样）的落地者 |
| 5 | `scripts/monitor_check_continuation.sh`（SOP_01 的自动化底座，跑一遍看输出结构） | 进度检查的数据来自哪段——你的抽样加在 checks.py 层还是 sh 层（**加在 checks.py 层**——sh 是共享脚本） |

## 3. 现场事实基线

- `_check_audit_pipe_health` 现状四段：Redis 队列+A15 / A16 count+A17 失败率+分布 /
  A18 门闸
- SOP_01 §8.5 首句："`@gated`装饰器把系统的 9 个语义动作（launcher 8个：… +
  feeder 1个：初次入队）变成可单步跟踪的门闸"
- SOP_01 §"数字口径说明"：check_01 实际输出 10 项的描述（A15-A18 加入后已过时——
  一并修正）
- 复核：`grep -n "9 个语义动作\|9个语义动作" docs/sop/SOP_01_system_health.md docs/patterns/StepGate.md`

**基线漂移预期**：WP-C 后 checks.py 已有 check_07；SOP_01 的 `check_01_system_health`
函数体（调用 _check_pending_gates/_check_flow_snapshot/_check_system_panorama/
_check_audit_pipe_health 四件套）不变。

## 4. 任务分解

### 任务 1：`_check_audit_pipe_health` 瘦身

改后结构（保留两段，删两段）：
```
--- Pipe 5 审计快速概览（详查见 SOP_07）---
  Redis paudit 四队列数（保留）
  A15 队列停滞快速预警：pending>0 且 running==0 且（可选增强：对比上一轮报表
    snapshot 的 pending 值无变化）→ 提示（保留在 01 做快速预警的理由：SOP 循环里
    01 的检查频率视角最先看到停滞）
  A18 简化：waiting 的 AUDIT 门闸计数 + "详单见 SOP_07 / --pending"（闭包输出
    移到 SOP_07 与通用 _check_pending_gates，01 只报数量）
  删除：A16 count / A17 失败率与分布段（SOP_07 项 1 已接管且更全）
  段尾加一行：审计系统完整健康检查（产出实物验证/交叉验证/孤儿对账）→ 见步骤 07
```

### 任务 2：SOP_01 进度直接检查抽样（checks.py 的 check_01 末尾加）

```python
def _check_completed_sample_files():
    """步骤01例行：completed 抽样实物验证（直接检查铁律——028 教训）。
    DB status=completed 不等于硬盘有 proof.md。随机抽 5 个 completed run，
    直接 ls/grep 验证。"""
    # AQL: status=='completed' SORT RAND() LIMIT 5 → run_key, work_dir, rounds_log 末条 proof_path
    # 对每个：proof_path（或 work_dir/proof.md fallback）→ exists? + grep '\\boxed'?
    # 输出：5 行逐条判定；缺失/无 boxed → 醒目 ⚠️（028 信号）
```
并在 `check_01_system_health` 的调用链加 `_check_completed_sample_files()`。

### 任务 3：SOP_01 文档同步

- §8.5："9 个语义动作（launcher 8 + feeder 1）"→"13 个语义动作（续传 9：launcher 8 +
  feeder 1；审计 4：见 SOP_07 / `--list`）"
- §"数字口径说明"段重写：check_01 实际输出项数（基础 8 + 门闸 Y + 行为流水 + 全景 +
  审计快速概览 + **completed 抽样实物验证**）——数字以改后代码为准点一遍
- §2 判断表加一行：| completed 抽样有缺失/无 boxed | 数据完整性事故信号 | 立即按 028
  处置（暂停选题引用该批数据+人工核查）|

### 任务 4：验证 + commit

```
python -m scripts.sop._set_next 01 后真跑 check_01（或直接跑 monitor sh + 手动调
python -c "from scripts.sop.checks import check_01_system_health; check_01_system_health('p27-full')"）
# 断言：无 A16/A17 输出；有 A15/简化 A18；有 completed 抽样 5 行输出
python -m scripts.sop._set_next <恢复>
```
commit：checks.py / SOP_01 文档。

## 5. 禁止事项

- ❌ 不删 A15（快速预警留 01——WP-C §5 也明确了）
- ❌ 不动 `_check_pending_gates`/`_check_flow_snapshot`/`_check_system_panorama`
- ❌ 抽样检查不修数据只报告（028 的处置是人/AI 判断）
- ❌ 不顺手改 StepGate.md 的"9 个"（那是 WP-F 的全量文档同步范围——除非你想在本 WP
  一并做，做则列入执行记录）

## 6. 验收 checklist

- [ ] `grep -n "A16\|A17\|audit_failure_rate" scripts/sop/checks.py` → 在
      `_check_audit_quality_review`/check_07 之外无残留（SOP_01 路径清零）
- [ ] check_01 真跑输出：含审计快速概览（A15/计数式 A18）+ completed 抽样 5 行（贴记录）
- [ ] SOP_01 §8.5 写 13 个；数字口径段与代码输出一致
- [ ] 判断表新增 028 处置行
- [ ] py_compile；commit 显式路径

## 7. 完成汇报要求

执行记录：删改 diff、真跑输出全文、文档段落前后对照。

## 8. 审计对照

1. 真跑 check_01 核对段落数与文档口径一致
2. 抽样检查我会拿它输出的一个 run 亲手复核（直接检查）
3. A16/A17 的功能在 check_07 中健在（交叉跑一次）
