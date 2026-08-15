# analysis-devin-failure-system

> **用途**：用并发devin cli实例分析失败题——判定每道失败题是"方向出错"还是"token不够"，并分类卡点类型。
>
> **核心设计**：devin cli在运行时不调用任何工具，只读AGENTS.md中的内容（题目+标准答案+AI历史thinking），在TUI中输出XML格式的分析结果。程序通过export的conversation.json收集结果。

## 架构

```
data_collector.py     ← 从DB+题库+trajectory收集三类数据，构造AGENTS.md
        ↓
analysis_launcher.py  ← 并发启动devin cli（tmux session，无工具调用）
        ↓
result_collector.py   ← 从export/pane中提取XML分析结果
        ↓
aggregator.py         ← 汇总所有分析结果，输出报告
```

## 组件

| 文件 | 职责 |
|---|---|
| `src/config.py` | 路径常量、DB连接、并发配置 |
| `src/data_collector.py` | 从ArangoDB获取失败题列表，从题库获取标准答案，从trajectory获取thinking，构造AGENTS.md |
| `src/analysis_launcher.py` | 并发启动devin cli（tmux），监控运行状态，判定完成 |
| `src/result_collector.py` | 从export的conversation.json或tmux pane中提取XML分析结果 |
| `src/aggregator.py` | 汇总所有分析结果，按维度1/维度2统计，输出JSON报告 |
| `src/db_schema.py` | ArangoDB集合定义（analysis_runs, analysis_events） |
| `templates/analysis_agents_md.md` | AGENTS.md模板（分析任务说明+输出格式） |

## 用法

```bash
# 1. 收集数据，构造AGENTS.md
python -m src.data_collector --batch-id analysis-batch-1 --limit 100

# 2. 并发启动分析
python -m src.analysis_launcher --batch-id analysis-batch-1 --concurrency 10

# 3. 收集结果
python -m src.result_collector --batch-id analysis-batch-1

# 4. 汇总报告
python -m src.aggregator --batch-id analysis-batch-1
```

## 输出格式

devin cli输出的XML格式（在TUI中）：

```xml
<analysis>
  <dimension1_verdict>DIRECTION_ERROR</dimension1_verdict>
  <dimension1_explanation>AI used polynomial analysis but standard solution uses mod p</dimension1_explanation>
  <dimension2_turning_point_type>mod_p_grouping</dimension2_turning_point_type>
  <dimension2_explanation>Standard solution groups by mod 4 to find contradiction</dimension2_explanation>
  <ai_direction_summary>AI explored polynomial factorization</ai_direction_summary>
  <standard_solution_key_technique>mod 4 grouping reveals hidden sign structure</standard_solution_key_technique>
</analysis>
### ANALYSIS COMPLETE
```

## 数据源

详见 `eight-system/runs/midhint/data_source_map.md`

## 设计原则

1. **devin cli无工具调用**：AGENTS.md中包含所有需要的信息，devin cli只读不写
2. **多组件解耦**：数据收集、启动、收集、汇总四个组件独立运行
3. **模仿solver_harness**：tmux session管理、DB记录、并发控制
4. **XML输出格式**：避免JSON的bash转义问题，XML的尖括号在tmux中更稳定
5. **程序化收集**：通过export的conversation.json提取XML，不依赖人工读取
