# WP-05: 阶段2 Monitor Pipe集成

> **依据**：p27_session_management_and_polish_spec.md §C.2.3
> **优先级**：P1
> **前置条件**：WP-04完成（启动器就绪）
> **预估工作量**：中等（修改monitor_continuation.py主循环+修改检查脚本）

---

## 目标

将Monitor Exec Devin启动逻辑集成到Monitor Pipe主循环中，实现自愈循环：Monitor Pipe每轮检查后自动判断是否启动Monitor Exec Devin，Monitor Exec Devin完成后写alert通知。

## 要读的文档

- `specs/p27_session_management_and_polish_spec.md` §C.2.3
- `src/monitor_continuation.py`（现有主循环）
- `src/monitor_exec_launcher.py`（WP-04新建的启动器）

## 任务清单

### 1. monitor_continuation.py主循环加入启动逻辑

- [ ] 每轮A/B类检查后，调`should_launch_monitor_exec(db, batch_id)`
- [ ] 返回True则调`launch_monitor_exec(db, batch_id)`
- [ ] 打印日志: `[monitor_exec_start] exec_seq={n} session={session_name}`

### 2. 每轮检查Monitor Exec Devin的DONE.md

- [ ] 调`check_monitor_exec_completion(db, batch_id)`
- [ ] 完成的写`monitor_exec_completed` alert（含MONITOR_EXEC_REPORT.md路径和commit hash）
- [ ] 更新注册表status=done

### 3. Monitor Exec Devin超时处理

- [ ] 超过`MONITOR_EXEC_MAX_RUNTIME_SECONDS`（900秒）标记stuck
- [ ] 不kill（见§B.6铁律——等DONE.md才处理）
- [ ] 写`monitor_exec_timeout` alert

### 4. C类检查改为只做抽样标记

- [ ] `flag_for_ai_review()`改为只做抽样标记（标记`needs_ai_review`）
- [ ] 不再只写标记等Master Agent——Monitor Exec Devin会读这些标记做真正的AI判断
- [ ] 确保标记包含足够信息（proof.md路径、HANDOVER.md路径）供Monitor Exec Devin读取

### 5. 更新p27_monitor_spec.md

- [ ] 新增§4 Monitor Exec Devin规范（引用p27_session_management_and_polish_spec.md §B）

### 6. 更新monitor_check_continuation.sh

- [ ] 行动清单精简——去掉"AI_REVIEW抽样结果需Master Agent检查"（现在Monitor Exec Devin做）
- [ ] 改为"有monitor_exec_completed alert时可选读REPORT了解本轮修复"

## 验证标准

- py_compile通过
- Monitor Pipe主循环正确调用启动器
- DONE.md检测正确
- 超时标记stuck不kill
- C类检查改为只标记

## 预期产出

- `src/monitor_continuation.py` 修改
- `specs/p27_monitor_spec.md` 修改
- `scripts/monitor_check_continuation.sh` 修改
- commit（显式路径add）

## 验证记录

（执行时在此记录验证结果）
