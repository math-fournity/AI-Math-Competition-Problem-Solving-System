# AnalysisSystem 开发工作包索引

> 本目录包含POC-2.7续传系统的后续开发和测试工作包。
> 拆解依据：AnalysisSystem.md §6（工作类型）+ p27_session_management_and_polish_spec.md §C（实施Checklist）+ 2026-08-19 session发现的实际问题。

---

## 需求点清单（CheckList）

| 文件 | 用途 | 读者 |
|---|---|---|
| `CheckList.md` | 系统全部功能需求点全集（13门类127点）——开发/验收/跨session用 | Master Agent / 开发者 |
| `CheckList-ExecDevin.md` | Exec Devin 必读子集（约68点）——从全集提取第一档+第二档 | Monitor Exec Devin |

**编号规则**：`<门类>-<序号>`（如 `SESS-01`、`MON-A1`、`EXEC-10`），编号稳定，commit message 可引用。状态标记：`[ ]` 待做 · `[~]` 进行中 · `[x]` 已完成 · `[!]` 已知有问题 · `[-]` 决定不做。

---

## 工作包清单

| 编号 | 标题 | 依赖 | 优先级 | 状态 |
|---|---|---|---|---|
| WP-01 | 阶段1真实运行验证 | 无 | P0 | 待执行 |
| WP-02 | 已知bug修复 | 无 | P0 | 待执行 |
| WP-03 | 阶段2配置与模板 | WP-02 | P1 | 待执行 |
| WP-04 | 阶段2 Monitor Exec Devin启动器 | WP-03 | P1 | 待执行 |
| WP-05 | 阶段2 Monitor Pipe集成 | WP-04 | P1 | 待执行 |
| WP-06 | 阶段2 export与report查看支持 | WP-05 | P2 | 待执行 |
| WP-07 | 阶段2端到端验证 | WP-05, WP-06 | P1 | 待执行 |
| WP-08 | 阶段3文档同步 | WP-07 | P2 | 待执行 |
| WP-09 | POC-2.7并发1运行和监控 | WP-01, WP-02 | P0 | 待执行 |
| WP-10 | 系统审计 | WP-09 | P2 | 待执行 |

## 依赖关系图

```
WP-01 (阶段1验证) ─┐
                    ├─→ WP-09 (并发1运行监控) ─→ WP-10 (系统审计)
WP-02 (bug修复) ───┘
     │
     └─→ WP-03 (配置模板) ─→ WP-04 (启动器) ─→ WP-05 (Pipe集成) ─→ WP-07 (端到端验证) ─→ WP-08 (文档同步)
                                                                          ↑
                                                              WP-06 (查看支持) ─┘
```

## 执行顺序建议

1. **WP-01 + WP-02 并行**（无互相依赖，都是P0）
2. **WP-09**（在WP-01和WP-02完成后，以并发1启动系统运行——这是长期运行的工作，可以在运行中并行做WP-03~WP-08）
3. **WP-03 → WP-04 → WP-05 → WP-06 → WP-07 → WP-08**（阶段2开发链，在WP-09运行期间串行推进）
4. **WP-10**（所有工作完成后审计）

## 优先级说明

- **P0**：阻塞性工作，不做的话系统无法正确运行——WP-01（验证阶段1代码）、WP-02（修已知bug）、WP-09（跑POC-2.7）
- **P1**：核心功能开发——WP-03~WP-05, WP-07（阶段2 Monitor Exec Devin）
- **P2**：辅助性工作——WP-06（查看支持）、WP-08（文档同步）、WP-10（审计）

## 当前系统状态（2026-08-19T06:45Z）

- 系统已完全停止（tmux server不存在，无p27进程）
- DB: prepared=789, completed=121, dead_session=9, running=0
- DB batch concurrency=1（已设为1）
- 已完成的commit：
  - de38a5e: 修复动态并发（launcher从DB读concurrency）
  - cafd195: 修复session_counter seq unique索引冲突
  - 7767fa8: 修复launcher重启覆盖DB concurrency
- 已知未修复的问题：
  - Monitor Pipe的expected_concurrency不从DB读（用启动参数5）
  - alert的_key冲突（同一轮同类型alert timestamp相同时_key重复）
  - rounds_log_export_missing大量出现（根因未诊断）
  - export_missing大量出现（根因未诊断）
  - 850+ alert堆积（Monitor Exec Devin未实现）

## 铁律提醒

- 改代码必须同步更新第一级文档（docs/*.md + AnalysisSystemDesign.md §4 + specs实现细节）
- git显式路径add，禁止 `git add -A/. /-u`
- 绝不kill无DONE.md的session
- 长时间命令用tmux
- 禁止inline脚本（超过3行写成文件）
- 人话铁律——所有文档/回复/注释/commit message用人话写
