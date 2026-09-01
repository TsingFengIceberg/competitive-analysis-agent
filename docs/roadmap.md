# 路线图

## 已完成的产品化能力

- 本地知识库、版本化文档、混合 Dense/Sparse 检索、重排和词法降级。
- GraphRAG 关系、时间版本、来源溯源、冲突查看和实体合并审计。
- 观察任务、变化检测、告警、完整报告版本归档和历史恢复。
- 检索反馈、版本化评估集、离线指标、线上延迟趋势和检索配额。
- SQLite 任务队列、调度租约、独立 Worker、取消、重试和 SSE/A2A 恢复。
- 独立标准 A2A Provider、AgentCard、Task、Artifact、认证和互操作测试。

## 当前边界

- 默认部署适合单机或小规模共享环境；大规模多实例仍建议外置 PostgreSQL、Redis 和对象存储。
- 默认评估集包含公开快照和合成回归样例，真实业务数据需要经过授权、脱敏和人工标注。
- S3/Qdrant 远程联通、真实 OCR 难例和高并发压测需要部署环境单独验证。

## 建议的后续顺序

1. 建立稳定的黄金数据集和 CI 质量门，持续追踪 Recall、MRR、NDCG、引用精确率、忠实度和延迟。
2. 增加文档级 ACL、租户隔离、Prompt Injection 防护、敏感信息处理和审计告警。
3. 优化 Parent-Child Chunk、Contextual Retrieval、多查询、Adaptive Top-K 和缓存策略。
4. 完善增量摄取、来源新鲜度、可靠性评分、OCR/表格/图像和多语言资料处理。
5. 在真实负载下做模型路由、批处理、Embedding 缓存、成本预算和 PostgreSQL/Redis 部署验证。
6. 最后再扩展 Agentic RAG、社区级 GraphRAG、多模态证据和更多通知渠道。

路线图服务于技术取舍和面试说明，不代表已经承诺的发布日期。
