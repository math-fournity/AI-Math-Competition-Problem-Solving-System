# 每轮角色与资产合同

> **状态**：WP-03 冻结的 v3 输入/输出合同；供 WP-02 生产编排、WP-04 形式化交付、
> WP-07 ACP 生命周期和 WP-10 sim 直接消费。
> **边界**：这是目录和证据约定，不是新的 artifact framework。旧续传资产在迁移期继续
> 可读，生产接线只需做路径适配，不重写历史。

## 一、角色序列

一道题只有一个长期 run。数学绝对 Round 单调递增；调度窗口不重置 Round 号。

- Round 1：`solver_initial`，直接解题；
- 后续观察阶段：`observer`，只消化紧邻前轮现场，写分析笔记；
- 后续推进阶段：`solver`，主要读取最新分析笔记，推进一个明确缺口。

观察者和解题者必须是分开的执行实例，同一道题内部串行。观察者不写 proof，解题者不做
全历史考古。角色只是长期管线中的阶段，不是额外题目管线。

## 二、规范目录

新 v3 运行的每个数学 Round 使用独立、永不覆盖的目录：

```text
<run_dir>/
  rounds/
    round<N>/
      prompt.md
      role.json
      runtime/
        notifications.jsonl
        thoughts.jsonl
        messages.jsonl
        tools.jsonl
        tmux.log                 # 非 tmux 后端可缺
      conversation.json          # 后端可导出时保留；不可替代实时通知流
      conversation_map.md        # observer scan/定点读取索引
      trajectory_reader.json     # backend reader manifest/共同能力
      trajectory_reads/          # scan/tail/search/inspect输出与使用证据
      工作笔记.md                 # solver 角色
      分析笔记.md                 # observer 角色
      proof.md                    # solver 候选成功时
      proof_partial.md            # 未完成但已有证明文本时
      formal/
      formal_verification.md
      formal_logs/
      verification/              # 其他临时检查脚本/结果
      round_result.json
```

生产后端可以先在隔离 cwd 运行，再原样归档到上述目录。路径名称如因 legacy 兼容需要适配，
DB 的 `rounds_log` 必须仍能定位同等实物，且同一 Round 的旧文件不得被覆盖。

## 三、所有角色共同必需资产

| 资产 | 要求 | 归属证据 |
|---|---|---|
| `prompt.md` | 本实例实际收到的完整 prompt | 内容 hash + mtime 不早于本阶段开始 |
| `role.json` | run/round/window/role/backend/model/effort/cwd/key lease ID（不含 secret） | 启动前写入，断言回显后补状态 |
| `runtime/notifications.jsonl` | ACP/后端原始通知逐条 flush | 每条时间戳；进程崩溃仍可读 |
| `runtime/thoughts.jsonl` | thinking/reasoning 主源；无该通道时在 role.json 说明 | 逐条 flush |
| `runtime/messages.jsonl` | message chunk | 逐条 flush，可为空但文件保留 |
| `runtime/tools.jsonl` | tool call/update、状态和路径 | 逐条 flush，可为空但文件保留 |
| `round_result.json` | 直接事实：开始/结束、终止证据、资产路径、候选状态 | 收尾时写，不用模型自述代替 |

`conversation.json` 和 `conversation_map.md` 是可选的后端导出/读取辅助。若导出通道截断或
损坏，必须在 `round_result.json` 记录，实时 notifications/thoughts 仍是主证据。

## 四、角色专属合同

### Round 1 / solver

- 必需：`工作笔记.md`（若 thinking 阶段来不及写，必须在结果中明确 missing，而不是伪造）；
- 未完成且已有证明文本：`proof_partial.md`；
- 候选成功：`proof.md`、`formal/`、`formal_verification.md`、`formal_logs/` 全部必需；
- 可以有 `verification/`，但其中脚本和结果不得只留 `/tmp`。

### observer

- 唯一语义交付：`分析笔记.md`；不得写/修改 `proof.md`；
- 分析笔记必须有七节：全局状态、真实前沿和推导骨架、死路、单一主缺口、历史修正、
  形式化覆盖、验证欠账；
- `round_result.json` 记录 scan/tail/search/read 的输入路径和读取区间，供 SOP 抽查是否真实
  消化尾部；另记录 `trajectory_reader` manifest 和 `trajectory_reads` 操作证据；不要求自动
  判断笔记数学质量。只有notes而无scan/tail/inspect证据不能证明053架构已实现。
- reader必须能从稳定idx展开reasoning、tool input/result和error；map/export只作辅助/兜底。

### 后续 solver

- 必需：`工作笔记.md`；主要输入是紧邻 observer 的 `分析笔记.md`；
- `role.json` 记录该 notes 的路径/hash，定点下钻旧档案时记录来源锚点；
- 候选成功包与 Round 1 相同；形式化不足时保留 partial 资产和下一缺口，不写最终正确。

## 五、形式化最小包

`formal_verification.md` 至少包含：原题形式化主命题、proof 的关键 claim、每个 claim 对应的
formal theorem/程序、工具和版本、精确重跑命令、日志路径、`sorry/admit/axiom` 检查、有限
搜索边界、未覆盖项和充分性论证。具体实现与审计规则见 061、WP-04、WP-05。

WP-04 的运行/归档 API、九个稳定报告 marker 和 rounds_log 字段见
`docs/architecture/formal-delivery.md`。结构完整和命令退出 0 均不等于审计充分。

这里不要求所有题使用同一种工具，也不把“命令退出 0”当充分性的全部。普遍命题的有限
Python 扫描默认只算旁证，除非 proof 已证明有限归约覆盖全部情况。

## 六、mtime、归属与收尾

1. 每个阶段启动前记录 `started_at`；只把 mtime 不早于该时间、且路径在本 Round 目录内的
   文件视为本阶段新产物。
2. 同名产物进入新 Round 目录，不覆盖旧 Round。legacy cwd 中的 `proof.md` 在删除前仍按
   现有规则归档 partial。
3. runtime jsonl 从启动即逐条 flush；实例异常退出也不得删除。
4. 临时脚本回收前复制到 `formal/` 或 `verification/`，重跑命令改为归档相对路径。
5. 先收集/校验全部资产，再释放 ACP/key lease；资产收集失败必须留 alert/待人工痕迹。

## 七、确定性验收与语义验收边界

程序可以确定性检查：文件存在、路径归属、mtime/hash、JSONL 可解析、模型回显、命令退出
码、日志存在、是否出现 `sorry/admit` 文本。分析笔记是否真正提供可信数学供料、形式化覆盖
是否充分等语义问题由审计 AI/Master Agent 按 SOP 判断。关键动作仍复用现有 Gate，不新增
平行审批机制。

分层reader的共同CLI、scan字段和使用证据见 `docs/architecture/layered-trajectory-reader.md`
与 `src/trajectory_reader_contract.py`；具体backend parser由WP-02/07/12实现。
