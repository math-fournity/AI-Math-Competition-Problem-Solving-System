# 065 — 工作包分层 Trajectory 设计缺陷复盘与纠偏记录

> **问题来源**：用户指出，053 吸收的观察者/解题者说明书已经明确要求观察者使用
> `oc-trajectory`——其两层遍历范式来自 `zcode-trajectory`——亲自分析其他 AI 的完整、
> 分层运行现场；新工作包却可能退化成只使用 map、摘要和 notes。
> **性质**：工作包设计缺陷复盘、根因分析、逐包改进方案和本次实际纠偏记录。
> **核心裁定**：这不是新增需求，而是 053 的既有实现级要求在 057~064 到工作包的分解中
> 被有损压缩。

---

## 一、结论

原 12 个工作包的总体产品大图、依赖方向和单包认知负载基本合理，不需要推翻。但是，
“完整分层 trajectory 如何交到 observer 手中、如何证明 observer 真实使用”这一条横切能力
没有形成闭环：

1. WP-03 把实体 skill/reader 压缩成 prompt 中的 `scan→tail→定点read` 词汇和
   `MAP_PATH/EXPORT_PATH`；
2. WP-03 的初次验收只证明模板写了这些词，没有冻结可执行 reader 接口和使用证据；
3. WP-02 强调角色轮换和 notes 结果，没有把 reader 进入 cwd、稳定 idx、tool/error 下钻列成
   核心生产动作；
4. WP-07 要求保存 OpenCode 通知流，却没有明确把通知主源转换成 observer 可用的分层 reader；
5. WP-10 可能只检查 notes 结构，fake observer 可以完全绕过真实 scan/inspect 仍通过；
6. WP-12 只要求 trajectory 路径同构，没有要求分层阅读能力同构；
7. WP-08 可能另造一套浅层 stuck 数据解释，而不是复用同一 runtime/reader 直接事实。

因此，WP-03 初次被判“完成”过早。正确处理不是新增工作包或重写系统，而是：

```text
补正 WP-03 的机器合同、模板和回归
  → 修订所有受影响未来工作包的自包含任务与验收
  → 再开始 WP-02 的生产实现
```

---

## 二、被工作包压缩丢失的原始要求

### 2.1 053/053a 已经明确的架构

权威资产包括：

- `dev-docs/053-v2续传编排技术说明书-观察者做题者递归消化链.md`；
- `dev-docs/053a-v2设计简版-观察者做题者递归消化链.md`；
- `dev-docs/053a-prompt_observer.md`；
- `dev-docs/053a-acp_v2参考实现.py`；
- 原始 repo 中 1962 的 R1~R6 运行资产。

053 不是一篇只讲理念的文档，而是实现级说明书。它规定的完整链条是：

```text
原始 trajectory 实时落盘且永不删除
  → observer 亲自使用 oc-trajectory
  → scan 获得廉价概览
  → tail 收殓工作笔记后的盲区
  → search/read 按需下钻
  → observer 自己决定信息取舍
  → 写分析笔记
  → solver 主要读取最新分析笔记
```

053 同时明确：`oc-trajectory` 的设计范式来自：

```text
/Users/user/skills-devin/zcode-trajectory.md
/Users/user/skills-devin/scripts/zcode_traj.py
```

这个原型采用两层遍历：

- 第一层 `scan` 流式读取大 JSONL，不展开巨大 messages，只列模型调用、turn、finish、error、
  tool、usage、短预览和稳定 `idx`；
- 第二层 `inspect` 用 `idx/message` 定点展开 reasoning、tool input、tool result 和 error。

“完整 trajectory”表示所有原始 reasoning/message/tool/error/usage/终因均可按需访问；它不
表示把几十万、几百万字符全文一次性塞进 observer 上下文。

### 2.2 为什么 map、HANDOVER 和 notes 不能替代 reader

1962 v1 已经证明：Master 把几十万字符推理压成 HANDOVER 裸结论，会产生信息损失和信任
税；“禁止重验”无法替代推导供料，R5 仍然回头重做已闭环情形。

如果新系统只把 `conversation_map.md` 和几个程序挑选的片段交给 observer，本质上仍然是让
程序或 Master 替接手者决定哪些内容重要，重新引入相同根因。

工作笔记也只是索引。最后一次更新工作笔记到实例被截断之间的最新进展只存在于 trajectory
尾部。Observer 还必须能看到真实 tool call/result/error，才能区分：

- “前轮计划运行验证”；
- “前轮实际运行了验证”；
- “命令运行成功”；
- “命令失败或只覆盖有限范围”；
- “模型因预算、provider、rate limit 或 pending tool 中断”。

---

## 三、原工作包哪里不合理

### 3.1 WP-03：验收对象从“能力”退化成“词汇”

WP-03 原文其实写了“必要的最小 trajectory 读取脚本或接口文档”，但初次实施主要完成了：

- observer 模板出现 `scan/tail/search/read`；
- 输入有 `MAP_PATH/EXPORT_PATH`；
- 分析笔记七节结构；
- 无答案 fixture；
- 静态关键词和模板渲染测试。

初次实现没有冻结：

- reader manifest、工具路径和完整原始 trajectory root；
- 共同 CLI 和 backend 适配边界；
- 第一层 scan 的稳定 idx 与“不得展开正文”；
- reasoning、tool input/result、error 的第二层下钻；
- observer 实际调用 reader 的证据；
- map-only 这一错误实现的反例。

因此，测试能证明“prompt 说要 scan”，却不能证明系统存在可使用的 scan 能力。WP-03 的初次
完成状态判早了。

### 3.2 WP-02：只验 notes 结果，不足以证明 053 编排成立

WP-02 的原任务集中在：

- `start_observer/check_observer`；
- notes mtime、非空和角色归属；
- observer/solver 串行轮换；
- notes/trajectory/formal 路径进入 rounds_log。

未来实现者可能采用：

```text
程序生成 conversation map
  → observer 读取 map 和几个片段
  → observer 写分析笔记
```

这种实现可能满足原清单，却没有做到：

```text
程序保存完整原始现场并提供分层 reader
  → observer 自己 scan 全运行脉络
  → observer 自己决定下钻 idx/message/tool
  → observer 自己形成分析笔记
```

包中虽写“observer 首动作 scan/tail”，但没有写清工具如何进入 cwd、原始 trajectory 路径、
稳定 idx、实际使用证据以及 map 不得替代原始数据。

### 3.3 WP-07：设计了完整数据保存，没有设计完整数据消费

WP-07 正确要求 OpenCode ACP 的 thought/message/tool/permission 实时落盘，native export 只作
兜底。但是它没有明确要求实现 OpenCode reader 并把 reader 交给 observer。

这会导致断链：

```text
磁盘拥有完整原始数据
  ≠
observer 能低成本、分层地使用完整数据
```

### 3.4 WP-10：结果断言可能让错误实现通过

只断言 `分析笔记.md` 存在、七节完整、写了尾部和验证欠账，不足以证明 observer 真实使用
了 reader。fake actor 可以直接写真 notes，完全绕过 scan/tail/inspect。

WP-10 原设计缺少这些过程不变量：

- scan 是否实际调用；
- tail 是否实际调用；
- 是否按稳定 idx 做过 inspect/read；
- reasoning/tool/error 是否可定点展开；
- notes 来源锚点是否能回到实物；
- map-only、无 reader 和全文注入是否被拒绝。

### 3.5 WP-12：trajectory 路径同构不等于阅读能力同构

如果 OpenCode 提供分层 reader，而 Devin 只返回 `conversation.json` 路径，backend 切换后
observer 的认知能力会退化。最小后端合同应同构核心阅读行为，不需要强行同构原始 schema。

### 3.6 WP-08：容易重复建设浅层解释器

stuck 证据需要最后 reasoning/message/tool/permission/error、pending tool 和 tail。若不明确
复用 WP-07/WP-12 的 runtime/reader 事实，WP-08 可能再写一套只看 pane、mtime 或日志尾部的
浅层解释器，造成数据口径分裂。

### 3.7 WP-05 与 WP-11：反馈和最终闭包缺少来源锚点审计

形式化不足如果只回流一条审计裸结论，下一 observer 仍然需要重验。审计缺口应附 formal run
路径和必要 trajectory idx/tool 锚点。

WP-11 则必须检查一级文档没有把“map 存在”“notes 存在”误称为 053 架构已经实现。

---

## 四、为什么原设计不合理

### 4.1 直接根因：对 053 做了二次有损压缩

053 表达的是一条实体能力链：

```text
原始数据
  → skill/parser
  → 分层命令
  → observer 实际调用
  → 使用证据
  → notes 来源锚点
```

工作包把它压成了：

```text
scan→tail→定点read
  → 写高质量 notes
```

后者保留了理念词汇，却丢失了可执行实体和可验收过程。这和 HANDOVER 失败的机制具有相似
性：富含实现细节和推导依据的资产被压缩成几条裸结论后，未来执行者只能自行猜测缺失部分。

### 4.2 当前态与目标态的职责分配不闭合

WP-03“不接生产 launcher”是正确边界，但被错误理解成“不需要冻结 reader 的机器接口”。
正确分工应是：

```text
WP-03 冻结行为、字段和测试接口
WP-02/WP-07/WP-12 实现具体 parser 和生产接线
```

而不是把 reader 整体推迟成一个没有明确负责人的未来事项。

### 4.3 测试偏结果，缺少过程不变量

静态 prompt 测试成本低且必要，但不能替代“observer 实际调用工具”的 sim。原设计没有明确
把过程证据分配给 WP-10，验收链因此缺失一环。

### 4.4 对“不要过度设计”的边界掌握不够准确

不建设通用 trajectory 平台是正确的；但不能因此删掉完成核心任务所必需的小型 reader。
奥卡姆剃刀应删除无必要的平台化抽象，而不是删除 observer 获得完整认知的必要工具。

---

## 五、应该如何改进

### 5.1 冻结共同能力，不共用臃肿 parser

所有 backend 共同提供：

```text
scan / tail / search / inspect
reasoning / tool_input / tool_result / error
```

OpenCode、legacy、Devin 各使用小型 adapter 解析自己的 schema。共同的是 CLI 语义、scan 字段、
稳定 idx 和使用证据，不把所有原始格式归一成一个大型平台。

### 5.2 Observer 必须得到工具和完整原始 root

Observer 模板必须有：

```text
TRAJECTORY_TOOL_PATH
TRAJECTORY_ROOT
```

`MAP_PATH/EXPORT_PATH`只能作辅助或兜底。Observer 必须实际执行：

```bash
python3 <reader> scan <root> --json
python3 <reader> tail <root> --chars 8000
python3 <reader> search <root> --pattern '<pattern>'
python3 <reader> inspect <root> --idx 42 --message 6 --reasoning
python3 <reader> inspect <root> --idx 51 --tool-input --tool-result --error
```

分析笔记关键论断应提供 Round、idx、message 或 tool 锚点。

### 5.3 记录实际使用证据

复用 `round_result.json` 或 runtime `tools.jsonl`，记录 reader manifest 和
`trajectory_reads`：

```json
{
  "operation": "inspect",
  "source_round": 7,
  "command": ["python3", "trajectory_reader.py", "inspect", "..."],
  "output_path": "trajectory_reads/inspect-42.json",
  "exit_code": 0,
  "selected_indices": [42]
}
```

不新增 DB、Gate 或控制系统。

### 5.4 增加过程门禁

WP-10 fake reader 必须证明：

- scan 和 tail 真实调用；
- 关键场景存在 inspect；
- scan 不含完整 reasoning/tool 正文；
- notes 来源锚点存在；
- map-only、无 reader 和全文注入均失败。

### 5.5 工作包之间的唯一职责

| WP | 改进后的职责 |
|---|---|
| WP-03 | 冻结共同 CLI、manifest、scan row、模板字段、使用证据和静态回归 |
| WP-02 | 生产角色轮换、legacy 最小 reader、实际调用与登记 |
| WP-07 | OpenCode 原始通知主源、OpenCode reader、复制进实例 cwd |
| WP-08 | 消费同一 runtime/reader 客观事实形成 suspected stuck 证据 |
| WP-10 | fake reader 过程门禁和 1962 来源锚点 |
| WP-12 | Devin 等价 reader，backend 切换后能力不退化 |
| WP-05 | 核对形式化工具实证，并返回带锚点的审计缺口 |
| WP-11 | 最终文档、运营关键词和实物闭包 |

WP-01、WP-04、WP-06、WP-09 保持原职责，不借本次纠偏扩项。

---

## 六、本次是如何改进的

### 6.1 新增机器与架构合同

新增 `src/trajectory_reader_contract.py`：

- reader manifest 的必需能力；
- cwd 内安全相对工具/root；
- 共同 CLI 命令构造；
- scan row 的稳定 idx 和正文禁入；
- observer read evidence 结构。

新增 `docs/architecture/layered-trajectory-reader.md`：

- 053 权威来源；
- 完整/分层的定义；
- scan/inspect 字段；
- observer 强制顺序；
- 实际使用证据；
- 各工作包职责。

这两个文件都不解析具体 backend，不建立通用 trajectory 平台。

### 6.2 补正 WP-03 的实际产物

补正 `templates/v3/prompt_observer_p.md`：

- 增加 `TRAJECTORY_TOOL_PATH/TRAJECTORY_ROOT`；
- 提供实际 scan/tail/search/inspect 命令；
- 把 map/export 降为辅助/兜底；
- 要求 reasoning/tool input/result/error 定点下钻；
- 要求 notes 来源锚点和 reader 使用证据。

补正 `src/prompt_contract.py`：缺少新字段时 fail-fast。

补正 `docs/architecture/round-artifact-contract.md`：增加：

```text
trajectory_reader.json
trajectory_reads/
round_result.trajectory_reader
round_result.trajectory_reads
```

新增无答案 fixture：

```text
tests/fixtures/1962/trajectory_reader_manifest.json
```

补正 `scripts/test_wp03_prompt_contract.py`：验证 manifest、共同命令、scan 正文禁入、inspect
flags 和 read evidence。

### 6.3 修订所有受影响的未来工作包

本次逐文件补正：

- `WP-02-生产观察者解题者核心编排.md`；
- `WP-03-提示词轮次资产合同与1962回归.md`；
- `WP-05-审计AI形式化充分性判定.md`；
- `WP-07-OpenCode-ACP目录配置与Lease生命周期接入.md`；
- `WP-08-Suspected-Stuck与Master-Agent介入.md`；
- `WP-10-全流程Sim-1962与形式化发布门禁.md`；
- `WP-11-历史迁移一级文档与运营闭包.md`；
- `WP-12-Devin-ACP备用与最小后端兼容.md`。

工作包总控增加唯一职责表，明确 WP-01/04/06/09 不负责 reader，避免重复实现和范围膨胀。

### 6.4 一级认知与追踪

README、src README、058、064、模板 README 已加入本补正入口。本 065 是用户要求的完整复盘
文档。WP-03 执行记录会追加补正事实和补正 commit；初次提交历史保留，不重写过去。

---

## 七、改进后的验收标准

### 7.1 WP-03 补正完成

- observer 模板在缺 reader 工具/root 时不能渲染；
- 共同能力包含 scan/tail/search/inspect/reasoning/tool input/result/error；
- scan 有唯一 idx 且不展开正文；
- reader 使用证据可机器校验；
- 1962 fixture 仍不包含最终答案和外部答案路径；
- 不接生产 launcher。

### 7.2 WP-02/WP-07 生产实现完成

- 每实例完整原始 trajectory 逐条落盘；
- reader 进入 observer cwd 并可运行；
- observer 真实执行 scan+tail，按需 inspect；
- notes 来源锚点可回到实物；
- map-only 实现不能通过；
- solver 默认不做全历史考古；
- 同题串行、Gate 和 Round 窗口语义不变。

### 7.3 WP-10 发布门禁完成

- fake reader 过程断言通过；
- 1962 行为和工具使用同时通过；
- backend 切换不退化；
- 大文件 scan 不全文加载；
- 无答案泄漏、secret 或生产路径。

---

## 八、防止本次纠偏再次过度设计

本次明确不做：

- 不新增 WP-13；
- 不建立 trajectory 服务、数据库或 UI；
- 不新增 Gate 或 SOP 步骤；
- 不强制不同 backend 共用一个原始 schema/parser；
- 不让 reader 总结数学内容；
- 不让 solver 默认通读完整历史；
- 不以纠偏名义修改生产 DB/Redis/key 或启动实例。

这次增加的是完成 053 核心任务所必需的最小 reader 合同，不是平台化扩张。

---

## 九、历史与提交记录

纠偏前相关提交：

- `707b4ac`：WP-03 初次实现；
- `1f6d439`：WP-03 初次证据回填。

初次实现中的三角色模板、资产合同和无答案 fixture 仍然有效。本次是在其上补齐分层 reader
实体接口和跨包职责，不撤销历史。纠偏 commit 和最终测试结果已回填 WP-03 执行记录及
工作包总控。

提交前直接验证：WP-03补正回归7/7 PASS；Python编译、reader manifest JSON、行尾与
`git diff --check`通过；065实物存在且README入口已可解析。纠偏未运行生产系统、未修改
DB/Redis/key、未处理用户`tmp/`。

纠偏实现提交：`d0496449cc9afa06c4956270deee6cde8984fabc`。提交态重新运行
`scripts/test_wp03_prompt_contract.py`，7/7 PASS；工作树只剩未跟踪`tmp/`。
