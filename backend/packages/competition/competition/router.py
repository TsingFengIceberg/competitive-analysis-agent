"""Conditional routing functions for the CI-Agent competition graph.

Per COMPETITION_PLAN.md §3.13 — route_after_* pure functions.
Each function reads CompetitionState and returns the next node name (str).
All functions are pure: dict → str, zero side effects, trivially testable.

v4: Pipeline structure is FIXED (O→C→A→R→W→H). Complexity only controls
execution depth (search budget, review rounds) — never skips nodes.
"""

from __future__ import annotations

from competition.stage_result import TERMINAL_FAILURE_STATUSES, latest_stage_result


def _stage_failed(state: dict, stage: str) -> bool:
    result = latest_stage_result(state, stage)
    return bool(result and result.get("status") in TERMINAL_FAILURE_STATUSES)


# ── Orchestrator Routing `[v4]` ──


def route_after_orchestrator(state: dict) -> str:
    """Orchestrator → Collector (always).

    Pipeline structure is fixed. Complexity tier only affects execution
    parameters — not which nodes run.
    """
    if state.get("error") or _stage_failed(state, "orchestrator"):
        return "error_handler"
    return "collector"


# ── Normal Mode Routing ──


def route_after_collector(state: dict) -> str:
    """Collector → Analyst (normal) or error_handler (no data / error)."""
    if state.get("error") or _stage_failed(state, "collector"):
        return "error_handler"
    collected = state.get("collected_data") or []
    if len(collected) == 0:
        return "error_handler"
    return "analyst"


def route_after_analyst(state: dict) -> str:
    """Analyst → Reviewer (always)."""
    if state.get("error") or _stage_failed(state, "analyst"):
        return "error_handler"
    return "reviewer"


def route_after_reviewer(state: dict) -> str:
    """Reviewer → Writer (passed / max rounds) or Collector (gap feedback).

    v4: max rounds is complexity-driven:
      quick: 1 round / standard: 2 rounds / deep: 3 rounds
    """
    if state.get("error") or _stage_failed(state, "reviewer"):
        return "error_handler"

    verdict = state.get("review_verdict") or {}
    if verdict.get("passed"):
        return "writer"

    orch = state.get("orchestration_result") or {}
    complexity = orch.get("complexity", "standard")
    max_rounds = {"quick": 1, "standard": 2, "deep": 3}
    cap = max_rounds.get(complexity, 2)

    review_round = state.get("review_round", 0)
    if review_round >= cap:
        return "writer"  # hard cap — proceed with uncertainty

    return "collector"


def route_after_writer(state: dict) -> str:
    """Writer → HITL Gate (always)."""
    if state.get("error") or _stage_failed(state, "writer"):
        return "error_handler"
    return "hitl_gate"


def route_after_hitl(state: dict) -> str:
    """HITL Gate → END / Collector / Analyst / Writer."""
    if state.get("error") or _stage_failed(state, "hitl_gate"):
        return "error_handler"
    decision = state.get("hitl_decision") or {}
    action = decision.get("action", "approve")

    if action == "approve":
        return "__end__"
    elif action == "replan":
        return "collector"
    elif action == "reanalyze":
        return "analyst"
    elif action == "rewrite":
        return "writer"
    return "__end__"
