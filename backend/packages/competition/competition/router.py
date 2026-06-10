"""Conditional routing functions for the CI-Agent competition graph.

Per COMPETITION_PLAN.md §3.13 — route_after_* pure functions.
Each function reads CompetitionState and returns the next node name (str).
All functions are pure: dict → str, zero side effects, trivially testable.

v4: Pipeline structure is FIXED (O→C→A→R→W→H). Complexity only controls
execution depth (search budget, review rounds) — never skips nodes.
"""

from __future__ import annotations


# ── Orchestrator Routing `[v4]` ──


def route_after_orchestrator(state: dict) -> str:
    """Orchestrator → Collector (always).

    Pipeline structure is fixed. Complexity tier only affects execution
    parameters — not which nodes run.
    """
    if state.get("error"):
        return "error_handler"
    return "collector"


# ── Normal Mode Routing ──


def route_after_collector(state: dict) -> str:
    """Collector → Analyst (normal) or error_handler (no data / error)."""
    if state.get("error"):
        return "error_handler"
    collected = state.get("collected_data") or []
    if len(collected) == 0:
        return "error_handler"
    return "analyst"


def route_after_analyst(state: dict) -> str:
    """Analyst → Reviewer (always)."""
    if state.get("error"):
        return "error_handler"
    return "reviewer"


def route_after_reviewer(state: dict) -> str:
    """Reviewer → Writer (passed / max rounds) or Collector (gap feedback).

    v4: max rounds is complexity-driven:
      quick: 1 round / standard: 2 rounds / deep: 3 rounds
    """
    if state.get("error"):
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
    if state.get("error"):
        return "error_handler"
    return "hitl_gate"


def route_after_hitl(state: dict) -> str:
    """HITL Gate → END / Collector / Analyst / Writer / deep_collector."""
    decision = state.get("hitl_decision") or {}
    action = decision.get("action", "approve")

    if action == "approve":
        return "deep_collector" if state.get("deep_mode") else "__end__"
    elif action == "replan":
        return "collector"
    elif action == "reanalyze":
        return "analyst"
    elif action == "rewrite":
        return "writer"
    return "__end__"


# ── Deep Mode Routing (§3.12, P1) ──


def route_after_deep_collector(state: dict) -> str:
    """Deep Collector → Deep Analyst."""
    if state.get("error"):
        return "deep_error_handler"
    return "deep_analyst"


def route_after_deep_analyst(state: dict) -> str:
    """Deep Analyst → Deep Reviewer."""
    if state.get("error"):
        return "deep_error_handler"
    return "deep_reviewer"


def route_after_deep_reviewer(state: dict) -> str:
    """Deep Reviewer → Deep Writer (passed / max rounds) or Deep Collector (gap)."""
    verdict = state.get("review_verdict") or {}
    if verdict.get("passed"):
        return "deep_writer"

    deep_round = state.get("deep_review_round", 0)
    if deep_round >= 5:
        return "deep_writer"

    return "deep_collector"


def route_after_deep_writer(state: dict) -> str:
    """Deep Writer → Deep HITL."""
    if state.get("error"):
        return "deep_error_handler"
    return "deep_hitl"


def route_after_deep_hitl(state: dict) -> str:
    """Deep HITL → feishu_delivery (approve) / deep_collector / deep_analyst / deep_writer."""
    decision = state.get("deep_hitl_decision") or {}
    action = decision.get("action", "approve")

    if action == "approve":
        return "feishu_delivery"
    elif action == "replan":
        return "deep_collector"
    elif action == "reanalyze":
        return "deep_analyst"
    elif action == "rewrite":
        return "deep_writer"
    return "feishu_delivery"
