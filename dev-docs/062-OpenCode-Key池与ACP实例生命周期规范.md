# 062 — OpenCode key 池与 ACP 实例生命周期规范

> **覆盖 Feature**：KEY-01~10、CON-03/06、REL-04、TST-03
> **外部来源**：`/Users/user/database/email-project.md`
> **目录配置参考**：`/Users/user/init-opencode.sh`
> **实施**：内部 key 池 `WP-06`；ACP 接入 `WP-07`
> **安全**：本文不记录任何真实 key、数据库密码或凭据值。

---

## 一、所有权分层

### 外部原表

`email_project.openrouter_keys` 是领取来源。系统选取 `status=active` 的记录后，在原表标记
`deactive`，表示 key 已被本系统取走，外部项目不得再分配。外部 schema 文档当前没有列
`deactive` 枚举，但脚本和用户裁定明确使用它；未来文档同步应补枚举。

### 本系统内部 key 表

领取后由本系统长期管理。ACP 实例回收只释放系统内部使用名额，不把外部记录恢复 active。

---

## 二、容量与 lease

key 与 ACP 不是永久一对一。每个 key 有用户/配置决定的 `capacity`，每个 ACP 实例取得一个
lease：

```text
available_slots = capacity - active_leases
```

必须保证：

- 每个 ACP 实例有唯一明确的 lease；
- 同一 key 可被多个实例使用；
- `active_leases <= capacity`；
- capacity 不在代码写死为 1 或 2；
- 初期可以配置 1，未来经用户决定改为 2 或其他值。

内部最小记录应能表达：内部 key ID、外部记录 ID、秘密值、状态、capacity、活跃实例关联、
领取/释放时间。存储技术和字段细节由 WP-06 根据现有 DB 模式最小实现，不发展成通用密钥
管理平台。

---

## 三、原子领取

`init-opencode.sh` 当前先查询一个 active key，再更新 deactive；并发领取时存在竞争窗口。
未来系统必须以原子或可验证互斥方式完成“选择+标记”，确保同一外部名额不被多个领取者
重复取走。实现前先只读核对外部表；任何变更都记录外部 ID，不打印 secret。

---

## 四、实例启动顺序

```text
1. 当前有解题管线槽
2. 找到内部 available_slots>0 的 key
3. 为 ACP instance_id 原子登记 lease
4. 准备该实例独立工作目录
5. 按 init-opencode.sh 的 provider 结构写 cwd/opencode.json
6. 启动 OpenCode ACP，cwd 必须是该目录
7. 显式设置 model/effort 并回显断言
8. 记录 instance_id、run、round、role、key内部ID和资产路径
```

目录配置结构为 OpenRouter provider、`baseURL=https://openrouter.ai/api/v1`、`apiKey=<lease
对应secret>`。不得在 repo 根写一个所有实例共享的生产配置。

若写配置、启动或模型断言失败，在确认没有活实例后回滚 lease；失败证据保留。

---

## 五、实例回收顺序

```text
1. 确认 ACP 已结束或经 Gate 安全停止
2. 刷新并关闭通知落盘
3. 保存 prompt、thought/message/tool、proof、formal、日志
4. 更新实例/run 状态
5. 删除或隔离含 secret 的临时 opencode.json（具体安全方式由WP裁定）
6. 释放该 instance 的 lease
7. 该 key 的一个 slot 回到内部可用容量
```

释放一个 lease 不等于整个 key 空闲；同 key 可能仍有其他活跃实例。

---

## 六、崩溃与对账

launcher 重启或进程崩溃时，程序提供确定性对账：内部 lease、backend 实例、DB/Redis、工作
目录和最后通知。只有确认旧实例不再使用 key，才能释放 lease；不确定时列给 SOP/Master
Agent，不盲目复用导致超容量。

不需要新审批系统。启动/kill 仍受现有 Gate；lease 是其下的资源操作。

---

## 七、秘密保护

- 真实 key 不进 Git、prompt、proof、notes、flow、alert、普通 status 输出。
- 日志只用内部 key ID；不复制 `init-opencode.sh` 输出 key 前 25 字符的行为。
- `opencode.json` 必须被忽略/隔离，测试使用假 key。
- 外部 DB 密码和连接 secret 不写入本 repo 文档或 fixture。
- 诊断时不得输出完整 key 池。

---

## 八、与 30 并发的关系

目标最大 30 条解题管线不等于 30 个 key。可启动实例上限同时受：

```text
DB实际管线并发值
目标容量30
内部key可用slot总数
backend/模型实际健康
```

若 15 个 key 各 capacity=2，理论可提供 30 个 lease；这只是例子，不是默认配置。审计等
其他 OpenCode ACP 角色也必须领取 lease，其实际资源是否与解题并行由后续运行配置决定。

---

## 九、最小测试

1. 外部 active→deactive，内部出现可用 key；重复领取失败。
2. capacity=1 并发两个请求，仅一个成功。
3. capacity=2 两实例成功、第三个等待/失败，不超额。
4. 两个目录的 opencode.json 对应各自 lease；允许同 key 在容量内重复。
5. 启动失败回滚 lease。
6. 同 key 两实例中一个结束，只释放一个 slot。
7. launcher 崩溃后对账，不把仍活实例的 lease 释放。
8. 30 个并发请求在假 key 池上无超额、无重复实例 lease。
9. Git/status/log/flow 中不出现假 key 明文（使用检测模式测试）。

---

## 十、非目标

- 不自动预测每个 key 最佳 capacity。
- 不建立复杂 key 评分、计费、轮换或云 KMS 平台。
- 不自动把外部 deactive 恢复 active。
- 不用 key 管理新增 Gate；复用现有实例启动/回收控制点。
