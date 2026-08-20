# 018 — teardown误删生产目录事故报告（2026-08-20）

> **性质**：AI（ZCode）在全流程模拟系统（017）收尾清理时误删生产 D 盘
> 目录。本文按铁律8（痕迹保留）完整记录根因链、损失清单、恢复动作与
> 加固，防止再犯。**责任人是我（AI）**——护栏设计不对称是我写的代码。

---

## 1. 事故经过

时间线（2026-08-20）：

1. 017 的 sim 建设完成，7 剧本全绿，进入收尾清理；
2. 我在 shell 手动 export 隔离环境执行
   `python -m src.sim.teardown --batch-id all-clean --purge-db --purge-files`；
3. **漏设 `SOLVER_BASE`/`TRAJECTORY_BASE`** → config 回落默认值（生产 D 盘
   路径）；
4. teardown 的护栏只检查了 ARANGO_DB 和 P27_REDIS_PREFIX 两项（都通过了
   ——我确实设了），**没有检查文件根**——而 setup.py 的护栏是三重检查
   （含文件根）。**创建侧和销毁侧护栏不对称**；
5. `shutil.rmtree` 删除了：
   - `/Volumes/data/math-agent-glm5.2-tmux-agents-dir/p27-continuation/`（生产
     work_dir 根：5958 个题目的工作目录）
   - `/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-continuation/`
     （生产 trajectory 根：各轮 export/tmux 日志）

万幸：生产 launcher 当时**不在运行**（tmux 无生产 session），没有题目在
误删后 dequeue 被烧成 launch_error。

## 2. 损失清单（诚实盘点）

| 数据 | 状态 | 说明 |
|---|---|---|
| 124 个 completed run 的 proof.md 文本 | ❌ **永久丢失** | DB 只存路径不存内容；rmtree 不进废纸篓；D盘APFS无快照（已查证） |
| 全部 run 的各轮 export（conversation.json） | ❌ 丢失 | 中间产物/审计材料 |
| 各轮 HANDOVER/prompt/map 文件 | ❌ 丢失 | 中间产物 |
| run 4712 的截断证据 export | ❌ 丢失 | 该 run 已被 collector 重置 prepared，将重跑 |
| 5958 个 prepared 的 work_dir | ✅ **已重建** | collector 重跑（problem_list.json 源头 + 原始 seed export 源头均在 dpb-* trajectory 目录，未受损）；抽样 500/500 验证通过 |
| DB 全量数据（runs/rounds_log/events/batches） | ✅ 完好 | 判定结论、轮次元数据都在 |
| 124 个 completed 的 COMPLETED 判定结论 | ✅ 完好 | final_status 分类（选题直接依赖）不受影响；受影响的是"证明文本复核"能力 |

## 3. 根因链

1. **直接原因**：手动 export 隔离环境时漏设两个文件根变量；
2. **设计缺陷（我的责任）**：teardown 的 guard 不完整——setup 有三重护栏
   （SIM_MODE + ARANGO_DB + 文件根），teardown 只有两重（ARANGO_DB +
   Redis前缀）。**破坏性操作的护栏必须与创建侧对称，且覆盖全部环境维度**；
3. **放大因素**：`--purge-files` 对生产默认路径直接 rmtree，无二次确认、
   无 dry-run 列表预览；
4. **深层教训（数据架构）**：proof 是解题成果的唯一凭证，却是"盘上单点
   文件 + DB只存路径"——单点丢失。**重要成果必须入库双写**。

## 4. 已完成的修复与加固

1. **teardown 护栏补全**：文件根检查加入（SOLVER_BASE/TRAJECTORY_BASE
   任一指向 /Volumes/data 或未设置即拒绝）——与 setup 对称；
2. **teardown session 匹配修复**：`batch_id in name` 因 run_key[-40:]
   截断失配漏杀（stall 剧本残留两个 fake session 实证）→ 改为 sim 题目
   id 强制 `sim_` 前缀匹配；
3. **proof 入库加固**：finalize_run_completed 现在把 proof 文本（≤100KB）
   写入 continuation_results——DB 成为 proof 第二份存档，本次丢失的
   124 份之外不会再有同类损失；
4. **数据恢复**：collector 重跑重建 5958 work_dir（含 4712 重置 prepared，
   P0 修复后它将正确走截断续传路径而非误判 dead）。

## 5. 防再犯规则（写给未来的我/AI）

1. **清场类代码（teardown/purge/clean）的默认值永远不该指向生产**——
   找不到隔离标记就拒绝，而不是回落默认；
2. 破坏性批量操作（rmtree/drop/flush）执行前必须先 dry-run 列出将删除
   的目标并比对预期——这次如果有"将删除：/Volumes/data/..."的预览，一眼
   就能发现不对；
3. 手动 export 环境变量是脆弱操作——隔离入口应只有 `run_sim` 一个
   （它程序化设置全量环境），setup/teardown 的 `__main__` 应当要求从
   run_sim 调用或至少打印将操作的全部路径；
4. 成果文件单点 = 未来事故。任何"只此一份"的产物都要问：丢了怎么办？

## 6. 遗留影响与建议

- 124 份 proof 文本不可恢复。若 Mid-Hint 选题只需 final_status 分类，
  零影响；若需 proof 复核，这 124 题失去文本证据（rounds_log 元数据
  仍记录了当时判定依据的 reason 字符串）；
- **生产 launcher 下次重启将加载 017 修复的 5 个 bug fix + 018 的 proof
  入库**——重启是净收益；
- 建议生产重启前先跑一轮 `run_sim --scenario solve3` 作发布门禁
  （017 §7）。

## 7. 关联

- 起源：`dev-docs/017-全流程模拟系统设计方案.md`（本次事故发生在 017
  收尾时；017 的 sim 价值判断不受影响——它首日捕获了 5 个真 bug，本事故
  是其清理环节的人为失误+设计缺陷）
- 修复代码：`src/sim/teardown.py`（护栏+匹配）、`src/continuation_launcher.py`
  （finalize proof 入库）
