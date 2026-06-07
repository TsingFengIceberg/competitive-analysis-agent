"""Orchestrator node — Query-Driven Dynamic Pipeline entry point `[v4 新增]`.

Performs pure semantic strategy analysis: complexity assessment, dimension
weighting, schema tailoring, and pipeline variant selection. Product name
resolution is handled by ProductResolver (pre-graph) — Orchestrator reads
verified products from state["target_products"].
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from deerflow.competition.schema import OrchestrationResult

logger = logging.getLogger(__name__)

# ── Prompt loading ──

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "orchestrator.md"


def _load_prompt() -> str:
    """Load the orchestrator system prompt from the prompt file."""
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    logger.warning("Orchestrator prompt file not found at %s — using minimal fallback", _PROMPT_PATH)
    return (
        "You are the Orchestrator Agent for a competitive analysis system. "
        "Parse the user's query intent and output a structured JSON routing instruction."
    )


# ── Default fallback values (used when Orchestrator fails) ──

_DEFAULT_DIMENSION_WEIGHTS = [
    {"dimension": "features", "weight": 0.7, "reason": "default fallback"},
    {"dimension": "pricing", "weight": 0.7, "reason": "default fallback"},
    {"dimension": "users", "weight": 0.5, "reason": "default fallback"},
    {"dimension": "market", "weight": 0.5, "reason": "default fallback"},
]


def _build_default_result() -> OrchestrationResult:
    """Build a fallback OrchestrationResult when LLM fails."""
    from deerflow.competition.schema import DimensionWeight

    return OrchestrationResult(
        complexity="standard",
        complexity_reason="fallback: Orchestrator LLM call failed — using default pipeline",
        dimension_weights=[DimensionWeight(**dw) for dw in _DEFAULT_DIMENSION_WEIGHTS],
        emphasized_aspects=[],
        schema_profile="baseline",
        summary="(Orchestrator degraded — default full pipeline)",
    )


def _parse_orchestrator_output(raw: str) -> dict | None:
    """Parse LLM output as JSON, with robust error recovery for common LLM issues.

    Handles:
      - markdown code blocks (```json ... ```)
      - leading/trailing text outside the JSON object
      - unescaped newlines in string values (common with Doubao)
    """
    text = raw.strip()

    # Strip markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove opening ```json or ```
        if lines[0].startswith("```"):
            lines = lines[1:]
        # Remove closing ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract just the JSON object: find first { and matching }
    first_brace = text.find("{")
    if first_brace == -1:
        return None

    # Find matching closing brace by counting nesting levels
    depth = 0
    last_brace = -1
    for i in range(first_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                last_brace = i
                break

    if last_brace > first_brace:
        extracted = text[first_brace:last_brace + 1]
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass

        # Last resort: try to fix unescaped newlines in string values
        # Replace literal newlines within quoted strings with \\n
        try:
            import re
            # Find all string values that span multiple lines and escape them
            fixed = re.sub(
                r'"(?P<value>[^"]*\n[^"]*)"',
                lambda m: '"' + m.group("value").replace("\n", "\\n") + '"',
                extracted,
            )
            return json.loads(fixed)
        except (json.JSONDecodeError, Exception):
            pass

    return None


# ── Main node function ──


def orchestrator_node(state: dict) -> dict:
    """Orchestrator Agent node — entry point of the competition graph.

    Reads state["user_request"] + state["target_products"] (already verified
    by ProductResolver), produces an OrchestrationResult that drives all
    downstream nodes.

    Returns a partial state update with:
        - orchestration_result: OrchestrationResult dict
        - complexity: str

    On failure: returns default fallback values so the pipeline never blocks.
    """
    from deerflow.competition.executor import execute_agent

    user_request = state.get("user_request", "")
    products = state.get("target_products") or []

    if not user_request:
        logger.warning("Orchestrator called with empty user_request — using defaults")
        orch = _build_default_result()
        return _build_return(orch)

    if not products:
        logger.warning("Orchestrator called with empty target_products — ProductResolver failed, degrading")
        orch = _build_default_result()
        return _build_return(orch)

    # ── Build task prompt ──
    system_prompt = _load_prompt()
    products_str = ", ".join(products) if products else "(none — ProductResolver failed)"

    # Industry context (Layer 2 of §3.20)
    from deerflow.competition.industry import get_industry_profile
    industry = state.get("industry", "general")
    profile = get_industry_profile(industry)
    industry_hint = ""
    if industry != "general" and profile.get("prompt_bias"):
        industry_hint = (
            f"\n\nINDUSTRY CONTEXT: {profile['label']}\n"
            f"Bias: {profile['prompt_bias']}\n"
        )

    task = (
        f"User query: {user_request}\n\n"
        f"Verified products: {products_str}"
        f"{industry_hint}\n\n"
        "Analyze the query intent and output a strategy routing instruction as a single JSON object "
        "following the format in your system prompt. "
        "Do NOT wrap in markdown code blocks — output raw JSON only."
    )

    # ── Invoke LLM ──
    try:
        raw, tokens = execute_agent(
            system_prompt,
            task,
            temperature=0.0,
            max_tokens=600,
            agent_name="Orchestrator",
        )
        logger.info("Orchestrator LLM call: %d tokens for %d products", tokens, len(products))
    except Exception:
        logger.exception("Orchestrator LLM call failed — degrading to default pipeline")
        orch = _build_default_result()
        return _build_return(orch)

    if not raw:
        logger.warning("Orchestrator returned empty content — degrading to default pipeline")
        orch = _build_default_result()
        return _build_return(orch)

    # ── Parse & validate ──
    parsed = _parse_orchestrator_output(raw)
    if parsed is None:
        logger.warning("Orchestrator JSON parse failed — raw output: %.200s", raw)
        orch = _build_default_result()
        return _build_return(orch)

    try:
        orch = OrchestrationResult(**parsed)
    except Exception:
        logger.exception("OrchestrationResult model_validate failed — degrading")
        orch = _build_default_result()
        return _build_return(orch)

    logger.info(
        "Orchestrator: complexity=%s schema=%s summary=%s",
        orch.complexity, orch.schema_profile, orch.summary,
    )

    return _build_return(orch)


def _build_return(orch: OrchestrationResult) -> dict:
    """Build the partial state return dict."""
    return {
        "orchestration_result": orch.model_dump(),
        "complexity": orch.complexity,
    }
