# WP-05 — 审计 AI 形式化充分性判定

> **覆盖 Feature**：FML-06~10、AUD-01/04/05/06、TST-05
> **依赖**：WP-04
> **高风险**：不能把“命令退出0”误当充分；不能把形式化不足误写数学失败或永久终态。

## 一、目标

扩展现有 proof audit：独立拆解 proof 关键 claim，检查 formal 主命题等价性和覆盖，扫描
逃逸口，在干净环境重跑，输出 PASS/数学失败/形式化不足/待人工。只有充分 PASS 才允许
现有 FINALIZE-PASS Gate 确认最终正确。

### 当前代码基线与预期触点

当前 proof audit 已有 collector/launcher/result collector、四 Gate、PARSE_ERROR 待人工和
SOP_04/07，但不读取formal包。预期触点：`src/proof_audit_{collector,launcher,
result_collector}.py`、审计模板、Gate docstring、SOP_04/07 checks/report和形式化正反测试。

## 二、前置认知

读 057、058、061、065、WP-04执行记录和分层trajectory reader合同；再读 proof audit collector/config/launcher/result
collector、prompt模板、四个审计 Gate、SOP_04/07、029~033 的 PARSE_ERROR 教训。

## 三、审计输入

- 原题和题目域；
- proof.md；
- formal目录；
- formal_verification.md；
- 解题侧日志和版本；
- 相关Round notes；
- 解题实例的分层trajectory reader manifest/使用证据（核对形式化命令是否真实执行、工具输出
  与报告是否一致；不要求审计AI通读全部reasoning）；
- 审计自己的独立工作目录和输出日志。

## 四、实施任务

1. 更新 audit prompt：命题等价、claim覆盖、逃逸口、独立重跑、有限/普遍边界。
2. 在审计 work_dir 复制只读输入，不让审计覆盖解题资产。
3. 提供确定性预检查：资产存在、命令可运行、sorry/admit/axiom扫描；结果只是证据，不代替
   语义覆盖判断。
4. 审计 AI 输出结构增加 formal sufficiency 论证和未覆盖 claim。
5. result collector 保持 PARSE_ERROR 待人工；新增语义最小映射，不为漂亮枚举膨胀schema。
6. FINALIZE-PASS Gate 增直接检查：formal源码、独立日志、主命题、覆盖、逃逸口。
7. 形式化不足不排除题目；生成可供下一observer消费的具体缺口。
   缺口附formal run路径和必要trajectory idx/tool锚点，不能只给裸结论。
8. SOP_04/07 增实物复核和不足/待人工清单，不新增STEP。

## 五、正反样本

- 完整主定理、无逃逸、重跑成功→PASS。
- 只有候选解代入，无完备性→FORMAL_INSUFFICIENT。
- 主命题漏正整数/量词→不等价。
- 含sorry→不得PASS。
- Python枚举有限上界冒充无限结论→不足。
- formal checker发现反例/定理错误→数学失败或明确失败证据。
- 审计无法判断外部公理可信性→NEEDS_REVIEW。
- 审计XML/结构解析失败→PARSE_ERROR，不改原题永久状态。

## 六、Gate和资产

- 复用现有FINALIZE PASS/FAIL Gate。
- Gate reason记录审计证据路径，不塞完整secret/大日志。
- audit conversation、prompt、formal重跑日志全部保留。
- 审计不得修proof后直接PASS；修复返回后续Round。

## 七、明确不做

- 不让程序启发式自动判断全部形式化充分性。
- 不新增形式化审批服务/Gate系统。
- 不把审计AI变成隐藏解题AI。
- 不因无法形式化就永久放弃题目。

## 八、验收 checklist

- [ ] audit prompt覆盖四层充分性检查
- [ ] 独立重跑和日志归档
- [ ] 逃逸口正反测试
- [ ] 形式化不足不会final PASS/永久失败
- [ ] PARSE_ERROR语义保持
- [ ] FINALIZE Gate直接证据完整
- [ ] SOP_04/07可发现待处理
- [ ] sim/单测通过
