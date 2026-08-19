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
