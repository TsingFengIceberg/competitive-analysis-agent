"""Collector node — multi-source data acquisition with dedup, stop conditions, and fallback.

Per COMPETITION_PLAN.md §3.4: 6 sub-rules governing data collection behavior.
Pure helper functions are separately testable; the node function wraps SubagentExecutor.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

from competition.schema import CollectedDataPoint

logger = logging.getLogger(__name__)

# ── Public API: Graph node ──


def collector_node(state: dict) -> dict:
    """Graph node: execute Collector with real web search, then structured LLM extraction.

    Two-phase collection:
      Phase 1: Run real web searches (Tavily/DDG) + deep-fetch top results
      Phase 2: LLM extracts structured CollectedDataPoints from raw search text
    """
    task = _build_collector_task(state)

    # Phase 1: Real web search
    search_context = _run_searches(state)
    if search_context:
        task += "\n\nREAL-TIME SEARCH RESULTS — extract data points from these:\n" + search_context

    raw_output, _tokens = _execute_collector(task, state)

    # Post-processing (§3.4.2-3.4.6)
    data_points = _parse_datapoints(raw_output)

    # Repair: if parsing produced nothing but we have raw output, ask LLM to reformat
    if not data_points and raw_output and isinstance(raw_output, str) and len(raw_output) > 100:
        logger.warning("Collector output parse failed — attempting LLM repair")
        try:
            raw_output, _repair_tokens = _repair_collector_output(raw_output)
            data_points = _parse_datapoints(raw_output)
        except Exception:
            logger.exception("Collector repair failed")
    data_points = deduplicate_datapoints(data_points)
    summary = build_collection_summary(data_points, state.get("target_products", []))
    summary["search_stats"] = _get_search_info()
    summary["complexity"] = state.get("complexity", "standard")

    # ── Self-assessment (§3.17.2) ──
    target_products = state.get("target_products", [])
    self_assessment = _build_collector_self_assessment(data_points, target_products)

    # ── Questionnaire generation `[§14, feature flag: enable_questionnaire=False]` ──
    questionnaire = None
    if state.get("enable_questionnaire"):
        try:
            questionnaire = _generate_questionnaire(state, data_points)
            if questionnaire:
                logger.info("Collector generated questionnaire: %s", questionnaire.get("title"))
        except Exception:
            logger.exception("Questionnaire generation failed — continuing without it")

    # ── Bounded Rework merge: replace old data for gapped product+category, keep rest ──
    existing_data = state.get("collected_data") or []
    gaps = state.get("knowledge_gaps") or []
    if gaps and existing_data:
        # Determine which (product, category) pairs are being re-collected
        gapped_pairs: set[tuple[str, str]] = set()
        for g in gaps:
            task_text = g.get("target_collect_task", "")
            # Extract product and category hints from the gap task
            for prod in state.get("target_products", []):
                if prod.lower() in task_text.lower():
                    for cat in ["features", "pricing", "users", "market"]:
                        if cat in task_text.lower() or g.get("type") in ("missing_data", "source_conflict"):
                            gapped_pairs.add((prod.lower(), cat))
        # Keep existing data except for gapped pairs
        kept = [
            dp for dp in existing_data
            if (dp.get("product", "").lower(), dp.get("category", "")) not in gapped_pairs
        ]
        merged = kept + [dp.model_dump() for dp in data_points]
        logger.info(
            "Bounded rework: kept %d existing + %d new data points (gapped pairs: %s)",
            len(kept), len(data_points), gapped_pairs,
        )
        data_points_for_state = merged
    else:
        data_points_for_state = [dp.model_dump() for dp in data_points]

    return {
        "collected_data": data_points_for_state,
        "collection_summary": summary,
        "collector_self_assessment": self_assessment,
        "questionnaire": questionnaire,
    }


# ── Task construction ──


def _build_collector_task(state: dict) -> str:
    """Construct the task description passed to SubagentExecutor.

    Incorporates §3.4.4 search query templates and §3.4.7 data source routing.
    When knowledge_gaps are present (rework round), restricts to re-collect only
    the gapped products+dimensions (Bounded Rework, §Torrent2002-inspired).
    """
    user_request = state.get("user_request", "")
    target_products = state.get("target_products", [])
    gaps = state.get("knowledge_gaps") or []

    if gaps:
        return _build_targeted_rework_task(state, gaps)

    products_str = ", ".join(target_products) if target_products else "(from user request)"

    brief = state.get("analysis_brief") or {}
    selected = [item.get("id") for item in brief.get("dimensions", []) if item.get("id")]
    categories = selected or ["features", "pricing", "users", "market"]
    market_scope = brief.get("market_scope", "Global / unspecified")
    time_range = brief.get("time_range", {}).get("label", "最近12个月")
    evidence_policy = brief.get("evidence_policy", "balanced")
    output_focus = ", ".join(brief.get("output_focus") or []) or "关键差异与可执行建议"
    category_details = (
        "  - features: product capabilities, differentiators, limitations\n"
        "  - pricing: tiers, prices, billing cycles, free tiers\n"
        "  - users: target segments, satisfaction scores, reviews\n"
        "  - market: market share, growth trends, funding, valuation"
        if not brief else
        chr(10).join(f"  - {category}: collect evidence for this dimension" for category in categories)
    )
    task = f"""Search for competitive intelligence data on: {products_str}

User request: {user_request}

For each product, collect data points covering these categories:
Selected categories (do not add unselected categories): {', '.join(categories)}
{category_details}
Scope constraints: market={market_scope}; time={time_range}; evidence={evidence_policy}; output focus={output_focus}

Search strategy (§3.4.7):
  - Chinese queries → use volcengine_web_search first
  - English queries → use tavily_search / brave_search first
  - Prefer authoritative sources for selected dimensions
  - Use review sources for user evidence and GitHub/API sources for technology evidence

Output format: a JSON array of objects, each with:
  id, product, category, label, value, confidence (0.0-1.0),
  source_url, source_type, collected_at (ISO 8601)
"""

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


def _build_targeted_rework_task(state: dict, gaps: list[dict]) -> str:
    """Build a bounded-rework task: only re-collect what the gaps specify."""
    products = state.get("target_products", [])
    products_str = ", ".join(products) if products else "(unknown)"
    brief = state.get("analysis_brief") or {}
    scope_hint = ""
    if brief:
        scope_hint = (
            f"\nBrief scope remains binding: market={brief.get('market_scope', 'Global / unspecified')}; "
            f"time={(brief.get('time_range') or {}).get('label', '最近12个月')}; "
            f"evidence={brief.get('evidence_policy', 'balanced')}; "
            f"dimensions={[item.get('id') for item in brief.get('dimensions', [])]}\n"
        )

    gap_lines = []
    for g in gaps[:10]:
        task_text = g.get("target_collect_task", g.get("description", ""))
        severity = g.get("severity", "major")
        gap_lines.append(f"  [{severity}] {task_text}")

    return f"""TARGETED RE-COLLECTION — only collect data for the specific gaps below.
Original products: {products_str}
{scope_hint}

Gap list (do NOT re-collect everything — only fill these gaps):
{chr(10).join(gap_lines)}

For each gap, find 2-3 new data points from DIFFERENT sources than before.
Output format: a JSON array of objects, each with:
  id, product, category, label, value, confidence (0.0-1.0),
  source_url, source_type, collected_at (ISO 8601)
"""


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


# ── Self-Assessment (§3.17.2) ──

COLLECTOR_DIMENSIONS = ["features", "pricing", "users", "market"]


def _build_collector_self_assessment(
    points: list[CollectedDataPoint],
    target_products: list[str],
) -> dict:
    """Build Collector self-assessment: coverage per product×dimension, gaps, confidence.

    Returns dict suitable for frontend visualization (green/yellow/red dot).
    """
    if not target_products:
        return {
            "coverage_score": 0.0,
            "gaps": [],
            "per_product": {},
            "total_data_points": len(points),
            "avg_confidence": 0.0,
        }

    # Count data points per product × dimension
    covered: dict[str, set[str]] = {p: set() for p in target_products}
    confidences: dict[str, list[float]] = {p: [] for p in target_products}

    for dp in points:
        if dp.product in covered:
            covered[dp.product].add(dp.category)
            confidences[dp.product].append(dp.confidence)

    # Per-product coverage score
    per_product: dict[str, float] = {}
    gaps: list[str] = []
    total_dimensions = len(COLLECTOR_DIMENSIONS)

    for product in target_products:
        dims_covered = len(covered.get(product, set()))
        per_product[product] = dims_covered / total_dimensions if total_dimensions > 0 else 0.0
        missing = [d for d in COLLECTOR_DIMENSIONS if d not in covered.get(product, set())]
        for dim in missing:
            gaps.append(f"{product}-{dim}")

    # Overall coverage score
    if target_products:
        coverage_score = sum(per_product.values()) / len(target_products)
    else:
        coverage_score = 0.0

    # Average confidence
    all_confs = [c for clist in confidences.values() for c in clist]
    avg_conf = sum(all_confs) / len(all_confs) if all_confs else 0.0

    return {
        "coverage_score": round(coverage_score, 2),
        "gaps": gaps,
        "per_product": per_product,
        "total_data_points": len(points),
        "avg_confidence": round(avg_conf, 2),
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
            else:
                # Validate: if LLM provided a date, check it's reasonable
                # (not a fabricated identical date for all items)
                val = str(item["collected_at"])
                try:
                    dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    now = datetime.now(UTC)
                    # Future dates or unreasonably old → override
                    if dt > now or dt.year < 2020:
                        item["collected_at"] = datetime.now(UTC).isoformat()
                    # Otherwise keep the source publication date
                except (ValueError, TypeError):
                    item["collected_at"] = datetime.now(UTC).isoformat()
            # Normalize source_type from real search results to valid schema values
            if "source_type" in item:
                item["source_type"] = _normalize_source_type(item["source_type"])
            points.append(CollectedDataPoint.model_validate(item))
        except Exception as e:
            logger.warning("Failed to parse data point: %s — %s", item.get("id", "?"), e)
    return points


_SOURCE_TYPE_MAP: dict[str, str] = {
    "comparison_article": "comparison",
    "industry_statistics": "stats",
    "industry_report": "stats",
    "pricing_guide": "pricing",
    "pricing_page": "pricing",
    "documentation": "docs",
    "technical_docs": "docs",
    "api_docs": "docs",
    "blog_post": "blog",
    "tutorial": "blog",
    "user_review": "review",
    "customer_review": "review",
    "press_release": "news",
    "market_report": "stats",
    "market_research": "stats",
    "social_media": "social",
    "forum": "social",
    "community": "social",
}


def _normalize_source_type(raw_type: str) -> str:
    """Map free-form source_type from LLM to a valid schema value."""
    normalized = raw_type.strip().lower().replace(" ", "_").replace("-", "_")
    if normalized in {"official", "review", "news", "interview", "social", "comparison", "pricing", "stats", "docs", "blog"}:
        return normalized
    return _SOURCE_TYPE_MAP.get(normalized, "news")  # fallback to "news"


def _run_searches(state: dict) -> str:
    """Phase 1: Run real web searches for each product × category, return formatted context.

    Uses adaptive context budgeting: model context window → available chars → tiered
    result count & snippet length. Task complexity (§3.17.1) adjusts search depth.
    """
    from competition.tools.search import (
        build_search_queries,
        calculate_budget,
        format_search_context,
        multi_search,
    )

    target_products: list[str] = state.get("target_products", [])
    if not target_products:
        return ""

    # Also include gap-related products for replan rounds (Bounded Rework)
    gaps = state.get("knowledge_gaps") or []
    is_rework = bool(gaps)
    gap_products: list[str] = []
    if gaps:
        import re as _re
        for g in gaps:
            task_text = g.get("target_collect_task", "")
            found = _re.findall(r"Search for.*?: ([A-Za-z][A-Za-z0-9 ]+)", task_text)
            gap_products.extend(found)
    if gap_products:
        target_products = list(set(gap_products))
    elif is_rework and not gap_products:
        # Rework but can't extract products — keep original targets but limit search depth
        pass

    # ── Task complexity adjustment (§3.17.1, v4: Orchestrator-driven) ──
    # Priority: Orchestrator's orchestration_result → state["complexity"] → "standard"
    orch = state.get("orchestration_result") or {}
    complexity = orch.get("complexity") or state.get("complexity", "standard")
    dimension_weights = orch.get("dimension_weights") or []
    complexity_config = _get_complexity_config(complexity)

    # Calculate adaptive context budget
    budget = calculate_budget()

    # Apply complexity overrides to budget
    budget.fetch_top_n = complexity_config["fetch_top_n"]
    budget.max_results = complexity_config["max_results"]

    # v4: If dimension_weights are available, adjust categories searched
    # Higher weight → include that dimension in the search explicitly
    brief = state.get("analysis_brief") or {}
    selected_categories = [item.get("id") for item in brief.get("dimensions", []) if item.get("id")]
    queries = build_search_queries(target_products, categories=selected_categories or None, complexity=complexity)

    # Industry keyword injection (Layer 2 of §3.20)
    from competition.industry import get_industry_profile
    industry = state.get("industry", "general")
    profile = get_industry_profile(industry)
    industry_kw = profile.get("search_keywords", [])
    if industry_kw and industry != "general":
        # Append industry keywords to the first 2 queries per product for coverage
        extra = []
        for product in target_products:
            for kw in industry_kw[:3]:
                extra.append(f"{product} {kw}")
        queries = queries + extra[:6]
        logger.info("Industry '%s': added %d keyword-augmented queries", industry, len(extra[:6]))
    if dimension_weights:
        weighted_dims = {dw["dimension"]: dw["weight"] for dw in dimension_weights}
        logger.info("Orchestrator dimension weights: %s", weighted_dims)
    logger.warning("═══ 🦆 DDG SEARCH: %d queries for %d products (complexity=%s, budget=%s, %dK tokens) ═══",
                   len(queries), len(target_products), complexity, budget.tier, budget.tokens // 1000)
    for i, q in enumerate(queries):
        logger.warning("  [%d/%d] %s", i + 1, len(queries), q)

    try:
        results = multi_search(queries, max_results=complexity_config["max_results_per_query"], fetch_top=budget.fetch_top_n)
    except Exception:
        logger.exception("Collector search failed")
        return ""

    if not results:
        logger.warning("DDG search returned ZERO results")
        return ""

    # Content persistence
    _persist_search_results(results)

    # Log what we found
    with_content = sum(1 for r in results if r.raw_content)
    logger.warning("DDG DONE: %d unique URLs (%d fetched)", len(results), with_content)

    # Per-product fair budget allocation: when analyzing multiple products,
    # global context trimming by content length can crowd out all but the
    # first product. Allocate budget fairly per product.
    if len(target_products) > 1:
        return _format_per_product_context(results, target_products, budget=budget)

    return format_search_context(results, budget=budget)


def _format_per_product_context(results: list, target_products: list[str], budget) -> str:
    """Format search context with fair per-product budget allocation.

    Without this, global top-N by content length lets the first product's
    long pages crowd out all other products, causing None-filled matrix cells.
    """
    from competition.tools.search import format_search_context

    # Score each result for each product: check if title/URL/snippet mentions it
    def _product_score(result, product: str) -> float:
        text = f"{result.title} {result.snippet or ''} {result.url}".lower()
        prod_lower = product.lower()
        if prod_lower in text:
            return 1.0
        words = prod_lower.split()
        if len(words) > 1:
            matches = sum(1 for w in words if w in text)
            return matches / len(words) * 0.5
        return 0.0

    # Assign each result to the product with highest score
    assigned: dict[str, list] = {p: [] for p in target_products}
    unassigned: list = []
    for r in results:
        best_product = None
        best_score = 0.0
        for p in target_products:
            s = _product_score(r, p)
            if s > best_score:
                best_score = s
                best_product = p
        if best_score > 0:
            assigned[best_product].append(r)
        else:
            unassigned.append(r)

    # Distribute unassigned results round-robin
    for i, r in enumerate(unassigned):
        assigned[target_products[i % len(target_products)]].append(r)

    # Format each product's results independently — each gets its own top-N
    parts: list[str] = []
    for product in target_products:
        prod_results = assigned.get(product, [])
        if not prod_results:
            parts.append(f"## {product}\n(No search results found for this product)\n")
            continue
        ctx = format_search_context(prod_results, budget=budget)
        if ctx.strip():
            parts.append(f"## Search results for: {product}\n{ctx}")

    return "\n\n".join(parts)


def _get_search_info() -> dict:
    """Build search visibility info for the UI."""
    from competition.tools.search import get_search_stats
    stats = get_search_stats()
    return {
        "backend": stats.get("backend", "none"),
        "total_queries": stats.get("total_queries", 0),
        "total_results": stats.get("total_results", 0),
        "queries": stats.get("queries", []),
    }


def _persist_search_results(results) -> None:
    """Save full fetched page text to content_store for downstream evidence verification."""
    import hashlib

    from competition.db import save_content

    count = 0
    for r in results:
        raw = getattr(r, "raw_content", None) or ""
        if not raw or len(raw) < 100:
            continue
        url = getattr(r, "url", "") or ""
        content_ref = hashlib.sha256(url.encode()).hexdigest()[:16]
        try:
            save_content(content_ref, url, raw)
            count += 1
        except Exception:
            pass
    if count:
        logger.info("Content store: persisted %d full-text pages", count)


# ── Task complexity (§3.17.1) ──

COMPLEXITY_CONFIG = {
    "quick": {
        "fetch_top_n": 1,
        "max_results": 12,
        "max_results_per_query": 3,
        "label": "快速模式",
        "description": "1-2 竞品简单对比，搜索预算 ~15K tokens",
    },
    "standard": {
        "fetch_top_n": 2,
        "max_results": 20,
        "max_results_per_query": 5,
        "label": "标准模式",
        "description": "2-4 竞品多维对比，搜索预算 ~30K tokens",
    },
    "deep": {
        "fetch_top_n": 3,
        "max_results": 30,
        "max_results_per_query": 8,
        "label": "深度模式",
        "description": "5+ 竞品战略分析或含预测/全景关键词，搜索预算 ~60K tokens",
    },
}


def _get_complexity_config(complexity: str) -> dict:
    """Get search configuration for the given complexity level."""
    return COMPLEXITY_CONFIG.get(complexity, COMPLEXITY_CONFIG["standard"])


def _repair_collector_output(raw_text: str) -> str | None:
    """Send broken output back to LLM for reformatting into valid JSON."""
    from competition.executor import execute_agent

    snippet = raw_text[:8000]
    repair_prompt = (
        "The following text should be a JSON array of competitive data points "
        "but failed to parse. Reformat it into a valid JSON array. "
        "Each object must have: id, product, category, label, value, confidence, "
        "source_url, source_type, collected_at. Output ONLY the JSON array."
    )
    result, _tokens = execute_agent(
        repair_prompt, snippet, temperature=0.0, max_tokens=4096, agent_name="Collector",
    )
    return result


def _execute_collector(task: str, state: dict) -> tuple[str | None, int]:
    """Execute Collector via lightweight LLM executor (production: SubagentExecutor). Returns (content, tokens)."""
    from competition.executor import execute_agent
    from competition.prompts import load_prompt

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


# ── Questionnaire Generation `[§14, feature flag: enable_questionnaire=False]` ──


def _generate_questionnaire(state: dict, data_points: list) -> dict | None:
    """Generate a structured questionnaire based on query + collected search data.

    Gated behind state["enable_questionnaire"] (default False). Reserves the
    Collector→HITL→Collector feedback loop for subjective data that web search
    cannot capture: user preferences, satisfaction, pain points, feature priorities.

    The questionnaire is rendered in the frontend, distributed to users, and
    responses flow back via POST /api/competition/{thread_id}/survey-response.
    LLM then structures responses as CollectedDataPoint[] for Analyst consumption.
    """
    from competition.executor import execute_agent

    user_request = state.get("user_request", "")
    products = state.get("target_products", [])
    gaps = state.get("knowledge_gaps") or []

    # Only generate questionnaire when web search can't cover subjective data
    subjective_signals = ["偏好", "满意度", "痛点", "体验", "评价", "感受", "survey", "questionnaire", "问卷", "调研"]
    has_subjective_intent = any(s in user_request for s in subjective_signals)
    has_data_gaps = len(data_points) < 10 or gaps

    if not has_subjective_intent and not has_data_gaps:
        return None

    system_prompt = (
        "You are a survey designer for competitive analysis. "
        "Generate a structured questionnaire to collect subjective user data "
        "that web search cannot provide: user preferences, satisfaction scores, "
        "pain points, feature priorities. Output raw JSON only."
    )
    task = (
        f"User query: {user_request}\n"
        f"Products being analyzed: {', '.join(products) if products else '(unknown)'}\n"
        f"Data points already collected via web: {len(data_points)}\n"
        f"Knowledge gaps: {json.dumps(gaps[:3]) if gaps else '(none)'}\n\n"
        "Generate a 5-8 question questionnaire mixing:\n"
        "- single_choice: for categorical preferences ('most important feature')\n"
        "- rating: for 1-5 scores ('satisfaction with X')\n"
        "- open: for qualitative feedback ('what is your biggest pain point?')\n\n"
        'Output format: {"title": "...", "description": "...", "target_audience": "...", '
        '"questions": [{"id": "q1", "type": "rating", "title": "...", "options": null, "required": true}, ...], '
        '"estimated_time_minutes": 5}'
    )

    try:
        raw, tokens = execute_agent(
            system_prompt, task,
            temperature=0.3, max_tokens=600, agent_name="QuestionnaireGenerator",
        )
        if raw:
            from competition.nodes.orchestrator import _parse_orchestrator_output
            parsed = _parse_orchestrator_output(raw)
            if parsed and parsed.get("questions"):
                parsed["_generated_at"] = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()
                parsed["_token_count"] = tokens
                logger.info("Generated questionnaire: '%s' (%d questions, %d tokens)",
                           parsed.get("title"), len(parsed.get("questions", [])), tokens)
                return parsed
    except Exception:
        logger.exception("Questionnaire generation failed")

    return None
