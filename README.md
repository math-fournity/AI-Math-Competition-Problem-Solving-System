# 错题分析系统

用并发 devin cli 实例分析失败题——判定每道失败题是"方向出错"还是"token 不够"，并分类卡点类型。

## 快速开始

1. `cp .env.example .env` 并填入真实配置
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install python-arango redis pyarrow pandas`
4. `source .env`
5. `cd analysis-devin-failure-system && python -m monitoring.continuation_control status --batch-id p27-full`

## 目录结构

见 `AnalysisSystem开发/README.md`

## git 历史

本 repo 从数学大师 repo（`/Users/user/glm5.2-math-worktree/`）用 git filter-repo 拆分而来，
保留了 `analysis-devin-failure-system/`、`AnalysisSystem开发/`、5 个设计文档、POC-2.7 数据、
conversation_mapper.py 的完整 commit 历史。
