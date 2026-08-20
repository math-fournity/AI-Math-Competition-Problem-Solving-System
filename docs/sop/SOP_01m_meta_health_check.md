# SOP_01m：元检查 — 健康检查的合理性

> **你的角色**：你是 SOP 系统的自我审查者。刚才你执行了 sop_01（健康检查），现在你要反思这一步本身的设计是否还合理。不是重做健康检查，而是检查健康检查这一步是否需要改进。

---

## 你要反思什么

上方已经打印了被检查的 SOP_01 文档内容。对照它，思考以下问题：

### 1. 检查项是否还全面？

- SOP_01 依赖 `monitor_check_continuation.sh` 的 8 项输出。这 8 项是否覆盖了系统所有可能的问题？
- 最近有没有出现新的问题类型，是这 8 项检查没覆盖的？
- `runtime_health_check.py` 的 10 维度（A-J）是否还够用？

### 2. 检查脚本本身是否还有效？

- `monitor_check_continuation.sh` 是否还能正确运行？
- 它的输出格式是否变化了？
- 它调用的底层脚本（`monitor_continuation.py`、`runtime_health_check.py`）是否有变化？

### 3. SOP 文档的指令是否清晰？

- 你执行 sop_01 时，SOP 文档的指令是否让你清楚地知道该做什么？
- 有没有含糊的地方导致你不确定怎么处理？

### 4. 阈值是否需要调整？

- `STUCK_SESSION_WARNING_THRESHOLD = 5` 是否还合适？
- `DONE_UNCLEANED_INFO_THRESHOLD = 20` 是否还合适？
- 其他阈值？

---

## 如果发现问题

如果你发现 SOP_01 需要改进：

1. **修改 `docs/sop/SOP_01_health_check.md`** — 用 edit 工具修改文档内容
2. **如果脚本逻辑需要改** — 修改 `scripts/sop/sop_01_health_check.py`
3. **如果底层检查脚本需要改** — 修改 `scripts/monitor_check_continuation.sh` 或 `src/monitor_continuation.py`
4. **commit 变更**

---

## 如果没有问题

如果 SOP_01 设计仍然合理——直接进入下一步。在 todo list 中记录"01m 检查通过，无需修改"。

---

## 你需要建立的 todo list

- 反思 SOP_01 的合理性（必做）
- 如果需修改：修改 SOP_01 文档/脚本 + commit（如有）
- **最后一项固定是**：执行下一个脚本 `python -m scripts.sop.sop_02_alert_triage`
