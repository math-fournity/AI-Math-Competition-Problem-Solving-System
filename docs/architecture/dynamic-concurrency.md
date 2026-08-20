# 动态并发设计

## 1. 问题背景

连续工作系统运行中需要调整并发数：
- **rate_limit时降并发**——API速率限制触发后，降低并发减少请求频率
- **API配额充足时升并发**——提高吞吐量
- **夜间/白天不同并发**——根据API负载情况调整

重启launcher来调整并发会中断正在运行的devin实例——这违反优雅停止原则。需要运行期动态调整。

## 2. 设计参考

### 解题系统的实现

解题系统用Redis作为配置中心：
```bash
# 修改并发
python pipe_control.py concurrency 50
# → Redis SET math:config:concurrency 50
# → runner下次poll时读取新值（2-5秒内生效）
```

runner每轮poll从Redis读取并发数：
```python
redis_conc = int(r.get("math:config:concurrency") or args.concurrency)
```

### 错题分析系统的实现

错题分析系统用ArangoDB的batch记录存储并发数：
```python
# launcher主循环每轮从DB读取（continuation_launcher.py 第645-656行）
try:
    batch_doc = db.collection(CONTINUATION_BATCHES_COLLECTION).get(batch_id)
    if batch_doc and "concurrency" in batch_doc:
        db_concurrency = batch_doc["concurrency"]
        if db_concurrency != concurrency:
            print(f"  [concurrency] 并发数调整: {concurrency} → {db_concurrency}（从DB读取）")
            concurrency = db_concurrency
except Exception:
    pass  # DB读取失败时保持当前concurrency，不让DB故障导致launcher崩溃
```

**注意**：concurrency参数（命令行`--concurrency`传入）是启动时的初始值。主循环中每轮从DB刷新，`set-concurrency`命令修改DB字段后，launcher在下次poll时自动读取新值。

**launcher重启不覆盖DB值**：launcher启动时先读DB中已有的concurrency，如果DB有值则用DB的（不覆盖），否则用启动参数初始化。这保证`set-concurrency`设置的值在launcher重启后仍然生效。

修改并发：
```python
db.collection("{name}_batches").update({"_key": batch_id, "concurrency": 20})
```

## 3. 两种方案的对比

| 维度 | Redis配置中心（解题系统） | DB记录（错题分析系统） |
|---|---|---|
| 修改方式 | `redis-cli SET` 或 `pipe_control.py concurrency` | `db.collection.update()` |
| 生效时间 | 下次poll（2-5秒） | 下次poll（poll_seconds间隔） |
| 持久化 | Redis重启后丢失（除非配置持久化） | ArangoDB持久化 |
| 独立命令 | 有（`pipe_control.py concurrency`） | 无（需要写代码修改DB） |
| 适用场景 | 频繁调整、多服务共享配置 | 不频繁调整、与batch记录绑定 |

## 4. 新Pipe如何选择

- **如果并发调整频繁**——用Redis配置中心（参考解题系统）
- **如果并发调整不频繁**——用DB记录（参考Pipe 4）
- **如果需要独立命令**——实现类似`pipe_control.py concurrency`的CLI命令

## 5. 关键约束

**动态并发只影响后续新启动的run**——当前正在running的run不受影响。这是正确的行为：
- 降并发：running的run继续完成，完成后不再启动新run，直到running数<新并发数
- 升并发：running的run继续，立即启动新run填满并发槽

**不能通过动态并发来中断正在运行的run**——那是优雅停止的职责。

## 6. 016事故教训（2026-08-20）

016事故（`dev-docs/016`）揭示了动态并发的一个盲区：set-concurrency本身生效了
（DB concurrency=1，launcher也读到了），但**真实并发是6个**——因为：

1. **内存dict不恢复**：launcher的running/handover_pending是内存dict，重启即清空。
   存量进程变孤儿，不占并发槽、不被监控——set-concurrency对它们无能为力
   （设计内，但放大了事故）。
2. **失控循环**：amo_bench_00000006陷入"旧产物秒判完成→截断重入队→再启动"循环，
   18分钟产生上千个handover session。
3. **四源脱节**：Redis视角"并发"=1，实际进程6个——队列状态与真实进程严重脱节。

**事后加固**：
- A13真实并发四源审计（tmux实际 vs DB vs Redis vs 设定）——见`p27_monitor_spec.md` §A13；
- A14启动抖动检测（行为流水churn_suspects，同题1小时≥5次launch=critical）——见§A14；
- 步进门闸（step_gate）+行为流水（observability）让Master Agent能"看见"流动+"拦住"动作。

**教训**：动态并发只约束新启动是正确的设计，但**存量+孤儿进程不受控**是真实风险——
必须配合A13四源审计+行为流水监控，不能只信DB里的concurrency字段。
