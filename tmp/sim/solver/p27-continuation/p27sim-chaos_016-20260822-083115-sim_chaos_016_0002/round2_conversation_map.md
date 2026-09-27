# Conversation.json 面包屑地图

> 生成程序：`scripts/conversation_mapper.py`
> 遍历原则：不假设schema，递归遍历所有节点

## 第一层：顶层概览

```
  steps  [list, list[1]]
```

## 第二层：steps数组概要（按时间顺序）

共 1 个step

```
  steps[0]  source=agent  [dict[5keys]]  message=0c  reasoning=1360c  tool=无
```

## 第三层：所有step详情

> 以下展开所有step（system/user/agent），确保不遗漏任何节点

### steps[0] (source=agent) 详情

```
steps[0].source  [str, 5c]  agent  ← 来源（system/user/agent）
steps[0].reasoning_content  [str, 1360c] (中字段)  预览: 让我继续深入思考这个问题的下一步。让我继续深入思考这个问题的下一步。让我继续深入思考这个问题的下一步。让我继续深入思考这个问题的下一步。让我继续深入思考这个问题的下一步。让我继续深入思考这个问题的下一步。让我继续深入思考这个问题的下一步。让我继续深入思考这个问题的下一步。让我继续深入思考这个问题的下一步。让我继续深入思考这个问题的下一步。让我继续深入思考这个问题的下一步。让我继续深入思考这个问题的...  ← thinking内容（AI内部思考）
steps[0].message  [str, 0c]    ← 消息内容（TUI输出或用户输入）
steps[0].tool_calls  [list, 0 elements]  ← 工具调用列表
steps[0].metrics  [dict, 1 keys]  ← 指标（token统计等）
  steps[0].metrics.completion_tokens  [int, 25000]  25000  ← completion token数（截断判定用）
```

## 统计摘要

- 总step数: 1
- system step: 0
- user step: 0
- agent step: 1

- agent step中有tool_calls的: 0
- agent step中有observation的: 0
- 总tool_call数: 0
- 截断step数: 1
  - agent step 0 (最后step被截断)