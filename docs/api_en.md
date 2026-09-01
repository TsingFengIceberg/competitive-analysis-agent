# API Reference

The backend runs at `http://localhost:8001` by default and exposes Swagger at `/docs`. Business APIs are scoped to the current user or knowledge-space permissions.

## Analysis and reports

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/competition/analyze` | Create an analysis task |
| GET | `/api/competition/stream/{thread_id}` | Frontend-specific SSE |
| GET | `/api/competition/report/{thread_id}` | Report and stage data |
| GET | `/api/competition/report/{thread_id}/history` | Version history and branches |
| GET | `/api/competition/report/{thread_id}/versions/{version}` | Complete version snapshot |
| GET | `/api/competition/report/{thread_id}/trace` | Agent process trace |
| PATCH | `/api/competition/report/{thread_id}/sections` | Human section edits |
| PUT | `/api/competition/report/{thread_id}` | HITL approval or rework |
| POST | `/api/competition/{thread_id}/cancel` | Cancel analysis |
| GET | `/api/competition/report/{thread_id}/export` | Markdown/JSON export |

## Monitoring and alerts

Manage schedules at `/api/competition/observation/schedules`, run now with `/api/competition/observation/schedules/{id}/run-now`, and inspect history at `/api/competition/observation/runs`. The change timeline is `/api/competition/intelligence/changes`, with detail at `/api/competition/intelligence/changes/{change_id}`.

Alert rules use `/api/competition/alerts/rules`; history and dispatch use `/api/competition/alerts/events` and `/api/competition/alerts/dispatch`. Subscriptions and feedback use `/api/competition/subscriptions` and `/api/competition/alerts/events/{event_id}/feedback`.

## Knowledge and RAG

| Capability | Paths |
| --- | --- |
| Status, documents, jobs | `/api/competition/knowledge/status`, `/documents`, `/jobs` |
| Upload/import/rebuild | `/upload`, `/import-inbox`, `/import-intelligence`, `/rebuild` |
| Retrieval and feedback | `/search`, `/retrieval-logs`, `/retrieval-feedback` |
| Evaluation and experiments | `/evaluate`, `/evaluation-datasets`, `/retrieval-experiments` |
| Source operations | `/sources/health`, `/sources/{id}/sync`, `/sources/{id}/retry` |
| Spaces and governance | `/spaces`, `/reviews`, `/governance/stats`, `/deletions` |
| Entities, relations, insights | `/entities`, `/graph`, `/events`, `/insights` |
| Evidence chunks | `/chunks/{chunk_id}` |

Use the FastAPI OpenAPI schema for exact request bodies; internal database fields are not public contracts.

## A2A

See the [A2A Provider documentation](a2a-provider_en.md) for AgentCard, JSON-RPC, Tasks, and SSE. It is separate from frontend-specific SSE.
