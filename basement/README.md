# basement/ — 认知闭包体系文档集

> **本目录是什么**：认知闭包体系的概念演进文档集。十篇文档（006-015）构成一个递进体系——从认知闭包概念定义（006）到工程优化（007）到迭代逼近（008）到孤岛修正（009）到 trace 幂等边界（010）到文档形态（011）到协同可见性困境（012），七篇的综述（013）和论证（014），以及 README 与 view 的统一（015）。这是基础设施研发的概念层，不是某个具体系统的文档。
>
> **与看法文件的关系**：本目录所有文件都属于"认知闭包体系"这一个主题，因此本目录 README 和 `views/cognitive-closure.md` 索引同一批文件。分工：本 README 是**目录入口**（服务阶段0岛屿遍历，简洁到够判断相关性），`views/cognitive-closure.md` 是**主题视图**（服务阶段1+闭包迭代，含完整三要素）。需要详细覆盖场景和依赖关系时，加载看法文件。

## 直接文件

| 文件 | 一句话说明 |
|---|---|
| `006-cognitive-closure-concept.md` | 体系起点，定义认知闭包 N 是什么，提出概念层级提升（闭包是贯穿所有阶段的底层必要条件） |
| `007-cognitive-closure-acquisition-optimization.md` | 闭包获取的工程优化，形式化为 `min\|M\| s.t. N⊆M`，五种获取策略和务实路径 |
| `008-cognitive-dynamic-process.md` | 复杂 N 的跨 session 迭代逼近（n1→n2→…→N），非单调性和收敛判据 |
| `009-island-cognitive-crisis.md` | 008 的根本性缺陷修正——孤岛认知危机，递归 README 遍历作为 fallback 分类学 |
| `010-trace-idempotency-practical-boundary.md` | trace 幂等的实用边界定义——实用粒度上的幂等，三个判定维度 |
| `011-cognitive-closure-document-form.md` | 闭包文档形态——三种面相，面相3 综述论文为标准形态 |
| `012-cognitive-pack-deliverable-and-co-visibility.md` | 体系当前前沿——协同可见性困境和四个应对方向 |
| `013-cognitive-closure-system-synthesis.md` | 七篇综述（面相3 实例），正文论述递进关系 + 参考文献 xpath 列表 |
| `014-cognitive-closure-system-argumentation.md` | 013 的配套论证文档——纳入决策理由、事实层核对、待验证协同关系 |
| `015-README-view-unification.md` | README 与 view 的统一——README 是事实层 view，看法文件是描述层 view，N 是临时 view；确立递归 README 的目录入口格式 |

## 本目录依赖关系

本目录被 `views/cognitive-closure.md`（认知闭包体系分类法）索引。本目录文档反复引用的外部资产：`/Users/user/skills-devin/` 下的 workflow.md/akash.md/read.md/read-sync.md/make-plan.md，以及本 repo 的 trace.csv/scripts/trace_verify.py/scripts/view_index.py/README.md/views/idempotency.md。本目录 README.md 是 009 §四.4 递归 README 要求的落地。
