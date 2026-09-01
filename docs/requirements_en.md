# Competition Requirements Coverage

| Requirement | Implementation |
| --- | --- |
| Clear boundaries for six Agents | `nodes/orchestrator.py`, `collector.py`, `analyst.py`, `reviewer.py`, `writer.py`, `hitl_gate.py` |
| Dual-track collection and VoC | `nodes/collector.py` |
| Competitive-intelligence schemas | `schema.py` |
| Structured JSON communication | AnalysisResult, ReviewVerdict, ReportData, and related types in `schema.py` |
| Reviewer quality checks and targeted rework | `nodes/reviewer.py`, `router.py` |
| Quantified feedback improvement | `competition_router.py` |
| `[n]` citations and traceability map | `nodes/writer.py`, `source-card.tsx` |
| Schema validation, retries, and fallback | `schema.py` and node error handling |
| Live DAG state | `dag.py`, `dag-graph.tsx` |
| Inspectable prompts, IO, and tokens | `process-trace-panel.tsx`, `agent-detail-panel.tsx`, `/trace` |
| End-to-end demonstrable flow | `graph.py`, `competition_router.py`, analysis pages |
| Hallucination and numeric checks | `nodes/reviewer.py`, `nodes/analyst.py` |
| Timeouts, retries, and degradation | `config.py`, `nodes/error_handler.py` |
| BranchTree, checkpoints, and source credibility | `branchtree/`, `db.py` |
| Coverage, corroboration, and improvement metrics | `nodes/writer.py`, `schema.py` |

Use this matrix to locate implementation during defense or interviews. Code, tests, and observed runtime behavior remain authoritative.
