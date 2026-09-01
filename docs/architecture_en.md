# Architecture and Workflow

## System boundary

The system consists of a Next.js frontend, a FastAPI gateway, a LangGraph competitive-analysis workflow, and SQLite/Qdrant knowledge storage. It exposes the existing REST/SSE APIs and an independent standard A2A Provider. A2A exposes the complete analysis system as one black-box Agent; internal Agents are not exposed as separate remote Agents.

## LangGraph workflow

| Stage | Role | Main output |
| --- | --- | --- |
| Orchestration | Orchestrator | Intent, complexity, effective dimensions, and schema |
| Collection | Collector | Deduplicated multi-source data points and coverage |
| Analysis | Analyst | Comparison matrix, SWOT, trends, and dynamic blocks |
| Review | Reviewer | Quality gate, citation/numeric checks, gaps, and rework plan |
| Writing | Writer | Structured report chapters, citations, and `traceability_map` |
| Human gate | HITL Gate | Confirmation, approval, cancellation, or natural-language rework |

Agents communicate through Pydantic schemas. `CompetitionState` represents business workflow state, while `StageResult` records normalized execution status, timing, token usage, and errors for each stage.

## Scope confirmation and adaptive dimensions

Analysis Brief is the contract for an analysis: products, decision goal, dimensions and weights, industry, audience, time range, depth, and evidence policy. Ambiguous scope or fewer than two products leaves the task in `input-required` before collection starts.

Dimensions have three layers: common candidates, industry candidates, and model-proposed dynamic dimensions. Users can remove or reweight the first two layers. Confirmed `effective_dimensions` is the only scope consumed by downstream Agents. Analyst-proposed blocks must include rationale, evidence, and an inclusion decision.

## Quality loop

Reviewer checks coverage, corroboration, source credibility, freshness, dimension completeness, numeric consistency, and semantic consistency. Gaps become product-by-dimension rework plans; Collector fills only those gaps within a bounded number of rounds. Each round persists a quality snapshot, improvement ratio, and repair delta. Writer cites only explicitly supporting evidence.

## Versions, reports, and human editing

Every report version stores an immutable snapshot containing the report, analysis result, reviewer verdict, stage results, token usage, collected data, Analysis Brief, original request, and rework feedback. HITL actions can fork any version into the BranchTree and compare versions.

The research workbench combines the version tree, report, quality gate, semantic verification, long-horizon insights, sources, evidence graph, and process trace. Human editing is limited to prose sections; tables and charts remain structured and read-only.

## Parallelism and reliability

Writer generates independent chapters with bounded concurrency while preserving chapter order. A timed-out or failed chapter uses a deterministic fallback. Agent calls have timeouts, bounded retries, circuit breaking, and degradation paths. Background work enters a durable queue; SQLite leases prevent duplicate observation execution across processes, and a standalone Worker can consume tasks outside the web process.

## Events and observability

Frontend-specific SSE carries progress, messages, and report updates. The A2A Provider has a separate standard SSE adapter. Events have stable IDs and can be replayed from persistence after disconnects. DAG, process trace, token, provenance, and quality views read persisted stage data rather than browser memory.

## Related code

- `backend/packages/competition/competition/graph.py`: LangGraph orchestration and routing
- `backend/packages/competition/competition/schema.py`: cross-stage schemas
- `backend/packages/competition/competition/nodes/`: Agent nodes
- `backend/packages/competition/competition/task_queue.py`: durable task queue
- `backend/app/task_worker.py`: standalone task Worker
- `frontend/src/components/competition/research-workbench.tsx`: research workbench
