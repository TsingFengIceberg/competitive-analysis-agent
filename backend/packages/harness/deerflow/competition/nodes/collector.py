"""Collector node — multi-source data acquisition with dedup, stop conditions, and fallback.

Per COMPETITION_PLAN.md §3.4: 6 sub-rules governing data collection behavior.
Pure helper functions are separately testable; the node function wraps SubagentExecutor.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

from deerflow.competition.schema import CollectedDataPoint

logger = logging.getLogger(__name__)

# ── Public API: Graph node ──


def collector_node(state: dict) -> dict:
    """Graph node: execute Collector via SubagentExecutor, apply post-processing rules.

    Returns partial state update. LangGraph auto-merges collected_data via op_add reducer.
    """
    task = _build_collector_task(state)
    # In production, this calls SubagentExecutor(config, tools, sandbox).execute(task).
    # For now, placeholder — real executor wired in after SubagentExecutor integration.
    raw_output, _tokens = _execute_collector(task, state)

    # Post-processing (§3.4.2-3.4.6)
    data_points = _parse_datapoints(raw_output)
    data_points = deduplicate_datapoints(data_points)
    summary = build_collection_summary(data_points, state.get("target_products", []))

    return {
        "collected_data": [dp.model_dump() for dp in data_points],
        "collection_summary": summary,
    }


# ── Task construction ──


def _build_collector_task(state: dict) -> str:
    """Construct the task description passed to SubagentExecutor.

    Incorporates §3.4.4 search query templates and §3.4.7 data source routing.
    """
    user_request = state.get("user_request", "")
    target_products = state.get("target_products", [])
    gaps = state.get("knowledge_gaps") or []

    products_str = ", ".join(target_products) if target_products else "(from user request)"

    task = f"""Search for competitive intelligence data on: {products_str}

User request: {user_request}

For each product, collect data points covering these categories:
  - features: product capabilities, differentiators, limitations
  - pricing: tiers, prices, billing cycles, free tiers
  - users: target segments, satisfaction scores, reviews
  - market: market share, growth trends, funding, valuation

Search strategy (§3.4.7):
  - Chinese queries → use volcengine_web_search first
  - English queries → use tavily_search / brave_search first
  - Official info (pricing, features) → firecrawl / jina_reader first
  - User reviews → G2 / ProductHunt / Reddit first
  - Tech depth → GitHub API first

Output format: a JSON array of objects, each with:
  id, product, category, label, value, confidence (0.0-1.0),
  source_url, source_type, collected_at (ISO 8601)
"""

    if gaps:
        task += "\n\nKnowledge gaps from previous round — prioritize these:\n"
        for g in gaps:
            task += f"  - [{g.get('type', '?')}] {g.get('target_collect_task', g.get('description', ''))}\n"

    context = state.get("context_report")
    if context and isinstance(context, dict):
        sections = context.get("sections", [])
        if sections:
            task += "\n\nPrevious analysis report findings (use as reference, verify and update):\n"
            for s in sections:
                content = s.get("content", "")
                if content:
                    task += f"\n### {s.get('title', '')}\n{content[:800]}\n"
            task += "\nFocus on finding NEW or UPDATED data beyond the above, especially recent changes.\n"

    return task


# ── Post-processing: Deduplication (§3.4.2) ──


def deduplicate_datapoints(points: list[CollectedDataPoint]) -> list[CollectedDataPoint]:
    """Merge duplicate data points (same product + category + semantically equivalent label).

    Rules:
    - Same value (diff < 5%) → merge, keep earliest, append source_url, take max confidence
    - Different value (diff >= 5%) → keep both, label annotated with source indicator
    - Same source_url → discard duplicate (collector bug)
    """
    if not points:
        return []

    seen: dict[tuple[str, str, str], CollectedDataPoint] = {}
    result: list[CollectedDataPoint] = []

    for dp in points:
        # Normalize label for comparison
        norm_label = _normalize_label(dp.label)
        key = (dp.product.lower(), dp.category, norm_label)

        if key in seen:
            existing = seen[key]
            # Same source_url → duplicate bug, skip
            if existing.source_url == dp.source_url:
                continue
            # Compare values
            if _values_similar(dp.value, existing.value):
                # Merge: append source, take max confidence
                merged_source = f"{existing.source_url}, {dp.source_url}"
                merged_conf = max(existing.confidence, dp.confidence)
                existing.source_url = merged_source
                existing.confidence = merged_conf
                continue
            else:
                # Divergent values → keep both with source annotation
                dp.label = f"{dp.label} [{_source_short(dp.source_url)}]"
                existing.label = f"{existing.label} [{_source_short(existing.source_url)}]"
                result.append(dp)
                continue

        seen[key] = dp
        result.append(dp)

    return result


def _normalize_label(label: str) -> str:
    """Normalize label for semantic equivalence comparison: lowercase, strip units/symbols."""
    # Remove common price/percentage suffixes
    label = label.lower().strip()
    label = re.sub(r"\$\d+(\.\d+)?", "$X", label)  # normalize prices
    label = re.sub(r"\d+%", "X%", label)  # normalize percentages
    label = re.sub(r"\s+", " ", label)
    return label


def _values_similar(v1: str | float, v2: str | float) -> bool:
    """Check if two values are within 5% tolerance (§3.4.2)."""
    try:
        f1 = float(v1)
        f2 = float(v2)
        if f2 == 0:
            return f1 == 0
        return abs(f1 - f2) / abs(f2) < 0.05
    except (ValueError, TypeError):
        return str(v1).strip().lower() == str(v2).strip().lower()


def _source_short(url: str) -> str:
    """Extract short domain identifier from URL for source annotation."""
    match = re.search(r"(?:https?://)?(?:www\.)?([^/]+)", url)
    return match.group(1) if match else url[:30]


# ── Post-processing: Collection Summary (§3.4.6) ──


def build_collection_summary(points: list[CollectedDataPoint], target_products: list[str]) -> dict:
    """Build the per-round collection summary for the observability panel."""
    if not points:
        return {
            "total_data_points": 0,
            "products_covered": {},
            "categories_covered": {},
            "source_types": {},
            "languages": {"zh": 0, "en": 0},
            "stopped_by": "no_results",
            "search_rounds": 0,
            "avg_confidence": 0.0,
            "low_confidence_points": 0,
        }

    products = {p: 0 for p in target_products}
    categories: dict[str, int] = {}
    sources: dict[str, int] = {}
    langs = {"zh": 0, "en": 0}

    for dp in points:
        if dp.product in products:
            products[dp.product] += 1
        categories[dp.category] = categories.get(dp.category, 0) + 1
        sources[dp.source_type] = sources.get(dp.source_type, 0) + 1
        # Crude language detection
        if any("一" <= c <= "鿿" for c in (dp.label + str(dp.value))):
            langs["zh"] += 1
        else:
            langs["en"] += 1

    confidences = [dp.confidence for dp in points]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    low_conf = len([c for c in confidences if c < 0.5])

    # Determine stop reason
    if len(points) >= 20 and len(sources) >= 3 and all(v >= 2 for v in products.values()):
        stopped_by = "soft_stop"
    else:
        stopped_by = "normal"

    return {
        "total_data_points": len(points),
        "products_covered": products,
        "categories_covered": categories,
        "source_types": sources,
        "languages": langs,
        "stopped_by": stopped_by,
        "search_rounds": 0,  # set by caller from SubagentExecutor metadata
        "avg_confidence": round(avg_conf, 2),
        "low_confidence_points": low_conf,
    }


# ── Internal helpers ──


def _parse_datapoints(raw: str | list | None) -> list[CollectedDataPoint]:
    """Parse raw Collector output into CollectedDataPoint list.

    Handles: markdown code fences, truncated JSON, plain text with embedded JSON.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        text = raw.strip()
        # Strip markdown code fences (```json or ```)
        text = re.sub(r"^```(?:json|jsonc)?\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
        try:
            items = json.loads(text)
        except json.JSONDecodeError:
            # Try to find a JSON array in the text
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                try:
                    items = json.loads(match.group())
                except json.JSONDecodeError:
                    # Try to salvage: extract individual JSON objects from truncated output
                    items = _salvage_json_objects(text)
                    if not items:
                        logger.warning("Collector output is not valid JSON (%d chars)", len(raw))
                        return []
            else:
                logger.warning("Collector output is not valid JSON (%d chars)", len(raw))
                return []
    else:
        return []

    points = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            if "collected_at" not in item:
                item["collected_at"] = datetime.now(UTC).isoformat()
            points.append(CollectedDataPoint.model_validate(item))
        except Exception as e:
            logger.warning("Failed to parse data point: %s — %s", item.get("id", "?"), e)
    return points


def _execute_collector(task: str, state: dict) -> tuple[str | None, int]:
    """Execute Collector via lightweight LLM executor (production: SubagentExecutor). Returns (content, tokens)."""
    from deerflow.competition.executor import execute_agent
    from deerflow.competition.prompts import load_prompt

    logger.info("Collector executing task (%d chars)", len(task))
    prompt = load_prompt("collector").replace("{task_description}", task)
    return execute_agent(prompt, task, max_tokens=8192, agent_name="Collector")


def _salvage_json_objects(text: str) -> list[dict]:
    """Attempt to extract individual JSON objects from truncated/partial output."""
    # Find all {...} objects in the text
    objects = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(text[start : i + 1])
                    objects.append(obj)
                except json.JSONDecodeError:
                    pass
                start = -1
    return objects
