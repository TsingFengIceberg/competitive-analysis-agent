<p align="center">
  <img src="images/logo.png" alt="Competitive-Analysis-Agent" width="80" />
</p>

<h1 align="center">Competitive-Analysis-Agent</h1>

<p align="center">English | <a href="./README.md">中文</a></p>

<p align="center"><strong>AI-powered competitive-analysis Agent collaboration system</strong></p>

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-ff6f00?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![React](https://img.shields.io/badge/React-19-61dafb?logo=react)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.8-3178c6?logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003b57?logo=sqlite&logoColor=white)](https://sqlite.org)

## Contents

- [Positioning](#positioning)
- [Core capabilities](#core-capabilities)
- [Architecture at a glance](#architecture-at-a-glance)
- [Quick start](#quick-start)
- [Documentation](#documentation)
- [Technology stack](#technology-stack)
- [Project structure](#project-structure)
- [Tests](#tests)
- [License](#license)

## Positioning

Competitive-Analysis-Agent turns competitive research into a traceable, reviewable, and interruptible Agent workflow. It starts with a natural-language request and covers scope confirmation, multi-source collection, evidence verification, comparative analysis, quality review, and report generation. It also provides continuous competitor monitoring, a local knowledge base/RAG layer, a research workbench, and a standard A2A Provider.

## Core capabilities

- **Structured Agent collaboration**: Orchestrator, Collector, Analyst, Reviewer, Writer, and HITL communicate through Pydantic schemas.
- **Pre-analysis scope confirmation**: Products, decision goal, dimensions, weights, industry, time range, and evidence policy are editable before execution.
- **Three-layer adaptive dimensions**: Common, industry, and model-proposed dimensions; users can remove or reweight candidates.
- **Evidence quality loop**: Citations, numeric consistency, source credibility, corroboration, and targeted rework are traceable.
- **Research workbench**: Version tree, quality gates, semantic verification, sources, evidence graph, and process trace in one workspace.
- **Continuous monitoring**: Scheduled incremental collection triggers deep analysis only for material changes and supports alerts and complete report history.
- **Local knowledge base and RAG**: Versioned documents, hybrid retrieval, reranking, GraphRAG, temporal filters, governance, and offline evaluation.
- **Reliability and recovery**: Durable task queue, schedule leases, standalone Worker, cancellation, retries, fallbacks, and SSE replay.
- **Standard A2A interoperability**: Independent AgentCard, JSON-RPC, Tasks, Artifacts, standard SSE, and replaceable authentication.

## Architecture at a glance

![System architecture](images/architecture.png)

```text
Next.js UI ── REST/SSE ── FastAPI Gateway
                              │
                       LangGraph Workflow
             Orchestrator → Collector → Analyst
                                  ↓          │
                              Reviewer ←─────┘
                                  ↓
                           Writer → HITL Gate
                              │
                SQLite + Qdrant + Object Storage
                              │
                     A2A Provider (separate adapter)
```

See [Architecture and workflow](docs/architecture_en.md) for state contracts, versions, HITL, and event design.

## Quick start

### Requirements

Python 3.12+, uv, Node.js 22+, and pnpm 10+.

```bash
make install
make dev
```

Open `http://localhost:2026/competition`. Common commands:

```bash
make stop
make restart
make watch
make start
make test
make lint
make build
```

DB configuration mode is the default. For debugging or demos:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
CI_AGENT_CONFIG_MODE=file make dev
```

Override ports with `BACKEND_PORT=8002 FRONTEND_PORT=2027 make dev`. See [Operations and troubleshooting](docs/operations_en.md) for startup, SSH tunneling, and diagnostics.

## Documentation

| Document | Use it for |
| --- | --- |
| [Architecture and workflow](docs/architecture_en.md) | Agent orchestration, state, HITL, versions, and reliability |
| [RAG and knowledge governance](docs/rag_en.md) | Ingestion, retrieval, GraphRAG, evaluation, and permissions |
| [Configuration guide](docs/configuration_en.md) | Models, search, monitoring, RAG storage, and Feishu |
| [A2A Provider](docs/a2a-provider_en.md) | AgentCard, JSON-RPC, Tasks, SSE, and authentication |
| [API reference](docs/api_en.md) | REST, SSE, monitoring, and knowledge endpoints |
| [Operations and troubleshooting](docs/operations_en.md) | Startup, tests, recovery, logs, and remote access |
| [Competition requirements coverage](docs/requirements_en.md) | Defense requirements mapped to implementation |
| [Roadmap](docs/roadmap_en.md) | Delivered capabilities, current boundaries, and next steps |

Chinese documentation is indexed at [docs/README.md](docs/README.md). Keep the root README and README_en.md synchronized in features and structure.

## Technology stack

| Layer | Technology |
| --- | --- |
| Orchestration | LangGraph StateGraph, conditional routing, feedback loops |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLite |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4 |
| Retrieval | BGE-M3, FastEmbed BM25, Qdrant RRF, bge-reranker-v2-m3 |
| Parsing | Docling, RapidOCR, OOXML fallback, BeautifulSoup |
| Tasks | SQLite durable queue, schedule leases, standalone Worker |
| Interoperability | `a2a-sdk==1.1.2`, A2A protocol 1.0 |
| Deployment | uv, pnpm, Docker configuration, Make commands |

## Project structure

```text
backend/app/                         # FastAPI gateway, A2A, task Worker
backend/packages/competition/        # LangGraph, schemas, RAG, monitoring, reports
backend/tests/                       # Backend unit and integration tests
frontend/src/app/competition/        # Analysis, monitoring, knowledge, and settings pages
frontend/src/components/competition/ # Reports, DAG, workbench, and evidence components
docs/                                # Topic documentation in both languages
evals/rag/                           # Offline RAG evaluation sets
scripts/                             # Startup, model, evaluation, and sync scripts
images/                              # Architecture and UI assets
```

Runtime databases, models, source files, and evaluation reports live under `.ci-agent/` and are not committed.

## Tests

```bash
make test
make lint
make rag-eval
cd backend && uv run --locked pytest tests/test_a2a_provider.py
```

For frontend checks use `frontend/node_modules/.bin/tsc --noEmit`, `eslint .`, and `prettier --check .`. Real S3/Qdrant connectivity tests require those services and credentials and are not part of the default local suite.

## License

[MIT](LICENSE)
