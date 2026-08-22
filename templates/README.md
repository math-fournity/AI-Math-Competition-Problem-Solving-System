# 解题提示词模板

## 当前默认合同

`v3/` 是 WP-03 冻结的通用三角色模板：

- `prompt_round1_p.md`：首轮解题者；
- `prompt_observer_p.md`：专职观察者；
- `prompt_solver_p.md`：后续专职解题者。

占位符和严格渲染接口见 `src/prompt_contract.py`；每轮产物见
`docs/architecture/round-artifact-contract.md`。WP-03 只冻结接口，生产接线由 WP-02 完成。

`formal_verification_TEMPLATE.md` 是 WP-04 的形式化覆盖报告模板；九个 HTML marker 是
解题侧检查和 WP-05 独立审计的稳定入口。运行/归档方法见
`docs/architecture/formal-delivery.md`。

Observer 模板的 `TRAJECTORY_TOOL_PATH/TRAJECTORY_ROOT` 和共同CLI来自
`docs/architecture/layered-trajectory-reader.md`。`MAP_PATH/EXPORT_PATH`只是辅助/兜底，
不能删除reader字段或恢复成摘要驱动。

## v2 参考模板

`v2/` 仍被独立 `src/v2_pipeline.py` 使用，也是 1962 方法论参考，但其形式化交付和路径合同
不完整，不能作为未来生产 v3 的默认模板。

原始 1962 的 `prompt_roundN.md` 把“观察档案”和“继续解题”放进同一实例，已被实验证明会
挤压预算并诱发倒退；本 repo 不提供该混合模板，也不得在生产默认路径恢复它。若为历史复验
读取，只能作为对照资产，不能注册为可选角色。
