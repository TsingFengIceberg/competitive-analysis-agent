# RAG 与知识治理

## 数据流

```text
文件/网页/RSS/JSON API
        ↓
解析、规范化、去重、版本化
        ↓
结构化分块 + 元数据 + 原始证据
        ↓
Dense/Sparse 索引与实体关系
        ↓
查询规划 → 混合召回 → 重排 → 权限/时效过滤
        ↓
证据上下文 → Analyst/Reviewer/Writer → 引用报告
```

原文、规范化 Markdown、版本、分块和处理任务分别保存。相同内容不会重复生成版本；新版本索引失败时，上一份可用版本继续服务。

## 解析与存储

- TXT、Markdown、HTML、CSV、JSON 直接解析。
- PDF、图片和复杂版式使用本地 Docling + RapidOCR。
- DOCX、XLSX、PPTX 在 Docling 资产不可用时使用 OOXML 降级解析。
- 原始对象可放在 Local、S3、MinIO 或 R2；SQLite 保存元数据，Qdrant 保存可重建向量索引。
- 知识空间负责成员角色、审批状态和保留期限；待审/驳回内容不会成为 Agent 证据。

## 检索策略

Dense 使用 BGE-M3，Sparse 使用 FastEmbed BM25，通过 Qdrant RRF 融合后由 `bge-reranker-v2-m3` 重排。过滤条件包括用户、知识空间、竞品、维度、市场、来源权威、发布时间和当前/历史/指定时间点版本。

查询规划器按问题类型选择低成本直查、混合检索、时效优先或多跳检索。比较、关系和时间演化问题会拆成首跳问题与证据桥接跳；重复命中会融合。语义模型或索引不可用时，自动降级为有界 SQLite 词法检索，并在日志和 provenance 中标记降级。

历史报告只作为记忆层，用于发现旧结论和规划新搜索，不能直接成为事实引用；当前报告线程会被排除，避免自我引用。上下文分为可引用原始证据、长期洞察和历史报告记忆三层。

## GraphRAG 与时间版本

SQLite 保存产品、能力、价格、集成、用户群、市场事件、来源和历史报告等类型化实体及带时间范围的关系。关系只从已批准版本和事件确定性生成，并追溯到原始分块。单一事实问题不强制走图检索，跨竞品、关系和时间问题才启用图路径。

价格关系会关闭旧有效期，同时存在的不同来源会显式标记冲突。图路径只有在原始证据分块进入当前 `collected_data` 时才可以支持事实结论，否则只能作为导航和分析记忆。

## 来源连接器与持续观察

支持网页、RSS/Atom、Sitemap 和 JSON API。URL 会检查协议、凭据和私有网段；ETag、Last-Modified、内容哈希和任务去重避免重复摄取。失败会记录冷却和重试状态，来源健康、条目数和同步历史可在知识库页面查看。

持续观察产生的实质变化和报告版本可以显式沉淀到知识库，并经过来源可信度、质量门和人工审批。无变化运行不会创建虚假的报告版本。

## 质量与评估

检索日志记录查询规划、过滤条件、命中分块、排序策略和耗时。人工反馈（相关、不相关、已引用）形成有界排序先验，并自动清理旧缓存。

`POST /api/competition/knowledge/evaluate` 支持版本化离线样例，计算 Recall、MRR、NDCG、拒答、追溯、核验、规划和治理指标。反馈还可以生成新的版本化评估集，用于 baseline/candidate 实验和 CI 回归。线上延迟、命中数和缓存命中率持久化后在知识库页面展示。

### RAG 实验与质量门

`evals/rag/real-v2.json` 是扩展评测集，包含事实、比较、时序、多跳和无答案问题，并为每条查询标注难度、语言/数据切分和 gold evidence。`evals/rag/experiments-v1.json` 定义 B0（无 RAG）、Dense-only、Hybrid、Hybrid + Reranker、完整方案和 Adaptive 六组对照。

运行 `make rag-experiments` 会在临时 SQLite/Qdrant 中依次运行这些策略（另含 intent-aware 的自适应候选），输出绝对变化、方向感知的相对变化、P50/P95 延迟、按类别/难度/切分聚合的指标，以及数据集和运行环境元数据。零基线的相对变化会明确标记为 undefined，避免产生虚假的百分比；报告仍写入被忽略的 `.ci-agent/evaluations/`。

评测 API 支持 `minimum_case_count` 和 `required_categories` 质量门。缺少样本或类别会使严格评测失败，而不是把空分组当作满分。检索命中率、答案正确率和 groundedness 必须分开解释。

`bootstrap` 置信区间和 `answer_quality_cases` 为答案级人工/评审模型评分预留了结构化入口；缺少真实评分时只报告覆盖率，不会生成虚假质量分数。运行时还会报告真实模型 usage（若调用方提供）、可选价格估算、失败/降级/超时/重试率、P99 延迟、吞吐和成本门禁；没有 usage 或价格时保持 `null`，并发吞吐只有在调用方提供真实 wall time 时才作为实测值。成对的 `robustness_queries` 可测试改写、翻译和短查询的检索稳定性。数据集质量指标检查元数据完整性、重复文本、干扰文档和类别分布，并可与上一版本计算漂移；若旧版本没有类别标签，会明确报告基线元数据不足，而不是误报漂移。`.github/workflows/rag-evaluation.yml` 默认运行确定性契约门，完整模型实验仅在手动触发且配置仓库变量 `CI_AGENT_RAG_GOLDEN_ENABLED=true` 时执行。

## 关键配置

常用变量：`CI_AGENT_KNOWLEDGE_ROOT`、`CI_AGENT_RAG_QDRANT_URL`、`CI_AGENT_RAG_QDRANT_API_KEY`、`CI_AGENT_OBJECT_STORE`、`CI_AGENT_RAG_MIN_SCORE`、`CI_AGENT_RAG_QUERY_EXPANSION` 和 `CI_AGENT_RAG_LEXICAL_FALLBACK`。完整配置见[配置指南](configuration.md)。

## 相关代码与验证

- `backend/packages/competition/competition/knowledge_parser.py`
- `backend/packages/competition/competition/knowledge_chunking.py`
- `backend/packages/competition/competition/knowledge_index.py`
- `backend/packages/competition/competition/knowledge_service.py`
- `backend/packages/competition/competition/knowledge_storage.py`
- `backend/packages/competition/competition/graph_algorithms.py`
- `evals/rag/real-v1.json`
- `evals/rag/real-v2.json`
- `evals/rag/experiments-v1.json`
- `scripts/run-rag-experiments.py`

运行 `make rag-eval` 可在临时存储中执行摄取、规划、检索、关系构建和主张核验，报告写入被 Git 忽略的 `.ci-agent/evaluations/`。
