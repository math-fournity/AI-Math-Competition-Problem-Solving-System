# SOP检查报表 — step_OP 运营知识刷新

> **填写说明**：本模板由 `scripts/sop/run.py` 自动复制到D盘报表目录。AI加载后逐项检查并填写，填写完用edit写回同一文件。
>
> **打勾规则**：`[x]` 通过 · `[!]` 有问题 · `[ ]` 待检查 · `[-]` 不适用
>
> **本步骤核心**：每轮循环末尾刷新运营知识（硬约束/外部索引/快速开始/SOP机制）+ 环境验证。这是循环最后一步，完成后cycle+1回到01。

---

## 系统快照摘要

| 指标 | 值 |
|---|---|
| 当前轮次 | （从snapshot.json或_state.json读取） |
| ARANGO_DB | （echo $ARANGO_DB） |

---

## 检查项清单

### 一、环境验证（ENV-01~07）

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| E1 | ARANGO_DB环境变量 | `echo $ARANGO_DB`输出xishujuzhen_math_glm52 | [ ] | |
| E2 | ArangoDB连接 | `python3 -c "from src.continuation_db_schema import connect_db; print(connect_db().properties())"` | [ ] | |
| E3 | Redis连接 | `python3 -c "from src.continuation_redis_queue import ping; print(ping())"`输出True | [ ] | |
| E4 | D盘挂载 | `ls /Volumes/data/`能列出内容 | [ ] | |
| E5 | .env已source | echo $ARANGO_DB不为空 | [ ] | |

### 二、运营知识刷新确认

| 编号 | 检查项 | 检查方法 | 结果 | 详情 |
|---|---|---|---|---|
| K1 | 硬约束已读 | 上方SOP_OP文档的10条基础+4条016/017/018新增，读一遍确认无变化 | [ ] | |
| K2 | 外部文档索引已读 | 上方索引表，确认知道每个文档在哪、讲什么 | [ ] | |
| K3 | 快速开始已读 | 上方5步环境配置，确认当前环境匹配 | [ ] | |

---

## 发现的问题

### Critical
（在此填写，或写「无」）

### Warning
（在此填写，或写「无」）

### Info
（在此填写，或写「无」）

---

## 执行的操作
（在此填写，或写「无操作」）

---

## 未修复的问题及原因
（在此填写，或写「无」）

---

## 下一轮建议
（在此填写，或写「无」）