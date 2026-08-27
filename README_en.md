<p align="center">
  <img src="images/logo.png" alt="Competitive-Analysis-Agent" width="80" />
</p>

<h1 align="center">Competitive-Analysis-Agent</h1>

<p align="center"><a href="./README_en.md">English</a> | <a href="./README.md">中文</a></p>

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-ff6f00?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![React](https://img.shields.io/badge/React-19-61dafb?logo=react)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.8-3178c6?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003b57?logo=sqlite&logoColor=white)](https://sqlite.org)

<p align="center"><strong>An AI-powered competitive intelligence and analysis agent collaboration system.</strong></p>

## Contents

- [Positioning](#positioning)
- [Architecture](#architecture)
- [Core Features](#core-features)
- [Technology Stack](#technology-stack)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [API](#api)
- [Competition Requirements](#competition-requirements)
- [Roadmap](#roadmap)
- [License](#license)

## Positioning

Competitive-Analysis-Agent is a "digital competitive intelligence team": six specialized AI agents use structured collaboration protocols to collect competitive data, cross-validate evidence, perform multi-dimensional comparisons, and generate interactive reports. The whole workflow is traceable, interruptible, and interactive.

## Architecture

![System architecture](images/architecture.png)

### Six agent roles

| Agent | Responsibility | Output |
|-------|----------------|--------|
| **Orchestrator** | Intent parsing, complexity assessment, dimension weights, and dynamic schema (depth x industry) | `OrchestrationResult` |
| **Collector** | Multi-source search, deduplication, coverage self-assessment, and VoC survey generation | `CollectedDataPoint[]` |
| **Analyst** | Comparison matrix, SWOT, trend forecast, and dynamic dimensions | `AnalysisResult` |
| **Reviewer** | Eight quality checks, gap detection, and targeted rework | `ReviewVerdict` |
| **Writer** | Structured report generation, `[n]` citations, and traceability map | `ReportData` |
| **HITL Gate / Rework Intent** | Human approval and natural-language routing to recollection, reanalysis, or rewrite | `HitlDecision` / `ReworkIntent` |

Agents communicate through structured Pydantic schemas rather than plain natural language. Prompts, inputs, outputs, and decisions can be inspected in the frontend process trace panel.

## Core Features

### Closed-loop quality feedback

Reviewer performs eight quality checks covering data coverage, cross-validation, source credibility, freshness, and dimension completeness, plus literal verification of numbers in source content. Gaps route the workflow back to Collector or Analyst for at most two rounds. Rework targets only missing product-dimension pairs instead of rerunning the entire pipeline, and each round records improvement and repair deltas.

### Evidence traceability

Every analytical claim carries an `[n]` citation. Hovering a citation opens a source card with URL, collection time, confidence, and verification state, with a direct link to the original source. Domains receive strong, medium, or weak evidence strength based on historical credibility, and low-credibility sources are down-weighted.

### Scope confirmation before analysis

Before execution, the system creates an editable **Analysis Brief** containing products, decision objective, dimension weights, industry, audience, time range, analysis depth, and evidence policy. Analysis starts only after ambiguity is resolved, at least two concrete products are confirmed, and a decision objective is present.

### Session reliability and recovery

Realtime SSE events and lightweight polling jointly maintain analysis state. Polling cannot overwrite an in-flight confirmation, cancellation, approval, or rework action. Network failures preserve the input draft and actionable error, while manual retry remains available. SSE reconnects resume from the last event ID, and a refreshed page reconstructs the session from persisted state.

### Continuous competitor monitoring

The **Competitor Monitoring** workspace in the sidebar manages scheduled or fixed-interval incremental collection. The system persists fact baselines and every run, and starts a full deep analysis only when a material change is detected, avoiding repeated searches and model calls. Users can edit, pause, run immediately, or delete schedules and review the change timeline, run history, alert rules, quiet hours, cooldowns, pending alerts, and delivery history in one place. Runs with material changes expose direct links to their complete reports, while a latest-changed shortcut and a separately paginated report archive keep every older report accessible even when recent runs are unchanged. Unchanged runs are explicitly marked as having no report version. Tasks, rules, and records are isolated per user.

### Local knowledge base and basic RAG

The **Local Knowledge Base** workspace supports file uploads, imports from a restricted Inbox path, and explicit promotion of selected monitoring facts. TXT, Markdown, HTML, CSV, and JSON use lightweight parsers; PDF, Office documents, and images are processed locally by Docling and RapidOCR. Original files, normalized Markdown, document versions, structured chunks, and ingestion jobs are stored separately. Identical content does not create another version, and a failed replacement keeps the previous indexed version usable.

Retrieval combines BGE-M3 dense vectors and Chinese-aware FastEmbed BM25 sparse vectors through Qdrant RRF fusion, followed by bge-reranker-v2-m3. Filters cover user, knowledge space, product, dimension, market, authority tier, source type, publication time, and current, historical, all-version, or as-of temporal modes. The query planner keeps focused fact lookups on a low-cost direct path and decomposes comparative, temporal, or multi-dimensional requests into batched first-hop queries plus an evidence-bridging hop before fusing repeated hits. Old versions remain in SQLite and Qdrant, and rebuilding restores every successfully indexed version. Promoting monitoring facts imports their complete version sequence using the original observation times.

Knowledge spaces provide owner, editor, and viewer roles. A space can require document approval and set a retention period. Pending or rejected content cannot become Agent evidence; expired content is removed from the index and file store while a body-free deletion audit remains. Approved versions resolve canonical product entities, cluster similar cross-source facts into single-source or corroborated events, and generate long-horizon insights in three explicit layers: facts, inferences, and hypotheses requiring validation. The workspace exposes version changes, numeric conflicts, entity events, layered insights, and governance state together.

Collector reuses local evidence before fresh web collection. Reviewer extracts factual claims from the comparison matrix, SWOT, trends, and dynamic insights, then batches explicit citations and local semantic retrieval to classify each claim as supported, contradicted, or insufficient while checking numbers and polarity. Writer may cite only evidence classified as supporting; contradictory and context-only material remains available in report audit data. Hits and verification results flow through the existing `CollectedDataPoint`, Analysis Context Pack, `ReviewVerdict`, `ReportData`, and `traceability_map` contracts. Missing model or index assets produce an explicit degraded verification state and do not block the analysis pipeline.

### Research workbench

Completed reports open in a full-screen research workbench with version tree, report, quality gate, semantic verification, long-horizon insights, sources, evidence graph, and process views. The verification view shows groundedness, citation precision, numeric consistency, and the supporting, contradictory, or insufficient evidence for each claim, with jumps to report sources and exact local historical chunks. The insight view preserves the facts, inferences, and hypotheses matched when that report version was generated and distinguishes evidence-linked items from context-only signals. The workbench also supports historical version navigation, diffs, exports, quality issue locating, and jumps from claims to report sections or source pages. The report directory, three-column scroll regions, and long text have independent boundaries to prevent overlap.

Every report version stores an immutable full snapshot containing the report body, analysis result, reviewer verdict, stage results, token usage, collected data, Analysis Brief, original request, and rework feedback. The version-detail API and workbench load these fields for the selected version, so quality, source, evidence, and process panels do not mix in current-version state. Historical records are labeled as “complete snapshot”, “partial snapshot”, or “unavailable”; missing legacy data is reported explicitly instead of being fabricated.

### Human report editing

The report editor provides per-section drafts, a changed-section counter, and one unified submit action. Opening an editor without changing text does not mark a section as changed; submitting automatically includes the currently open draft and reports update count and improvement ratio. Tables and charts remain read-only so structured report data is not accidentally damaged.

### Evidence graph

The evidence graph maps report claims and `[n]` citations, counts total, linked, and unsupported claims, and distinguishes multi-source, single-source, and unsupported evidence. Selecting a claim returns to its report section; selecting a source opens the source inspector with verification, credibility, and original URL details.

### Parallel report generation

Writer generates independent report chapters in bounded parallel while preserving chapter order. Tasks have concurrency limits, timeouts, cancellation, saturation protection, and deterministic fallbacks. A failed chapter does not block the complete report, and chapter-level progress is emitted in process events.

### Quality gate and version audit

Every report version stores an independent quality snapshot covering dimension coverage, source quality, single/multi/unsupported claims, blocking issues, warnings, reviewer notes, rework rounds, and improvement metrics. Quality and evidence information travel with the version for before/after audits.

### BranchTree

Agent execution is versioned. Each HITL intervention can create a branch, fork from any historical version, compare versions, and merge branches. After a report is generated, users can type a natural-language rework request in the same input box. Rework Intent routes it to `replan`, `reanalyze`, or `rewrite`, and records the result as a traceable version.

### Rework input and version tracking

Initial and rework queries appear as user bubbles before their corresponding execution rounds, keeping human input, agent phase messages, and the version tree aligned.

### Dynamic schema

The three-layer dimension model combines common fixed dimensions, industry candidates, and an LLM-adaptive layer. Common and industry dimensions are visible in the Analysis Brief and can be removed or reweighted. Confirmed `effective_dimensions` are shared by Collector, Analyst, Reviewer, and Writer. Analyst may propose evidence-backed dynamic blocks with a reason, source, and inclusion decision, preventing silent scope expansion.

### Observability

- **DAG execution graph**: five node states, animated edges, dashed feedback loops, and self-assessment dots.
- **Process trace**: inspect each node's prompt, input, output, token usage, and structured JSON.
- **Traceability chain**: jump from a report claim to its source data.
- **Human correction panel**: edit report chapters online and quantify improvement.

### Evolving source credibility

Each source domain has a credibility score from 0 to 1. Reviewer verification updates it across sessions using verified, conflict, error, and outdated outcomes. Pages are persisted in full so downstream agents can verify claims against original content instead of relying only on summaries.

### Agent reliability

A circuit breaker interrupts repeated calls after three consecutive duplicates. Per-agent timeouts and fallback handling prevent a single model failure from blocking the complete workflow.

### Preference profiles

`profile.md` defines analysis style, dimension weights, source rules, and other durable preferences. Orchestrator injects the profile into prompts at session start.

### Feishu integration

The system can send completion notifications, export reports to Feishu documents automatically, and expose a manual Feishu export action. Each feature is independently switchable and disabled by default.

## Technology Stack

| Layer | Technology |
|-------|------------|
| **Orchestration** | LangGraph StateGraph, conditional routing, and feedback loops |
| **Backend** | Python 3.12, FastAPI, Pydantic v2, and SQLite |
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS 4, and [DeerFlow](https://github.com/bytedance/deer-flow) UI/auth components |
| **DAG visualization** | [@xyflow/react](https://reactflow.dev/) |
| **LLM** | OpenAI-compatible APIs |
| **Search** | Tavily, DuckDuckGo, Jina AI, and provider-native web search |
| **RAG retrieval** | BGE-M3, FastEmbed BM25, Qdrant Local RRF fusion, and bge-reranker-v2-m3 |
| **Document parsing** | Docling, RapidOCR, and BeautifulSoup for PDF, Office, image, HTML, Markdown, CSV, JSON, and TXT |
| **Deployment** | uv + pnpm, with Next.js proxying FastAPI |
| **Persistence** | SQLite for business/knowledge metadata, Qdrant Local for rebuildable vectors, and `.ci-agent/knowledge` for source and normalized files |

## Quick Start

### Requirements

| Dependency | Version |
|------------|---------|
| Python | 3.12+ |
| uv | Latest stable |
| Node.js | 22+ |
| pnpm | 10+ |

### Make commands (recommended)

```bash
cp .env.example .env    # Fill in DOUBAO_API_KEY and other keys
make install            # Install dependencies
make dev                # Start the low-I/O local stack
```

Open `http://localhost:2026/competition` after startup. `make dev` reuses an existing frontend build when sources are unchanged and does not enable backend file watching, which is suitable for shared servers.

Common commands:

```bash
make stop               # Stop services
make restart            # Restart in low-I/O mode
make watch              # Hot reload (high I/O; use only when needed)
make start              # Start with an existing production build
make test               # Run tests
make lint               # Run linters
make build              # Rebuild the frontend
```

On hosts without pnpm or with restricted process networking, the fallback build uses the installed Next.js binary and Webpack. Production startup reuses `.next` output and does not require file watching.

To use different ports:

```bash
BACKEND_PORT=8002 FRONTEND_PORT=2027 make dev
```

### Start services separately

```bash
# Terminal 1: backend
cd backend
PYTHONDONTWRITEBYTECODE=1 uv run --locked --no-dev --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8001

# Terminal 2: frontend (run pnpm build once first)
cd frontend
pnpm start --hostname 0.0.0.0 --port 2026
```

## Configuration

The project supports two configuration modes selected by `CI_AGENT_CONFIG_MODE`:

| Mode | Trigger | Configuration source | Use case |
|------|---------|----------------------|----------|
| **DB mode** (default) | Unset or `CI_AGENT_CONFIG_MODE=db` | SQLite `user_settings`, managed in Settings | Production and multi-user isolation |
| **File mode** | `CI_AGENT_CONFIG_MODE=file` | `config.yaml` + `.env` | Debugging, demos, and no-account use |

### Continuous monitoring runtime

FastAPI starts an in-process observation scheduler by default, which is appropriate for the current single-process deployment. The following environment variables control it:

| Variable | Default | Description |
|----------|---------|-------------|
| `CI_AGENT_OBSERVATION_SCHEDULER_ENABLED` | `true` | Start and stop the observation scheduler with FastAPI |
| `CI_AGENT_OBSERVATION_POLL_SECONDS` | `30` | Interval for scanning due schedules; runtime minimum is 5 seconds |
| `CI_AGENT_NOTIFICATION_WEBHOOK` | empty | Optional alert webhook; Feishu delivery continues to use current user settings |

Manage schedules and alert rules at `/competition/monitoring`. Multi-process or horizontally scaled deployments should enable only one scheduler instance or move polling to a dedicated task worker.

### Local RAG models and storage

After installing dependencies, prepare the local models once. This requires several GB of disk and network access to Hugging Face:

```bash
uv run --project backend --locked python scripts/setup-rag-models.py
```

Models are stored under `.ci-agent/models`; originals, normalized Markdown, and the Qdrant index are stored under `.ci-agent/knowledge`. Both locations are ignored by Git. Runtime loading is local-only and never downloads models automatically. Open `/competition/knowledge` to manage documents. The default per-file limit is 50 MB; server-side files may be placed in `.ci-agent/knowledge/inbox` and imported by relative path.

FastAPI warms the local retrieval models in the background by default so the first analysis does not pay the full model-loading cost. Analysis retrieval normalizes common product aliases and bilingual dimension names, batch-encodes multiple product-by-dimension queries, and caches repeated query vectors and retrieval results. Activating a new document version, deleting a document, or rebuilding the index automatically invalidates the affected user's result cache.

The default strict set, `evals/rag/real-v1.json`, contains human-curated snapshots of public first-party competitor documentation with source URLs, capture times, and expected labels. `basic-v1.json` remains an explicitly synthetic unit-regression set. Neither enters the business knowledge base. The command below runs ingestion, cost-routed query planning, retrieval, and claim verification against temporary SQLite and in-memory Qdrant stores. It reports Recall@5, MRR, NDCG@5, no-answer abstention accuracy, traceability completeness, P50/P95 latency, direct/multi-hop route accuracy, decomposition coverage, claim-status accuracy, contradiction recall, citation precision, numeric-consistency accuracy, and groundedness, then writes the detailed report under the ignored `.ci-agent/evaluations/` directory:

```bash
make rag-eval
```

The following environment variables override storage and retrieval defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `CI_AGENT_DB_PATH` | `.ci-agent/competition.db` | SQLite path for business and knowledge metadata |
| `CI_AGENT_KNOWLEDGE_ROOT` | `.ci-agent/knowledge` | Root for originals, normalized files, Inbox, and indexes |
| `CI_AGENT_RAG_EMBEDDING_PATH` | `.ci-agent/models/embeddings/bge-m3` | Dense embedding model directory |
| `CI_AGENT_RAG_RERANKER_PATH` | `.ci-agent/models/rerankers/bge-reranker-v2-m3` | Cross-encoder reranker directory |
| `CI_AGENT_RAG_FASTEMBED_PATH` | `.ci-agent/models/fastembed` | BM25 model cache |
| `CI_AGENT_RAG_QDRANT_PATH` | `.ci-agent/knowledge/indexes/qdrant` | Qdrant Local directory |
| `CI_AGENT_RAG_MAX_UPLOAD_BYTES` | `52428800` | Maximum uploaded file size in bytes |
| `CI_AGENT_RAG_MIN_SCORE` | `0.08` | Minimum final reranked score |
| `CI_AGENT_RAG_PREWARM` | `true` | Warm local retrieval models in the background after FastAPI starts |
| `CI_AGENT_RAG_QUERY_VECTOR_CACHE_SIZE` | `256` | In-process query-vector LRU capacity; set to `0` to disable |
| `CI_AGENT_RAG_RESULT_CACHE_SIZE` | `256` | User- and filter-isolated retrieval-result LRU capacity |
| `CI_AGENT_RAG_RESULT_CACHE_TTL_SECONDS` | `300` | Retrieval-result cache lifetime; set to `0` to disable |

### DB mode

Open `/competition/settings` and configure LLM providers, API keys, search backends, Feishu credentials, and per-agent parameters. Settings are stored per user in `.ci-agent/competition.db` and synchronized across devices after login.

The settings panel contains:

- **API credentials**: LLM provider name/key/base URL, Tavily/Jina keys, and multiple Feishu credential sets.
- **Configuration groups**: independent presets with search and Feishu switches and per-agent overrides.
- **Per-agent overrides**: provider, model, temperature, timeout, and max turns for each agent.

### File mode (debug/demo)

File mode reads `config.yaml` and `.env` directly and can be used without an account. LLM and search keys live in `.env`; model routing, search switches, Feishu switches, and per-agent parameters live in `config.yaml`.

```bash
cp .env.example .env
cp config.example.yaml config.yaml
# Edit .env and config.yaml
CI_AGENT_CONFIG_MODE=file make dev
```

### Configuration sync

The `scripts/sync-user-config.py` utility migrates settings between File and DB modes:

```bash
uv run --project backend --locked --no-dev --no-sync python scripts/sync-user-config.py push <user_email>
uv run --project backend --locked --no-dev --no-sync python scripts/sync-user-config.py pull <user_email>
uv run --project backend --locked --no-dev --no-sync python scripts/sync-user-config.py push <user_email> --dry-run
uv run --project backend --locked --no-dev --no-sync python scripts/sync-user-config.py pull <user_email> --dry-run
```

### Environment file

Copy `.env.example` and fill only the providers and integrations you use. Typical variables include `DOUBAO_API_KEY`, `DEEPSEEK_API_KEY`, `QWEN_API_KEY`, `TAVILY_API_KEY`, `JINA_API_KEY`, `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_NOTIFY_OPEN_ID`, and `FEISHU_TENANT`. Search falls back to free DuckDuckGo search when optional search keys are absent.

DB mode does not require `.env` or `config.yaml`; File mode does.

### `config.yaml`

File mode uses built-in defaults. Copy `config.example.yaml` to assign providers, models, search switches, Feishu switches, and per-agent overrides. The file uses a two-level provider and configuration-group structure with an `active_group` selector. Each agent can override `provider` and `model` or inherit the group defaults.

### Feishu integration (optional)

Enable notification, automatic document export, or manual document export independently in the active configuration group. Prepare an enterprise self-built Feishu application, enable the bot capability, publish the required permissions, and fill the four Feishu variables in `.env`.

### Configuration locations

```text
competitive-analysis-agent/
├── .env               # API keys (not committed)
├── config.yaml        # Agent tuning (not committed)
├── .env.example       # Key template
└── config.example.yaml # Parameter template
```

## Project Structure

```text
competitive-analysis-agent/
├── backend/
│   ├── app/                           # FastAPI entrypoint and gateway routes
│   ├── packages/competition/           # LangGraph agents, schemas, tools, DB, and BranchTree
│   │   └── competition/knowledge_*.py   # Parsing, chunking, versioning, indexing, and retrieval
│   ├── tests/                          # Backend tests
│   ├── pyproject.toml                  # uv workspace configuration
│   └── uv.lock                         # Locked dependencies
├── frontend/
│   └── src/
│       ├── app/competition/             # Competition routes and shell
│       │   └── knowledge/               # Knowledge management and retrieval verification
│       ├── app/api/competition/         # SSE proxy route
│       └── components/competition/      # Chat, report, workbench, evidence, and trace UI
├── scripts/                            # Build, run, stop, and configuration helpers
├── images/                             # Documentation images
├── .env.example                         # Environment template
├── config.example.yaml                  # Agent configuration template
├── Makefile                             # Build/start/test shortcuts
├── README.md                            # Chinese documentation
└── README_en.md                         # English documentation
```

## Competition Requirements

| Requirement | Description | Implementation |
|-------------|-------------|----------------|
| R1 | Clear six-agent boundaries | `nodes/orchestrator.py`, `collector.py`, `analyst.py`, `reviewer.py`, `writer.py`, `hitl_gate.py` |
| R2 | Dual-track collection and survey | `nodes/collector.py` VoC Aggregator |
| R3 | Product knowledge schemas | `schema.py` |
| R4 | Structured JSON communication | `schema.py` result and decision models |
| R5 | Eight reviewer gap checks and rework | `nodes/reviewer.py` + `router.py` |
| R6 | Quantified feedback improvement | `competition_router.py` improvement ratio |
| R7 | `[n]` citations and traceability map | `nodes/writer.py` + `source-card.tsx` |
| R8 | Schema validation, retry, and fallback | `schema.py` model validation |
| R9 | Live DAG highlighting and animated edges | `dag.py` + `dag-graph.tsx` |
| R10 | Inspectable prompts, I/O, decisions, and tokens | Process trace UI + `/trace` |
| R11 | Complete end-to-end workflow | `graph.py` + SSE gateway + frontend |
| R12 | Hallucination controls | Reviewer and Analyst evidence checks |
| R13 | Timeout, retry, and degradation | Per-agent config and error handler |
| R14 | BranchTree, checkpoints, and source credibility | `branchtree/` + `db.py` |
| R15 | Quantified coverage, validation, and improvement | Writer metrics + schemas |

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/competition/analyze` | Create an analysis task and return a thread ID |
| GET | `/api/competition/stream/{thread_id}` | SSE progress and agent output stream |
| GET | `/api/competition/report/{thread_id}` | Get report and phase data |
| GET | `/api/competition/report/{thread_id}/history` | Get version history and branches |
| GET | `/api/competition/report/{thread_id}/versions/{version}` | Get the immutable full snapshot for one report version |
| GET | `/api/competition/report/{thread_id}/trace` | Get agent execution trace |
| PATCH | `/api/competition/report/{thread_id}/sections` | Edit report sections |
| PUT | `/api/competition/report/{thread_id}` | Submit HITL decision |
| POST | `/api/competition/{thread_id}/cancel` | Stop a running analysis |
| GET | `/api/competition/report/{thread_id}/export` | Export Markdown or JSON |
| GET | `/api/competition/me` | Get current user information |
| GET | `/api/competition/history` | List analysis history |
| GET | `/api/competition/observation/runtime` | Get continuous monitoring scheduler status |
| GET / POST | `/api/competition/observation/schedules` | List or create observation schedules for the current user |
| PUT / DELETE | `/api/competition/observation/schedules/{schedule_id}` | Edit or delete an observation schedule |
| POST | `/api/competition/observation/schedules/{schedule_id}/run-now` | Run an observation schedule immediately |
| GET | `/api/competition/observation/runs` | List observation run history for the current user |
| GET | `/api/competition/intelligence/changes` | List the incremental intelligence change timeline |
| GET | `/api/competition/intelligence/changes/{change_id}` | Get one change with its current fact, sources, and version history |
| GET | `/api/competition/intelligence/items` | List intelligence facts available for explicit knowledge ingestion |
| GET | `/api/competition/knowledge/status` | Get knowledge database, model, and index status |
| GET / POST / PATCH | `/api/competition/knowledge/spaces` | Manage project knowledge spaces, approval, and retention policies |
| GET / PUT / DELETE | `/api/competition/knowledge/spaces/{space_id}/members` | Manage viewer and editor membership |
| POST | `/api/competition/knowledge/documents/{document_id}/review` | Approve or reject a pending document |
| GET | `/api/competition/knowledge/events` | List canonical-entity events clustered across sources |
| GET / POST | `/api/competition/knowledge/insights` / `/api/competition/knowledge/insights/refresh` | List or regenerate fact, inference, and hypothesis layers |
| GET | `/api/competition/knowledge/deletions` | List auditable deletion records |
| POST | `/api/competition/knowledge/retention/run` | Apply expired retention policies immediately |
| POST | `/api/competition/knowledge/upload` | Upload and asynchronously parse, chunk, and index a document |
| POST | `/api/competition/knowledge/import-inbox` | Import a file by restricted Inbox-relative path |
| POST | `/api/competition/knowledge/import-intelligence` | Promote explicitly selected intelligence facts into knowledge documents |
| GET | `/api/competition/knowledge/documents` | List documents with status, product, source-type, and pagination filters |
| GET / DELETE | `/api/competition/knowledge/documents/{document_id}` | Inspect versions/chunks or delete a document |
| POST | `/api/competition/knowledge/documents/{document_id}/reindex` | Reparse and reindex the current usable version |
| GET | `/api/competition/knowledge/jobs`, `/api/competition/knowledge/jobs/{job_id}` | Inspect asynchronous ingestion and rebuild jobs |
| POST | `/api/competition/knowledge/search` | Run filtered hybrid retrieval and reranking |
| GET | `/api/competition/knowledge/chunks/{chunk_id}` | Read an authorized original evidence chunk |
| POST | `/api/competition/knowledge/rebuild` | Rebuild the current user's Qdrant index from SQLite |
| GET / POST | `/api/competition/alerts/rules` | List or create alert rules |
| PUT / DELETE | `/api/competition/alerts/rules/{rule_id}` | Edit or delete an alert rule |
| GET / POST | `/api/competition/alerts/events` / `/api/competition/alerts/dispatch` | List alert history or dispatch pending alerts |

Use `?summary=true` on report polling requests for a lightweight active-state response. Terminal states still return complete report data. FastAPI Swagger is available at `http://localhost:8001/docs`.

## Roadmap

The current system combines realtime search with local hybrid RAG and persists business, knowledge, and evidence data in SQLite, Qdrant Local, and file storage. It is ready for an end-to-end competition demonstration. Productization directions reserved by the architecture include:

### Advanced RAG

- Add optional model-based rewriting or HyDE only for complex requests where the real golden set demonstrates gains over the current zero-LLM direct/multi-hop planner.
- Extend the current entity events, cross-source clustering, and three-layer insights with editable relationships, hypothesis approval/rejection, analyst feedback, and historical accuracy.
- Continuously expand authorized real evaluation coverage with completed reports, observation histories, PDF/OCR edge cases, cross-language questions, and hard negatives without training on or contaminating production knowledge.

### Higher concurrency and productionization

- Move in-memory `_store` state to Redis or PostgreSQL for horizontal gateway scaling.
- Move threaded analysis to Celery or another queue with independent workers.
- Upgrade SQLite WAL to PostgreSQL for concurrent writes and connection pooling.
- Add per-user or per-tenant token budgets, rate limits, and search quotas.
- Extend authentication to full project spaces and permission isolation.

## License

[MIT](LICENSE)
