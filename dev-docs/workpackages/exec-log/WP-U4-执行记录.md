# WP-U4 执行记录 — 双管线执行后端架构设计

> **执行时间**: 2026-08-21（EDT）
> **执行者**: Claude (ox-alpha, opencode)
> **状态**: ✅ 完成（045 报告，零代码改动）

---

## 一、做了什么

产出 `dev-docs/045-双管线执行后端架构设计.md`：

1. **接口定义**：BackendTask/BackendHandle/BackendStatus/ExecutionBackend 全签名，
   含铁律 15 的 start() 断言链、finish_reason 信息性定位（end_turn 失真——043）、
   trunc_comp_threshold 属性化（实测校准）
2. **差异适配 8 点**逐点方案（完成检测/权限/session/模型/强度/自定义通知/错误信号/
   截断分层+trajectory 三层）
3. **切换机制**：DB batch.backend 字段 + set-backend 命令 + 每轮 poll 刷新
   （WP-G 同构）；健康探测；auto-fallback 设计为默认关（用户拍板项）、切回永远人工
4. **架构验证**：三方案对比表（抽象 vs 复制 launcher vs 全重写），工作量佐证引
   044（tmux 功能点仅 12/40 属 agent 会话层）
5. **给 V 系列输入**映射表 + 037 不变量逐条核对（含一条必要收紧：截断/成功判定
   走组装后结构）

## 二、验收 checklist 对照

- [x] 接口定义完整（start/poll/terminate/完成语义 + finish_reason +
      trunc_comp_threshold）+ 签名级伪代码
- [x] 行为等价性表：§三适配表 8 差异点 × 3 后端（≥8 业务事件的等价表达）
- [x] 差异适配 8 点逐一有方案（完成检测留 U5 参数位已标注 🔶）
- [x] 选择/切换机制：DB 配置源/set-backend/健康探测/回退策略（自动回退默认关）
- [x] 截断检测分层设计完整（对齐 038 §九 + 043 实测修正）
- [x] 架构对比专节（工作量数据引 044）
- [x] 045 报告 + "给 V 系列输入"小节；零代码改动

## 三、关键设计决策记录

1. **成功分界判据移位**：stopReason/finish_reason 仅信息性；成败 = 组装产物
   message 非空且含预期标记——043 end_turn 失真的直接推论
2. **comp 阈值以实测校准**：043 发现 ox-alpha 有效上限 32000 ≠ 宣称 131072；
   comp 条件降为辅助项（rc/msg/tc 主判）
3. **model/reasoning_effort 进 BackendTask**：与 concurrency 同源从 DB batch 读
   （铁律 15 与 WP-G 模式合一）
4. auto-fallback 代码可做但**默认关闭**，切回永远人工——适度依赖边界

## 四、遗留

- done_silence_seconds 的 OpenCode 具体值 🔶 待 U5 实测
- 错误模式在 ACP 通知里的真实形态 🔶 待 U5 实测
