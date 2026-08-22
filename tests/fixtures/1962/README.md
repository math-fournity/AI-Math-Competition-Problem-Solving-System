# 1962 编排离线回归 fixture

这组 fixture 只保留能验证编排行为的**无答案现场**：裸 HANDOVER 的信任税、R2 尾部收殓、
R3 分析笔记对后续 solver 的供料、R4 新定理与验证欠账、R5 组装任务。它不包含最终答案、
最终 proof、完整推导或指向外部答案资产的路径。

证据来源是原始 repo 的提交 `e041b6a`、`52d57a3`、`07af0ce`、`d403dc9`、`16e2cc9`；
fixture 内容经过人工去答案和符号化，只用于离线检查 prompt 合同，不声称是原文逐字副本。

普通测试不在线调用模型。`manifest.json` 把五个真实回归意图映射成模板必须保留的行为标签；
`scripts/test_wp03_prompt_contract.py` 检查角色边界、读取纪律、资产合同和防泄漏。未来若做真实
模型回归，应把单个 scene 文件复制进隔离目录，禁止复制本目录 README/manifest 或任何后续
轮答案资产，并独立记录模型、effort、key、成本和输出。
