# Roadmap

## Delivered product capabilities

- Local knowledge base, versioned documents, hybrid Dense/Sparse retrieval, reranking, and lexical fallback.
- GraphRAG relations, temporal versions, provenance, conflict inspection, and audited entity merges.
- Monitoring schedules, material-change detection, alerts, complete report archives, and historical recovery.
- Retrieval feedback, versioned evaluation datasets, offline metrics, online latency trends, and quotas.
- SQLite task queue, schedule leases, standalone Worker, cancellation, retries, and SSE/A2A recovery.
- Independent standard A2A Provider with AgentCard, Tasks, Artifacts, auth, and interoperability tests.

## Current boundaries

- The default deployment targets a single host or small shared environment. Large multi-instance deployments should externalize PostgreSQL, Redis, and object storage.
- The default evaluation sets contain public snapshots and synthetic regression cases. Real business data requires authorization, redaction, and human labeling.
- Remote S3/Qdrant connectivity, difficult OCR cases, and high-concurrency load tests require environment-specific validation.

## Recommended order of work

1. Establish a stable golden set and CI quality gates for Recall, MRR, NDCG, citation precision, groundedness, and latency.
2. Add document-level ACLs, tenant isolation, Prompt Injection defenses, sensitive-data handling, and audit alerts.
3. Improve Parent-Child Chunking, Contextual Retrieval, multi-query, Adaptive Top-K, and caching.
4. Complete incremental ingestion, freshness and reliability scoring, OCR/table/image, and multilingual handling.
5. Validate model routing, batching, embedding caches, cost budgets, and PostgreSQL/Redis deployment under real load.
6. Only then expand agentic RAG, community-level GraphRAG, multimodal evidence, and additional notification channels.

This roadmap records engineering trade-offs and interview context; it is not a release-date commitment.
