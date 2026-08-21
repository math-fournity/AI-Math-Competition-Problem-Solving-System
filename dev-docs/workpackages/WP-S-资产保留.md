# WP-S — 解题运行结果资产保留（partial proof 归档最优先）

> **优先级**: 第二批（**项 1 是 P1 漏洞修复，优先执行**；项 2-6 可分次）
> **依赖**: 无（项 1 独立；项 6 存量盘点独立）
> **预计规模**: continuation_launcher.py ~25 行 + cleanup 脚本 ~10 行 + 盘点脚本
> ~120 行 + 文档同步
> **性质**: 代码修复（资产丢失路径）+ 数据盘点。**项 1 改判定相关路径——需 sim 门禁**

---

## 0. 给执行 AI 的第一句话

AGENTS.md 新硬约束"解题运行结果资产保留铁律"写"remove_old_proof 删除的前提是上一轮
proof 已归档"——**这个前提在代码里不存在**：`remove_old_proof()` 直接 `unlink()`，
归档只在成功轮（有 boxed）执行。无 boxed 的部分证明（AI 写了一半的证明）从不归档、
必被删除——现场实证：`00001653` 的 work_dir/proof.md（3777 字节、无 boxed、
dead_session）就是待删资产。你要让删除前先归档（两全：016 防误判不受影响），并完成
资产保留的其余 5 项。

## 1. 背景（为什么）

- 用户需求（032 §7.6）："没做出来的 round 的 conversation.json 包含 AI 的完整推理
  过程……是分析 AI 能力边界的宝贵数据，比做出来的更有价值"——部分 proof 同理
  （AI 推到哪里断掉的物证）
- 033 发现漏洞 → 034 独立验证接受 → AGENTS.md 铁律已立但表述与代码不符（:238 的
  "前提是已归档"）——本 WP 让代码兑现铁律并修正表述
- 016 P0-2 的教训（旧 proof 残留被误判完成）**不能因此回退**：work_dir/proof.md
  仍然要删（防误判），只是删前归档副本

## 2. 前置认知加载清单

| # | 加载什么 | 提取什么 |
|---|---|---|
| 1 | `AGENTS.md` 搜"解题运行结果资产保留铁律" | 铁律全文：必须保留清单表 / 唯一允许的删除 / 反模式（本 WP 是它的代码兑现） |
| 2 | `src/continuation_launcher.py` 的 `remove_old_proof`（搜 GATE-REMOVE-OLD-PROOF） | 现状：unlink 无归档；docstring 检查项 2 说"上轮proof已归档"——你要让这句话变真 |
| 3 | 同文件 `overwrite_round1_seed`（搜 GATE-OVERWRITE-ROUND1-SEED） | round1 镜像逻辑（项 2 在此扩展）；注意 trajectory 路径常量 CONTINUATION_TRAJECTORY_BASE 的用法（搜 `round_traj_dir =`） |
| 4 | 同文件搜 `shutil.copy2`（1 处，成功轮归档） | 归档的现有姿势（copy2 保 mtime） |
| 5 | `scripts/cleanup_continuation_runs.py`（111 行） | 项 5 的守卫对象：只删 prepared 的 DB 记录 |
| 6 | `scripts/sop/checks.py` 的 `check_02_data_integrity` 的 file_checks 结构 | 项 3 的挂载点（round==1 分支现在只查 export） |
| 7 | 现场证据（直接检查）：`ls -la /Volumes/data/math-agent-glm5.2-tmux-agents-dir/p27-continuation/p27-full-deepmath_103k_00001653/proof.md` + `grep -c boxed <该文件>` | 亲眼看到待删资产（0 匹配=无 boxed） |
| 8 | `dev-docs/033` §三.1（round1 export 两处皆无的实测） | 项 2/6 的背景：旧数据 round1 export 已丢，只对新 run 生效 |

## 3. 现场事实基线（2026-08-21 09:30）

| 事实 | 复核命令 |
|---|---|
| remove_old_proof 无归档（unlink 直删） | 读函数体 |
| 归档只在 proof_found 分支（shutil.copy2 → round{N}_proof.md） | grep shutil.copy2 |
| 00001653：proof.md 3777B 无 boxed，DB dead_session | §2.7 的命令 |
| 旧 run round1 export 双缺（traj 无 round1/ 目录、work_dir 无 round1_export.json） | `ls` 两个位置 |
| cleanup_continuation_runs.py 只删 DB prepared 记录，不删文件 | 读 §分类逻辑 |
| work_dir 无自动清理代码（032/033 已查） | grep rmtree scripts/ src/（仅 sim/teardown 有守卫） |

**基线漂移预期**：WP-K 会改 dead_session 分支（ai_gave_up）——不冲突（归档逻辑在
remove_old_proof，判定在别处）。若 WP-K 已执行，rounds_log reason 可能出现 ai_gave_up，
盘点脚本的统计口径包含它。

## 4. 任务分解

### 项 1（P1，先做）：remove_old_proof 删前归档 partial proof

改 `remove_old_proof()`：
```python
proof = Path(work_dir) / PROOF_FILE_NAME
if not proof.exists(): return
if started_at is not None and proof.stat().st_mtime >= started_at: return  # 新proof不删（原逻辑）
# 新增：删前归档——无论是否有 boxed，非空 proof 都是资产（AGENTS.md 资产保留铁律）
if proof.stat().st_size > 0:
    partial = Path(work_dir) / f"round{round_num}_proof_partial.md"
    import shutil; shutil.copy2(proof, partial)
    logger.info(f"[{work_dir}] 旧proof归档为 {partial.name}（{proof.stat().st_size}B）后删除")
proof.unlink()
```
要点：
- 命名 `round{N}_proof_partial.md`——与成功轮的 `round{N}_proof.md`（完整归档）区分，
  SOP/统计不混淆
- 同轮多次启动时覆盖旧 partial（同一份文件的内容快照，保留最新即可）
- **门闸 docstring 检查项 2 改写**：从"上轮 proof 已归档 → 查法：ls round*_proof.md"
  改为"删除动作会自动归档 partial → 查法：ls round{N}_proof_partial.md 在删除后存在"
- 同步修正 `AGENTS.md:238` 一段："但前提是上一轮的 proof 已归档"改为"删除前自动归档
  为 round{N}_proof_partial.md（2026-08-21 WP-S 起）"

**sim 门禁**：remove_old_proof 是 016 P0-2 的关键路径——跑 `src/sim` 的 solve3 剧本
确认无回归（sim 覆盖了旧 proof 残留场景）。sim 跑法见 `dev-docs/017`（简版：
`SIM_MODE=1` + 对应 env 隔离 + 运行既有剧本脚本）。若 sim 环境不可用，写最小单测
`scripts/test_wp_s_partial_archive.py`（构造 work_dir+假 proof+调 remove_old_proof+
断言 partial 生成且原文件删除+再次调用幂等）。

### 项 2：round1 export 双写统一

改 `overwrite_round1_seed()`（或其调用处——保持门闸函数行为单一，选调用处
`launch_batch` 的 round==1 分支）：镜像写到 work_dir 的同时，复制一份到
`CONTINUATION_TRAJECTORY_BASE/run_key/round1/exports/conversation.json`（mkdir
parents=True）。rounds_log 的 round1 条目 export 字段**维持指向 work_dir 镜像**
（兼容现有 SOP_02 检查与历史数据），执行记录里注明双位置。

### 项 3：SOP_02 检查升级

`checks.py` `check_02_data_integrity`：round==1 的 file_checks 增加
`("export_round1_traj", "输出", False)`（可选检查——旧 run 没有；查的是项 2 的新位置，
缺失时计 warning 不计 issue，输出提示"该 run 早于 WP-S"）。

### 项 4：审计产保留确认（代码层无删改，加防线说明）

grep 确认 proof_audit_* 代码无删除 export/work_dir 的逻辑（预期无）。在
`proof_audit_collector.py` 的 docstring 加一句："审计 work_dir 与 export 不论成败永久
保留（资产保留铁律）——失败审计的 conversation.json 是审计质量分析数据"。

### 项 5：清理脚本守卫

`cleanup_continuation_runs.py`：
- 分类循环加防御断言：`assert not r.get('rounds_log'), f"有产出记录的 run 禁止删除: {r['key]}"`
  （当前逻辑天然满足——prepared 无 rounds_log；断言防未来改坏）
- docstring 加一行"绝不删有 rounds_log 的 run（资产保留铁律）"

### 项 6：存量资产盘点

写 `scripts/audit_asset_retention.py`：
```
扫描 p27_continuation_runs 全部 run 的 rounds_log 每条：
  - export / prompt_path / proof_path / handover_path / map_path 各字段
  - Path.exists() 判存在，统计：
    每类字段的 (总数/存在数/缺失数/缺失率)
    缺失样本列表（最多列 20 条/类，含 run_key+路径）
  - 特殊口径：round1 条目按"work_dir round1_export.json 或 traj round1 位置任一存在"计
  - partial proof 存量：统计现有 work_dir 的 round*_proof_partial.md（项 1 前=0，作基线）
输出报告到 stdout + 写 dev-docs/038-资产存量盘点报告.md（含表格与结论：
丢失面多大、主要集中在哪类、是否需要补救建议——只报告不动数据）
```

### 收尾：py_compile 全部改动 + sim/单测 + commit + 文档

文档同步：AGENTS.md（:238 修正+当前问题清单更新）、SYSTEM_CLOSURE §5 rounds_log 说明
（partial 归档命名）、`docs/sop/SOP_02_data_integrity.md` 检查项段加 round1 双位置说明。

## 5. 禁止事项

- ❌ work_dir/proof.md 的删除本身**不能省**（016 P0-2：残留 proof 会被误判完成——
  你只加"先归档"，不加"不删除"）
- ❌ 不动成功轮归档逻辑（round{N}_proof.md 命名与时机不变）
- ❌ 盘点脚本**只读**（发现缺失记录，不尝试"修复"）
- ❌ 不清理历史 orphan partial 文件（不存在的东西无从清理）

## 6. 验收 checklist

- [ ] 项 1：单测/sim 输出贴记录——断言含"partial 生成+原文件删除+无 boxed 也归档+幂等"
- [ ] 项 1：GATE-REMOVE-OLD-PROOF docstring 检查项 2 已改写；`--register` 刷新
- [ ] AGENTS.md:238 表述已修正（"自动归档"替代"前提是已归档"）
- [ ] 项 2：新 run 的 round1 出现在 traj round1/exports/（可构造一个 dry 场景或读代码
      路径+单测断言；若无法起真 run，单测 overwrite 调用处的行为）
- [ ] 项 3：check_02 输出含新检查行（贴一段输出）
- [ ] 项 4：grep 证据（审计代码无删除逻辑）+ docstring 已加
- [ ] 项 5：cleanup 脚本断言存在（构造一条假有 rounds_log 数据走 --dry-run 验证拒绝路径）
- [ ] 项 6：dev-docs/038 报告存在，含每类字段缺失率表
- [ ] py_compile 过；commit 显式路径

## 7. 完成汇报要求

执行记录：每项的验证输出、038 报告摘要（丢失面结论）、sim/单测选择及原因、
AGENTS.md diff 摘要。

## 8. 审计对照

1. 项 1 我会实际构造场景验证（假 work_dir+无 boxed proof+调函数）——partial 生成、
   原文件没了、再跑一轮（新 proof 不删分支）不误归档
2. 038 报告的数字我会抽查 3 个 run 亲手 ls 核对（直接检查——审计者自己也守铁律）
3. AGENTS.md 与代码表述一致性重查（这是 032 犯过的错：铁律写了代码没兑现）
4. sim solve3 或等效单测的证据必须在执行记录里
