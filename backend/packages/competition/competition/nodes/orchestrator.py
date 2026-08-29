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

from competition.schema import OrchestrationResult

logger = logging.getLogger(__name__)

# ── Prompt loading ──

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "orchestrator.md"
_PROFILE_PATH = Path(__file__).parent.parent / "profile.md"


def _load_prompt() -> str:
    """Load the orchestrator system prompt from the prompt file."""
    if _PROMPT_PATH.exists():
        prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    else:
        logger.warning("Orchestrator prompt file not found at %s — using minimal fallback", _PROMPT_PATH)
        prompt = (
            "You are the Orchestrator Agent for a competitive analysis system. "
            "Parse the user's query intent and output a structured JSON routing instruction."
        )
    # Append project profile if available (§curryxjh-inspired)
    if _PROFILE_PATH.exists():
        profile = _PROFILE_PATH.read_text(encoding="utf-8").strip()
        if profile:
            prompt += "\n\n## 项目长期偏好（profile.md）\n\n" + profile
            prompt += "\n\n以上偏好是本项目的长期配置，请在所有决策中优先遵守。"
    return prompt


# ── Default fallback values (used when Orchestrator fails) ──

_DEFAULT_DIMENSION_WEIGHTS = [
    {"dimension": "features", "weight": 0.7, "reason": "default fallback"},
    {"dimension": "pricing", "weight": 0.7, "reason": "default fallback"},
    {"dimension": "users", "weight": 0.5, "reason": "default fallback"},
    {"dimension": "market", "weight": 0.5, "reason": "default fallback"},
]


def _build_default_result() -> OrchestrationResult:
    """Build a fallback OrchestrationResult when LLM fails."""
    from competition.schema import DimensionWeight

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
      - Chinese punctuation in JSON (： → :, ， → ,)
      - mixed Chinese-prose / JSON hybrid output
    """
    import re

    text = raw.strip()

    # Strip markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Normalize Chinese punctuation to ASCII for JSON compatibility
    text = text.replace("“", '"').replace("”", '"')  # Chinese double quotes
    text = text.replace("：", ":").replace("，", ",")  # ：→: ，→,

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to extract just the JSON object: find first { and matching }
    first_brace = text.find("{")
    if first_brace == -1:
        return None

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

        # Fix unescaped newlines in string values
        try:
            fixed = re.sub(
                r'"(?P<value>[^"]*\n[^"]*)"',
                lambda m: '"' + m.group("value").replace("\n", "\\n") + '"',
                extracted,
            )
            return json.loads(fixed)
        except (json.JSONDecodeError, Exception):
            pass

        # Last resort: field-by-field regex extraction
        return _extract_orchestrator_fields(text)

    return None


def _extract_orchestrator_fields(text: str) -> dict | None:
    """Extract orchestrator fields from broken JSON using regex."""
    import re

    result: dict = {}

    # Extract complexity
    m = re.search(r'"complexity"\s*:\s*"(quick|standard|deep)"', text)
    if m:
        result["complexity"] = m.group(1)

    # Extract complexity_reason
    m = re.search(r'"complexity_reason"\s*:\s*"([^"]*)"', text)
    if m:
        result["complexity_reason"] = m.group(1)

    # Extract schema_profile
    m = re.search(r'"schema_profile"\s*:\s*"(baseline|deep)"', text)
    if m:
        result["schema_profile"] = m.group(1)

    # Extract summary
    m = re.search(r'"summary"\s*:\s*"([^"]*)"', text)
    if m:
        result["summary"] = m.group(1)

    # Extract dimension_weights: try to parse each weight object (JSON format)
    dim_weights = []
    for m in re.finditer(
        r'\{\s*"dimension"\s*:\s*"(features|pricing|users|market|technology)"\s*,\s*"weight"\s*:\s*([\d.]+)\s*,\s*"reason"\s*:\s*"([^"]*)"\s*\}',
        text,
    ):
        dim_weights.append({
            "dimension": m.group(1),
            "weight": float(m.group(2)),
            "reason": m.group(3),
        })

    # Also try Chinese-prose dimension weight format:
    #   维度：功能特性
    #   权重：0.8
    #   原因：...
    _DIM_CN_MAP = {
        "功能特性": "features", "功能": "features",
        "定价": "pricing", "价格": "pricing", "定价策略": "pricing",
        "用户": "users", "用户画像": "users", "使用体验": "users",
        "市场": "market", "市场格局": "market", "竞争格局": "market",
        "技术": "technology", "技术架构": "technology", "技术栈": "technology",
    }
    for m in re.finditer(
        r'维度[：:]\s*(\S+?)\s*\n\s*权重[：:]\s*([\d.]+)\s*\n\s*原因[：:]\s*([^\n]+)',
        text,
    ):
        cn_dim = m.group(1).strip()
        eng_dim = _DIM_CN_MAP.get(cn_dim)
        if eng_dim:
            dim_weights.append({
                "dimension": eng_dim,
                "weight": float(m.group(2)),
                "reason": m.group(3).strip(),
            })
    if dim_weights:
        result["dimension_weights"] = dim_weights

    # Extract emphasized_aspects
    aspects = []
    for m in re.finditer(r'"([^"]+)"', text):
        # Grab quoted strings that look like Chinese analysis aspects (not JSON keys)
        val = m.group(1)
        if val and not val.startswith("dimension") and not val.startswith("complexity") \
           and not val.startswith("schema") and not val.startswith("summary") \
           and not val.startswith("reason") and not val.startswith("weight") \
           and not val.startswith("features") and not val.startswith("pricing") \
           and not val.startswith("users") and not val.startswith("market") \
           and not val.startswith("technology") \
           and any('一' <= c <= '鿿' for c in val):
            aspects.append(val)
    # Only keep aspects between complexity_reason and the end
    if aspects:
        result["emphasized_aspects"] = aspects[:3]  # max 3

    if "complexity" not in result:
        return None
    return result


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
    from competition.executor import execute_agent

    user_request = state.get("user_request", "")
    products = state.get("target_products") or []
    brief = state.get("analysis_brief") or {}
    try:
        from competition.rag_context import build_agent_evidence_bundle, prompt_excerpt

        rag_context = build_agent_evidence_bundle(state, role="orchestrator")
    except Exception:
        logger.exception("Orchestrator RAG context build failed")
        rag_context = None

    if not user_request:
        logger.warning("Orchestrator called with empty user_request — using defaults")
        orch = _build_default_result()
        return _build_return(orch, brief, rag_context=rag_context)

    if not products:
        logger.warning("Orchestrator called with empty target_products — ProductResolver failed, degrading")
        orch = _build_default_result()
        return _build_return(orch, brief, rag_context=rag_context)

    # ── Build task prompt ──
    system_prompt = _load_prompt()
    products_str = ", ".join(products) if products else "(none — ProductResolver failed)"
    brief_hint = ""
    if brief:
        brief_hint = (
            f"\nConfirmed Analysis Brief: market={brief.get('market_scope', 'Global / unspecified')}; "
            f"time={(brief.get('time_range') or {}).get('label', '最近12个月')}; "
            f"dimensions={[item.get('id') for item in brief.get('dimensions', [])]}; "
            f"complexity={brief.get('complexity', 'standard')}; "
            f"output_focus={brief.get('output_focus') or []}. Treat these as hard constraints.\n"
        )

    # Industry context (Layer 2 of §3.20)
    from competition.industry import get_industry_profile
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
        f"{industry_hint}{brief_hint}\n"
        "Analyze the query intent and output a strategy routing instruction as a single JSON object "
        "following the format in your system prompt. "
        "Do NOT wrap in markdown code blocks — output raw JSON only."
    )
    if rag_context and rag_context.get("evidence"):
        task += "\n\nRAG COVERAGE SIGNALS (planning only; do not treat as final facts):\n" + prompt_excerpt(rag_context)

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
        return _build_return(orch, brief, rag_context=rag_context)

    if not raw:
        logger.warning("Orchestrator returned empty content — degrading to default pipeline")
        orch = _build_default_result()
        return _build_return(orch, brief, rag_context=rag_context)

    # ── Parse & validate ──
    parsed = _parse_orchestrator_output(raw)
    if parsed is None:
        logger.warning("Orchestrator JSON parse failed — raw output: %.200s", raw)
        orch = _build_default_result()
        return _build_return(orch, rag_context=rag_context)

    try:
        orch = OrchestrationResult(**parsed)
    except Exception:
        logger.exception("OrchestrationResult model_validate failed — degrading")
        orch = _build_default_result()
        return _build_return(orch, rag_context=rag_context)

    logger.info(
        "Orchestrator: complexity=%s schema=%s summary=%s",
        orch.complexity, orch.schema_profile, orch.summary,
    )

    return _build_return(orch, brief, rag_context=rag_context)


def _build_return(orch: OrchestrationResult, brief: dict | None = None, *, rag_context: dict | None = None) -> dict:
    """Build the partial state return dict."""
    if brief:
        dimensions = brief.get("effective_dimensions") or brief.get("dimensions") or []
        orch.complexity = brief.get("complexity", orch.complexity)
        orch.schema_profile = "deep" if orch.complexity == "deep" else "baseline"
        from competition.schema import DimensionWeight
        orch.dimension_weights = [
            DimensionWeight(dimension=item.get("id", ""), weight=item.get("weight", 0), reason="confirmed Analysis Brief")
            for item in dimensions if item.get("id")
        ]
        orch.emphasized_aspects = list(brief.get("output_focus") or [])[:3]
        orch.complexity_reason = "constrained by confirmed Analysis Brief"
    return {
        "orchestration_result": orch.model_dump(),
        "complexity": orch.complexity,
        "rag_context": rag_context,
    }
