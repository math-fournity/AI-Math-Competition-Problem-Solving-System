---
trigger: always_on
---

# devin cli model 参数必须显式指定

**硬约束**：所有启动 devin cli 的代码，必须显式指定 `--model` 参数。不允许省略、不允许空值、不允许使用无效 model 名。

## 有效的 model 名

通过 `devin models list` 查询。当前项目使用的 model：

| model 名 | 说明 | 用途 |
|---|---|---|
| `glm-5-2` | GLM-5.2 High, 200K context, Free | **本项目解题和分析的默认 model** |

其他可选（如需更高能力时）：
- `glm-5-2-max` — GLM-5.2 Max
- `glm-5-2-1m` — GLM-5.2 High 1M context
- `glm-5-2-none` — GLM-5.2 No Thinking

**无效名（踩过的坑）**：`glm-5.2-high` — 点号（`.`）不是横线（`-`），且没有 `-high` 后缀变体。这个值会导致 devin cli 启动失败或使用错误模型。

## 配置位置

| 文件 | 变量 | 当前值 | 用途 |
|---|---|---|---|
| `src/continuation_config.py` | `DEVIN_MODEL` | `glm-5-2` | Pipe 4 续传（continuation_launcher/start_handover/launch_solve） |
| `src/config.py` | `DEVIN_MODEL` | `glm-5-2` | Pipe 1/2/3（analysis/audit/selection/solver launcher） |

## 启动代码中的检查点

每次启动 devin cli 时，必须记录结构化日志 `event=devin_cli_launch model=xxx`：
```python
log_event(logger, "info", "devin_cli_launch",
          problem_id=pid, round=round_num, session_type="solve",
          model=DEVIN_MODEL, permission_mode=DEVIN_PERMISSION_MODE,
          batch_id=batch_id)
```

SOP_01 系统健康检查步骤中，用以下命令检索 model 参数：
```
python -m scripts.sop.log_search --event devin_cli_launch --tail 30
python -m scripts.sop.log_search --event devin_cli_launch --stats
```

如果发现 model 参数为空或值不在 `devin models list` 中，这是 critical 问题。

## 什么时候触发本规则

- 修改任何 launcher 文件中的 devin cli 启动命令时
- 修改 `DEVIN_MODEL` 配置时
- 新建使用 devin cli 的脚本时
- SOP_01 系统健康检查时（检查日志中的 model 参数）
