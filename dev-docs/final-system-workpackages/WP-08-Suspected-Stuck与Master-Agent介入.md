# WP-08 — suspected stuck 与 Master Agent 定时介入

> **覆盖 Feature**：SUP-01~08、REL-04/05、OPS-01/02
> **依赖**：WP-02、WP-07
> **核心原则**：程序给证据，Master Agent判断；SOP发现，现有Gate执行。

## 一、目标

将网络/provider/OpenCode抖动导致的无输出变成可观察、可人工智能处置的候选：程序汇总
客观证据，不自动盲kill/盲发继续；SOP_01定时呈现；Master选择等待、继续、结束本轮、重启、
换key或移交用户；动作通过现有Gate并落flow。

### 当前代码基线与预期触点

当前有max runtime、部分stall/rate-limit检测、SOP_01、Gate和flow，但没有ACP活动证据包、
suspected语义或“继续”受控动作。预期触点：ACP runtime状态、monitor、`scripts/sop/checks.py`、
SOP_01及报表、observability、必要的Gate docstring和演练测试。

## 二、前置认知

读 057、058、063、WP-02/07执行记录；再读 ACP通知实现、monitor、SOP_01/checks/report、
StepGate、observability、session registry、rate limit和stall历史（016/034/035/036）。

## 三、证据包

实现最小结构/报表，包含：run/round/role/instance、silent duration、last event、process alive、
pending tool/permission、provider error、prompt response、运行时长、notes/proof/formal mtime、
key内部ID、同key/多key横向概览、notification尾部路径。

不打印secret；不强行计算根因概率。

## 四、实施任务

1. 可靠活动时间更新：thought/message/tool/permission/response/error。
2. 静默阈值来自配置；超过只标 suspected，不写永久终态。
3. SOP_01/checks/report列候选和查法，不新增SOP步骤。
4. 提供安全动作原语：发送一次“继续”、结束Round并刷新资产、基础设施重启/换lease。
5. Master动作要求reason并写flow；“继续”不是自动heartbeat。
6. 结束Round复用kill Gate，先保存资产再释放lease，题目仍可继续。
7. 未介入时保持安全：不无限重发、不反复kill。
8. 发现稳定可确定的新模式时只记录后续改进，不在本包堆启发式。

## 五、Gate裁定

评估“发送继续”是否需要一个最小语义Gate或可安全复用现有Gate，形成有证据的裁定；无论
结果都不得给所有ACP RPC加Gate。kill/requeue/launch继续现有Gate。

## 六、测试/演练

- 正常深思考有chunk，不误报。
- 无chunk但pending tool，证据完整、不自动kill。
- 长静默候选进入SOP；Master不动作时保持一次告警/可复查。
- 手动继续只发一次、reason落flow；模拟恢复。
- 手动结束保存资产、释放lease、下一窗口继续。
- 同key一个异常/两个异常/多key异常横向输出。
- provider错误和rate limit保留现有确定性分类。

## 七、明确不做

- 不实现完美stuck自动分类。
- 不固定300秒为不可改硬常量。
- 不新建Supervisor服务/UI/工作流。
- 不自动调整key capacity。
- 不让Master Agent代推数学。

## 八、验收 checklist

- [ ] 客观证据包完整
- [ ] suspected非终态
- [ ] SOP_01定时可见
- [ ] 等待/继续/结束/重启原语可控
- [ ] 现有Gate与flow承载理由
- [ ] 结束Round仍可续传
- [ ] lease安全
- [ ] 无自动心跳和控制体系膨胀
