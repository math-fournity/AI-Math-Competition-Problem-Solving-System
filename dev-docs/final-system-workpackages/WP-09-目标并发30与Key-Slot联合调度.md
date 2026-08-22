# WP-09 — 目标并发 30 与 key slot 联合调度

> **覆盖 Feature**：CON-01~06、KEY-03/04、PROD-02、TST-03
> **依赖**：WP-01、WP-06、WP-07
> **用户参数**：目标最大解题管线30；实际并发和key capacity由用户/DB决定。

## 一、目标

在不写死默认 concurrency 的前提下，让调度同时遵守：DB实际并发、目标容量上限30、key
可用slot和同题串行。提供隔离环境下30并发容量验证；不在本包擅自把生产调到30。

### 当前代码基线与预期触点

当前DB动态并发已完成，launcher按running+handover占槽；无目标30权威配置、key slot和ACP
实例实物对账。预期触点：batch schema/control、launcher取槽、WP-06 key接口、monitor A13、
SOP状态输出和并发竞态测试。不得恢复任何代码默认concurrency。

## 二、前置认知

读 057、058、059、062、064、WP-01/06/07执行记录；再读 dynamic-concurrency、launcher
取槽逻辑、DB batch、monitor A13、session registry、sim并发断言和WP-G历史。

## 三、调度不变量

```text
active_solve_pipelines <= DB concurrency <= target_max(30)
active_key_leases_per_key <= key.capacity
启动实例前同时有pipeline slot和key slot
同题observer/solver任意时刻最多一个活实例/lease
```

30 是当前产品容量目标和可配置上限，不是 launcher 参数默认值；若用户以后更新目标，由
权威配置/文档调整，不改散落代码常量。

## 四、实施任务

1. 为 batch/配置表达目标最大值与实际值，选择单一权威来源；无值时明确报错/提示。
2. 调度前组合检查pipeline slot和key slot；取得失败不污染DB/Redis running。
3. 处理并发值运行中下降：不kill已有实例，只影响新启动（沿用现有原则）。
4. key capacity下降/disabled时不超发；活跃超额列待处理，不盲kill。
5. monitor/SOP展示：实际管线、DB值、目标30、key总capacity/活跃lease，不显示secret。
6. A13从tmux四源适配到backend/lease实物，不大重写其它SOP。
7. 建30并发fake ACP压力/竞态测试，证明无同题双实例、无超额lease、无重复入队。

## 五、明确不做

- 不自动把生产concurrency改30。
- 不做参数推荐实验。
- 不自动调整key capacity。
- 不实现复杂公平/优先级算法。
- 不把审计并发偷偷计入解题30；其他ACP角色单独在文档中如实报告实际资源。

## 六、测试

1. DB concurrency 1/10/30。
2. concurrency>30 拒绝或要求用户明确更新目标权威配置；行为单测。
3. key slot不足时只启动可承载数量。
4. 15 keys×capacity2 支撑30 fake实例；不得视为默认生产配置。
5. 同题角色切换不短时双lease。
6. 动态降并发不kill已有实例。
7. 竞态下无超额/重复。
8. monitor直接对账backend和lease。

## 七、验收 checklist

- [ ] DB实际并发仍是动态权威
- [ ] 目标最大30被正确表达而非默认硬编码
- [ ] pipeline/key双槽原子安全
- [ ] 同题串行
- [ ] fake 30并发测试通过
- [ ] monitor/SOP可见且无secret
- [ ] 未触碰生产并发值
