# 分层 trajectory reader 与 observer 使用合同

> **权威来源**：053 §3/§4、053a observer prompt、原始1962 `oc-trajectory` 实验；
> `zcode-trajectory.md`/`zcode_traj.py` 是两层遍历方法原型。
> **性质**：既有架构要求的补正，不是新需求，也不是新的通用平台。

## 一、不可退化的核心

Observer 必须亲自使用分层工具消化上一 AI 的完整原始运行现场。Master/程序只保存原始资产、
提供工具和路径，不替 observer 挑选“重要内容”或生产 HANDOVER。`conversation_map.md`、工作
笔记和 tail 都只是索引，不能替代可下钻的完整 trajectory。

“完整”表示所有 reasoning/message/tool/error/usage/终因均可按需访问；不是把全文一次性塞进
上下文。正确模式是第一层廉价概览，再用稳定定位参数展开少数关键细节。

## 二、共同能力合同

每个实际 backend 的小型 reader 必须提供：

```text
scan      不展开正文的全运行概览，输出稳定idx
tail      最后思考/事件，收殓工作笔记后的盲区
search    跨完整原始数据定位关键词/对象
inspect   按idx/message展开reasoning、tool input/result、error
```

共同 CLI 语义：

```bash
python3 <reader> scan <trajectory-root> --json
python3 <reader> tail <trajectory-root> --chars 8000
python3 <reader> search <trajectory-root> --pattern '<pattern>'
python3 <reader> inspect <trajectory-root> --idx 42 --message 6 --reasoning
python3 <reader> inspect <trajectory-root> --idx 51 --tool-input --tool-result --error
```

具体 parser 不共用：OpenCode ACP、legacy export/ATIF、Devin ACP 各自适配自己的 schema。共同
的是行为与证据，不把不同格式硬塞进庞大抽象框架。

## 三、第一层 scan 输出

scan 必须流式读取大文件，不展开完整 messages/reasoning/tool 正文。每行至少含：

```text
idx / event_type / role / started_at / finish_reason / error_name
tool_names / usage / source_ref / 短text_head（可选）
```

backend 有 turn/request/full-tail-delta 等概念时应额外保留；例如 ZCode 必须用
`messagesKind/messageOffset` 重建上下文，不能把 tail/delta 当完整历史。OpenCode 应保留 ACP
notification类型、message/tool ID、pending状态和BUDGET_STARVED直接证据。

## 四、第二层 inspect

稳定 idx 必须能展开：

- reasoning/thinking 原文；
- assistant message；
- tool/permission 输入；
- tool result/update/error；
- provider/backend error；
- usage、finish reason、模型/effort回显；
- 原始数据位置和时间。

任何大正文只在用户/observer明确指定 idx/message 时展开。Reader 自身不得总结数学内容。

## 五、Observer 强制顺序

```text
读前轮工作笔记（索引，可缺）
  → 实际执行scan
  → 实际执行tail
  → search/inspect关键结论、死路、tool和error
  → 必要时按锚点下钻更早Round
  → 边分析边写分析笔记
```

分析笔记的关键论断要给来源 Round + idx/message/tool 锚点，并区分“计划执行”和“真实执行”。
Solver 默认只读最新分析笔记；只有明确疑点和锚点时才定点下钻旧 trajectory。

## 六、实际使用证据

Observer 产生的 `round_result.json`（或同等现有资产）至少记录：

```json
{
  "trajectory_reader": {
    "schema_version": 1,
    "backend": "opencode_acp",
    "command_prefix": ["python3", "trajectory_reader.py"],
    "trajectory_root": "inputs/round7/trajectory",
    "capabilities": [
      "scan", "tail", "search", "inspect",
      "reasoning", "tool_input", "tool_result", "error"
    ]
  },
  "trajectory_reads": [
    {
      "operation": "scan",
      "source_round": 7,
      "command": ["python3", "trajectory_reader.py", "scan", "...", "--json"],
      "output_path": "trajectory_reads/scan.jsonl",
      "exit_code": 0,
      "selected_indices": []
    }
  ]
}
```

证据可来自 runtime tools.jsonl 自动采集，不要求 observer 手填，也不新建DB/Gate。生产检查
至少看到 scan+tail；需要核实结论/tool时看到 inspect。只有 notes 存在不能证明架构正确。

机器合同在 `src/trajectory_reader_contract.py`：校验 reader manifest、scan row、共同命令和
读取证据。它不解析backend数据，也不判断分析笔记数学质量。

## 七、工作包职责

| WP | 职责 |
|---|---|
| WP-03 | 冻结本合同、observer工具字段、无答案fixture和静态接口回归 |
| WP-02 | 接生产角色轮换；legacy路径提供最小reader；登记实际使用证据 |
| WP-07 | OpenCode ACP原始通知流和OpenCode reader；放入每实例cwd |
| WP-08 | 消费同一runtime/reader事实做suspected stuck证据，不另造浅层检测 |
| WP-10 | fake reader断言scan/tail/inspect真实调用和来源锚点 |
| WP-12 | Devin ACP提供等价reader能力，不只返回trajectory路径 |

WP-01/04/06/09不负责reader实现，不得被借机扩项；WP-05可用reader核查解题/审计工具使用，
WP-11最终审计文档和运营闭包。
