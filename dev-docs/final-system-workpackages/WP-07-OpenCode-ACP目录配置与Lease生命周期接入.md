# WP-07 — OpenCode ACP 目录配置与 lease 生命周期接入

> **覆盖 Feature**：KEY-06/07、KEY-08/09、AST-04/05、REL-04、CON-03
> **依赖**：WP-02、WP-06
> **吸收旧调查**：042~046、045后端接口、053参考实现；只实现当前必要接线。

## 一、目标

每个 OpenCode ACP observer/solver 实例启动前取得内部 key lease，在独立 cwd 按
`init-opencode.sh` 结构写 `opencode.json`，显式设置模型/effort并回显断言；运行中实时保存
通知；实例结束和资产收集后释放 lease。失败/崩溃不泄漏或超额复用名额。

### 当前代码基线与预期触点

`src/v2_pipeline.py` 能启动OpenCode ACP并断言模型/effort、实时落thoughts，但使用固定模型和
独立批处理，未接内部lease/生产registry。预期触点：ACP执行模块或当前v2模块的最小提取、
生产launcher接线、session registry、资产路径、graceful shutdown、fake ACP测试；不删除
legacy tmux后端。

## 二、前置认知

读 057、058、060、062、064、WP-02/06执行记录；再读：

- `src/v2_pipeline.py`、`scripts/run_v2_batch.py`；
- 042~046 和 `dev-docs/053a-acp_v2参考实现.py`；
- OpenCode ACP通知/模型配置探针测试；
- graceful shutdown、session registry、资产保留规则。

## 三、实施任务

1. 定义最小 ACP instance context：instance/run/round/role/cwd/key内部ID/lease/backend状态。
2. lease 成功后在 cwd 原子写配置；权限限制；确保配置不被Git追踪。
3. initialize/session/new/model/effort回显fail-fast。
4. prompt、thought/message/tool/permission实时落盘；native export仅作为兜底并验证JSON。
5. 完成/BUDGET_STARVED/异常/优雅停止都刷新资产。
6. 正常结束：收集后释放lease；启动失败：确认无活实例后回滚；崩溃：进入对账，不盲释放。
7. 将 backend session 与现有 registry/DB/flow 对应；不要求一次消灭legacy tmux。
8. 输出中只记录key内部ID，不打印secret/opencode.json正文。

## 四、Gate

- 启动仍受现有launch Gate；Gate检查有管线槽、有key slot、cwd和资产路径。
- kill仍受现有kill Gate；增加通知刷新和lease安全检查。
- 底层ACP RPC、写配置、通知落盘不加Gate。

## 五、异常路径

- 无key slot：不启动实例，不污染running。
- 配置写失败：释放lease，保留错误。
- 模型/effort断言失败：关闭实例、归档日志、释放lease。
- provider/network错误：分类并交现有重试/Supervisor。
- launcher崩溃：重启后对账实例和lease。
- export 64KB截断：notification jsonl为主源，不能误删。

## 六、明确不做

- 不启用自动Devin fallback。
- 不删除legacy后端。
- 不实现key capacity调优。
- 不建立新的通用后端平台超过当前接口需要。
- 不直接放量30。

## 七、测试

1. fake ACP + fake key，两个cwd配置隔离。
2. 同key capacity=2 两实例成功，第三个不启动。
3. model/effort断言失败回滚。
4. prompt/notification/proof/formal资产完整。
5. 正常/异常/优雅停止lease生命周期。
6. launcher崩溃对账不超额复用。
7. secret泄漏扫描。
8. observer/solver串行，同题不持有两个活lease。

## 八、验收 checklist

- [ ] per-instance cwd/opencode.json
- [ ] key lease正确占用/释放
- [ ] 模型/effort回显断言
- [ ] 通知实时落盘
- [ ] 全异常路径不泄漏secret或lease
- [ ] 现有Gate复用
- [ ] fake ACP/sim通过
- [ ] legacy路径未破坏
