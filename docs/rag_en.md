# RAG and Knowledge Governance

## Data flow

```text
Files/web/RSS/JSON API
        ↓
Parse, normalize, deduplicate, version
        ↓
Structure-aware chunks + metadata + raw evidence
        ↓
Dense/Sparse indexes and entity relations
        ↓
Query planning → hybrid retrieval → reranking → ACL/time filters
        ↓
Evidence context → Analyst/Reviewer/Writer → cited report
```

Original files, normalized Markdown, versions, chunks, and processing jobs are stored separately. Identical content does not create another version; if a replacement index fails, the previous usable version remains available.

## Parsing and storage

- TXT, Markdown, HTML, CSV, and JSON are parsed directly.
- Local Docling + RapidOCR handles PDF, images, and complex layouts.
- DOCX, XLSX, and PPTX use an OOXML fallback when Docling assets are unavailable.
- Raw objects can use Local, S3, MinIO, or R2; SQLite stores metadata and Qdrant stores rebuildable vector indexes.
- Knowledge spaces enforce member roles, approval state, and retention. Pending or rejected content cannot become Agent evidence.

## Retrieval

Dense BGE-M3 and FastEmbed BM25 sparse vectors are fused with Qdrant RRF, then reranked by `bge-reranker-v2-m3`. Filters cover user, space, product, dimension, market, authority, publication time, and current/historical/as-of versions.

The query planner selects direct, hybrid, freshness-first, or multi-hop retrieval. Comparative, relational, and temporal questions are decomposed into first-hop queries and evidence-bridging hops. Semantic or index failures fall back to bounded SQLite lexical retrieval and are marked in logs and provenance.

Historical reports are memory only: they can reveal old conclusions and guide fresh searches but cannot become factual citations. The current report thread is excluded. Context is separated into citable raw evidence, long-horizon insights, and historical-report memory.

## GraphRAG and temporal versions

SQLite stores typed products, capabilities, prices, integrations, audiences, market events, sources, historical reports, and time-bounded relationships. Relations are deterministically generated only from approved versions and events, with links to original chunks. Graph retrieval is reserved for cross-product, relational, and temporal questions.

Price intervals close old versions, while conflicting simultaneously valid source values are surfaced. A graph path can support a factual conclusion only when its source chunk is included in current `collected_data`.

## Connectors and monitoring

Web pages, RSS/Atom, Sitemaps, and JSON APIs are supported. URLs are checked for schemes, credentials, and private networks. ETag, Last-Modified, content hashes, and task deduplication avoid duplicate ingestion. Failure cooldowns, retries, health, entry counts, and sync history are visible in the knowledge workspace.

Material changes and report versions from continuous monitoring can be explicitly promoted into the knowledge base, subject to source credibility, quality gates, and human approval. Unchanged runs do not create fake report versions.

## Quality and evaluation

Retrieval logs record planning, filters, hits, ranking profile, and latency. Human feedback (relevant, not relevant, cited) becomes a bounded ranking prior and invalidates stale caches.

`POST /api/competition/knowledge/evaluate` accepts versioned offline cases and computes Recall, MRR, NDCG, abstention, traceability, verification, planning, and governance metrics. Feedback can generate versioned evaluation datasets for baseline/candidate experiments and CI regression. Online latency, result count, and cache-hit samples are persisted and shown in the workspace.

### RAG experiments and quality gates

`evals/rag/real-v2.json` is an expanded benchmark covering fact, comparison, temporal, multi-hop, and no-answer queries, with difficulty, split, and gold-evidence labels for every query. `evals/rag/experiments-v1.json` defines six controlled strategies: B0 (no RAG), dense-only, hybrid, hybrid plus reranker, the full candidate pipeline, and adaptive retrieval.

Run `make rag-experiments` to execute the matrix in temporary SQLite/Qdrant storage, including an intent-aware adaptive candidate. The report contains absolute and direction-aware relative changes, P50/P95 latency, category/difficulty/split aggregates, and dataset/runtime metadata. Relative changes from a zero baseline are explicitly marked undefined so the report cannot manufacture a percentage. Reports remain under ignored `.ci-agent/evaluations/`.

The evaluation API supports `minimum_case_count` and `required_categories` quality gates. Missing samples or required categories fail a strict evaluation instead of being treated as a perfect empty group. Retrieval hit rate, answer correctness, and groundedness must be interpreted separately.

Bootstrap confidence intervals and `answer_quality_cases` provide structured entry points for human or judge-model answer scoring. Without real scores, the system reports coverage only and never invents a quality value. Runtime reports also expose supplied model usage, optional price estimates, failure/degraded/timeout/retry rates, P99 latency, throughput, and cost gates; values remain `null` when usage or pricing is unavailable, and concurrent throughput is treated as measured only when the caller supplies real wall time. Paired `robustness_queries` measure retrieval stability under paraphrases, translations, and short queries. Dataset-quality checks cover metadata completeness, duplicate text, distractors, and category drift against the previous version; when the older version lacks category labels, the report explicitly marks baseline metadata as insufficient instead of claiming drift. `.github/workflows/rag-evaluation.yml` runs deterministic contract gates by default; the full model experiment runs only on manual dispatch when the repository variable `CI_AGENT_RAG_GOLDEN_ENABLED=true` is enabled.

## Key configuration

Common variables include `CI_AGENT_KNOWLEDGE_ROOT`, `CI_AGENT_RAG_QDRANT_URL`, `CI_AGENT_RAG_QDRANT_API_KEY`, `CI_AGENT_OBJECT_STORE`, `CI_AGENT_RAG_MIN_SCORE`, `CI_AGENT_RAG_QUERY_EXPANSION`, and `CI_AGENT_RAG_LEXICAL_FALLBACK`. See the [configuration guide](configuration_en.md) for the complete table.

## Code and validation

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

Run `make rag-eval` to execute ingestion, planning, retrieval, relation construction, and claim verification using temporary stores. Reports are written under ignored `.ci-agent/evaluations/`.
