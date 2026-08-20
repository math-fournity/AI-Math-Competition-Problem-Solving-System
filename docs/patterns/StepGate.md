# StepGate — 步进门闸设计范式（基于数据库信号的单步跟踪系统）

> **这是什么**：让 Master Agent 能够"卡住"自动化系统的任何一个关键动作、
> 检查之前的工作、再放行的通用设计范式。起源于 2026-08-20 的 016 事故
> （`dev-docs/016-动态并发设置失效与amo_bench失控循环事故调查报告.md`）——
> launcher 在 18 分钟里执行了上千次"启动 devin cli"动作，Master Agent
> 既看不见（存量检查的盲区，已由行为流水补齐）也**拦不住**。
>
> **与 MonitorPipe.md 的关系**：MonitorPipe 范式解决"怎么检查系统健康"
> （发现问题），StepGate 范式解决"怎么冻结系统动作"（介入系统）。两者配合：
> 行为流水（observability）让你看见流动，门闸让你卡住流动。
>
> **首次实现**：`src/step_gate.py`（POC-2.7 续传 Pipe，9 个门闸：
> launcher 8 个 + feeder 1 个）。

---

## 0. 心智模型：工程师单步跟踪 + X/Y 注意力模型

整套范式的心智模型是：**Master Agent 像一个工程师单步跟踪系统的运行**——
在关键动作点设断点（闸），断点命中时读取该处的检查清单（checklist），
核对"系统在这里做的事是对的"再继续。

注意力模型（Master Agent 只在 Y 出现时操心）：

```
X = mode（auto/hold）   Master Agent → 代码 的控制变量（"布防"一个闸）
Y = waiting_for(+上下文)  代码 → Master Agent 的需求发起（断点"命中"）
```

- **无 Y** = 代码不要求 Master Agent 操心这个位置。auto 模式静默记
  gate_pass 流水，事后可审计——注意力不被打扰；
- **hold 但无 Y**（布防未触发）也是信息：说明该动作路径在此期间没有
  发生（如 hold 住 requeue_skip 一整天没命中 = 防抖路径没触发过）；
- **Y 出现** = 单步时刻：SOP_01 例程 / `--pending` 会完整输出该闸的
  认知闭包（checklist），Master Agent 按清单核对后 `--step` 放行或维持
  hold。`proceed` 是回程握手：Master Agent 置 1，代码自清零后执行。

## 1. 问题：自动系统的"最后一公里信任"

自动化系统跑得越久，越会出现"检查体系报了警，但系统还在继续做危险动作"的窗口：

- Monitor 报了 critical alert → 但 alert 要等 Master Agent 下一轮 SOP 才处理 → 中间系统照跑；
- Master Agent 怀疑某个判定逻辑有 bug → 只能 kill 整个系统（把正常任务也杀了）；
- 事后审计只能靠日志推断"当时它做了什么"，无法回答"如果当时我拦一下会怎样"。

**根因**：系统只有"开"（全自动）和"关"（整体停止）两种状态，缺少
"在指定动作点暂停等审批"的中间态。

## 2. 核心设计（四条）

### 2.1 DB 信号变量：动作点等待 0→1，代码自清零

系统的每个关键动作执行前，先查数据库里的信号变量（`proceed` 字段）：

```
[代码] 动作前 → 查 mode：
  auto  → 直接执行（记流水）
  hold  → 冻结。每2秒轮询 proceed 字段
          proceed == 1 ? → 代码自己把 proceed 重置为 0 → 执行动作
          （期间每60秒写一条心跳流水，Master Agent 知道"还卡着"）
```

**信号是 Master Agent set 的**（`--step GATE-ID` 置 1）。自清零由代码完成
（不是 Master Agent 清），保证"一次放行 = 一次执行"，天然防重入。

### 2.2 装饰器封装：一致的行为，零散的打点

用 Python 装饰器（`@gated`）把动作函数包起来，统一完成
注册/流水/等待/降级——所有门闸行为一致，业务函数只写业务：

```python
@gated
def kill_session(session_name, run_key, pid, reason):
    """【门闸: GATE-KILL-SESSION】kill一个解题session的tmux（不可逆）。

    触发场景（reason字段区分）：
    - reason=completed：run完成，证明已归档，正常清理；
    ...

    放行前Master Agent应检查：
    1. DONE.md已出现、export已落盘；
    ...
    """
    tmux_kill(session_name)
```

调用点可传 `gate_ctx={"run_key":..., "reason":...}` 提供放行时的上下文
（Master Agent 用 `--pending` 能看到"谁在等、为什么"）。

装饰器可选带分类标签 `@gated(resource="redis"|"db"|"file"|"tmux")`，
默认 `"action"`。标签不改变任何行为，只供 `--hold-resource` 批量操作
（如 hold 住 tmux+file ≈ 冻结所有不可逆动作）。

### 2.3 认知闭包（checklist）：docstring 是唯一事实源

Master Agent 在单步时刻怎么知道"这个位置要检查什么"？答案是每个闸的
docstring 里有一段自包含的**认知闭包**——但闭包放在哪里、怎么传递，
是一个必须想清楚的设计决策（本范式试过错，见 §3）：

```
开发时刻：  代码+docstring（含"放行前…检查"段）← 唯一事实源，随代码同commit
              │ import时 inspect 反射进注册表
              │ launcher启动/--register 时同步进DB（DB只是缓存/运输层）
              ▼
单步时刻：  代码走到被hold的闸 → 置Y（waiting_for，含run_key/pid上下文）
              │ SOP_01例程 / --pending 检查Y
              ▼
            脚本按"放行前"标题截取闭包段完整输出 → Master Agent按清单核对
              │
              ▼
            --step（proceed=1）→ 代码自清零继续执行
```

三条存放原则（为什么不放 DB 字段 / SOP 提示词里）：

1. **不放 DB 字段**：谁改代码就得记得同步改 DB——双事实源必然漂移。
   docstring 与代码同一个编辑、同一个 commit、grep 直达，**不可能漂移**。
   DB 里的 `doc` 字段是反射同步的缓存，不是源。
2. **不放 SOP 提示词**：SOP 文档写**程序性知识**（"发现 Y 时怎么办"，
   写一次对所有闸通用）；闸的 docstring 写**陈述性知识**（"这个位置什么
   是对的"，随代码写随代码改）。如果 SOP 枚举各闸 checklist，每加一个闸
   改一份 SOP，N 闸 × 7 文档的漂移矩阵。
3. **"放行前"标题是机器可提取的接口**：所有闸的 docstring 固定写
   `放行前Master Agent应检查并论证：` 段落（约定是 docstring 的最后
   一段），含【检查项】（每项含查法）+【论证依据】（可放行+理由/不可放行+理由）。
   `extract_checklist()` 按这个标题截取，`--pending` 和 SOP_01
   检查脚本输出完整闭包。没这段的闸是半成品。
   **放行用 `--step GATE-ID --reason '...'` 附理由**——理由落盘到 gate_release
   流水，grep 可回溯。没有理由的放行=审计断点。

### 2.4 定位用"函数名+docstring"，不用行号

- **函数名 = 日志标志**：`kill_session` → `GATE-KILL-SESSION`。
  `grep -rn kill_session src/` 直达代码块。行号会随代码变动失效，
  函数名不会（改名时 grep 不到 = 显式提醒你注册表变了）。
- **docstring = 自包含注释文档**：注册表经 `inspect` 从函数元数据
  **自动收集**（file/function/doc 三元组，launcher 启动时同步进 DB
  的 `p27_step_gates` 集合），**永不与代码漂移**——手工维护的目录
  一定会漂移，自动收集的不会。
- docstring 必须自包含：**这个动作是什么 / 为什么要追踪管理它 /
  放行前 Master Agent 应检查什么**。这三问是门闸文档的固定结构。

## 3. 范围铁律（最重要的工程决策）

**门闸只设在"语义动作"上——一个有独立正确性标准的业务动作。
只读判定不设闸，底层 I/O 封装也不设闸。**

| 设闸（语义动作） | 不设闸：只读判定 | 不设闸：底层 I/O 封装 |
|---|---|---|
| 启动进程（launch_solve/start_handover） | is_truncated 等纯读取判定 | enqueue_pending / dequeue_pending |
| 杀进程（kill_session） | 队列长度/session数等状态查询 | add_running / update_stats |
| 重入队（requeue_truncated/requeue_skip） | | （continuation_redis_queue 全模块无闸） |
| 初次入队（feeder 的 feed_enqueue） | | |
| 文件操作（overwrite_round1_seed/remove_old_proof） | | |
| 写终态（finalize_run_completed） | | |

**底层 I/O 封装不设闸**是踩过坑后的结论（016 后曾试过"所有 Redis 写
全闸"的资源闸方案，已回退）：同一个底层函数被多条业务路径调用
（enqueue_pending 有 feeder / 截断重入队 / 防抖重入队三个调用方），
各自的正确性标准不同——**"这次入队对不对"的答案在调用方，不在 Redis
写本身**，所以那个粒度上写不出统一的 checklist，而 checklist 恰恰是
门闸的核心价值。闸设在语义动作上，调用方路径天然分离，每个闸的
checklist 才能写清楚。

为什么只读判定也不设闸：launcher 主循环 15 秒一轮，每轮几十次判定，
5957 道题 × 5 轮 = 数万次放行，每次审批 10-60 秒，**系统吞吐归零，
7x24 自动运行就不存在了**。只读判定改为行为流水全量记录
（见 `src/observability.py`），事后可审计。

这个取舍的通用原则：**可观测性管"看到"，门闸管"拦住"——看到要全量，
拦住要精选。**

## 4. 安全设计

| 场景 | 行为 | 理由 |
|---|---|---|
| DB 不可达 | 降级 auto 放行 | 门闸是审计/调试工具，不能因 DB 故障拖死系统 |
| hold 等待中 DB 瞬断 | 继续轮询 | 不能因 DB 抖动漏执行动作 |
| 模式读取 | 10 秒内存缓存 | Master Agent 设 hold 后最多 10 秒生效，避免每动作查一次 DB |
| 等待期间 | 60 秒心跳写流水 | Master Agent 可见"还卡着、卡了多久" |
| 放行信号 | 代码自清零 | 一次放行=一次执行，防重入 |

**已知代价（必须写进使用文档）**：hold 阻塞的是调用线程——对 launcher
这种单线程主循环，意味着 stall 检测暂停。所以 hold 是**调试/审计模式**，
不是常态；用完必须 `--auto` 恢复。

## 5. DB Schema（`p27_step_gates` 集合，每门闸一文档）

```json
{
  "_key": "GATE-KILL-SESSION",      // gate_id，函数名生成
  "file": "src/continuation_launcher.py",  // 定位三元组（inspect自动收集）
  "function": "kill_session",
  "doc": "【门闸: GATE-KILL-SESSION】kill一个解题session...(自包含文档全文)",
  "resource": "tmux",               // 分类标签：action/redis/db/file/tmux
  "mode": "auto",                    // auto | hold
  "proceed": 0,                      // 放行信号：Master Agent置1，代码自清零
  "waiting_for": {"run_key": "...", "pid": "...", "reason": "truncated"},
  "waiting_since": "2026-08-20T...",
  "updated_at": "..."
}
```

注册表在 **launcher 启动时自动同步**（`sync_registry_to_db`——内部 import
launcher 和 feeder 以触发所有装饰器收集）——代码加新门闸只需写 `@gated`
函数，DB 目录自动更新。**注意**：新加闸的模块必须在 `sync_registry_to_db`
里被 import，否则注册不到（feeder 的闸第一次接时就漏过这个）。

## 6. Master Agent 操作面（CLI）

```bash
python -m src.step_gate --register    # 注册/刷新门闸目录到DB
python -m src.step_gate --list        # 目录：按resource分组/文档/模式/等待状态
python -m src.step_gate --hold GATE-LAUNCH-SOLVE    # 卡住下一次解题启动
python -m src.step_gate --pending     # 谁在等——完整输出checklist+论证依据闭包（单步时刻）
python -m src.step_gate --step GATE-LAUNCH-SOLVE --reason '看到1✓+2✓...理由...'    # 放行（附理由，落盘flow流水）
python -m src.step_gate --auto GATE-LAUNCH-SOLVE    # 恢复自动
python -m src.step_gate --hold-all / --auto-all     # 批量切换
python -m src.step_gate --hold-resource tmux        # 按分类批量hold
```

**典型工作流（调试模式）**：
1. monitor 报 `launch_churn`（A14 启动抖动告警）；
2. `--hold GATE-LAUNCH-SOLVE` 卡住启动动作；
3. `--pending` 看被卡住的是哪个 run、上下文是什么——输出末尾就是该闸
   docstring 里"放行前Master Agent应检查"清单的**完整闭包**；
4. 按清单逐项核查（查行为流水 `python -m src.observability --run-key <key>`）；
5. 有问题 → 保持 hold 排查；没问题 → `--step` 放行一次再看下一次；
6. 结束后 `--auto` 恢复。

**SOP 例行接线（Y 通道进 7x24 循环）**：SOP_01 的健康检查脚本每轮自动
查 `waiting_for` 非空的闸——有 Y 就完整打印闭包并提示"系统冻结在此"，
Master Agent 不会因为注意力被下一轮 SOP 带走而漏掉被冻结的系统。

## 7. 已知坑（移植时必读）

1. **`__main__` 模块双实例**：`python -m src.step_gate` 会把本文件作为
   `__main__` 模块运行，与业务代码 import 的 `src.step_gate` 是**两个
   模块实例**——装饰器注册表在后者，CLI 前者读到的是空的。修法：CLI 入口
   委托给真正的模块实例：
   ```python
   if __name__ == "__main__":
       from src.step_gate import _main   # 不是直接调本文件的_main
       _main()
   ```
2. **gate_ctx 不透传**：装饰器拦截 `gate_ctx` 关键字参数作为流水上下文，
   业务函数签名里不能有同名参数。
3. **hold 与优雅停止**：被 hold 卡住的代码收不到 SIGTERM 的即时响应，
   会等到放行后才检查停止标志——紧急停止流程要考虑先 `--auto-all`。

## 8. 移植指南（给新 Pipe / 新项目）

1. 复制 `src/step_gate.py`，改 `COLLECTION` 常量为新 Pipe 的集合名
   （如 `analysis_step_gates`）；
2. 把业务代码里的**语义动作**提取成小函数（这一步本身就是代码质量
   提升——内联的状态操作块必须先变成函数才能装装饰器）。只提取语义
   动作，不要给底层 I/O 封装装闸（见 §3）；
3. 每个函数加 `@gated`（按需带 resource 标签）+ 按三问结构写 docstring
   （是什么/为什么追踪/放行前检查什么）——"放行前"段是必须的，
   它是 `--pending` 输出的闭包；
4. 主循环启动处调 `sync_registry_to_db()`，**函数体内 import 所有带闸
   的模块**（漏 import = 闸注册不到 DB）；
5. 配套行为流水（observability）——没有流水，hold 时的"检查之前的工作"
   就没有数据来源；两者是一对；
6. 在 SOP 健康检查脚本里接 Y 通道（查 waiting_for 非空 → 完整输出闭包），
   并在 SOP 文档里登记操作面（SOP_01 §8.5 是范例）。

## 9. 与其他机制的关系

| 机制 | 回答的问题 | 层 |
|---|---|---|
| 行为流水（observability.py） | 系统做了什么、为什么 | 看（全量，事后可审计） |
| Monitor A 类检查（monitor_continuation.py） | 系统状态是否异常 | 测（自动报警，如 A13/A14） |
| **步进门闸（step_gate.py）** | **在指定动作点冻结等审批** | **拦（精选，事前介入）** |
| SOP 循环（scripts/sop/） | 谁来综合判断和处置 | 人（Master Agent 决策层） |

四层合起来才是完整的"Master Agent 全程了解并控制系统运行"：
流水让你看见 → 检查让你知道异常 → 门闸让你拦住 → SOP 让你闭环。

## 10. 参考

- 首次实现：`src/step_gate.py`（含完整注释）+ `scripts/test_016_step_gate.py`（13断言）
- 起源事故：`dev-docs/016-*.md` §13
- 使用文档：`docs/sop/SOP_01_system_health.md` §8.5、`docs/architecture/operational-concerns.md` §6
- 姊妹范式：`docs/patterns/MonitorPipe.md`（检查范式）、`src/observability.py`（行为流水）

