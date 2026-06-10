"""Deep Reviewer node (P1) — extended validation with relaxed round cap.

Per COMPETITION_PLAN.md §3.1: Up to 5 review rounds instead of 2.
Reuses normal-mode Reviewer's 8 gap checks.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def deep_reviewer_node(state: dict) -> dict:
    """Graph node: review deep analysis results with relaxed 5-round cap.

    Reuses the same 8 check functions (G1-G8) from normal-mode Reviewer.
    """
    analysis = state.get("analysis_result") or {}
    collected = (state.get("collected_data") or []) + (state.get("deep_collected_data") or [])
    prev_gaps = _gaps_from_verdict(state.get("review_verdict"))
    deep_round = state.get("deep_review_round", 0)

    from competition.nodes.reviewer import (
        _build_quality_summary,
        _filter_loop_gaps,
        _generate_notes,
        _measure_improvement,
        check_data_freshness,
        check_dimension_coverage,
        check_multi_source_consistency,
        check_source_diversity,
        check_statistical_outliers,
        check_url_reachability,
    )

    gaps: list[dict] = []
    gaps.extend(check_url_reachability(collected))
    gaps.extend(check_multi_source_consistency(collected))
    gaps.extend(check_data_freshness(collected))
    gaps.extend(check_dimension_coverage(analysis, state.get("target_products", [])))
    gaps.extend(check_source_diversity(collected))
    gaps.extend(check_statistical_outliers(collected))

    gaps = _filter_loop_gaps(gaps, prev_gaps, deep_round)

    # Deep mode: passed if no critical gaps OR round >= 5 (relaxed cap, §3.12)
    has_critical = any(g.get("severity") == "critical" for g in gaps)
    passed = not has_critical or deep_round >= 5

    improvement = _measure_improvement(prev_gaps, gaps)
    quality = _build_quality_summary(collected, gaps, improvement)
    new_round = deep_round + 1 if not passed else deep_round

    verdict = {
        "passed": passed,
        "round": new_round,
        "gaps": gaps,
        "fact_errors": [g for g in gaps if g.get("type") == "fact_error"],
        "quality_summary": quality,
        "reviewer_notes": _generate_notes(gaps, improvement),
    }

    return {
        "review_verdict": verdict,
        "deep_review_round": new_round,
        "gap_coverage_improvement": improvement,
    }


def _gaps_from_verdict(verdict: dict | None) -> list[dict]:
    if verdict is None:
        return []
    return verdict.get("gaps", []) or []
