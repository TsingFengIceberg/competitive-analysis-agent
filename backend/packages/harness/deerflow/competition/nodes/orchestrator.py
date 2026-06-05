"""Orchestrator node — Query-Driven Dynamic Pipeline entry point `[v4 新增]`.

Replaces scattered LLM/keyword calls at the API entry point with a single
structured LLM invocation that resolves products, assesses complexity,
allocates dimension weights, selects schema profile, and chooses the
pipeline variant — all in one shot.
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


def _build_default_result(products: list[str], complexity: str = "standard") -> OrchestrationResult:
    """Build a fallback OrchestrationResult when LLM fails."""
    from deerflow.competition.schema import DimensionWeight

    return OrchestrationResult(
        products=products,
        product_confidence={p: "medium" for p in products} if products else {},
        complexity=complexity,
        complexity_reason="fallback: Orchestrator LLM call failed — using default pipeline",
        dimension_weights=[DimensionWeight(**dw) for dw in _DEFAULT_DIMENSION_WEIGHTS],
        schema_profile="full",
        emphasized_aspects=[],
        pipeline_variant="full",
        auto_discovered_competitors=[],
        summary="(Orchestrator degraded — default full pipeline)",
    )


def _parse_orchestrator_output(raw: str) -> dict | None:
    """Parse LLM output as JSON, handling markdown code blocks."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
        else:
            text = "\n".join(lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ── Main node function ──


def orchestrator_node(state: dict) -> dict:
    """Orchestrator Agent node — entry point of the competition graph.

    Reads state["user_request"] and optionally state["target_products"],
    produces an OrchestrationResult that drives all downstream nodes.

    Returns a partial state update with:
        - orchestration_result: OrchestrationResult dict
        - complexity: str
        - target_products: list[str] (may be updated if products were auto-discovered)

    On failure: returns default fallback values so the pipeline never blocks.
    """
    from deerflow.competition.executor import execute_agent

    user_request = state.get("user_request", "")
    existing_products = state.get("target_products") or []

    if not user_request:
        logger.warning("Orchestrator called with empty user_request — using defaults")
        orch = _build_default_result(existing_products)
        return _build_return(orch, existing_products)

    # ── Build task prompt ──
    system_prompt = _load_prompt()
    task = (
        f"User query: {user_request}\n\n"
        f"Explicit products provided: {json.dumps(existing_products) if existing_products else '(none — extract from query)'}\n\n"
        "Analyze the query and output the routing instruction as a single JSON object "
        "following the format in your system prompt. "
        "Do NOT wrap in markdown code blocks — output raw JSON only."
    )

    # ── Invoke LLM ──
    try:
        raw, tokens = execute_agent(
            system_prompt,
            task,
            temperature=0.0,
            max_tokens=800,
            agent_name="Orchestrator",
        )
        logger.info("Orchestrator LLM call: %d tokens", tokens)
    except Exception:
        logger.exception("Orchestrator LLM call failed — degrading to default pipeline")
        orch = _build_default_result(existing_products)
        return _build_return(orch, existing_products)

    if not raw:
        logger.warning("Orchestrator returned empty content — degrading to default pipeline")
        orch = _build_default_result(existing_products)
        return _build_return(orch, existing_products)

    # ── Parse & validate ──
    parsed = _parse_orchestrator_output(raw)
    if parsed is None:
        logger.warning("Orchestrator JSON parse failed — raw output: %.200s", raw)
        orch = _build_default_result(existing_products)
        return _build_return(orch, existing_products)

    try:
        orch = OrchestrationResult(**parsed)
    except Exception:
        logger.exception("OrchestrationResult model_validate failed — degrading")
        orch = _build_default_result(existing_products)
        return _build_return(orch, existing_products)

    # ── Merge explicit products with auto-discovered ──
    all_products: list[str] = list(existing_products) if existing_products else []

    for p in orch.products:
        if p not in all_products:
            all_products.append(p)
    for p in orch.auto_discovered_competitors:
        if p not in all_products:
            all_products.append(p)

    if not all_products and existing_products:
        all_products = list(existing_products)
        orch.products = all_products
        logger.info("Orchestrator resolved no products — keeping explicit: %s", all_products)
    elif not all_products:
        logger.warning("Orchestrator resolved 0 products — will attempt fallback extraction in gateway")

    orch.products = all_products
    logger.info(
        "Orchestrator resolved: products=%s complexity=%s schema=%s variant=%s summary=%s",
        all_products, orch.complexity, orch.schema_profile, orch.pipeline_variant, orch.summary,
    )

    return _build_return(orch, all_products)


def _build_return(orch: OrchestrationResult, products: list[str]) -> dict:
    """Build the partial state return dict."""
    return {
        "orchestration_result": orch.model_dump(),
        "complexity": orch.complexity,
        "target_products": products,
    }
