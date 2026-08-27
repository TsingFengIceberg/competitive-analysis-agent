"""Deterministic query planning for local competitive-intelligence retrieval."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from competition.knowledge_types import RetrievalFilters

_SPACE = re.compile(r"\s+")

_PRODUCT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Claude Code", ("claude code", "claude-code", "anthropic claude code")),
    ("OpenAI Codex", ("openai codex", "codex", "codex cli", "codex-cli")),
    ("GitHub Copilot", ("github copilot", "copilot", "github-copilot")),
    ("Cursor", ("cursor", "cursor editor", "cursor ide")),
    ("Windsurf", ("windsurf", "codeium windsurf", "windsurf editor")),
)

_DIMENSION_GROUPS: dict[str, tuple[str, ...]] = {
    "features": ("features", "feature", "功能", "功能与体验", "capabilities", "user experience"),
    "pricing": ("pricing", "price", "定价", "定价与商业模式", "cost", "commercial model"),
    "users": ("users", "用户", "用户与场景", "使用场景", "adoption", "use cases"),
    "market": ("market", "市场", "市场与竞争", "competition", "competitive landscape"),
    "technology": ("technology", "技术", "技术与集成", "integration", "architecture"),
}


def normalize_query_text(value: str) -> str:
    """Normalize user text without changing its semantic content."""
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", value or "")).strip()


def _key(value: str) -> str:
    return normalize_query_text(value).casefold()


_PRODUCT_LOOKUP = {_key(alias): canonical for canonical, aliases in _PRODUCT_GROUPS for alias in (canonical, *aliases)}
_DIMENSION_LOOKUP = {_key(alias): canonical for canonical, aliases in _DIMENSION_GROUPS.items() for alias in (canonical, *aliases)}


def canonical_product(value: str) -> str:
    normalized = normalize_query_text(value)
    return _PRODUCT_LOOKUP.get(normalized.casefold(), normalized)


def canonical_dimension(value: str) -> str:
    normalized = normalize_query_text(value)
    return _DIMENSION_LOOKUP.get(normalized.casefold(), normalized)


def expand_product_aliases(value: str) -> tuple[str, ...]:
    """Return filter values that match common names for the same product."""
    canonical = canonical_product(value)
    aliases = next(
        ((canonical_name, *values) for canonical_name, values in _PRODUCT_GROUPS if canonical_name == canonical),
        (canonical,),
    )
    return _unique(aliases)


def expand_dimension_aliases(value: str) -> tuple[str, ...]:
    canonical = canonical_dimension(value)
    return _unique((canonical, *_DIMENSION_GROUPS.get(canonical, ())))


def _unique(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_query_text(value)
        identity = normalized.casefold()
        if normalized and identity not in seen:
            seen.add(identity)
            result.append(normalized)
    return tuple(result)


def rewrite_retrieval_query(base_query: str, product: str, dimension: str) -> str:
    """Add stable bilingual product and dimension context to a retrieval query."""
    parts = [normalize_query_text(base_query)]
    canonical_name = canonical_product(product)
    if canonical_name and _key(canonical_name) not in _key(parts[0]):
        parts.append(canonical_name)
    canonical_dim = canonical_dimension(dimension)
    dimension_terms = _DIMENSION_GROUPS.get(canonical_dim, (canonical_dim,))
    if dimension_terms:
        parts.append(" ".join(dimension_terms[:4]))
    return normalize_query_text(" ".join(part for part in parts if part))


@dataclass(frozen=True)
class AnalysisRetrievalQuery:
    query: str
    product: str
    dimension: str
    filters: RetrievalFilters


@dataclass(frozen=True)
class RetrievalStep:
    step_id: str
    query: str
    purpose: str
    hop: int = 1
    depends_on: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "query": self.query,
            "purpose": self.purpose,
            "hop": self.hop,
            "depends_on": list(self.depends_on),
        }


@dataclass(frozen=True)
class RetrievalPlan:
    route: str
    normalized_query: str
    steps: tuple[RetrievalStep, ...]
    reasons: tuple[str, ...] = ()
    estimated_cost: str = "low"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "normalized_query": self.normalized_query,
            "steps": [step.to_dict() for step in self.steps],
            "reasons": list(self.reasons),
            "estimated_cost": self.estimated_cost,
            "metadata": self.metadata,
        }


_COMPLEX_MARKERS = (
    "compare",
    "comparison",
    "versus",
    " vs ",
    "why",
    "how has",
    "trend",
    "difference",
    "relationship",
    "impact",
    "before and after",
    "比较",
    "对比",
    "为什么",
    "原因",
    "趋势",
    "变化",
    "影响",
    "关系",
    "演进",
    "先后",
)
_TEMPORAL_MARKERS = (
    "trend",
    "change",
    "changed",
    "history",
    "historical",
    "timeline",
    "over time",
    "before and after",
    "past month",
    "past quarter",
    "past year",
    "趋势",
    "变化",
    "历史",
    "时间线",
    "演进",
    "过去",
    "近一个月",
    "近半年",
    "近一年",
    "最近一次",
    "首次出现",
)
_CLAUSE_SPLIT = re.compile(r"\s*(?:，|；|;|以及|并且|同时|相比于|versus|\bvs\.?\b|\band\b)\s*", re.IGNORECASE)


def plan_retrieval_query(
    query: str,
    filters: RetrievalFilters | None = None,
    *,
    max_steps: int = 6,
) -> RetrievalPlan:
    """Route simple lookups cheaply and decompose comparative/causal requests."""
    scoped = filters or RetrievalFilters()
    normalized = normalize_query_text(query)
    lowered = f" {normalized.casefold()} "
    clauses = _unique([part for part in _CLAUSE_SPLIT.split(normalized) if len(part.strip()) >= 4])
    complex_reasons: list[str] = []
    if any(marker in lowered for marker in _COMPLEX_MARKERS):
        complex_reasons.append("query_contains_comparison_temporal_or_causal_language")
    if len(scoped.products) > 1:
        complex_reasons.append("multiple_products")
    if len(scoped.dimensions) > 1:
        complex_reasons.append("multiple_dimensions")
    if len(clauses) >= 3:
        complex_reasons.append("multiple_semantic_clauses")
    route = "multi_hop" if complex_reasons else "direct"
    if route == "direct":
        return RetrievalPlan(
            route=route,
            normalized_query=normalized,
            steps=(RetrievalStep("q1", normalized, "direct_lookup"),),
            reasons=("single_focused_information_need",),
        )

    variants: list[tuple[str, str]] = [(normalized, "original_intent")]
    for clause in clauses[:3]:
        variants.append((clause, "subquestion"))
    for product in scoped.products[:4]:
        for dimension in scoped.dimensions[:4] or ("",):
            variants.append((rewrite_retrieval_query(normalized, product, dimension), "scoped_rewrite"))
    if any(marker in lowered for marker in _TEMPORAL_MARKERS):
        variants.append((f"{normalized} timeline previous current evidence", "temporal_subquestion"))
    unique_variants: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value, purpose in variants:
        key = _key(value)
        if value and key not in seen:
            seen.add(key)
            unique_variants.append((value, purpose))
    steps = [RetrievalStep(f"q{index + 1}", value, purpose) for index, (value, purpose) in enumerate(unique_variants[: max_steps - 1])]
    steps.append(
        RetrievalStep(
            f"q{len(steps) + 1}",
            normalized,
            "bridge_from_first_hop_evidence",
            hop=2,
            depends_on=tuple(step.step_id for step in steps),
        )
    )
    return RetrievalPlan(
        route=route,
        normalized_query=normalized,
        steps=tuple(steps),
        reasons=tuple(complex_reasons),
        estimated_cost="medium",
        metadata={"max_steps": max_steps, "llm_calls": 0},
    )


def build_bridge_query(plan: RetrievalPlan, first_hop: list[Any]) -> str:
    """Use first-hop entity and dimension signals for a bounded second hop."""
    products = _unique([str(getattr(hit, "product", "")) for hit in first_hop])[:3]
    dimensions = _unique([str(getattr(hit, "dimension", "")) for hit in first_hop])[:3]
    suffix = " ".join([*products, *dimensions, "cross-source evidence relationship"])
    return normalize_query_text(f"{plan.normalized_query} {suffix}")


def build_analysis_queries(state: dict[str, Any], *, max_queries: int = 20) -> list[AnalysisRetrievalQuery]:
    """Build deduplicated product/dimension retrieval queries from graph state."""
    brief = state.get("analysis_brief") or {}
    raw_products = state.get("target_products") or brief.get("target_products") or []
    products = _unique([canonical_product(str(value)) for value in raw_products])
    selected_dimensions = brief.get("effective_dimensions") or brief.get("dimensions") or []
    raw_dimensions = [str(item.get("id")) for item in selected_dimensions if isinstance(item, dict) and item.get("id")]
    dimensions = _unique([canonical_dimension(value) for value in raw_dimensions] or ["features", "pricing", "users", "market", "technology"])
    time_range = brief.get("time_range") if isinstance(brief.get("time_range"), dict) else {}
    base_query = str(state.get("user_request") or brief.get("objective") or "competitive intelligence")
    temporal_context = " ".join(
        str(value)
        for value in (
            base_query,
            brief.get("objective") or "",
            brief.get("output_focus") or "",
        )
    ).casefold()
    temporal_mode = "all" if any(marker in temporal_context for marker in _TEMPORAL_MARKERS) else "current"
    pairs = [(product, dimension) for product in products for dimension in dimensions]
    if not pairs:
        pairs = [("", dimension) for dimension in dimensions]
    queries: list[AnalysisRetrievalQuery] = []
    seen: set[tuple[str, str]] = set()
    for product, dimension in pairs:
        identity = (_key(product), _key(dimension))
        if identity in seen:
            continue
        seen.add(identity)
        queries.append(
            AnalysisRetrievalQuery(
                query=rewrite_retrieval_query(base_query, product, dimension),
                product=product,
                dimension=dimension,
                filters=RetrievalFilters(
                    products=expand_product_aliases(product) if product else (),
                    dimensions=expand_dimension_aliases(dimension),
                    market_scope=str(brief.get("market_scope") or ""),
                    published_after=time_range.get("start"),
                    published_before=time_range.get("end"),
                    include_reports=False,
                    temporal_mode=temporal_mode,
                ),
            )
        )
        if len(queries) >= max_queries:
            break
    return queries
