"""Deterministic entity, event, and long-horizon insight construction."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from competition.knowledge_query import canonical_product, normalize_query_text
from competition.knowledge_types import AUTHORITY_PRIORS

_NUMBER = re.compile(r"(?<![\w.])(?:[$¥€£]\s*)?\d+(?:[.,]\d+)?%?")
_TOKEN = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]{1,4}", re.IGNORECASE)


def entity_key(value: str) -> str:
    canonical = canonical_product(value) or "General market"
    return normalize_query_text(canonical).casefold()


def entity_id(space_id: str, value: str) -> str:
    digest = hashlib.sha256(f"{space_id}|{entity_key(value)}".encode()).hexdigest()[:24]
    return f"kent-{digest}"


def classify_event_type(dimension: str, version_no: int) -> str:
    normalized = dimension.casefold()
    if normalized == "pricing":
        return "pricing_change" if version_no > 1 else "pricing_signal"
    if normalized in {"features", "technology"}:
        return "capability_change" if version_no > 1 else "capability_signal"
    if normalized in {"market", "users"}:
        return "market_signal"
    return "document_update" if version_no > 1 else "document_signal"


def _tokens(value: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN.finditer(value)}


def _numbers(value: str) -> tuple[str, ...]:
    return tuple(sorted({match.group(0).replace(" ", "").casefold() for match in _NUMBER.finditer(value)}))


def event_cluster_key(entity: str, dimension: str, statement: str, occurred_at: str | None) -> str:
    month = str(occurred_at or "")[:7]
    numbers = "|".join(_numbers(statement))
    signal = numbers or "|".join(sorted(_tokens(statement))[:10])
    digest = hashlib.sha256(f"{entity_key(entity)}|{dimension.casefold()}|{month}|{signal}".encode()).hexdigest()[:24]
    return f"kevt-cluster-{digest}"


def event_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    if left.get("entity_id") != right.get("entity_id") or left.get("dimension") != right.get("dimension"):
        return 0.0
    left_numbers = set(_numbers(str(left.get("statement") or "")))
    right_numbers = set(_numbers(str(right.get("statement") or "")))
    left_tokens = _tokens(str(left.get("statement") or ""))
    right_tokens = _tokens(str(right.get("statement") or ""))
    if not left_tokens or not right_tokens:
        return 0.0
    lexical = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    if left_numbers and right_numbers and left_numbers == right_numbers and lexical >= 0.12:
        return min(1.0, 0.72 + lexical)
    return lexical


def build_event_candidate(
    document: dict[str, Any],
    *,
    version_no: int,
    chunk: dict[str, Any],
) -> dict[str, Any]:
    product = str(document.get("product") or "General market")
    statement = normalize_query_text(str(chunk.get("text") or ""))[:1600]
    occurred_at = document.get("published_at") or document.get("observed_at") or chunk.get("created_at")
    authority = str(document.get("authority_tier") or "third_party")
    return {
        "space_id": str(document.get("space_id") or ""),
        "entity_id": entity_id(str(document.get("space_id") or ""), product),
        "entity_name": canonical_product(product) or product,
        "entity_alias": product,
        "event_type": classify_event_type(str(document.get("dimension") or ""), version_no),
        "dimension": str(document.get("dimension") or "general"),
        "title": str(document.get("title") or "Knowledge update"),
        "statement": statement,
        "occurred_at": occurred_at,
        "authority_tier": authority,
        "confidence": AUTHORITY_PRIORS.get(authority, 0.5),
        "cluster_key": event_cluster_key(product, str(document.get("dimension") or "general"), statement, occurred_at),
        "document_id": document["document_id"],
        "version_no": version_no,
        "chunk_id": chunk.get("chunk_id"),
        "source_uri": document.get("source_uri") or "",
    }


def build_long_term_insights(events: list[dict[str, Any]], *, space_id: str) -> list[dict[str, Any]]:
    """Create explicitly separated facts, inferences, and hypotheses."""
    by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_entity[str(event.get("entity_id") or "")].append(event)
    output: list[dict[str, Any]] = []
    for current_entity, entity_events in by_entity.items():
        ordered = sorted(entity_events, key=lambda item: str(item.get("occurred_at") or item.get("last_seen_at") or ""))
        latest = ordered[-1]
        output.append(
            _insight(
                space_id,
                current_entity,
                "fact",
                f"Latest verified signal: {latest.get('title') or latest.get('dimension')}",
                str(latest.get("statement") or ""),
                float(latest.get("confidence") or 0.5),
                [str(latest.get("event_id") or "")],
                ordered,
            )
        )
        dimensions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in ordered:
            dimensions[str(event.get("dimension") or "general")].append(event)
        for dimension, dimension_events in dimensions.items():
            if len(dimension_events) < 2:
                continue
            evidence_ids = [str(item.get("event_id") or "") for item in dimension_events[-5:]]
            output.append(
                _insight(
                    space_id,
                    current_entity,
                    "inference",
                    f"Repeated {dimension} movement",
                    f"{len(dimension_events)} separately retained events indicate sustained activity in {dimension}; this is an inference from event frequency, not a direct source claim.",
                    min(0.9, 0.5 + 0.08 * len(dimension_events)),
                    evidence_ids,
                    dimension_events,
                )
            )
        if len(dimensions) >= 2 and len(ordered) >= 3:
            recent = ordered[-6:]
            evidence_ids = [str(item.get("event_id") or "") for item in recent]
            labels = ", ".join(sorted(dimensions)[:4])
            output.append(
                _insight(
                    space_id,
                    current_entity,
                    "hypothesis",
                    "Possible coordinated product movement",
                    f"Signals across {labels} may reflect a coordinated strategy. This is a hypothesis and requires additional independent evidence before use as a conclusion.",
                    0.35,
                    evidence_ids,
                    recent,
                )
            )
    return output


def _insight(
    space_id: str,
    current_entity: str,
    insight_type: str,
    title: str,
    summary: str,
    confidence: float,
    event_ids: list[str],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    identity = f"{space_id}|{current_entity}|{insight_type}|{title}|{'|'.join(event_ids)}"
    dates = [str(item.get("occurred_at") or item.get("last_seen_at") or "") for item in events]
    return {
        "insight_id": f"kins-{hashlib.sha256(identity.encode()).hexdigest()[:24]}",
        "space_id": space_id,
        "entity_id": current_entity,
        "insight_type": insight_type,
        "title": title,
        "summary": summary,
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "period_start": min(dates) if dates else None,
        "period_end": max(dates) if dates else None,
        "evidence_event_ids": [value for value in event_ids if value],
        "metadata": {"generated_by": "deterministic_event_reasoner", "requires_human_review": insight_type == "hypothesis"},
    }
