"""Single-layer state definition for the CI-Agent competition analysis system.

State Architecture
------------------
CompetitionState (single graph, no nested subgraphs)
  └── Collector → Analyst → Reviewer → Writer → HITL Gate

Key design:
- 4 Agent roles mapped to 4 nodes + 1 HITL Gate + 1 error handler
- Annotated[list, op_add] reducers auto-merge multi-round/parallel results
- error field triggers Graph-level routing to error_handler node
- review_round stays top-level for routing ergonomics (§3.12 route_after_reviewer)
"""

from operator import add as op_add
from typing import Annotated, NotRequired, TypedDict

from langchain.agents import AgentState


class CompetitionState(AgentState):
    """CI-Agent single-graph state for competitive intelligence analysis.

    Corresponds to COMPETITION_PLAN.md §3.9 — complete field inventory.
    LangGraph requires all graph states to include ``messages`` (inherited from AgentState).
    """

    # ── User Input ──
    user_request: NotRequired[str | None]
    """Natural language analysis request from user."""
    target_products: NotRequired[list[str] | None]
    """Products to compare, e.g. ['cursor', 'copilot', 'windsurf']."""
    persona: NotRequired[str | None]
    """"pm" | "entrepreneur" | "both" — drives Writer dual-perspective output."""
    deep_mode: NotRequired[bool | None]
    """False = normal mode only, True = normal + deep mode pipeline."""

    # ── Collector Output (accumulated across rounds via op_add reducer) ──
    collected_data: Annotated[list[dict], op_add]
    """Structured CollectionResult per §3.4.1 — source_url + confidence required."""
    collection_summary: NotRequired[dict | None]
    """Per-round summary: total_data_points, products_covered, stopped_by, etc. (§3.4.6)."""
    knowledge_gaps: NotRequired[list[dict] | None]
    """Gaps discovered by Reviewer → deep mode Collector re-targets these."""

    # ── Analyst Output ── [竞赛要求 R4]
    analysis_result: NotRequired[dict | None]
    """AnalysisResult: comparison_matrix + swot + trends + forecast + visualization_paths (§3.13.3)."""

    # ── Reviewer Output ──
    review_verdict: NotRequired[dict | None]
    """ReviewVerdict: passed + gaps + fact_errors + quality_summary (§3.13.4)."""
    review_round: NotRequired[int | None]
    """Current feedback round (top-level for routing ergonomics, §3.12 route_after_reviewer)."""
    gap_coverage_improvement: NotRequired[float | None]
    """Improvement ratio: resolved gaps / total gaps identified this round (§3.12.1)."""

    # ── Writer Output (normal mode) ── [竞赛要求 R7]
    report_data: NotRequired[dict | None]
    """ReportData: interactive frontend-native report replacing legacy .md strings (§3.7.2)."""
    traceability_map: NotRequired[dict | None]
    """claim_id → {url, fetch_timestamp, confidence} — per-claim source traceability."""
    review_package: NotRequired[dict | None]
    """ReviewPackage: Writer → HITL Gate approval briefing (§3.13.5)."""

    # ── Deep Mode ──
    deep_collected_data: Annotated[list[dict], op_add]
    """Incremental data collected in deep mode (op_add accumulator)."""
    deep_review_round: NotRequired[int | None]
    """Deep mode Reviewer round counter."""
    deep_report: NotRequired[str | None]
    """Deep mode final report (HTML)."""
    deep_feishu_url: NotRequired[str | None]
    """Feishu document URL from deep mode delivery."""

    # ── HITL Gate ──
    hitl_decision: NotRequired[dict | None]
    """HitlDecision: action + comment + target_focus + timestamp (§3.13.7)."""
    deep_hitl_decision: NotRequired[dict | None]
    """Deep mode HITL decision (separate from normal mode)."""

    # ── Error ──
    error: NotRequired[str | None]
    """Non-empty triggers Graph-level routing to error_handler node (§3.15.6.3)."""
