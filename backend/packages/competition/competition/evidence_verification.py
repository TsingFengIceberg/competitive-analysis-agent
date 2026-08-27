"""Deterministic, batched claim-to-evidence verification for competitive reports."""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from competition.knowledge_types import KnowledgeHit, RetrievalFilters

_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.])[-+]?\d+(?:[.,]\d+)?\s*(?:%|％|美元|元|万元|万|亿|k|m|b)?", re.I)
_LATIN_RE = re.compile(r"[a-z0-9]+", re.I)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_NEGATION_RE = re.compile(
    r"(?:\b(?:no|not|never|without|cannot|can't|doesn't|isn't|aren't|won't|lack(?:s|ed|ing)?)\b|"
    r"(?:不支持|不提供|不包含|不能|无法|没有|并未|尚未|未提供|无此|缺少))",
    re.I,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _claim_id(origin: str, product: str, dimension: str, text: str) -> str:
    digest = hashlib.sha256(f"{origin}\0{product}\0{dimension}\0{text}".encode()).hexdigest()[:16]
    return f"claim-{digest}"


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _append_claim(
    claims: list[dict[str, Any]],
    *,
    text: Any,
    origin: str,
    product: Any = "",
    dimension: Any = "",
    source_ids: Any = None,
) -> None:
    claim_text = _clean_text(text)
    if len(claim_text) < 4:
        return
    normalized_ids = [str(value) for value in (source_ids or []) if str(value).strip()]
    product_text = _clean_text(product)
    dimension_text = _clean_text(dimension)
    claims.append(
        {
            "claim_id": _claim_id(origin, product_text, dimension_text, claim_text),
            "claim_text": claim_text,
            "origin": origin,
            "product": product_text,
            "dimension": dimension_text,
            "source_data_point_ids": list(dict.fromkeys(normalized_ids)),
        }
    )


def extract_claims(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract stable factual claims from structured Analyst output."""
    claims: list[dict[str, Any]] = []
    matrix = analysis.get("comparison_matrix") or {}
    if isinstance(matrix, dict):
        for cell in matrix.get("cells") or []:
            if isinstance(cell, dict):
                _append_claim(
                    claims,
                    text=cell.get("evidence"),
                    origin="comparison_matrix",
                    product=cell.get("product"),
                    dimension=cell.get("dimension"),
                    source_ids=cell.get("source_data_point_ids"),
                )
    swot = analysis.get("swot") or {}
    if isinstance(swot, dict):
        for product, value in swot.items():
            if not isinstance(value, dict):
                continue
            for item in value.get("items") or []:
                if isinstance(item, dict):
                    text = item.get("statement") or item.get("evidence")
                    _append_claim(
                        claims,
                        text=text,
                        origin=f"swot.{item.get('category', 'item')}",
                        product=product,
                        source_ids=item.get("source_data_point_ids"),
                    )
    for trend in analysis.get("trends") or []:
        if isinstance(trend, dict):
            _append_claim(
                claims,
                text=trend.get("evidence"),
                origin="trend",
                dimension=trend.get("dimension"),
                source_ids=trend.get("source_data_point_ids"),
            )
    for block_index, block in enumerate(analysis.get("dynamic_blocks") or []):
        if not isinstance(block, dict) or block.get("included", True) is False:
            continue
        data = block.get("data") or {}
        candidates: list[Any] = []
        if isinstance(data, dict):
            for key in ("insight", "text", "content", "summary", "conclusion", "value"):
                if data.get(key):
                    candidates.append(data[key])
            if not candidates and block.get("block_type") == "insight_text":
                candidates.extend(value for value in data.values() if isinstance(value, str))
        for item_index, text in enumerate(candidates):
            _append_claim(
                claims,
                text=text,
                origin=f"dynamic_block.{block_index}.{item_index}",
                dimension=block.get("title"),
                source_ids=block.get("source_data_point_ids"),
            )
    unique: dict[str, dict[str, Any]] = {}
    for claim in claims:
        unique.setdefault(claim["claim_id"], claim)
    return list(unique.values())


def _tokens(text: str) -> set[str]:
    lowered = text.casefold()
    latin = set(_LATIN_RE.findall(lowered))
    cjk = _CJK_RE.findall(lowered)
    cjk_tokens = set(cjk)
    cjk_tokens.update("".join(cjk[index : index + 2]) for index in range(max(0, len(cjk) - 1)))
    return {value for value in latin | cjk_tokens if value}


def lexical_similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    return round(intersection / math.sqrt(len(left_tokens) * len(right_tokens)), 6)


def _numbers(text: str) -> set[str]:
    values: set[str] = set()
    for match in _NUMBER_RE.findall(text):
        normalized = match.casefold().replace(" ", "").replace("，", ",").replace("％", "%")
        values.add(normalized)
    return values


def numeric_consistency(claim: str, evidence: str) -> bool | None:
    claim_numbers = _numbers(claim)
    if not claim_numbers:
        return None
    evidence_numbers = _numbers(evidence)
    if not evidence_numbers:
        return None
    return claim_numbers.issubset(evidence_numbers)


def _polarity(text: str) -> bool:
    return bool(_NEGATION_RE.search(text))


def _relevant_polarity(text: str, query: str) -> bool:
    """Ignore unrelated disclaimers by checking the sentence closest to the claim."""
    sentences = [value.strip() for value in re.split(r"(?<=[.!?。！？])\s*", text) if value.strip()]
    if not sentences:
        return _polarity(text)
    relevant = max(sentences, key=lambda value: lexical_similarity(query, value))
    return _polarity(relevant)


def _point_candidate(point: dict[str, Any], *, explicit: bool) -> dict[str, Any]:
    text = _clean_text(point.get("value") or point.get("evidence") or point.get("label"))
    return {
        "data_point_id": str(point.get("id") or "") or None,
        "document_id": point.get("knowledge_document_id"),
        "chunk_id": point.get("knowledge_chunk_id"),
        "version_no": point.get("knowledge_version_no"),
        "source_url": str(point.get("source_url") or ""),
        "source_title": str(point.get("source_title") or point.get("label") or ""),
        "excerpt": text[:1200],
        "authority_tier": str(point.get("source_authority") or point.get("source_type") or ""),
        "published_at": point.get("published_at"),
        "observed_at": point.get("collected_at"),
        "valid_from": point.get("knowledge_valid_from"),
        "valid_to": point.get("knowledge_valid_to"),
        "temporal_status": point.get("knowledge_temporal_status") or "unknown",
        "retrieval_score": point.get("retrieval_score"),
        "explicit": explicit,
    }


def _hit_candidate(hit: KnowledgeHit) -> dict[str, Any]:
    return {
        "data_point_id": None,
        "document_id": hit.document_id,
        "chunk_id": hit.chunk_id,
        "version_no": hit.version_no,
        "source_url": hit.source_uri or f"knowledge://{hit.document_id}/{hit.chunk_id}",
        "source_title": hit.title,
        "excerpt": hit.text[:1200],
        "authority_tier": hit.authority_tier,
        "published_at": hit.published_at,
        "observed_at": hit.observed_at,
        "valid_from": hit.valid_from,
        "valid_to": hit.valid_to,
        "temporal_status": hit.temporal_status,
        "retrieval_score": hit.score,
        "explicit": False,
    }


def _default_semantic_scores(groups: list[tuple[str, list[str]]]) -> list[list[float]]:
    return [[lexical_similarity(query, text) for text in texts] for query, texts in groups]


def _relation(claim: str, candidate: dict[str, Any], semantic_score: float) -> tuple[str, bool | None]:
    excerpt = candidate["excerpt"]
    numeric = numeric_consistency(claim, excerpt)
    relevant = semantic_score >= 0.20 or float(candidate.get("retrieval_score") or 0.0) >= 0.45
    if relevant and numeric is False:
        return "contradicts", numeric
    if relevant and _relevant_polarity(claim, excerpt) != _relevant_polarity(excerpt, claim):
        return "contradicts", numeric
    if numeric is True or semantic_score >= 0.46 or (
        candidate.get("explicit") and semantic_score >= 0.14
    ):
        return "supports", numeric
    return "context", numeric


def verify_claims(
    analysis: dict[str, Any],
    collected: list[dict[str, Any]],
    *,
    user_id: str = "default",
    search_many: Callable[[list[tuple[str, RetrievalFilters, int]], str], list[list[KnowledgeHit]]] | None = None,
    semantic_scorer: Callable[[list[tuple[str, list[str]]]], list[list[float]]] | None = None,
) -> dict[str, Any]:
    """Verify claims against cited data and optional batched local semantic retrieval."""
    claims = extract_claims(analysis)
    generated_at = _now()
    if not claims:
        return {
            "schema_version": 1,
            "status": "empty",
            "generated_at": generated_at,
            "total": 0,
            "supported": 0,
            "contradicted": 0,
            "insufficient": 0,
            "groundedness": 0.0,
            "citation_precision": 0.0,
            "numeric_consistency": 1.0,
            "degraded_reason": None,
            "claims": [],
        }

    points_by_id = {str(point.get("id")): point for point in collected if isinstance(point, dict) and point.get("id")}
    candidates_by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        for point_id in claim["source_data_point_ids"]:
            point = points_by_id.get(point_id)
            if point:
                candidates_by_claim[claim["claim_id"]].append(_point_candidate(point, explicit=True))

    degraded_reason: str | None = None
    if search_many is not None:
        requests = [
            (
                claim["claim_text"],
                RetrievalFilters(
                    products=(claim["product"],) if claim["product"] else (),
                    dimensions=(claim["dimension"],) if claim["dimension"] else (),
                    temporal_mode="current",
                ),
                4,
            )
            for claim in claims
        ]
        try:
            result_groups = search_many(requests, user_id)
            for claim, hits in zip(claims, result_groups, strict=True):
                existing = {
                    (candidate.get("document_id"), candidate.get("chunk_id"), candidate.get("data_point_id"))
                    for candidate in candidates_by_claim[claim["claim_id"]]
                }
                for hit in hits:
                    candidate = _hit_candidate(hit)
                    key = (candidate.get("document_id"), candidate.get("chunk_id"), None)
                    if key not in existing:
                        candidates_by_claim[claim["claim_id"]].append(candidate)
        except Exception as exc:
            degraded_reason = f"Local semantic retrieval unavailable: {type(exc).__name__}"

    groups = [
        (claim["claim_text"], [candidate["excerpt"] for candidate in candidates_by_claim[claim["claim_id"]]])
        for claim in claims
    ]
    scorer = semantic_scorer or _default_semantic_scores
    try:
        score_groups = scorer(groups)
    except Exception as exc:
        score_groups = _default_semantic_scores(groups)
        reason = f"Semantic reranker unavailable: {type(exc).__name__}"
        degraded_reason = f"{degraded_reason}; {reason}" if degraded_reason else reason

    verified: list[dict[str, Any]] = []
    supported_explicit = 0
    explicit_total = 0
    numeric_claims = 0
    numeric_consistent_claims = 0
    for claim, scores in zip(claims, score_groups, strict=True):
        evidence: list[dict[str, Any]] = []
        for candidate, score in zip(candidates_by_claim[claim["claim_id"]], scores, strict=True):
            normalized_score = max(0.0, min(1.0, float(score)))
            relation, number_match = _relation(claim["claim_text"], candidate, normalized_score)
            if candidate.get("explicit"):
                explicit_total += 1
                if relation == "supports":
                    supported_explicit += 1
            evidence.append(
                {
                    key: value
                    for key, value in {
                        **candidate,
                        "explicit": None,
                        "semantic_score": round(normalized_score, 6),
                        "relation": relation,
                        "numeric_match": number_match,
                    }.items()
                    if key != "explicit"
                }
            )
        evidence.sort(
            key=lambda item: (
                {"contradicts": 2, "supports": 1, "context": 0}[item["relation"]],
                item["semantic_score"],
            ),
            reverse=True,
        )
        support = [item for item in evidence if item["relation"] == "supports"]
        conflicts = [item for item in evidence if item["relation"] == "contradicts"]
        if conflicts:
            status = "contradicted"
            confidence = max(item["semantic_score"] for item in conflicts)
            reason = "Evidence with matching context contains a numeric or polarity conflict."
        elif support:
            status = "supported"
            confidence = max(item["semantic_score"] for item in support)
            reason = "At least one semantically relevant evidence item supports the claim."
        else:
            status = "insufficient"
            confidence = max((item["semantic_score"] for item in evidence), default=0.0)
            reason = "No sufficiently relevant supporting evidence was found."
        numeric_values = [
            item["numeric_match"]
            for item in evidence
            if item["relation"] != "context" and item["numeric_match"] is not None
        ]
        claim_numeric_consistency = (
            None
            if not _numbers(claim["claim_text"]) or not numeric_values
            else not any(value is False for value in numeric_values)
        )
        if claim_numeric_consistency is not None:
            numeric_claims += 1
            numeric_consistent_claims += int(claim_numeric_consistency)
        verified.append(
            {
                **claim,
                "status": status,
                "confidence": round(confidence, 6),
                "reason": reason,
                "numeric_consistency": claim_numeric_consistency,
                "evidence": evidence[:8],
                "checked_at": generated_at,
            }
        )

    counts = {status: sum(item["status"] == status for item in verified) for status in ("supported", "contradicted", "insufficient")}
    total = len(verified)
    return {
        "schema_version": 1,
        "status": "degraded" if degraded_reason else "ready",
        "generated_at": generated_at,
        "total": total,
        **counts,
        "groundedness": round(counts["supported"] / total, 6),
        "citation_precision": round(supported_explicit / explicit_total, 6) if explicit_total else 0.0,
        "numeric_consistency": round(numeric_consistent_claims / numeric_claims, 6) if numeric_claims else 1.0,
        "degraded_reason": degraded_reason,
        "claims": verified,
    }


def verification_gaps(summary: dict[str, Any], review_round: int) -> list[dict[str, Any]]:
    """Translate verification outcomes into existing Reviewer rework contracts."""
    gaps: list[dict[str, Any]] = []
    for claim in summary.get("claims") or []:
        status = claim.get("status")
        if status not in {"contradicted", "insufficient"}:
            continue
        contradictory = status == "contradicted"
        gaps.append(
            {
                "gap_id": f"gap-verify-{review_round}-{claim['claim_id']}",
                "type": "source_conflict" if contradictory else "missing_data",
                "check_method": "semantic_claim_verification",
                "method": "semantic_claim_verification",
                "description": (
                    f"Claim conflicts with retrieved evidence: {claim['claim_text']}"
                    if contradictory
                    else f"Claim lacks sufficient semantic evidence: {claim['claim_text']}"
                ),
                "evidence": claim.get("reason", ""),
                "target_collect_task": f"Collect authoritative evidence for: {claim['claim_text']}",
                "severity": "critical" if contradictory else "major",
                "related_data_point_ids": claim.get("source_data_point_ids") or [],
            }
        )
    return gaps
