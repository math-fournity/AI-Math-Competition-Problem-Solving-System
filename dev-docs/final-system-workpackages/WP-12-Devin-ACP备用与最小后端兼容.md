# WP-12 — Devin ACP 备用与最小后端兼容

> **覆盖 Feature**：BCK-01、BCK-03、BCK-06/07、REL-01、PROD-05
> **依赖**：WP-07
> **历史输入**：037、045、048、049 与旧 WP-U7/V5
> **边界**：实现可用备用和人工受控切换，不默认启用复杂 auto-fallback。

## 一、目标

在 OpenCode ACP 主后端已经接入生产生命周期后，为 Devin ACP 提供同一最小执行合同：启动、
状态、停止、终因、资产和形式化元数据同构。Master Agent 可根据客观健康证据，通过现有
Gate 为后续实例选择备用后端；不复制一套独立解题状态机。

### 当前代码基线与预期触点

当前 035/042 已验证 Devin ACP 信号，045 定义后端接口，048 设计健康/回退，但 src 没有生产
Devin ACP backend。预期触点：WP-07形成的最小执行接口、Devin adapter、模型显式参数、
通知/导出归一、backend选择配置、现有launch Gate、fake ACP测试和运营文档。

## 二、前置认知

读 057、058、060、063、064、065、WP-07执行记录和分层trajectory reader合同；再读
035、042、045、048、049 和 Devin ACP
实测脚本/日志。核对当前 Devin CLI 实际协议，不能只信旧文档行号。

## 三、最小后端合同

两后端必须向上层提供同构的：instance/session ID、role、start/poll/stop、last activity、usage、
finish reason、notification/trajectory路径、proof/formal路径和错误分类。后端差异留在adapter，
observer/solver、无限Round和audit不应复制分支业务逻辑。
“trajectory路径同构”必须提升为“分层阅读能力同构”：scan/tail/search/inspect、稳定idx、
reasoning/tool input/result/error/usage/终因均可达；具体ATIF/ACP解析留在Devin adapter。

## 四、实施任务

1. 实现 Devin ACP adapter，显式指定可用模型；Devin无effort接口时如实记录，不伪造。
2. 权限请求、通知、终态和导出归一到WP-07资产合同。
   同时实现Devin小型reader并满足`layered-trajectory-reader.md`；不能只返回conversation路径。
3. backend选择来自DB/配置，不写死；默认切换策略仍由用户决定。
4. 提供人工受控选择动作：Master检查主后端证据，经现有launch Gate让后续实例用Devin。
5. 切换不改变题目run/Round编号，不覆盖OpenCode历史资产。
6. OpenCode恢复后不自动切回；交Master/用户判断。
7. 若auto-fallback代码已有需求，仅准备默认关闭的最小能力和测试，不在本包擅自启用。

## 五、key边界

062 的OpenRouter key lease针对OpenCode实例。Devin凭据/认证按其现有机制管理，不强行塞入
同一key表；但所有secret都遵守不进Git/log/flow。切换时必须释放已结束OpenCode实例的lease，
不因选择Devin破坏内部key对账。

## 六、明确不做

- 不建第三套launcher/DB/Redis队列。
- 不删除legacy `-p`。
- 不默认开启auto-fallback或自动切回。
- 不实现复杂健康评分；复用WP-08证据和Master判断。
- 不把后端抽象扩大成无关通用插件平台。

## 七、测试

1. fake Devin ACP正常完成、BUDGET_STARVED、错误、停止。
2. 同一题OpenCode轮后切Devin继续，Round/资产连续。
3. 两后端conversation/notes/formal元数据同构。
4. 人工切换reason进入Gate/flow。
5. OpenCode恢复后不会自动切回。
6. secret扫描和legacy回归。
7. OpenCode/Devin reader共同能力和使用证据同构，backend切换后observer不退化。

## 八、验收 checklist

- [ ] Devin ACP adapter满足最小合同
- [ ] 不复制业务状态机
- [ ] 资产和终因同构
- [ ] 分层trajectory reader能力同构
- [ ] 人工受控切换通过现有Gate
- [ ] auto-fallback默认未启用
- [ ] key/secret边界正确
- [ ] fake ACP和跨后端续传测试通过
