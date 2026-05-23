"""Deep Collector node (P1) — incremental data acquisition based on knowledge gaps.

Per COMPETITION_PLAN.md §3.1: Same structure as Collector, but targets knowledge_gaps
from normal-mode Reviewer, with additional data sources (video/douyin/feishu).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def deep_collector_node(state: dict) -> dict:
    """Graph node: incremental collection targeting knowledge gaps.

    Uses normal-mode analysis_result and knowledge_gaps as input.
    Adds deep-mode sources: YouTube transcript, Bilibili, Douyin, Feishu docs.
    """
    user_request = state.get("user_request", "")
    target_products = state.get("target_products", [])
    gaps = state.get("knowledge_gaps") or []
    analysis = state.get("analysis_result") or {}

    # Extract unresolved dimensions from analysis
    matrix = analysis.get("comparison_matrix", {})
    missing_dims = _find_missing_dimensions(matrix, target_products)

    task = _build_deep_task(user_request, target_products, gaps, missing_dims)
    raw_output = _execute_deep_collector(task, state)

    # Reuse normal-mode Collector's post-processing
    from deerflow.competition.nodes.collector import _parse_datapoints, build_collection_summary, deduplicate_datapoints
    points = _parse_datapoints(raw_output)
    points = deduplicate_datapoints(points)
    summary = build_collection_summary(points, target_products)
    summary["mode"] = "deep"

    return {
        "deep_collected_data": [dp.model_dump() for dp in points],
        "collection_summary": summary,
    }


def _find_missing_dimensions(matrix: dict, products: list[str]) -> list[str]:
    """Find dimensions with missing data across products."""
    cells = matrix.get("cells", [])
    dimensions = set(matrix.get("dimensions", []))
    missing = []
    for dim in dimensions:
        if not any(c.get("product") in products and c.get("dimension") == dim for c in cells):
            missing.append(dim)
    return missing


def _build_deep_task(user_request: str, products: list[str], gaps: list[dict], missing_dims: list[str]) -> str:
    """Build deep Collector task description with enhanced source instructions."""
    products_str = ", ".join(products) if products else "(unknown)"

    task = f"""Deep incremental collection for: {products_str}

Original request: {user_request}

This is DEEP MODE — use additional sources beyond normal web search:
  1. YouTube transcripts (via youtube-transcript-api)
  2. Bilibili video info + subtitles (中文科技评测)
  3. Feishu documents (if available via lark-cli)
  4. Douyin video search (via 抖音开放平台 API)

Prioritize these knowledge gaps from the first analysis round:
"""
    for g in gaps:
        task += f"  - [{g.get('type', '?')}] {g.get('target_collect_task', '')}\n"

    if missing_dims:
        task += f"\nMissing dimensions to fill: {', '.join(missing_dims)}\n"

    return task


def _execute_deep_collector(task: str, state: dict) -> list | None:
    """Placeholder: execute Deep Collector via SubagentExecutor."""
    logger.info("Deep Collector executing (%d chars)", len(task))
    return None
