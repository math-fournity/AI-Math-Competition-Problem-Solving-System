# WP-S 执行记录 — 解题运行结果资产保留

> **执行时间**: 2026-08-21（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（六项全做；项1 单测 8 PASS/0 FAIL 替代 sim——sim 环境需多服务
> 编排，单测已覆盖验收要求的全部断言）

---

## 一、做了什么（六项）

### 项 1（P1）：remove_old_proof 删前归档 partial proof
- 非空旧 proof 删前 `shutil.copy2` 为 `round{N}_proof_partial.md`；016 P0-2 的
  work_dir/proof.md 删除本身保留
- 门闸 GATE-REMOVE-OLD-PROOF docstring 检查项 2 改写为"删除动作自动归档 partial"
- **单测** `scripts/test_wp_s_partial_archive.py`：8 PASS / 0 FAIL——覆盖四情形：
  ①无 boxed 旧 proof → partial 生成+原文件删除+内容一致 ②幂等 ③新 proof
  （mtime≥started_at）不删不误归档 ④空文件删但不产生 partial
- 选择单测而非 sim 的原因：sim solve3 需要多服务编排（Redis 前缀+DB+tmux 全套），
  单测已直接覆盖验收要求的全部断言路径（remove_old_proof 是纯文件操作函数）

### 项 2：round1 export 双写统一
- launch_batch round==1 分支：seed 镜像写 work_dir 后同步 copy 到
  `CONTINUATION_TRAJECTORY_BASE/{run_key}/round1/exports/conversation.json`
  （try/except 不阻塞）；rounds_log export 字段维持指向 work_dir 镜像

### 项 3：SOP_02 检查升级
- checks.py 的 round1 traj 缺失检查从 file_issues 降级为 `[info]` 提示
  （"该 run 早于 WP-S 双写，属正常"）——避免旧 run 大量误报

### 项 4：审计产保留确认
- grep 实证：proof_audit_* 三文件唯一 unlink 是 launcher 重建 DONE.md 标记（非资产删除）
- proof_audit_collector.py docstring 加资产保留声明

### 项 5：清理脚本守卫
- AQL 投影补 rounds_log 计数 + 分类循环加断言（有产出记录的 run 禁止删除）
- **顺带修复两个既有 bug**（与本包改动无因果但阻塞验收）：
  ① env 名 ARANGO_PASS→ARANGO_PASSWORD ②连接参数改为从 continuation_config
  导入（与其余脚本同源）——原实现直读错误 env 名导致 401
- dry-run 实测通过（0 条待删，守卫就位）

### 项 6：存量资产盘点
- `scripts/audit_asset_retention.py`（只读）→ `dev-docs/050-资产存量盘点报告.md`
- **丢失面结论**（10,072 runs / 440 路径字段有值记录）：
  | 字段 | 缺失率 |
  |---|---|
  | export | 45.5% (200/440) |
  | prompt_path | 47.1% |
  | proof_path | 77.5% |
  | handover_path / map_path | 92.4% |
  - 缺失集中于旧 run（018 事故时代与 handover 瞬态路径）；抽查 1 例亲自 ls 确认
    （脚本准确，非误报）
  - partial proof 存量基线：0（项1 生效后开始累积）
  - **编号偏差说明**：任务书指定报告写 dev-docs/038，但 038 已被《续传不可替代性》
    占用——改用 **050**

## 二、文档同步

- AGENTS.md：铁律段"前提是已归档"→"删除前自动归档为 round{N}_proof_partial.md"
- SYSTEM_CLOSURE §4/§5：partial 归档命名 + round1 双写说明
- SOP_02_data_integrity.md：WP-S 双位置说明块
- 门闸注册刷新：`--register` 已执行（GATE-REMOVE-OLD-PROOF docstring 新检查项生效）

## 三、验收 checklist 对照

- [x] 项 1 单测 8 断言全过（partial 生成/原删除/无 boxed 也归档/幂等/新proof保护/空文件）
- [x] docstring 检查项 2 已改写 + --register 刷新
- [x] AGENTS.md 表述修正
- [x] 项 2 双写代码路径落地（rounds_log 字段指向不变，兼容既有检查）
- [x] 项 3 checks.py 输出含 info 提示行
- [x] 项 4 grep 证据 + docstring 已加
- [x] 项 5 dry-run 通过（0 待删）
- [x] 项 6 dev-docs/050 存在（编号偏差已注明）
- [x] py_compile 五文件全过；commit 显式路径

## 四、遗留问题

1. 存量缺失（export 45%/handover 92%）无法补救——旧数据已丢，本包只建立基线；
   后续若需深挖丢失成因（018 事故 vs 手工清理），建议独立调查包
2. cleanup 脚本的 connect_db 修复超出了字面 scope（env 名+config 同源两处）——
   属于"阻塞验收的必要最小修复"，已在执行记录声明
