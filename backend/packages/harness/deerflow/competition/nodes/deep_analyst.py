"""Deep Analyst node (P1) — extended analysis with segmentation, prediction, and financial modeling.

Per COMPETITION_PLAN.md §3.1: Builds on normal-mode analysis_result with deeper dimensions.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def deep_analyst_node(state: dict) -> dict:
    """Graph node: perform deeper analysis on the combined normal + deep data.

    Adds: segment-level analysis, financial projections, full visualization suite.
    """
    analysis = state.get("analysis_result") or {}
    deep_data = state.get("deep_collected_data") or []
    target_products = state.get("target_products", [])

    task = _build_deep_analyst_task(analysis, deep_data, target_products)
    raw_output = _execute_deep_analyst(task, state)

    # Reuse normal-mode Analyst's result builder + self-check
    from deerflow.competition.nodes.analyst import _build_analysis_result, self_check
    result = _build_analysis_result(raw_output, state)
    # Augment with deep-mode markers
    result["_deep_mode"] = True
    errors = self_check(result, target_products)
    if errors:
        logger.warning("Deep Analyst self-check: %d issues", len(errors))

    return {"analysis_result": result}


def _build_deep_analyst_task(analysis: dict, deep_data: list[dict], products: list[str]) -> str:
    products_str = ", ".join(products) if products else "(unknown)"
    deep_count = len(deep_data)

    return f"""Deep analysis for: {products_str}

Existing analysis: {analysis.get('comparison_matrix', {}).get('summary', 'N/A')}
New deep-mode data points: {deep_count}

Perform extended analysis:
1. Segment-level comparison (by user type, geography, use case)
2. Financial/market projections (6-month, 12-month, 24-month)
3. Competitive moat assessment (barriers to entry, switching costs)
4. Full visualization suite (radar, heatmap, stacked bar, bubble chart)
5. Update SWOT with deep-mode evidence

Output the same AnalysisResult JSON structure as normal mode.
"""


def _execute_deep_analyst(task: str, state: dict) -> dict | None:
    """Placeholder: execute Deep Analyst via SubagentExecutor."""
    logger.info("Deep Analyst executing (%d chars)", len(task))
    return None
