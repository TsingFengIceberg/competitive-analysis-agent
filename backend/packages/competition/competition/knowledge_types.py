"""Shared contracts for the local competitive-intelligence knowledge base."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AUTHORITY_PRIORS: dict[str, float] = {
    "primary": 0.95,
    "structured_fact": 0.90,
    "change_event": 0.82,
    "third_party": 0.65,
    "report": 0.40,
}


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    section_path: str = ""
    page_no: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    markdown: str
    blocks: list[ParsedBlock]
    media_type: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    document_id: str
    version_no: int
    user_id: str
    ordinal: int
    text: str
    contextual_text: str
    section_path: str
    page_no: int | None
    token_count: int
    qdrant_point_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalFilters:
    products: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    market_scope: str = ""
    source_types: tuple[str, ...] = ()
    authority_tiers: tuple[str, ...] = ()
    published_after: str | None = None
    published_before: str | None = None
    include_reports: bool = False
    temporal_mode: str = "current"
    as_of: str | None = None
    space_ids: tuple[str, ...] = ()
    retrieval_mode: str = "hybrid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "products": list(self.products),
            "dimensions": list(self.dimensions),
            "market_scope": self.market_scope,
            "source_types": list(self.source_types),
            "authority_tiers": list(self.authority_tiers),
            "published_after": self.published_after,
            "published_before": self.published_before,
            "include_reports": self.include_reports,
            "temporal_mode": self.temporal_mode,
            "as_of": self.as_of,
            "space_ids": list(self.space_ids),
            "retrieval_mode": self.retrieval_mode,
        }


@dataclass(frozen=True)
class KnowledgeHit:
    chunk_id: str
    document_id: str
    version_no: int
    title: str
    text: str
    contextual_text: str
    source_uri: str
    source_type: str
    authority_tier: str
    product: str
    dimension: str
    market_scope: str
    section_path: str
    page_no: int | None
    published_at: str | None
    observed_at: str | None
    valid_from: str | None
    valid_to: str | None
    temporal_status: str
    score: float
    retrieval_sources: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def confidence(self) -> float:
        authority = AUTHORITY_PRIORS.get(self.authority_tier, 0.5)
        return round(max(0.0, min(1.0, 0.55 * self.score + 0.45 * authority)), 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "version_no": self.version_no,
            "title": self.title,
            "text": self.text,
            "contextual_text": self.contextual_text,
            "source_uri": self.source_uri,
            "source_type": self.source_type,
            "authority_tier": self.authority_tier,
            "product": self.product,
            "dimension": self.dimension,
            "market_scope": self.market_scope,
            "section_path": self.section_path,
            "page_no": self.page_no,
            "published_at": self.published_at,
            "observed_at": self.observed_at,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "temporal_status": self.temporal_status,
            "score": self.score,
            "confidence": self.confidence,
            "retrieval_sources": list(self.retrieval_sources),
            "metadata": self.metadata,
        }
