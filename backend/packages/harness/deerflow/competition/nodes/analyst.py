"""Analyst node — multi-dimensional comparison, SWOT, trends, forecast, and self-check.

Per COMPETITION_PLAN.md §3.5: 7 sub-rules governing analysis behavior.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Mandatory + optional comparison dimensions (§3.5.1)
MANDATORY_DIMENSIONS = ["功能", "定价", "用户"]
OPTIONAL_DIMENSIONS = ["市场", "技术", "团队"]

# Category → dimension mapping
CATEGORY_DIMENSION_MAP = {
    "features": "功能",
    "pricing": "定价",
    "users": "用户",
    "market": "市场",
}


def analyst_node(state: dict) -> dict:
    """Graph node: execute Analyst via SubagentExecutor, validate output structure.

    Three-tier hallucination suppression + degradation (§COMPETITION_PLAN):
    1. Prompt enforces cross-inference with collected-data citations only (no open-ended hallucination)
    2. Self-check verifies citation integrity; coverage gaps → honest "不足" markers
    3. Reviewer G4.5 catches all-NA competitors → replan → Collector re-targeted search

    Returns partial state update with analysis_result + optional coverage_warning.
    """
    target_products = state.get("target_products", [])

    # ── Primary analysis ──
    try:
        task = _build_analyst_task(state)
        raw_output, _tokens = _execute_analyst(task, state)
    except Exception:
        logger.exception("Analyst execute_structured_agent failed, using empty result")
        return {"analysis_result": _empty_analysis_result(state),
                "coverage_warning": None}

    result = _build_analysis_result(raw_output, state)
    if not result.get("comparison_matrix", {}).get("cells"):
        logger.warning("Analyst produced empty comparison_matrix — raw output type=%s, sample=%s",
                       type(raw_output).__name__, str(raw_output)[:200] if raw_output else "None")

    errors = self_check(result, target_products)
    if errors:
        logger.warning("Analyst self-check found %d issues: %s", len(errors), errors)

        # A1 retry: if any target_products are completely missing from matrix, retry once
        missing_products = [e for e in errors if e.startswith("A1:")]
        if missing_products:
            logger.warning("Analyst retrying for missing products: %s", missing_products)
            task_retry = _build_analyst_task(state)
            # Add explicit focus on missing products
            mp_names = [e.split(": ")[1].split(" has ")[0] for e in missing_products]
            task_retry += (
                f"\n\n⚠ RETRY — Missing products from matrix: {', '.join(mp_names)}. "
                "You MUST include cells for these products in ALL dimensions."
            )
            try:
                raw_retry, _retry_tokens = _execute_analyst(task_retry, state)
                result_retry = _build_analysis_result(raw_retry, state)
                # Merge: add any missing cells from retry
                old_cells = result.get("comparison_matrix", {}).get("cells", [])
                old_products = {c.get("product", "") for c in old_cells if isinstance(c, dict)}
                for c in result_retry.get("comparison_matrix", {}).get("cells", []):
                    if isinstance(c, dict) and c.get("product") not in old_products:
                        old_cells.append(c)
                result = result_retry
                result["comparison_matrix"]["cells"] = old_cells
                errors = self_check(result, target_products)
            except Exception:
                logger.exception("Analyst retry failed")

        if errors and result.get("comparison_matrix", {}).get("summary"):
            result["comparison_matrix"]["summary"] += f" (⚠ {len(errors)} self-check warning(s))"

    # ── Coverage assessment (no retry — honest gap flagging) ──
    coverage = _validate_matrix_coverage(result, target_products)

    # ── Self-assessment (§3.17.2) ──
    collected = state.get("collected_data") or []
    self_assessment = _build_analyst_self_assessment(result, target_products, collected)

    # ── Guarantee: every target_product appears in the matrix at least once ──
    matrix = result.get("comparison_matrix", {})
    cells = matrix.get("cells", [])
    dims = matrix.get("dimensions", [])
    if not dims:
        dims = list(MANDATORY_DIMENSIONS)
    products_in_matrix = {c.get("product", "") for c in cells if isinstance(c, dict)}
    for product in target_products:
        if product not in products_in_matrix:
            logger.warning("Forcing placeholder cells for missing product: %s", product)
            for dim in dims:
                cells.append({
                    "product": product,
                    "dimension": dim,
                    "rating": None,
                    "evidence": "数据不足-系统自动补全占位（搜索和LLM分析均未覆盖该竞品该维度）",
                    "evidence_source": "insufficient",
                    "source_data_point_ids": [],
                })
    matrix["cells"] = cells
    result["comparison_matrix"] = matrix

    return {
        "analysis_result": result,
        "coverage_warning": coverage if coverage["na_products"] or coverage.get("low_coverage_products") else None,
        "analyst_self_assessment": self_assessment,
    }


def _build_analyst_task(state: dict) -> str:
    """Build the task description for the Analyst SubagentExecutor call.

    Four-tier evidence strategy (hallucination suppression per competition spec):
    Tier 1 direct_data — rating backed by ≥1 collected data point (citation mandatory)
    Tier 2 cross_inference — rating derived from OTHER collected data, MUST cite cross-ref IDs
    Tier 3 insufficient — genuinely no data available → honest "数据不足" marker
    Tier 4 estimated — ONLY when review_round >= 1 (replan already attempted), use
      pretraining knowledge as last resort, marked "⚠️预训练推测-未经实时验证"
    """
    user_request = state.get("user_request", "")
    target_products = state.get("target_products", [])
    collected = state.get("collected_data") or []
    persona = state.get("persona", "pm")
    review_round = state.get("review_round", 0)

    products_str = ", ".join(target_products) if target_products else "(unknown)"
    data_count = len(collected)

    categories_present = {dp.get("category", "") for dp in collected if isinstance(dp, dict)}
    dimensions = list(MANDATORY_DIMENSIONS)
    for cat, dim in CATEGORY_DIMENSION_MAP.items():
        if cat in categories_present and dim not in dimensions:
            dimensions.append(dim)

    # Tier 4: only available when replan has been attempted (review_round >= 1)
    tier4_section = ""
    if review_round >= 1:
        tier4_section = """
Tier 4 "estimated" (LAST RESORT — use ONLY after Tier 1/2/3 exhausted):
  The system has already attempted re-collection for this analysis. When even
  cross-inference fails, you may use pretraining knowledge as a fallback:
  → rating: best-guess (1-5), evidence: "⚠️预训练推测-未经实时验证: <specific reasoning>"
  → evidence_source: "estimated", source_data_point_ids: []
  → This data is CLEARLY MARKED as unverified.
"""

    return f"""Analyze competitive intelligence data for: {products_str}

User request: {user_request}
Persona: {persona}
Available data points: {data_count}

OUTPUT JSON WITH THESE SECTIONS:

1. comparison_matrix — EVERY product × EVERY dimension. Each cell has:
   - rating (1-5): numeric rating, or null only if Tier 3
   - evidence: specific data backing the rating
   - evidence_source: one of "direct_data" | "cross_inference" | "insufficient"{' | "estimated"' if review_round >= 1 else ''}
   - source_data_point_ids: list of referenced data point IDs from the input

2. swot — per product, ≥2 items: category, statement, evidence, source_data_point_ids (≥1)

3. trends — dimension, direction (up/down/stable/unclear), confidence, evidence

4. forecast (optional) — 6-month and 12-month projections, with disclaimer
5. visualization_paths — recommended charts (radar, heatmap, bar, line, pie, stacked_bar)
6. extra_fields (OPTIONAL) — domain-specific dimensions beyond the standard 4.
   Identify dimensions unique to this industry. Each must have source citations:
   - SaaS: integration_count, api_openness, sla_guarantee
   - Hardware: chip_model, power_consumption, weight
   - Gaming: engine, platforms, monetization_model
   - Format: {"field_name": {"value": ..., "evidence": "...", "source_data_point_ids": [...]}}
   - If no industry-specific dimensions are clear, use empty object {{}}.

━━━ FOUR-TIER EVIDENCE STRATEGY (ANTI-HALLUCINATION) ━━━

Tier 1 "direct_data": Use when ≥1 collected data point directly supports the rating.
  → source_data_point_ids MUST list the actual data point IDs.

Tier 2 "cross_inference": Use when NO direct data exists but you can infer from
  OTHER collected data points about the SAME product in different dimensions,
  or from the SAME dimension of OTHER products. Example:
  "Product A定价数据(来源dp-12): $29/月; Product B被描述为'更亲民的价格'(来源dp-7)
  → 推断 Product B 定价大约在 $15-20/月，评分 4"
  → source_data_point_ids MUST list the cross-referenced IDs (dp-12, dp-7).
  → evidence MUST explain the inference chain.

Tier 3 "insufficient": Use only when NEITHER direct nor cross-inference is
  possible for this product×dimension. This is an honest gap statement:
  → rating: null, evidence: "数据不足-该竞品该维度无可用的直接或间接数据"
  → evidence_source: "insufficient", source_data_point_ids: []
  → This will trigger Reviewer to request targeted re-collection.
{tier4_section}
⚠ NEVER:
- Use open-ended "industry knowledge" or general web knowledge as a source
  (unless Tier 4 is explicitly permitted above)
- Cite a source that doesn't exist in the input data point list
- Use the same evidence text for multiple cells (each must be specific)

Products: {products_str}
Dimensions: {", ".join(dimensions)}

Scoring: Quantitative → quantile mapping | Qualitative → LLM judgment with citation
"""


def _repair_json(text: str) -> str:
    """Repair common LLM JSON errors: trailing commas, unclosed braces/strings.

    Also attempts to salvage truncated JSON by auto-closing unmatched brackets.
    Returns repaired text — may still be invalid JSON if the damage is too severe.
    """
    import re

    # 1. Remove markdown code fences
    text = re.sub(r"^```(?:json|jsonc)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)

    # 2. Remove trailing commas before closing ] or }
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # 3. Repair empty values: "key":, → "key": null,
    text = re.sub(r":\s*,", ": null,", text)

    # 4. Auto-close unclosed strings (single trailing quote on last line)
    lines = text.split("\n")
    if lines:
        last = lines[-1]
        # If last line has odd number of quotes, add closing quote
        if last.count('"') % 2 != 0 and not last.rstrip().endswith('"'):
            lines[-1] = last.rstrip() + '"'
    text = "\n".join(lines)

    # 5. Count and auto-close unmatched brackets
    pairs = {"{": "}", "[": "]"}
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(pairs[ch])
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
    # Append missing closing brackets in reverse order
    closing = "".join(reversed(stack))
    text = text.rstrip() + closing

    return text


def _llm_repair_json(raw_text: str, exc: json.JSONDecodeError) -> dict | str | None:
    """Ask the LLM to fix its own broken JSON — the ultimate fallback.

    Sends the raw output + the parse error back to the model with a one-shot
    repair instruction. Returns the parsed dict/str on success, or the empty
    result on failure.
    """
    from deerflow.competition.executor import execute_agent

    # Keep the payload as small as possible to minimise token cost
    snippet = raw_text[:6000]
    error_msg = f"JSONDecodeError at line {exc.lineno}, col {exc.colno}: {exc.msg}"

    prompt = (
        "You are a JSON repair bot. The following text was meant to be valid JSON "
        "but failed to parse. Fix ALL syntax errors (unclosed brackets, trailing commas, "
        "unescaped characters, truncated strings, etc.) and output ONLY the corrected "
        "JSON. Do not change any data — only fix the syntax.\n\n"
        f"Parse error: {error_msg}\n\n"
        "Broken JSON:\n"
        f"{snippet}"
    )

    logger.warning("Attempting LLM JSON repair (error: %s)", error_msg)
    result, tokens = execute_agent(prompt, "Fix the JSON syntax and return only the corrected JSON.", temperature=0.0, max_tokens=8192, agent_name="Analyst")
    if result:
        text = _repair_json(result)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM JSON repair also failed (%d chars)", len(result))
    return None


def _build_analysis_result(raw: dict | str | None, state: dict) -> dict:
    """Normalize raw Analyst output into a dict suitable for AnalysisResult.model_validate()."""
    if raw is None:
        return _empty_analysis_result(state)

    if isinstance(raw, str):
        import re

        text = _repair_json(raw)
        logger.warning("Analyst JSON parse attempt: first 200 chars=%s, last 100 chars=%s",
                       text[:200], text[-100:])
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            # Regex fallback: try to find any JSON object in the repaired text
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    raw = json.loads(match.group())
                except json.JSONDecodeError:
                    pass  # falls through to LLM repair below
            # LLM self-repair: ask the model to fix its own broken JSON
            if not isinstance(raw, dict):
                raw = _llm_repair_json(raw if isinstance(raw, str) else text, exc)

    if not isinstance(raw, dict):
        return _empty_analysis_result(state)

    # Ensure minimum structure
    raw.setdefault("comparison_matrix", {"products": state.get("target_products", []), "dimensions": [], "cells": [], "summary": ""})
    raw.setdefault("swot", {})
    raw.setdefault("trends", [])
    raw.setdefault("forecast", None)
    raw.setdefault("visualization_paths", [])
    raw.setdefault("extra_fields", {})

    return raw


def _empty_analysis_result(state: dict) -> dict:
    """Return a minimal valid AnalysisResult when Analyst produces nothing."""
    return {
        "comparison_matrix": {
            "products": state.get("target_products", []),
            "dimensions": [],
            "cells": [],
            "summary": "Analysis failed to produce results",
        },
        "swot": {},
        "trends": [],
        "forecast": None,
        "visualization_paths": [],
    }


# ── Self-Check (§3.5.5) ──


def self_check(result: dict, target_products: list[str]) -> list[str]:
    """Run A1-A5 self-check on the analysis result. Returns list of issue descriptions."""
    issues = []

    # A1: Every target_product has ≥1 rating in comparison_matrix
    matrix = result.get("comparison_matrix", {})
    cells = matrix.get("cells", [])
    products_in_matrix = {c.get("product", "") for c in cells if isinstance(c, dict)}
    for product in target_products:
        if product not in products_in_matrix:
            issues.append(f"A1: {product} has no ratings in comparison_matrix")

    # A2: Every SWOT item has source_data_point_ids
    swot = result.get("swot", {})
    for product_name, swot_data in swot.items():
        if not isinstance(swot_data, dict):
            continue
        for item in swot_data.get("items", []):
            if not isinstance(item, dict):
                continue
            source_ids = item.get("source_data_point_ids", [])
            if not source_ids:
                issues.append(f"A2: SWOT item '{item.get('statement', '?')}' for {product_name} has no source_data_point_ids")

    # A3: All referenced data point IDs can be traced — skipped (needs actual data points)
    # A4: Quantitative ratings annotated — checked at Review stage
    # A5: Summary includes data coverage
    # A6: Cross-inference cells MUST cite cross-referenced data point IDs
    for c in cells:
        if not isinstance(c, dict):
            continue
        src = c.get("evidence_source", "")
        ids = c.get("source_data_point_ids", [])
        if src == "cross_inference" and (not ids or len(ids) < 1):
            issues.append(f"A6: cross_inference cell {c.get('product')}/{c.get('dimension')} has no source_data_point_ids — citation required")

    summary = matrix.get("summary", "")
    if summary and "coverage" not in summary.lower() and "覆盖" not in summary:
        issues.append("A5: comparison_matrix.summary should mention data coverage")

    return issues


def _validate_matrix_coverage(result: dict, target_products: list[str]) -> dict:
    """Check N/A + insufficient ratio per product in comparison matrix.

    Returns {"na_products": [...], "low_coverage_products": [...]}.
    na_products = products where EVERY dimension is null/"N/A" (Reviewer-critical).
    low_coverage_products = products where >40% dimensions are insufficient (warning).
    """
    matrix = result.get("comparison_matrix", {})
    cells = matrix.get("cells", [])
    dimensions = matrix.get("dimensions", [])
    if not cells or not target_products:
        return {"na_products": [], "low_coverage_products": []}

    dim_count = len(dimensions) if dimensions else 1

    product_rated: dict[str, int] = {p: 0 for p in target_products}
    product_total: dict[str, int] = {p: 0 for p in target_products}
    for c in cells:
        if not isinstance(c, dict):
            continue
        product = c.get("product", "")
        if product not in product_total:
            continue
        product_total[product] += 1
        rating = c.get("rating")
        src = c.get("evidence_source", "")
        is_absent = rating is None or str(rating).strip().upper() == "N/A" or src == "insufficient"
        if not is_absent:
            product_rated[product] += 1

    na_products: list[str] = []
    low_products: list[str] = []
    for product in target_products:
        total = product_total[product]
        rated = product_rated[product]
        if total == 0:
            # Product completely missing from matrix
            na_products.append(product)
            continue
        ratio = rated / max(total, dim_count)
        if ratio <= 0:
            na_products.append(product)
        elif ratio < 0.6:
            low_products.append(product)

    return {"na_products": na_products, "low_coverage_products": low_products}


# ── Self-Assessment (§3.17.2) ──


def _build_analyst_self_assessment(result: dict, target_products: list[str], collected: list[dict]) -> dict:
    """Build Analyst self-assessment: cross-validation ratio, single-source claims, confidence.

    Evaluates how many claims in the analysis have ≥2 independent sources backing them.
    Returns dict suitable for frontend green/yellow/red dot visualization.
    """
    matrix = result.get("comparison_matrix", {})
    cells = matrix.get("cells", [])
    swot = result.get("swot", {})

    # Count cells with evidence sources
    total_claims = 0
    multi_source_claims = 0
    single_source_claims: list[str] = []
    insufficient_cells = 0

    for c in cells:
        if not isinstance(c, dict):
            continue
        src_ids = c.get("source_data_point_ids", [])
        n_sources = len(src_ids) if isinstance(src_ids, list) else 0

        total_claims += 1
        if c.get("evidence_source") == "insufficient":
            insufficient_cells += 1
        elif n_sources >= 2:
            multi_source_claims += 1
        elif n_sources == 1:
            label = f"{c.get('product', '?')}/{c.get('dimension', '?')}"
            single_source_claims.append(label)
        # n_sources == 0 but not insufficient → cross_inference or estimated

    # SWOT claims
    for _product_name, swot_data in swot.items():
        if not isinstance(swot_data, dict):
            continue
        for item in swot_data.get("items", []):
            if not isinstance(item, dict):
                continue
            src_ids = item.get("source_data_point_ids", [])
            n_sources = len(src_ids) if isinstance(src_ids, list) else 0
            total_claims += 1
            if n_sources >= 2:
                multi_source_claims += 1
            elif n_sources == 1:
                statement = item.get("statement", "")[:60]
                single_source_claims.append(statement)

    # Cross-validation ratio
    cross_validated_ratio = multi_source_claims / total_claims if total_claims > 0 else 0.0

    # Confidence breakdown: high (≥2 sources), medium (1 source), low (0 sources/insufficient)
    confidence_breakdown = {
        "high": multi_source_claims,
        "medium": len(single_source_claims),
        "low": insufficient_cells,
    }

    return {
        "cross_validated_ratio": round(cross_validated_ratio, 2),
        "single_source_claims": single_source_claims[:10],  # cap at 10
        "total_claims": total_claims,
        "insufficient_cells": insufficient_cells,
        "confidence_breakdown": confidence_breakdown,
    }


# ── Visualization Triggers (§3.5.4) ──


def recommend_charts(result: dict) -> list[str]:
    """Determine which charts to generate based on data conditions. Returns chart type names."""
    charts = []

    matrix = result.get("comparison_matrix", {})
    cells = matrix.get("cells", [])
    products = matrix.get("products", [])
    dimensions = matrix.get("dimensions", [])

    has_ratings = all(
        any(c.get("product") == p and c.get("dimension") == d and c.get("rating") is not None for c in cells)
        for p in products for d in dimensions
    ) if products and dimensions else False

    if has_ratings and len(products) >= 2 and len(dimensions) >= 3:
        charts.append("radar")  # Multi-product multi-dim comparison

    if len(products) >= 3 and len(dimensions) >= 5:
        charts.append("heatmap")  # Feature coverage matrix

    trends = result.get("trends", [])
    if any(t.get("dimension", "").lower() in ("市场份额", "market share", "增长", "growth") for t in trends):
        charts.append("line")  # Growth trends

    swot = result.get("swot", {})
    if swot:
        charts.append("bar")  # SWOT summary counts

    return charts


def _execute_analyst(task: str, state: dict) -> tuple[dict | str | None, int]:
    """Execute Analyst via lightweight LLM executor, return (raw dict/str for fallback, token_count)."""
    from deerflow.competition.executor import execute_structured_agent
    from deerflow.competition.prompts import load_prompt_with_vars

    persona = state.get("persona", "pm")
    profile = {"pm": "PM 视角：从产品功能角度看，侧重功能维度比较", "entrepreneur": "创业者视角：从市场机会角度看，侧重定价和商业模式比较"}
    persona_str = profile.get(persona, profile["pm"])

    logger.info("Analyst executing task (%d chars)", len(task))
    prompt = load_prompt_with_vars("analyst", persona_profile=persona_str)
    result, tokens = execute_structured_agent(prompt, task, agent_name="Analyst", max_tokens=8192)
    # Pass raw string through for fallback parsing in _build_analysis_result
    return (result if isinstance(result, (dict, str)) else None, tokens)
