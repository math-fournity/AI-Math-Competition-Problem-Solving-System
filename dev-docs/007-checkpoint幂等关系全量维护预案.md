# 007-checkpoint幂等关系全量维护预案

**日期**：2026-08-19
**性质**：工作包预案（checkpoint 幂等关系全量维护的分析和拆解计划）
**触发**：ENV-07 幂等维护时发现 154 个 checkpoint 中只有 5 个有追溯关系（覆盖率 3.2%）

---

## §1 现状

### 1.1 数据

| 指标 | 数值 |
|---|---|
| checkpoint 总数 | 154 |
| 有追溯关系的 | 5（ENV-07, MON-A1, MON-A2, RUN-01, ENV-01） |
| 孤立的（无追溯关系） | 149 |
| 覆盖率 | 3.2% |

### 1.2 现有追溯关系

```
ENV-01  --part-of--> WP-01
ENV-07  --implements--> 7个launcher函数（函数级）
ENV-07  --depends-on--> config.py / continuation_config.py
ENV-07  --specified-by--> checklist/ENV-07.md
MON-A1  --implements--> analysis_control.py（文件级+函数级）
MON-A1  --specified-by--> p27_monitor_spec.md（文件级+章节级）
MON-A1  --part-of--> WP-09
MON-A2  --part-of--> WP-09
RUN-01  --implements--> monitor_check.sh
RUN-01  --part-of--> WP-09
```

---

## §2 分类分析

### 2.1 需要追溯关系的（107个）

这些 checkpoint 对应代码中的具体实现，应该记录 `implements` 关系（精确到函数级）。

| 门类 | 数量 | 对应什么代码 | 追溯目标 |
|---|---|---|---|
| EXEC | 28 | `continuation_config.py` 中的常量/模板 | `continuation_config.py::常量名` 或 `continuation_config.py` |
| SESS | 12 | `continuation_db_schema.py` 等 session 管理代码 | `continuation_db_schema.py::函数名` |
| LAUNCH | 10 | launcher 中的具体函数 | `src/continuation_launcher.py::函数名` |
| CTRL | 9 | CLI 命令实现（start/stop/status/health） | `src/continuation_launcher.py::函数名` 或 `src/analysis_launcher.py::函数名` |
| RUN | 8 | 检查脚本 | `scripts/monitor_check.sh` 等 |
| ENV | 7 | 配置定义 | `src/config.py` / `src/continuation_config.py` |
| AUDIT | 7 | 审计代码 | `monitoring/` 下对应文件 |
| MON-A | 12 | `monitoring/analysis_control.py` 等 | `monitoring/analysis_control.py::函数名` |
| MON-B | 9 | `monitoring/` 续传质量检查代码 | `monitoring/` 下对应文件/函数 |
| MON-C | 5 | `monitoring/` 抽样标记逻辑 | `monitoring/` 下对应文件/函数 |

### 2.2 不需要 implements 关系的（47个）

这些不对应代码实现，但部分可能需要 `specified-by` 关系（指向定义它们的规范文档）。

| 门类 | 数量 | 性质 | 可能的关系 |
|---|---|---|---|
| HARD | 10 | 行为约束（如"启动前确认 ARANGO_DB"） | `specified-by` → 规范文档 |
| DOC | 8 | 文档同步任务（如"文档体系加入 XXX"） | `traces-to` → 目标文档 |
| DEC | 7 | 待决策问题（如"Monitor Exec Devin 的 model"） | `specified-by` → spec 文档 |
| SELF-S | 17 | Exec Devin 自检行为 | `specified-by` → p27_monitor_pipe_operations.md |
| MON-A-issue | 5 | 已知问题 | `traces-to` → 对应的 MON-A 检查项 |

---

## §3 工作包拆解

### 3.1 拆解原则

- 按门类分批，每个工作包处理一个门类
- 先做代码对应关系明确的门类（EXEC/SESS/LAUNCH/CTRL/ENV）
- 后做需要深入理解代码的门类（MON-A/MON-B/MON-C/AUDIT/RUN）
- 最后做非 implements 关系的门类（HARD/DOC/DEC/SELF-S/MON-A-issue）

### 3.2 工作包列表

| 工作包 | 门类 | checkpoint数 | 工作内容 | 优先级 |
|---|---|---|---|---|
| WP-TRACE-01 | ENV | 7 | 记录 ENV-01~06 的 depends-on（配置文件）+ specified-by（规范文档）。ENV-07 已完成 | 高 |
| WP-TRACE-02 | EXEC | 28 | 记录 EXEC-01~28 的 implements（continuation_config.py 中的常量/模板） | 高 |
| WP-TRACE-03 | SESS | 12 | 记录 SESS-01~12 的 implements（continuation_db_schema.py 等） | 高 |
| WP-TRACE-04 | LAUNCH | 10 | 记录 LAUNCH-01~10 的 implements（launcher 中的函数） | 高 |
| WP-TRACE-05 | CTRL | 9 | 记录 CTRL-01~09 的 implements（CLI 命令实现） | 高 |
| WP-TRACE-06 | MON-A | 12 | 记录 MON-A2~A12 的 implements（analysis_control.py 等）。MON-A1 已完成 | 中 |
| WP-TRACE-07 | MON-B | 9 | 记录 MON-B1~B9 的 implements（续传质量检查代码） | 中 |
| WP-TRACE-08 | MON-C | 5 | 记录 MON-C1~C5 的 implements（抽样标记逻辑） | 中 |
| WP-TRACE-09 | RUN | 8 | 记录 RUN-02~08 的 implements（检查脚本）。RUN-01 已完成 | 中 |
| WP-TRACE-10 | AUDIT | 7 | 记录 AUDIT-01~07 的 implements（审计代码） | 中 |
| WP-TRACE-11 | HARD | 10 | 记录 HARD-01~10 的 specified-by（规范文档） | 低 |
| WP-TRACE-12 | DOC | 8 | 记录 DOC-01~08 的 traces-to（目标文档） | 低 |
| WP-TRACE-13 | DEC | 7 | 记录 DEC-01~07 的 specified-by（spec 文档） | 低 |
| WP-TRACE-14 | SELF-S | 17 | 记录 SELF-S1~S17 的 specified-by（p27_monitor_pipe_operations.md） | 低 |
| WP-TRACE-15 | MON-A-issue | 5 | 记录 MON-A!01~!05 的 traces-to（对应的 MON-A 检查项） | 低 |

### 3.3 依赖关系

- 各工作包之间**无强依赖**——可以并行
- 但建议按优先级顺序执行：高优先级的门类代码对应关系最明确，做起来最快
- 每个工作包完成后 commit，保持 trace.csv 幂等

### 3.4 每个工作包的工作流程

```
1. 读该门类所有 checkpoint 文件，理解每个 checkpoint 要求什么
2. 搜索代码库，找到对应的代码文件和函数
3. 记录 implements 关系到 trace.csv（精确到函数级）
4. 如有规范文档，记录 specified-by 关系
5. 验证：trace.py query <checkpoint编号> 确认关系完整
6. commit（trace.csv 变更）
```

---

## §4 验收标准

1. **107 个 checkpoint 有 implements 关系**——每个都精确到函数级（如 `file::function`）
2. **47 个 checkpoint 有 specified-by 或 traces-to 关系**——指向定义它们的规范文档
3. **trace.csv 幂等**——给定任何 commit 时间点，trace.csv 精确反映所有 checkpoint 的追溯关系
4. **覆盖率从 3.2% 提升到 100%**

---

## §5 风险和注意事项

1. **工作量**——107 个 checkpoint 逐个追溯代码实现，是一个大型工作。建议分批做，每批一个门类
2. **代码可能不存在**——有些 checkpoint 的状态是 `[ ]`（待做），对应的代码可能还没实现。这种情况记录为"待实现"，不强行建立 implements 关系
3. **函数级追溯的精度**——有些 checkpoint 对应的是常量定义（如 EXEC-01 是 `MONITOR_EXEC_CONCURRENCY = 1`），这种情况追溯到文件级即可，不需要函数级
4. **已完成 vs 待做**——状态 `[x]` 的 checkpoint 代码已存在，可以追溯。状态 `[ ]` 的可能代码不存在，需要判断
