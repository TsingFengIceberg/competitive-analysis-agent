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

### Research workbench

Completed reports open in a full-screen research workbench with version tree, report, quality gate, sources, evidence graph, and process views. It supports historical version navigation, diffs, exports, quality issue locating, and jumps from claims to report sections or source pages. The report directory, three-column scroll regions, and long text have independent boundaries to prevent overlap.

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
| **Deployment** | uv + pnpm, with Next.js proxying FastAPI |
| **Persistence** | SQLite WAL: analysis history, phase history, source credibility, product baseline, and branch snapshots |

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
│   ├── tests/                          # Backend tests
│   ├── pyproject.toml                  # uv workspace configuration
│   └── uv.lock                         # Locked dependencies
├── frontend/
│   └── src/
│       ├── app/competition/             # Competition routes and shell
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
| GET | `/api/competition/report/{thread_id}/trace` | Get agent execution trace |
| PATCH | `/api/competition/report/{thread_id}/sections` | Edit report sections |
| PUT | `/api/competition/report/{thread_id}` | Submit HITL decision |
| POST | `/api/competition/{thread_id}/cancel` | Stop a running analysis |
| GET | `/api/competition/report/{thread_id}/export` | Export Markdown or JSON |
| GET | `/api/competition/me` | Get current user information |
| GET | `/api/competition/history` | List analysis history |

Use `?summary=true` on report polling requests for a lightweight active-state response. Terminal states still return complete report data. FastAPI Swagger is available at `http://localhost:8001/docs`.

## Roadmap

The current system uses realtime search and SQLite persistence and is ready for an end-to-end competition demonstration. Productization directions reserved by the architecture include:

### RAG and vector storage

- Reuse product baselines and historical evidence across analyses.
- Use semantic retrieval for Reviewer evidence checks, including paraphrases and cross-language claims.
- Compare long-term market and pricing trends across accumulated reports.

### Higher concurrency and productionization

- Move in-memory `_store` state to Redis or PostgreSQL for horizontal gateway scaling.
- Move threaded analysis to Celery or another queue with independent workers.
- Upgrade SQLite WAL to PostgreSQL for concurrent writes and connection pooling.
- Add per-user or per-tenant token budgets, rate limits, and search quotas.
- Extend authentication to full project spaces and permission isolation.

## License

[MIT](LICENSE)
