**⚠️ 已废弃（2026-08-19）**：Monitor Exec Devin（独立devin cli）不再实现。由 Master Agent SOP 流程控制机制取代（scripts/sop/run.py）。本工作包保留作为历史参考。

# WP-04: 阶段2 Monitor Exec Devin启动器

> **依据**：p27_session_management_and_polish_spec.md §C.2.2
> **优先级**：P1
> **前置条件**：WP-03完成（配置和模板就绪）
> **预估工作量**：大（新建核心模块，4个函数+复用DONE.md机制）

---

## 目标

新建`src/monitor_exec_launcher.py`——Monitor Exec Devin的启动器，实现定时启动、防重复启动、prompt构造、完成检查。

## 要读的文档

- `specs/p27_session_management_and_polish_spec.md` §B.5（prompt构造逻辑）+ §B.6（export保留）+ §B.7（并发控制）+ §C.2.2
- `src/continuation_launcher.py`（复用launch_solve的DONE.md机制和tmux log机制）
- `src/session_registry.py`（allocate_seq + create_session_record）

## 任务清单

### 1. 新建src/monitor_exec_launcher.py

- [ ] `should_launch_monitor_exec(db, batch_id) -> bool`
  - 查注册表：无 `type=monitor_exec, status=running` 的记录
  - 查时间：距离上一轮Monitor Exec完成已过 `MONITOR_EXEC_INTERVAL`
  - 返回True/False

- [ ] `build_monitor_exec_prompt(exec_seq, db) -> str`
  - 读`templates/monitor_exec_prompt.md`模板
  - 替换`{exec_seq}`占位符
  - 从上一轮的WORKLOG.md复制到本轮work_dir（见§B.5的WORKLOG传递逻辑）
  - prompt不注入alert详情——Monitor Exec Devin自己运行检查脚本获取
  - prompt不注入WORKLOG内容——Monitor Exec Devin自己读work_dir中的WORKLOG.md

- [ ] `launch_monitor_exec(db, batch_id) -> session_name`
  - 调`allocate_seq(db)`分配全局seq
  - 创建work_dir: `/Volumes/data/p27-monitor-exec/{exec_seq}/`
  - 写prompt到work_dir/monitor_exec_prompt.txt
  - 调`create_session_record(db, seq, session_name, type="monitor_exec", exec_seq=..., ...)`
  - 启动devin cli到tmux: `devin -p --prompt-file ... --export ...`
  - session名: `p27-s{seq:04d}-monitor-exec-{exec_seq}`

- [ ] `check_monitor_exec_completion(db, batch_id) -> list[completed]`
  - 查注册表中 `type=monitor_exec, status=running` 的记录
  - 对每个记录检查DONE.md是否出现
  - 出现的更新status=done，返回完成列表

### 2. 复用launch_solve的机制

- [ ] DONE.md检测机制（与Solver Devin相同）
- [ ] tmux log机制
- [ ] 超时处理：超过`MONITOR_EXEC_MAX_RUNTIME_SECONDS`标记stuck，不kill（见§B.6铁律）

### 3. 单元测试

- [ ] 测试`should_launch_monitor_exec`：无running时返回True，有running时返回False
- [ ] 测试`should_launch_monitor_exec`：间隔未到时返回False
- [ ] 测试`build_monitor_exec_prompt`：prompt包含正确的exec_seq和work_dir路径
- [ ] 测试`launch_monitor_exec`：注册表记录被正确创建

## 验证标准

- py_compile通过
- 单元测试全部通过
- `should_launch_monitor_exec`逻辑正确（防重复启动+间隔控制）
- `launch_monitor_exec`正确分配seq、创建注册表记录、启动devin cli

## 预期产出

- `src/monitor_exec_launcher.py` 新建
- commit（显式路径add）

## 验证记录

（执行时在此记录验证结果）
