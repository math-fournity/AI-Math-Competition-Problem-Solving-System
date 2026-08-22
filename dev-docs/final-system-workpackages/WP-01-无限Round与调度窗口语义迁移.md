# WP-01 — 无限 Round 与调度窗口语义迁移

> **覆盖 Feature**：RND-01~08、CON-05、REL-06、TST-04
> **依赖**：无
> **核心风险**：当前 `TRUNCATED_AT_MAX` 是永久 completed；错误迁移会丢失继续资格或
> 重复运行旧 Round。
> **状态**：✅ 完成（实现与证据见 `exec-log/WP-01-执行记录.md`）

## 一、目标

把“最多 max_rounds 轮后永久失败”改成“每次调度窗口默认处理若干新 Round；窗口结束释放
资源但题目仍可继续”。绝对 Round 编号跨窗口单调，历史资产不覆盖。历史
`TRUNCATED_AT_MAX` 保持可读，并提供 dry-run 继续候选盘点；本包不未经用户批准批量改 DB。

### 当前代码基线与预期触点

当前 launcher 在出队前和运行终态段两次把达到 max 写入 completed；sim 的 never/h_timeout
也断言永久 `TRUNCATED_AT_MAX`。预期触点：`src/continuation_launcher.py`、DB schema、
Redis queue、result collector、monitor、`src/sim/{scenarios,assert_final,run_sim}.py`、失败池
查询脚本及 059/064 所列一级文档。不要修改原始历史报告内容来伪造一致。

## 二、前置认知

完整读取 057、058、059、064；再读：

- `src/continuation_launcher.py`：`launch_batch`、max 判断、truncated 分支；
- `src/continuation_db_schema.py`、Redis queue、result collector、monitor；
- `src/sim/scenarios.py`、`assert_final.py`、`run_sim.py`；
- `docs/architecture/solve-pipeline.md`、`operational-concerns.md`；
- `docs/sop/SYSTEM_CLOSURE.md`、SOP_Z、monitor spec；
- `scripts/p27_failure_pool_audit.py`。

先用 `rg 'TRUNCATED_AT_MAX|max_rounds'` 全量建影响表，不能只改 launcher。

## 三、目标语义不变量

1. 配置值仅限制本次窗口新执行 Round 数。
2. 绝对 `current_round` 不重置。
3. 窗口结束不进入永久 final/completed 语义。
4. 未解题进入可发现、可重新调度状态。
5. 重启/重入队从下一绝对 Round 开始。
6. `ai_gave_up` 和形式化不足也不剥夺未来继续资格。
7. 已确认数学正确或用户明确放弃才永久停止未解循环。
8. 所有历史 `TRUNCATED_AT_MAX` 可查询，不静默消失。

## 四、实施任务

1. 给窗口额度起无歧义的内部语义/字段；优先兼容现有 CLI，不为改名大重构。
2. 修改 launcher 两处 max 分支：归档、释放、写原因、进入可继续集合。
3. 明确 infra 重试是否消耗窗口额度，并用单测冻结；建议按“成功启动的数学工作 Round”
   计数，但必须以现有数据结构可可靠表达为准。
4. 修改 DB/Redis/result collector/monitor 对永久终态的假设。
5. 增加“重新调度历史未解题”的最小入口或复用 feeder；必须幂等。
6. 新增只读脚本盘点历史 `TRUNCATED_AT_MAX` 及下一 Round，默认 dry-run。
7. 更新 sim：两个窗口跨 R1~R4、候选 proof 审计不足后再继续、gave_up 后可继续。
8. 更新一级文档和行为流水事件语义。

## 五、Gate 与资产

- 复用现有 requeue/finalize/launch Gate；窗口结束不是新增审批系统。
- Gate docstring 移除“到 max 必须永久 TRUNCATED_AT_MAX”的错误论证。
- 窗口结束前检查 prompt/export/notes/partial/formal 路径已登记。
- 不删除或覆盖历史 round；旧 proof 按现有 partial 归档规则处理。

## 六、明确不做

- 不实现最优选题/公平算法。
- 不设置新的默认窗口数字。
- 不自动迁移生产历史 DB。
- 不改 observer/solver 编排（WP-02）。
- 不新增 Gate 或工作流引擎。

## 七、测试与验证

- 单测：绝对 Round、窗口计数、第二次调度、gave_up、审计不足。
- sim：窗口=2 连续两次，最终 R4 完成；R1~R4 资产都在。
- 兼容：历史 `TRUNCATED_AT_MAX` 查询可见，dry-run 不写 DB。
- 直接检查：DB run、Redis、rounds_log、硬盘目录、flow 五源一致。
- `rg` 检查一级现行文档不再宣称 max 是题目寿命；历史报告允许保留并标历史。

## 八、验收 checklist

- [x] 窗口用完不永久 completed/failed
- [x] 未解题可再次调度并从下一 Round 继续
- [x] 绝对 Round 编号和资产不覆盖
- [x] 历史状态兼容和 dry-run 报告存在
- [x] Gate/flow 理由正确
- [x] sim 跨窗口通过
- [x] 未改生产 DB
- [x] 文档同步
