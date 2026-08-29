"""Deterministic retrieval strategy contracts and score explanations.

The Qdrant adapter performs the actual vector queries.  This module keeps the
strategy vocabulary and score semantics independent from that adapter so API,
evaluation, and future remote indexes can share one contract.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from competition.knowledge_types import RetrievalFilters

RETRIEVAL_MODES = {"hybrid", "dense", "sparse"}
RANKING_PROFILES = {"balanced", "freshness", "authority"}


@dataclass(frozen=True)
class QueryClassification:
    """Deterministic intent classification used to choose retrieval cost."""

    intent: str
    complexity: str
    needs_graph: bool
    needs_freshness: bool
    needs_multi_hop: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "complexity": self.complexity,
            "needs_graph": self.needs_graph,
            "needs_freshness": self.needs_freshness,
            "needs_multi_hop": self.needs_multi_hop,
            "reasons": list(self.reasons),
        }


_COMPARISON_TERMS = ("compare", "comparison", "versus", " vs ", "对比", "比较", "差异")
_TEMPORAL_TERMS = ("latest", "current", "trend", "history", "timeline", "最新", "当前", "趋势", "历史", "时间线")
_RELATION_TERMS = ("relationship", "integrate", "compatible", "alternative", "关系", "集成", "兼容", "替代")
_FACT_TERMS = ("what", "which", "how much", "price", "是什么", "多少", "价格", "功能")


def classify_query(query: str, filters: RetrievalFilters | None = None) -> QueryClassification:
    """Classify a retrieval request without an additional LLM call."""
    lowered = f" {(query or '').casefold()} "
    scope = filters or RetrievalFilters()
    reasons: list[str] = []
    comparison = len(scope.products) > 1 or any(term in lowered for term in _COMPARISON_TERMS)
    temporal = scope.temporal_mode != "current" or any(term in lowered for term in _TEMPORAL_TERMS)
    relation = any(term in lowered for term in _RELATION_TERMS)
    fact = any(term in lowered for term in _FACT_TERMS)
    if comparison:
        reasons.append("comparison_intent")
    if temporal:
        reasons.append("temporal_intent")
    if relation:
        reasons.append("relationship_intent")
    if len(scope.dimensions) > 1:
        reasons.append("multiple_dimensions")
    if relation or temporal:
        intent = "relationship" if relation else "temporal"
    elif comparison:
        intent = "comparison"
    elif fact:
        intent = "fact"
    else:
        intent = "exploration"
    complexity = "high" if relation or (comparison and temporal) else "medium" if comparison or temporal or len(scope.dimensions) > 1 else "low"
    return QueryClassification(
        intent=intent,
        complexity=complexity,
        needs_graph=relation or comparison,
        needs_freshness=temporal,
        needs_multi_hop=relation or comparison or temporal,
        reasons=tuple(reasons or ["general_exploration"]),
    )


def adaptive_strategy(
    query: str,
    filters: RetrievalFilters | None = None,
    *,
    preferred_mode: str | None = None,
    preferred_profile: str | None = None,
) -> RetrievalStrategy:
    """Choose a bounded retrieval strategy from query intent and explicit preferences."""
    classification = classify_query(query, filters)
    mode = preferred_mode if preferred_mode in RETRIEVAL_MODES else "hybrid"
    profile = preferred_profile if preferred_profile in RANKING_PROFILES else "balanced"
    if classification.needs_freshness and profile == "balanced":
        profile = "freshness"
    if classification.intent == "fact" and preferred_mode is None:
        mode = "sparse"
    return RetrievalStrategy(
        mode=mode,
        ranking_profile=profile,
        candidate_limit=64 if classification.complexity == "high" else 40,
        rerank=classification.complexity != "low",
        dense_weight=0.58 if classification.intent in {"comparison", "relationship"} else 0.5,
        sparse_weight=0.42 if classification.intent in {"comparison", "relationship"} else 0.5,
    ).normalized()


def feedback_adjustment(
    *,
    relevant: int = 0,
    not_relevant: int = 0,
    citation_used: int = 0,
) -> float:
    """Return a bounded user-feedback prior for one chunk."""
    positive = min(8, max(0, int(relevant))) + 0.5 * min(8, max(0, int(citation_used)))
    negative = min(8, max(0, int(not_relevant)))
    return round(max(-0.12, min(0.12, 0.018 * positive - 0.025 * negative)), 6)


@dataclass(frozen=True)
class RetrievalStrategy:
    mode: str = "hybrid"
    ranking_profile: str = "balanced"
    candidate_limit: int = 40
    rerank: bool = True
    dense_weight: float = 0.5
    sparse_weight: float = 0.5

    def normalized(self) -> RetrievalStrategy:
        mode = self.mode if self.mode in RETRIEVAL_MODES else "hybrid"
        profile = self.ranking_profile if self.ranking_profile in RANKING_PROFILES else "balanced"
        candidate_limit = max(1, min(int(self.candidate_limit), 200))
        dense = max(0.0, float(self.dense_weight))
        sparse = max(0.0, float(self.sparse_weight))
        if mode == "dense":
            dense, sparse = 1.0, 0.0
        elif mode == "sparse":
            dense, sparse = 0.0, 1.0
        elif dense + sparse == 0:
            dense, sparse = 0.5, 0.5
        else:
            total = dense + sparse
            dense, sparse = dense / total, sparse / total
        return RetrievalStrategy(mode, profile, candidate_limit, bool(self.rerank), dense, sparse)

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "mode": normalized.mode,
            "ranking_profile": normalized.ranking_profile,
            "candidate_limit": normalized.candidate_limit,
            "rerank": normalized.rerank,
            "dense_weight": round(normalized.dense_weight, 4),
            "sparse_weight": round(normalized.sparse_weight, 4),
        }


def reciprocal_rank_fusion(
    ranked_lists: dict[str, Iterable[str]],
    *,
    weights: dict[str, float] | None = None,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse independent dense/sparse result IDs with weighted RRF.

    This pure helper is used by evaluation and fallback adapters.  Qdrant's
    native RRF remains the fast path, while the returned scores are normalized
    to ``[0, 1]`` for the public hit contract.
    """
    scores: dict[str, float] = {}
    source_weights = weights or {}
    for source, values in ranked_lists.items():
        weight = max(0.0, float(source_weights.get(source, 1.0)))
        for rank, item_id in enumerate(values, start=1):
            key = str(item_id)
            if key:
                scores[key] = scores.get(key, 0.0) + weight / (k + rank)
    if not scores:
        return []
    maximum = max(scores.values())
    return sorted(
        ((item_id, round(score / maximum, 6) if maximum else 0.0) for item_id, score in scores.items()),
        key=lambda item: (-item[1], item[0]),
    )


def explain_retrieval(
    *,
    strategy: RetrievalStrategy,
    recall_score: float,
    rerank_score: float | None,
    authority_score: float,
    freshness_score: float,
) -> dict[str, Any]:
    """Return a bounded, non-sensitive explanation for one hit."""
    config = strategy.normalized()
    return {
        "mode": config.mode,
        "ranking_profile": config.ranking_profile,
        "dense_weight": config.dense_weight,
        "sparse_weight": config.sparse_weight,
        "recall_score": round(max(0.0, min(1.0, recall_score)), 6),
        "rerank_score": round(max(0.0, min(1.0, rerank_score if rerank_score is not None else 0.0)), 6),
        "authority_score": round(max(0.0, min(1.0, authority_score)), 6),
        "freshness_score": round(max(0.0, min(1.0, freshness_score)), 6),
        "reranked": bool(config.rerank and rerank_score is not None),
    }
