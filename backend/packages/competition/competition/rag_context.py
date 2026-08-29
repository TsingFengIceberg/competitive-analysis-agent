"""Role-aware, budget-bounded evidence bundles for graph agents."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from competition.knowledge_chunking import estimate_tokens
from competition.knowledge_types import AUTHORITY_PRIORS

SCHEMA_VERSION = "rag-context.v1"
ROLE_BUDGETS = {
    "orchestrator": 3000,
    "analyst": 12000,
    "reviewer": 9000,
    "writer": 10000,
    "collector": 6000,
}


def evidence_coverage(bundle: dict[str, Any], *, products: list[str] | None = None, dimensions: list[str] | None = None) -> dict[str, Any]:
    """Summarize product/dimension coverage for routing and targeted collection."""
    evidence = [item for item in bundle.get("evidence") or [] if isinstance(item, dict)]
    expected_products = {str(value).casefold() for value in products or [] if str(value).strip()}
    expected_dimensions = {str(value).casefold() for value in dimensions or [] if str(value).strip()}
    covered_products = {str(item.get("product") or "").casefold() for item in evidence if item.get("product")}
    covered_dimensions = {str(item.get("dimension") or "").casefold() for item in evidence if item.get("dimension")}
    covered_pairs = {
        (str(item.get("product") or "").casefold(), str(item.get("dimension") or "").casefold())
        for item in evidence
        if item.get("product") and item.get("dimension")
    }
    expected_pairs = {(product, dimension) for product in expected_products for dimension in expected_dimensions}
    missing_pairs = sorted(expected_pairs - covered_pairs)
    missing_products = sorted(expected_products - covered_products)
    missing_dimensions = sorted(expected_dimensions - covered_dimensions)
    return {
        "expected_products": sorted(expected_products),
        "expected_dimensions": sorted(expected_dimensions),
        "covered_products": sorted(covered_products),
        "covered_dimensions": sorted(covered_dimensions),
        "missing_products": missing_products,
        "missing_dimensions": missing_dimensions,
        "expected_pairs": [list(pair) for pair in sorted(expected_pairs)],
        "covered_pairs": [list(pair) for pair in sorted(covered_pairs & expected_pairs)],
        "missing_pairs": [list(pair) for pair in missing_pairs],
        "targeted_tasks": [
            {"product": product, "dimension": dimension, "task": f"Collect authoritative {dimension} evidence for {product}"}
            for product, dimension in missing_pairs[:24]
        ],
        "coverage_ratio": round(
            len(covered_pairs & expected_pairs) / max(1, len(expected_pairs))
            if expected_pairs
            else (len(expected_products & covered_products) + len(expected_dimensions & covered_dimensions))
            / max(1, len(expected_products) + len(expected_dimensions)),
            6,
        ),
        "needs_targeted_collection": bool(missing_products or missing_dimensions or missing_pairs or bundle.get("abstain")),
    }


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _freshness(item: dict[str, Any], *, now: datetime) -> float:
    stamp = _parse_time(item.get("published_at") or item.get("observed_at") or item.get("collected_at"))
    if stamp is None:
        return 0.35
    age_days = max(0.0, (now - stamp).total_seconds() / 86400)
    return max(0.0, min(1.0, 2.718281828 ** (-age_days / 365.0)))


def _identity(item: dict[str, Any]) -> str:
    return str(item.get("knowledge_chunk_id") or item.get("chunk_id") or item.get("id") or "")


def _to_evidence(item: dict[str, Any], *, role: str, now: datetime) -> dict[str, Any]:
    authority_tier = str(item.get("authority_tier") or item.get("source_authority") or "third_party")
    chunk_id = _identity(item)
    text = str(item.get("text") or item.get("value") or "").strip()
    evidence = {
        "evidence_id": chunk_id or hashlib.sha256(text.encode("utf-8")).hexdigest()[:24],
        "knowledge_document_id": item.get("knowledge_document_id") or item.get("document_id"),
        "knowledge_chunk_id": chunk_id or None,
        "product": item.get("product") or "",
        "dimension": item.get("dimension") or item.get("category") or "",
        "title": item.get("title") or item.get("source_title") or item.get("label") or "",
        "text": text,
        "source_url": item.get("source_url") or item.get("source_uri") or "",
        "source_type": item.get("source_type") or "",
        "authority_tier": authority_tier,
        "authority_score": round(AUTHORITY_PRIORS.get(authority_tier, 0.5), 6),
        "freshness_score": round(_freshness(item, now=now), 6),
        "retrieval_score": float(item.get("retrieval_score") or item.get("score") or 0.0),
        "section_path": item.get("section_path") or "",
        "page_no": item.get("page_no"),
        "citation_eligible": authority_tier != "report" and bool(chunk_id or item.get("source_url") or item.get("source_uri")),
        "temporal_status": item.get("knowledge_temporal_status") or item.get("temporal_status") or "current",
    }
    evidence["token_count"] = estimate_tokens(text)
    evidence["selection_role"] = role
    return evidence


def build_agent_evidence_bundle(
    state: dict[str, Any],
    *,
    role: str,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Build one deterministic evidence view shared by Analyst/Reviewer/Writer."""
    role = role if role in ROLE_BUDGETS else "analyst"
    budget = max(500, int(max_tokens or ROLE_BUDGETS[role]))
    now = datetime.now(UTC)
    pack = state.get("analysis_context_pack") if isinstance(state.get("analysis_context_pack"), dict) else {}
    candidates: list[dict[str, Any]] = []
    if isinstance(pack.get("evidence"), list):
        candidates.extend(item for item in pack["evidence"] if isinstance(item, dict))
    candidates.extend(item for item in state.get("collected_data") or [] if isinstance(item, dict))

    deduped: dict[str, dict[str, Any]] = {}
    for item in candidates:
        evidence = _to_evidence(item, role=role, now=now)
        identity = evidence["evidence_id"]
        previous = deduped.get(identity)
        # Current-run records override durable snapshots for the same chunk.
        if previous is None or item in (state.get("collected_data") or []):
            deduped[identity] = evidence

    def rank(item: dict[str, Any]) -> tuple[float, float, float, str]:
        return (
            float(item.get("retrieval_score") or 0.0) * 0.60 + float(item.get("authority_score") or 0.0) * 0.25 + float(item.get("freshness_score") or 0.0) * 0.15,
            float(item.get("authority_score") or 0.0),
            float(item.get("freshness_score") or 0.0),
            str(item.get("evidence_id") or ""),
        )

    ordered = sorted(deduped.values(), key=rank, reverse=True)
    selected: list[dict[str, Any]] = []
    used_tokens = 0
    truncated = 0
    for item in ordered:
        cost = int(item.get("token_count") or 1)
        if used_tokens + cost > budget:
            truncated += 1
            continue
        selected.append(item)
        used_tokens += cost

    quality = pack.get("quality") if isinstance(pack.get("quality"), dict) else {}
    quality_state = str(quality.get("quality_state") or ("available" if selected else "missing"))
    abstain_reasons: list[str] = []
    if not selected:
        abstain_reasons.append("no_evidence_in_scope")
    if quality_state in {"missing", "fetch_failed"}:
        abstain_reasons.append(f"context_quality_{quality_state}")
    if quality.get("conflicts"):
        abstain_reasons.append("conflicting_sources_require_review")
    products = [str(value) for value in (state.get("target_products") or [])]
    brief_dimensions = (state.get("analysis_brief") or {}).get("effective_dimensions") or (state.get("analysis_brief") or {}).get("dimensions") or []
    dimensions = [str(item.get("id")) for item in brief_dimensions if isinstance(item, dict) and item.get("id")]
    coverage = evidence_coverage({"evidence": selected, "abstain": bool(abstain_reasons)}, products=products, dimensions=dimensions)
    return {
        "schema_version": SCHEMA_VERSION,
        "role": role,
        "generated_at": now.isoformat(),
        "budget_tokens": budget,
        "used_tokens": used_tokens,
        "candidate_count": len(ordered),
        "selected_count": len(selected),
        "truncated_count": truncated,
        "quality_state": quality_state,
        "abstain": bool(abstain_reasons),
        "abstain_reasons": abstain_reasons,
        "coverage": coverage,
        "evidence": selected,
        "selection_policy": "retrieval_score_0.60_authority_0.25_freshness_0.15",
    }


def prompt_excerpt(bundle: dict[str, Any], *, max_chars: int = 24000) -> str:
    """Serialize only the bounded bundle, never internal paths or credentials."""
    import json

    payload = {
        "schema_version": bundle.get("schema_version"),
        "role": bundle.get("role"),
        "quality_state": bundle.get("quality_state"),
        "abstain": bundle.get("abstain"),
        "abstain_reasons": bundle.get("abstain_reasons") or [],
        "evidence": bundle.get("evidence") or [],
    }
    return json.dumps(payload, ensure_ascii=False, default=str)[:max_chars]
