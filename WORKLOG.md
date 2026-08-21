# WORKLOG — SOP监控循环跨轮记忆

> 每轮SOP循环结束时续写。下一轮循环的AI读这个文件就能快速恢复上下文。

---

## WP-P 现场补救 · 2026-08-21

### 做了什么
工作包WP-P（030需求1的事故现场补救）执行完毕：5个审计devin cli早已完成但launcher被杀导致结果无人收集。本次把结果收进来、清掉孤儿、修正三处状态。

1. **修DB status**：5个"DB显示running实际已完成"的审计run，逐条亲眼验证DONE.md+export（137-293KB）后改为completed。脚本 scripts/fix_wp_p_running_status.py（dry-run先行）。commit 见 git log。
2. **收集审计结果**：跑 result_collector 收集10条——9条PASS/PASS_WITH_CAVEAT入库 p27_proof_audits，1条（deepmath_103k_00000036）截断样本走 mark_parse_error（audit_passed=None+alert待人工，status不动）。
3. **清Redis**：HDEL paudit:running 的5个成员，HLEN=0。
4. **kill孤儿session**：5个paudit tmux session逐个验证DONE.md后kill（00000036的DONE.md内容是退出码1=devin异常退出，与其截断互证），归零。
5. **差1核对**：见下方"重要发现"。

### 重要发现1：result_collector解析bug（已修，commit a4c436b）
extract_audit_from_export 写的是 source=='assistant'，实测export格式是 'agent'（续传/审计统一 system/user/agent）——10个真实export一个都提取不到，收集器从上线起就收不到任何东西。另发现"export存在但无文本"分支静默skip导致截断样本永远停在audit_status=null被反复重扫，已按029 §3.3接mark_parse_error。单测 scripts/test_wp_p_export_parse.py 10 PASS。

### 重要发现2：差1根因（只报告未修复）
paudit-p27-full-amo_bench_00000006 在DB prepared但不在Redis任何队列，审计从未跑过（work_dir空、无门闸痕迹）。证据链指向：07:50:39启动的第一个审计launcher实例（日志只有一行batch_start就消失）pop了字典序最小的06后、在audit_launch之前崩溃——dequeue(ZPOPMIN破坏性)到launch之间无try/except，key无声丢失。数据本身健康（proof_text 5327B）。处置：按WP-P纪律只报告；建议下批审计跑之前给该代码段加try/except（可并入WP-H），然后重新入队该key。

### 终态
p27_proof_audits=9（5 PASS+4 PASS_WITH_CAVEAT）；runs=131 prepared+10 completed+0 running；tmux paudit=0；paudit:running=0。130 pending保持原样未动（等WP-G实验决定怎么跑）。

---

## 第0轮 · 2026-08-20

### 检查发现
- **系统健康**：launcher和monitor刚启动（修复了ANALYSIS_ROOT bug后），历史alert已全部清理
- **数据完整性**：919个run，121个COMPLETED（13.17%），789个prepared（86%未跑），9个dead_session
- **alert**：50条未处理alert（历史），分8种类型。全部已resolve（1013个alert批量处理）
- **AI判断**：0个待判断条目（ai_review_sample未设置needs_ai_review标记——已修复代码bug）

### 修复操作
1. **continuation_control.py ANALYSIS_ROOT未定义** → 改为PROJECT_ROOT。commit 8bb5430
2. **monitor_continuation.py ai_review_sample未设置needs_ai_review** → 抽样后设置run的needs_ai_review=True。commit 61feead

### 思考
- **历史数据丢失**：10个COMPLETED的run的export文件丢失（proof.md完整）。这是devin cli崩溃/系统重启时的运行时问题，非代码bug。当前launcher的export路径逻辑正确。
- **stuck session清理**：14个stuck session（s0016~s0029）全部清理。这些是devin cli崩溃后tmux session消失但无DONE.md的遗留。run状态：2个dead_session、1个completed、5个prepared（handover阶段崩溃）。
- **题源完成率差异**：deepmath 31.7% vs oda/polymath/omni/amo/mathnet 全0%。789个prepared中大部分是这些题源——还没跑到。需关注launcher是否在正确入队。
- **报表系统首次运行**：SOP报表系统首次实际使用，每个step都生成了report.md+snapshot.json+snapshot_runs.json+check_output.txt。报表模板从文件复制工作正常。

---

## 第1轮 · 2026-08-20

### 检查发现
- **系统健康**：launcher+monitor运行正常，1个solve session在跑
- **进度**：130/919(14%)，121 COMPLETED，1 running，788 prepared
- **alert**：53个新alert（历史数据丢失+stuck session），已全部resolve
- **AI判断**：0个待判断条目（monitor还没运行到ai_review抽样）

### 修复操作
- 清理stuck session p27-s0030
- 批量resolve 53个新alert
- set-concurrency将batch并发数从1调整为5

### 思考
- **并发数问题**：batch concurrency被设为1而非5。可能是之前运行时设的。已用set-concurrency调整。
- **85个round1 export缺失**：全部是prepared run（没跑过），不是bug。check_02对prepared run也检查round1 export，过于严格。
- **29个DB孤儿run**：属于其他batch（full-analysis-v2-r*），不影响p27-full。
- **系统开始正常运转**：launcher在dequeue，1个solve session在跑。并发数调到5后应该会启动更多session。
