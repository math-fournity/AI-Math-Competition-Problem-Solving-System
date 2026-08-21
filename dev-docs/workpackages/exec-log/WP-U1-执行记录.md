# WP-U1 执行记录 — ACP 双后端基线复验（含勘误弧线）

> **执行时间**: 2026-08-21 12:40–13:30（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（含一次重大勘误：初版冒烟跑错模型，已修正并重出基线）

---

## 一、做了什么

### 第一轮（初版冒烟）

1. 基线复核：opencode 版本、openrouter/ox-alpha 配置、auth 条目、devin 版本
2. 写 `scripts/test_wp_u1_acp_smoke.py`（参数化双后端），tmux 中跑通双后端冒烟：
   OpenCode 721 信号/109s/文件写读✅；Devin 38 信号/stopReason=end_turn/10s ✅
3. Ox Alpha 免费性证据：OpenRouter `/api/v1/key` 实测 limit=null 无上限、用量近零
4. 写基线报告 `dev-docs/042`

### 第二轮（用户指出两个问题后的深挖与勘误）

用户指出：①启动 opencode 时没设思考强度；②如何确认 opencode 确实接受了模型？
按指示先搜文档再分析源码（~/opencode = anomalyco/opencode，更新到 dev 最新）：

- **发现默认模型陷阱**：session/new 响应的 configOptions 显示初始模型是
  `opencode/big-pickle`——初版冒烟根本没跑在 ox-alpha 上！根因：opencode.json
  无顶层 model 默认项 + 客户端未显式选择
- **机制实证**（`scripts/probe_acp_model_config.py`）：
  - `session/set_config_option {configId:"model"}` 换模型，**响应回显 currentValue
    即接受确认**
  - 切模型后 configOptions 新增 **effort 项**；ox-alpha variants=[low,high,max]，
    **默认 low**；设 max 回显 ✅
  - 方法名注意：SDK 0.16.1 = set_config_option；最新 dev 源码改名 set_config
    （客户端需兼容探测）
- **修正冒烟脚本**（加三步设置+断言）并重跑：ox-alpha+max 正确基线 =
  45 信号/14s/**response 返回 end_turn**（推翻"OpenCode 不返回 response"旧结论，
  或为 big-pickle 特有——U5 跨任务实测确认）
- **知识资产同步**：skill §3.8 新增（skills-devin `7bc3acf`）；opencode acp skill
  改为 devin 同款薄指针跳转机制、删本地副本（config 仓 `d1d329d`）
- **042 报告勘误节**：初版数据作废、v2 数据替换、两条结论修正、V1 硬性要求

## 二、验收 checklist 对照

- [x] 脚本存在，双后端各跑通（v2 OpenCode 输出贴于 042 §五；Devin 于 §一）
- [x] jsonl 落盘 tmp/（不提交）；信号计数表在报告
- [x] thought_chunk>0（v2=35，正确模型下）；两后端文件写读成功
- [x] prompt response 行为记录（含勘误 2 的修正）
- [x] Ox Alpha 免费性证据一条
- [x] 042 含"基线事实"节 + 勘误节
- [x] 生产代码零改动；commit 只含脚本+报告（c310171 / b211945）

## 三、遗留问题

1. "response 不返回"的真实边界（big-pickle 特有 vs 任务相关）→ U5 跨任务实测
2. opencode.json 无顶层 model 默认项——是否给全局配置加默认模型属用户决策
   （管线侧由 V1 的 start() 强制设置兜底，不依赖配置）
3. 本会话曾两次违反长命令铁律（阻塞 TUI）——已固化为全局 rule
   long-commands-use-tmux（config 仓 `496ec40`）
