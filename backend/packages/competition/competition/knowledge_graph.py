"""Evidence-governed relationship graph construction and retrieval routing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from competition.knowledge_intelligence import entity_id, entity_key
from competition.knowledge_query import canonical_product, normalize_query_text

_TOKEN = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]{1,4}", re.IGNORECASE)
_PRICE = re.compile(
    r"(?:[$¥€£]\s*\d+(?:[.,]\d+)?(?:\s*(?:/|per)\s*[a-z]+)?|\d+(?:[.,]\d+)?\s*(?:美元|元|人民币|usd|cny)(?:\s*/\s*[\u3400-\u9fffa-z]+)?)",
    re.IGNORECASE,
)
_INTEGRATIONS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("GitHub", r"\bgithub\b"),
        ("GitLab", r"\bgitlab\b"),
        ("Slack", r"\bslack\b"),
        ("Jira", r"\bjira\b"),
        ("Visual Studio Code", r"\b(?:visual studio code|vs\s*code|vscode)\b"),
        ("JetBrains IDEs", r"\bjetbrains\b"),
        ("Model Context Protocol", r"\b(?:model context protocol|mcp)\b"),
        ("Kubernetes", r"\bkubernetes\b"),
        ("Docker", r"\bdocker\b"),
    )
)

_RELATION_MARKERS = (
    "relationship",
    "related",
    "depend",
    "integrat",
    "compatible",
    "replace",
    "alternative",
    "ecosystem",
    "impact",
    "evolution",
    "关系",
    "关联",
    "依赖",
    "集成",
    "兼容",
    "替代",
    "生态",
    "影响",
    "演进",
)
_TEMPORAL_MARKERS = (
    "change",
    "history",
    "timeline",
    "before",
    "after",
    "over time",
    "变化",
    "历史",
    "时间线",
    "之前",
    "之后",
    "演进",
)


def graph_entity_key(entity_type: str, value: str) -> str:
    normalized = normalize_query_text(value).casefold() or "unknown"
    if entity_type == "product":
        return entity_key(value)
    return f"{entity_type}:{normalized}"


def graph_entity_id(space_id: str, entity_type: str, value: str) -> str:
    if entity_type == "product":
        return entity_id(space_id, value)
    digest = hashlib.sha256(f"{space_id}|{graph_entity_key(entity_type, value)}".encode()).hexdigest()[:24]
    return f"kent-{digest}"


def relation_cluster_key(
    space_id: str,
    source_entity_id: str,
    target_entity_id: str,
    relation_type: str,
    dimension: str,
    temporal_bucket: str = "",
) -> str:
    identity = f"{space_id}|{source_entity_id}|{target_entity_id}|{relation_type}|{dimension.casefold()}|{temporal_bucket}"
    return f"krel-cluster-{hashlib.sha256(identity.encode()).hexdigest()[:24]}"


def relation_id(cluster_key: str) -> str:
    return f"krel-{hashlib.sha256(cluster_key.encode()).hexdigest()[:24]}"


def _entity(
    space_id: str,
    entity_type: str,
    name: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical_name = canonical_product(name) if entity_type == "product" else normalize_query_text(name)
    return {
        "entity_id": graph_entity_id(space_id, entity_type, canonical_name),
        "space_id": space_id,
        "canonical_name": canonical_name,
        "entity_type": entity_type,
        "normalized_key": graph_entity_key(entity_type, canonical_name),
        "alias": name,
        "metadata": metadata or {},
    }


def _target_for_document(document: dict[str, Any], event: dict[str, Any]) -> tuple[str, str, str, bool]:
    source_type = str(document.get("source_type") or "")
    dimension = str(document.get("dimension") or "general").casefold()
    title = normalize_query_text(str(document.get("title") or event.get("title") or "Knowledge signal"))
    statement = str(event.get("statement") or "")
    combined = f"{title} {statement}"
    if source_type == "analysis_report":
        return "report", title, "summarized_in", False
    if dimension == "pricing":
        match = _PRICE.search(combined)
        return "price", match.group(0) if match else title, "priced_at", True
    if dimension == "technology":
        integration = next((name for name, pattern in _INTEGRATIONS if pattern.search(combined)), None)
        if integration:
            return "integration", integration, "integrates_with", True
        return "capability", title, "uses_capability", True
    if dimension == "features":
        return "capability", title, "provides", True
    if dimension == "users":
        return "audience", title, "targets", True
    if dimension == "market":
        return "market_event", title, "participates_in", True
    return "topic", title, "associated_with", True


def build_relation_candidates(
    document: dict[str, Any],
    *,
    event: dict[str, Any],
    chunk: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Build deterministic, evidence-backed graph entities and relations."""
    space_id = str(document.get("space_id") or "")
    product_name = canonical_product(str(document.get("product") or "General market"))
    product = _entity(space_id, "product", product_name)
    target_type, target_name, relation_type, citation_eligible = _target_for_document(document, event)
    metadata = dict(document.get("metadata") or {})
    lineage = metadata.get("lineage") or {}
    target = _entity(
        space_id,
        target_type,
        target_name,
        metadata={
            "document_id": document.get("document_id"),
            "report_thread_id": lineage.get("thread_id") if target_type == "report" else None,
        },
    )
    # Event clusters retain their first occurrence. Relationship versions own
    # the current document version's validity interval instead.
    occurred_at = document.get("published_at") or document.get("observed_at") or chunk.get("created_at") or event.get("occurred_at")
    relations = [
        _relation(
            space_id,
            product,
            target,
            relation_type,
            str(document.get("dimension") or "general"),
            str(event.get("statement") or ""),
            occurred_at,
            float(event.get("confidence") or 0.5),
            citation_eligible=citation_eligible,
            metadata={
                "event_id": event.get("event_id"),
                "generation": "deterministic_relation_builder",
                "usage_policy": ("citable_when_evidence_is_in_context" if citation_eligible else "planning_only_not_factual_evidence"),
                "report_thread_id": lineage.get("thread_id") if target_type == "report" else None,
            },
        )
    ]
    entities = [product, target]

    original_url = str(metadata.get("original_source_url") or document.get("source_uri") or "")
    parsed = urlparse(original_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        source = _entity(space_id, "source", parsed.netloc.casefold())
        entities.append(source)
        relations.append(
            _relation(
                space_id,
                product,
                source,
                "documented_by",
                str(document.get("dimension") or "general"),
                f"{product_name} evidence is documented by {parsed.netloc.casefold()}.",
                occurred_at,
                float(event.get("confidence") or 0.5),
                citation_eligible=True,
                metadata={
                    "event_id": event.get("event_id"),
                    "generation": "deterministic_relation_builder",
                    "source_uri": original_url,
                    "usage_policy": "provenance_relation",
                },
            )
        )
    return {"entities": entities, "relations": relations}


def _relation(
    space_id: str,
    source: dict[str, Any],
    target: dict[str, Any],
    relation_type: str,
    dimension: str,
    statement: str,
    valid_from: str | None,
    confidence: float,
    *,
    citation_eligible: bool,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    cluster_key = relation_cluster_key(
        space_id,
        source["entity_id"],
        target["entity_id"],
        relation_type,
        dimension,
        str(valid_from or "")[:7] if relation_type == "priced_at" else "",
    )
    return {
        "relation_id": relation_id(cluster_key),
        "space_id": space_id,
        "source_entity_id": source["entity_id"],
        "target_entity_id": target["entity_id"],
        "relation_type": relation_type,
        "dimension": dimension,
        "statement": normalize_query_text(statement)[:1600],
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "valid_from": valid_from,
        "cluster_key": cluster_key,
        "citation_eligible": citation_eligible,
        "metadata": metadata,
    }


@dataclass(frozen=True)
class GraphRetrievalPlan:
    use_graph: bool
    route: str
    reasons: tuple[str, ...]
    max_hops: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "use_graph": self.use_graph,
            "route": self.route,
            "reasons": list(self.reasons),
            "max_hops": self.max_hops,
        }


def plan_graph_retrieval(state: dict[str, Any]) -> GraphRetrievalPlan:
    brief = state.get("analysis_brief") or {}
    query = normalize_query_text(str(state.get("user_request") or brief.get("objective") or ""))
    lowered = query.casefold()
    products = state.get("target_products") or brief.get("target_products") or []
    reasons: list[str] = []
    if len(products) > 1:
        reasons.append("multiple_products")
    if any(marker in lowered for marker in _RELATION_MARKERS):
        reasons.append("relationship_intent")
    if any(marker in lowered for marker in _TEMPORAL_MARKERS):
        reasons.append("temporal_relationship_intent")
    use_graph = bool(reasons)
    return GraphRetrievalPlan(
        use_graph=use_graph,
        route="hybrid_graph" if use_graph else "vector_only",
        reasons=tuple(reasons or ["focused_fact_lookup"]),
        max_hops=2 if "relationship_intent" in reasons or len(products) > 1 else 1,
    )


def graph_tokens(value: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN.finditer(value)}
