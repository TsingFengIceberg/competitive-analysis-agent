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

    Returns partial state update with analysis_result.
    """
    task = _build_analyst_task(state)
    raw_output, _tokens = _execute_analyst(task, state)
    result = _build_analysis_result(raw_output, state)
    if not result.get("comparison_matrix", {}).get("cells"):
        logger.warning("Analyst produced empty comparison_matrix — raw output type=%s, sample=%s",
                       type(raw_output).__name__, str(raw_output)[:200] if raw_output else "None")
    errors = self_check(result, state.get("target_products", []))

    if errors:
        logger.warning("Analyst self-check found %d issues: %s", len(errors), errors)
        # §3.5.5: annotate result with self-check warnings
        if result.get("comparison_matrix", {}).get("summary"):
            result["comparison_matrix"]["summary"] += f" (⚠ {len(errors)} self-check warning(s))"

    return {"analysis_result": result}


def _build_analyst_task(state: dict) -> str:
    """Build the task description for the Analyst SubagentExecutor call."""
    user_request = state.get("user_request", "")
    target_products = state.get("target_products", [])
    collected = state.get("collected_data") or []
    persona = state.get("persona", "pm")

    products_str = ", ".join(target_products) if target_products else "(unknown)"
    data_count = len(collected)

    # Determine available dimensions from collected data
    categories_present = {dp.get("category", "") for dp in collected if isinstance(dp, dict)}
    dimensions = list(MANDATORY_DIMENSIONS)
    for cat, dim in CATEGORY_DIMENSION_MAP.items():
        if cat in categories_present and dim not in dimensions:
            dimensions.append(dim)

    return f"""Analyze competitive intelligence data for: {products_str}

User request: {user_request}
Persona: {persona}
Available data points: {data_count}

Required analysis dimensions: {", ".join(dimensions)}

Output a JSON object with these sections:

1. comparison_matrix — for each product × dimension, provide:
   - rating (1-5): use quantile mapping for quantitative data, LLM judgment for qualitative
   - evidence: specific data supporting the rating
   - source_data_point_ids: list of referenced data point IDs

2. swot — for each product, list SWOT items with:
   - category: "strength" / "weakness" / "opportunity" / "threat"
   - statement, evidence, source_data_point_ids (≥1 required per §3.5.3)

3. trends — list trend findings with dimension, direction (up/down/stable/unclear), confidence, evidence

4. forecast (optional, only if trend data sufficient):
   - Include 6-month and 12-month projections per product × dimension
   - disclaimer: "以下预测基于公开数据趋势外推，不构成投资建议"

5. visualization_paths — list of chart files to generate (radar, heatmap, bar, line, pie, stacked_bar)

Scoring rules (§3.5.2):
- Quantitative data → quantile_to_rating(value, all_values, lower_is_better)
- Qualitative data → LLM judgment with ≥1 source_data_point_id
- No data for dimension → rating = null, label "无数据"

Self-check before output (§3.5.5):
- Every product has ≥1 rating in comparison_matrix (A1)
- Every SWOT item has source_data_point_ids (A2)
- All referenced data point IDs exist in the input
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

    summary = matrix.get("summary", "")
    if summary and "coverage" not in summary.lower() and "覆盖" not in summary:
        issues.append("A5: comparison_matrix.summary should mention data coverage")

    return issues


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
