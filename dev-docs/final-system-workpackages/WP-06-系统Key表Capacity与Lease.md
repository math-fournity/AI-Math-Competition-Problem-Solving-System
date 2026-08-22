# WP-06 — 系统 key 表、capacity 与 lease

> **覆盖 Feature**：KEY-01~05、KEY-08~10、CON-06、TST-03
> **依赖**：无
> **外部状态风险**：真实领取会把外部记录改 deactive；默认只实现/测试/dry-run，真实领取需
> 用户确认。

## 一、目标

建立最小内部 key 池：可从外部 active 原子领取并标 deactive；内部 key 有可配置 capacity；
ACP 实例原子取得/释放 lease；不泄漏秘密。给 WP-07/09 提供清晰接口。

### 当前代码基线与预期触点

当前repo没有内部key schema/模块/控制命令；`init-opencode.sh` 是外部单次领取脚本，且选择
与更新分离。预期触点：新增最小key schema/访问模块、必要的控制/查询入口、隔离DB测试和
安全文档；不改生产ACP启动路径。

## 二、前置认知

读 057、058、062、064；只读检查：

- `/Users/user/database/email-project.md` schema；
- `/Users/user/init-opencode.sh` 的 active→deactive 与配置结构；
- 本 repo DB schema/collection模式、事务/更新能力、测试fixture。

不得在输出、文档、测试快照中打印真实 key 或数据库密码。

## 三、最小数据语义

字段命名可按现有约定裁定，但必须表达：内部ID、外部记录ID、secret、状态、capacity、活跃
lease/实例关联、时间。可用独立lease记录或可原子更新的嵌入结构，选择最简单且能证明并发
正确的方案。

## 四、实施任务

1. schema和唯一索引：外部ID/api key去重，instance lease唯一。
2. `claim_external_key`：选择active+标deactive+写内部表；设计原子性/竞争测试。
3. `lease_key(instance_id,...)`：选择剩余slot并原子占用。
4. `release_lease(instance_id)`：幂等，只释放该实例一个名额。
5. `mark_disabled/exhausted/set_capacity`：只提供显式运营接口，不自动调参。
6. status/查询只输出内部ID、capacity、lease数，不输出secret。
7. dry-run列候选外部ID，不修改外部表。
8. fake DB/隔离集合并发测试；真实外部调用必须显式开关和用户批准。

## 五、并发不变量

- active_leases≤capacity；
- 同instance最多一个活lease；
- release幂等；
- 启动失败可释放；
- capacity降低不得制造“静默超额”，需拒绝或标待处理；具体最小行为单测冻结；
- 外部deactive领取后不在ACP回收时恢复active。

## 六、安全

- secret字段不进入repr/log/flow/alert；
- 测试用假key；
- 不把真实key写Git；
- init脚本打印前25字符的行为不复制；
- 错误信息不包含完整opencode.json。

## 七、明确不做

- 不生成生产opencode.json（WP-07）。
- 不实现自动capacity学习、评分、成本优化、KMS平台。
- 不真实领取key，除非用户在执行时批准数量/环境。
- 不新增Gate；key lease是实例启动动作下的资源操作。

## 八、测试与验收

- [ ] 外部领取原子性/去重测试
- [ ] capacity=1/2并发租约测试
- [ ] 第三请求不超额
- [ ] release幂等和启动失败回滚
- [ ] 崩溃遗留lease可查询但不盲释放
- [ ] secret泄漏扫描通过
- [ ] dry-run零外部写
- [ ] WP-07/09接口文档和fixture就绪
