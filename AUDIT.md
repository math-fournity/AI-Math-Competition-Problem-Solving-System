# 数据审计方法 — 纲举目张查到每道题每轮每个round的所有数据

> **用途**：本文档说明如何通过数据库为入口，纲举目张地查到每一道题的每一次解题运行的每一个round的所有输入、输出、devin export数据。所有查询都以独立编号为线索——题目编号、run编号、round编号——从DB定位到文件系统路径，再读文件内容。
>
> **适用场景**：审计某道题的完整解题过程 / 检查某个run的数据完整性 / 追溯某个round的输入输出链路 / 批量检查某题源的所有run / 检查SOP报表中发现的异常run

---

## 一、编号体系

系统中有三层独立编号，从粗到细：

| 层级 | 编号 | 格式 | 示例 | 在DB中的位置 |
|---|---|---|---|---|
| 题目 | `problem_id` | `{题源}_{题号}` | `deepmath_103k_00000295` | `p27_continuation_runs.problem_id` |
| 解题运行 | `run_key` / `_key` | `{batch_id}-{problem_id}` | `p27-full-deepmath_103k_00000295` | `p27_continuation_runs._key` |
| 轮次 | `round` | 整数（2,3,4,5...） | `2` | `p27_continuation_runs.rounds_log[].round` |

**编号规则说明**：
- **题源前缀**（problem_id的下划线前第一段）：`deepmath` / `oda` / `polymath` / `omni` / `amo` / `mathnet` —— 标识题目来源数据集
- **batch_id**：`p27-full` —— 标识这一批题的运行批次
- **run_key = batch_id + "-" + problem_id** —— 全局唯一，是DB中run的主键`_key`
- **round编号从2开始**：round 1是原始解题（seed_export），round 2+是续传轮。rounds_log中记录的是续传轮（从2开始），round 1的数据在`seed_export`和`round1_export.json`中

---

## 二、数据库集合地图

审计相关的4个核心集合 + 1个辅助集合：

| 集合名 | 用途 | 文档数 | 主键`_key` | 关键字段 |
|---|---|---|---|---|
| `p27_continuation_runs` | 每道题的解题运行记录 | 919 | `{batch_id}-{problem_id}` | problem_id, status, final_status, rounds_log, work_dir, trajectory_dir, seed_export |
| `p27_continuation_events` | 运行事件流（launched/completed/failed） | 609 | 自动 | run_key, event_type, data, timestamp |
| `p27_continuation_results` | 完成后的归档结果 | 0 | - | （当前为空，待归档） |
| `p27_sessions` | devin cli session注册表 | 15 | seq编号 | session_name, type, run_key, round, export_path, status |
| `p27_monitor_alerts` | 监控告警 | 3303 | 自动 | alert_type, severity, status, details |

**集合关系图**：

```
p27_continuation_runs (1) ──< (N) p27_continuation_events
        │                           通过 run_key 关联
        │
        ├──< (N) p27_sessions       通过 run_key / problem_id 关联
        │                           每个 round 对应 1-2 个 session（handover + solve）
        │
        └──> 文件系统               通过 work_dir / trajectory_dir / rounds_log[].*_path 关联
```

---

## 三、审计查询方法

### 查询0：总览——全batch状态分布

```python
# 在项目根目录执行
source .venv/bin/activate && source .env
python3 -c "
import sys; sys.path.insert(0, '.')
from src.continuation_db_schema import connect_db
db = connect_db()
cursor = db.aql.execute('''
FOR run IN p27_continuation_runs
COLLECT status = run.status, fs = run.final_status
WITH COUNT INTO cnt
RETURN {status, fs, cnt}
''')
for r in cursor:
    print(f'{r[\"status\"]:15s} {str(r[\"fs\"]):15s} {r[\"cnt\"]}')
"
```

### 查询1：查一道题的完整run记录

**入口**：已知`problem_id`（如`deepmath_103k_00000295`），查它的run记录。

```python
python3 -c "
import sys, json; sys.path.insert(0, '.')
from src.continuation_db_schema import connect_db
db = connect_db()
pid = 'deepmath_103k_00000295'  # ← 改成你要查的problem_id
cursor = db.aql.execute('FOR r IN p27_continuation_runs FILTER r.problem_id == @pid RETURN r', bind_vars={'pid': pid})
docs = list(cursor)
if not docs:
    print(f'未找到 problem_id={pid}')
else:
    r = docs[0]
    print(f'run_key: {r[\"_key\"]}')
    print(f'status: {r[\"status\"]}, final_status: {r[\"final_status\"]}')
    print(f'work_dir: {r[\"work_dir\"]}')
    print(f'trajectory_dir: {r[\"trajectory_dir\"]}')
    print(f'seed_export (round1原始export): {r.get(\"seed_export\",\"无\")}')
    print(f'original_exp_id: {r.get(\"original_exp_id\",\"无\")}')
    print(f'rounds_log ({len(r.get(\"rounds_log\",[]))}轮):')
    for rl in r.get('rounds_log', []):
        print(f'  round {rl[\"round\"]}: method={rl.get(\"method\")}, completed={rl.get(\"completed\")}, truncated={rl.get(\"truncated\")}')
        print(f'    export: {rl.get(\"export\",\"无\")}')
        print(f'    prompt: {rl.get(\"prompt_path\",\"无\")}')
        print(f'    proof:  {rl.get(\"proof_path\",\"无\")}')
        print(f'    handover: {rl.get(\"handover_path\",\"无\")}')
        print(f'    map: {rl.get(\"map_path\",\"无\")}')
        print(f'    prev_export: {rl.get(\"prev_export\",\"无\")}')
"
```

### 查询2：查一道题的事件流

```python
python3 -c "
import sys; sys.path.insert(0, '.')
from src.continuation_db_schema import connect_db
db = connect_db()
pid = 'deepmath_103k_00000295'  # ← 改成你要查的problem_id
run_key = f'p27-full-{pid}'
cursor = db.aql.execute('FOR e IN p27_continuation_events FILTER e.run_key == @rk SORT e.timestamp RETURN e', bind_vars={'rk': run_key})
for e in cursor:
    print(f'{e[\"timestamp\"][:19]} {e[\"event_type\"]:25s} data={e.get(\"data\",{})}')
"
```

### 查询3：查一道题的session注册

```python
python3 -c "
import sys; sys.path.insert(0, '.')
from src.continuation_db_schema import connect_db
db = connect_db()
pid = 'deepmath_103k_00000295'  # ← 改成你要查的problem_id
run_key = f'p27-full-{pid}'
cursor = db.aql.execute('FOR s IN p27_sessions FILTER s.run_key == @rk OR s.run_key == @pid SORT s.seq RETURN s', bind_vars={'rk': run_key, 'pid': pid})
for s in cursor:
    print(f's{str(s[\"seq\"]).zfill(4)} {s[\"type\"]:10s} round={s.get(\"round\")} status={s[\"status\"]} alive={s.get(\"tmux_alive\")}')
    print(f'  session_name: {s[\"session_name\"]}')
    print(f'  export_path: {s.get(\"export_path\",\"无\")}')
    print(f'  work_dir: {s.get(\"work_dir\",\"无\")}')
"
```

### 查询4：按题源批量查完成率

```python
python3 -c "
import sys; sys.path.insert(0, '.')
from src.continuation_db_schema import connect_db
db = connect_db()
cursor = db.aql.execute('''
FOR run IN p27_continuation_runs
LET src = SPLIT(run.problem_id, '_')[0]
COLLECT source = src INTO group = run.final_status
RETURN {source, total: LENGTH(group), completed: COUNT(group[* FILTER CURRENT == 'COMPLETED'])}
''')
for r in cursor:
    rate = r['completed']/r['total'] if r['total'] > 0 else 0
    print(f'{r[\"source\"]:12s} {r[\"completed\"]:4d}/{r[\"total\"]:4d} = {rate:.1%}')
"
```

### 查询5：查某个round的完整输入输出链路

**这是审计的核心查询**——给定problem_id和round编号，查出这个round的所有输入文件和输出文件。

```python
python3 -c "
import sys, json, os; sys.path.insert(0, '.')
from src.continuation_db_schema import connect_db
from pathlib import Path
db = connect_db()
pid = 'deepmath_103k_00000295'  # ← 改成你要查的problem_id
round_num = 2                   # ← 改成你要查的round编号
cursor = db.aql.execute('FOR r IN p27_continuation_runs FILTER r.problem_id == @pid RETURN r', bind_vars={'pid': pid})
r = list(cursor)[0]
print(f'=== {pid} round {round_num} 审计 ===')
print()

# round 1 的数据在 seed_export / round1_export.json
if round_num == 1:
    print('--- round 1 输入 ---')
    print(f'  problem.txt: {r.get(\"problem_path\",\"无\")}')
    print()
    print('--- round 1 输出 ---')
    seed = r.get('seed_export', '无')
    print(f'  seed_export (原始export): {seed}')
    # round1_export.json 在 work_dir 中
    work_dir = Path(r.get('work_dir', ''))
    r1_export = work_dir / 'round1_export.json'
    print(f'  round1_export.json: {r1_export} (存在={r1_export.exists()})')
    print()
    print('--- 文件大小 ---')
    for p in [seed, str(r1_export)]:
        if p and p != '无' and Path(p).exists():
            print(f'  {Path(p).name}: {Path(p).stat().st_size} bytes')
        else:
            print(f'  {p}: 不存在')

# round 2+ 的数据在 rounds_log 中
else:
    rl = None
    for entry in r.get('rounds_log', []):
        if entry['round'] == round_num:
            rl = entry
            break
    if not rl:
        print(f'未找到 round {round_num} 的记录')
    else:
        print('--- 输入文件 ---')
        inputs = {
            'prompt_path': rl.get('prompt_path'),
            'prev_export': rl.get('prev_export'),
            'handover_path': rl.get('handover_path'),
            'map_path': rl.get('map_path'),
        }
        for name, path in inputs.items():
            exists = Path(path).exists() if path else False
            size = Path(path).stat().st_size if exists else 0
            print(f'  {name:15s}: {\"✓\" if exists else \"✗\"} {path} ({size}B)')

        print()
        print('--- 输出文件 ---')
        outputs = {
            'export': rl.get('export'),
            'proof_path': rl.get('proof_path'),
        }
        for name, path in outputs.items():
            exists = Path(path).exists() if path else False
            size = Path(path).stat().st_size if exists else 0
            print(f'  {name:15s}: {\"✓\" if exists else \"✗\"} {path} ({size}B)')

        print()
        print('--- round元数据 ---')
        print(f'  method: {rl.get(\"method\")}')
        print(f'  completed: {rl.get(\"completed\")}')
        print(f'  truncated: {rl.get(\"truncated\")}')
        print(f'  reason: {rl.get(\"reason\",\"无\")}')
        print(f'  handover_success: {rl.get(\"handover_success\")}')
"
```

### 查询6：读某个round的export内容（thinking）

```python
python3 -c "
import sys, json; sys.path.insert(0, '.')
from src.continuation_db_schema import connect_db
db = connect_db()
pid = 'deepmath_103k_00000295'  # ← 改成你要查的problem_id
round_num = 2                   # ← 改成你要查的round编号
cursor = db.aql.execute('FOR r IN p27_continuation_runs FILTER r.problem_id == @pid RETURN r', bind_vars={'pid': pid})
r = list(cursor)[0]
if round_num == 1:
    export_path = r.get('seed_export')
else:
    for entry in r.get('rounds_log', []):
        if entry['round'] == round_num:
            export_path = entry.get('export')
            break
    else:
        export_path = None
if export_path:
    data = json.load(open(export_path))
    # conversation.json 结构：messages数组
    msgs = data.get('messages', data) if isinstance(data, dict) else data
    print(f'export文件: {export_path}')
    print(f'消息数: {len(msgs) if isinstance(msgs, list) else \"非列表\"}')
    # 找thinking（reasoning_content字段）
    for i, msg in enumerate(msgs if isinstance(msgs, list) else []):
        if isinstance(msg, dict):
            rc = msg.get('reasoning_content') or msg.get('thinking')
            if rc:
                print(f'消息[{i}] thinking (前500字): {rc[:500]}...')
                break
else:
    print(f'未找到 round {round_num} 的export路径')
"
```

### 查询7：查异常run（有launched无completed/failed）

```python
python3 -c "
import sys; sys.path.insert(0, '.')
from src.continuation_db_schema import connect_db
db = connect_db()
cursor = db.aql.execute('''
FOR e IN p27_continuation_events
FILTER e.event_type == 'continuation_launched'
COLLECT rk = e.run_key INTO events = e.event_type
RETURN {run_key: rk, events: events}
''')
all_events = list(cursor)
incomplete = []
for e in all_events:
    evs = e.get('events', [])
    has_launched = any('launched' in x for x in evs)
    has_end = any('completed' in x or 'failed' in x for x in evs)
    if has_launched and not has_end:
        incomplete.append(e['run_key'])
print(f'有launched无completed/failed的run: {len(incomplete)}个')
for rk in incomplete[:20]:
    print(f'  {rk}')
"
```

### 查询8：查所有prepared但未跑的run

```python
python3 -c "
import sys; sys.path.insert(0, '.')
from src.continuation_db_schema import connect_db
db = connect_db()
cursor = db.aql.execute('''
FOR run IN p27_continuation_runs
FILTER run.status == 'prepared'
RETURN {pid: run.problem_id, src: SPLIT(run.problem_id, '_')[0]}
''')
runs = list(cursor)
from collections import Counter
src_counts = Counter(r['src'] for r in runs)
print(f'prepared总数: {len(runs)}')
print('按题源:')
for src, cnt in src_counts.most_common():
    print(f'  {src}: {cnt}')
"
```

---

## 四、文件系统地图

每道题在D盘有两个目录——工作目录和trajectory目录：

### 工作目录（work_dir）

```
/Volumes/data/math-agent-glm5.2-tmux-agents-dir/p27-continuation/{run_key}/
├── problem.txt                    ← 题目文本（round 1输入）
├── round1_export.json             ← round 1的原始export（从seed_export复制过来）
├── round1_conversation_map.md     ← round 1的对话地图（handover用）
├── round1_handover_prompt.txt     ← handover AI的提示词
├── round1_HANDOVER.md             ← handover AI产出的交接文档
├── round1_handover_run/           ← handover AI的运行目录
│   └── conversation.json          ← handover AI的export
├── round2_prompt.txt              ← round 2的提示词（含HANDOVER+map）
├── round2_proof.md                ← round 2的证明产出
├── round3_prompt.txt              ← round 3的提示词（如有）
├── round3_proof.md                ← round 3的证明产出（如有）
└── ...                            ← round 4, 5, ...
```

### Trajectory目录（trajectory_dir）

```
/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-continuation/{run_key}/
├── exports/                       ← round 1的export（如有）
├── tmux/                          ← tmux日志
├── round2/                        ← round 2的运行数据
│   ├── exports/
│   │   └── conversation.json      ← round 2的devin export（含thinking）
│   └── tmux/
│       └── ...                    ← tmux输出日志
├── round3/                        ← round 3的运行数据（如有）
│   ├── exports/
│   │   └── conversation.json
│   └── tmux/
└── ...
```

### 文件对应关系（DB → 文件系统）

| DB字段 | 文件 | 内容 | 阶段 |
|---|---|---|---|
| `run.seed_export` | 外部路径 | round 1原始export（来自原始解题run） | round 1输出 |
| `run.problem_path` | work_dir/problem.txt | 题目文本 | round 1输入 |
| `rounds_log[N].prompt_path` | work_dir/round{N}_prompt.txt | 第N轮的提示词 | round N输入 |
| `rounds_log[N].prev_export` | work_dir/round{N-1}_export.json | 上一轮的export | round N输入 |
| `rounds_log[N].handover_path` | work_dir/round{N-1}_HANDOVER.md | 交接文档 | round N输入 |
| `rounds_log[N].map_path` | work_dir/round{N-1}_conversation_map.md | 对话地图 | round N输入 |
| `rounds_log[N].export` | trajectory_dir/round{N}/exports/conversation.json | devin export（含thinking） | round N输出 |
| `rounds_log[N].proof_path` | work_dir/round{N}_proof.md | 证明产出 | round N输出 |

---

## 五、审计操作流程

### 流程A：审计一道题的完整解题过程

1. **确定problem_id**——如 `deepmath_103k_00000295`
2. **执行查询1**——查run记录，确认status、final_status、rounds_log
3. **执行查询2**——查事件流，确认launched/completed/failed的时间线
4. **执行查询3**——查session注册，确认每个round的devin cli session
5. **对每个round执行查询5**——查输入输出文件链路，确认文件存在性
6. **对关键round执行查询6**——读export内容，检查thinking是否在解这道题
7. **读proof.md**——检查证明质量和boxed答案

### 流程B：审计某题源的所有run

1. **执行查询4**——查该题源的完成率
2. **如果完成率=0%**——执行查询8，确认是否都是prepared（没跑到）
3. **如果有跑过但都失败的**——对每个失败的run执行查询2，查失败原因（reason字段）
4. **统计失败原因分布**——stall / truncated / no_proof / dead_session

### 流程C：审计SOP报表中发现的异常

1. **读SOP报表**——从D盘报表目录读report.md
2. **对报表中标记为`[!]`的检查项**——逐个追溯到具体run
3. **对每个异常run**——执行查询1+查询5，确认问题
4. **记录审计结论**——写回report.md的"未修复的问题及原因"节

### 流程D：批量检查数据完整性

1. **执行查询7**——查有launched无completed/failed的run
2. **对每个incomplete的run**——执行查询1，查status
3. **如果status=running**——正常（还在跑）
4. **如果status=completed/dead_session**——异常（事件丢失），记录

---

## 六、SOP报表中的快照数据

每次SOP检查会在D盘生成系统快照，包含全量per-run数据：

```
/Volumes/data/math-agent-glm5.2-tmux-agents-trajectory/p27-sop-reports/cycle_{NNN}/step_{XX}/{timestamp}/
├── snapshot.json          ← 聚合统计（总数/完成数/完成率/按题源分组）
├── snapshot_runs.json     ← 全量per-run数据（919条，每条含problem_id/status/final_status/current_round/...）
├── check_output.txt       ← 脚本输出原文
└── report.md              ← AI填写的报表
```

**快照用途**：审计某一轮SOP检查时系统的完整状态。不需要每次都查DB——读快照即可知道那一轮检查时有多少run、完成率多少、哪些题源0%。

**快照中每条run的字段**：
- `problem_id` — 题目编号
- `status` — run状态（prepared/completed/dead_session）
- `final_status` — 最终状态（COMPLETED/None）
- `rounds_count` — 已跑轮数
- `current_round` — 当前轮编号
- `last_method` — 最后一轮的方法
- `last_completed` — 最后一轮是否完成
- `last_truncated` — 最后一轮是否截断
- `updated_at` — 最后更新时间
- `work_dir` — 工作目录路径

---

## 七、审计命令速查

所有审计查询都已封装为可复制的python命令。使用前先激活环境：

```bash
cd /Users/user/AI-Math-Competition-Problem-Solving-System
source .venv/bin/activate && source .env
```

然后复制本文档中查询1-8的任意一个python命令到终端执行，修改`pid`变量为你要查的problem_id即可。

**常用problem_id列表**（可用来测试）：
- `deepmath_103k_00000295` — COMPLETED，1轮，有完整proof
- `deepmath_103k_00000043` — FAILED（stall），有失败事件
- `oda_00000001` — prepared（未跑）
