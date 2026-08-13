"""Low-cost, deterministic pre-analysis Brief builder (P1.1).

This module deliberately performs no web search. It normalizes explicit input,
uses conservative text extraction, and optionally asks one bounded structured
model call only when the request does not provide enough candidate information.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from competition.schema import (
    BRIEF_DIMENSION_LABELS,
    AnalysisBrief,
    BriefAmbiguity,
    BriefDimension,
    BriefTimeRange,
)

CONFIRMATION_MODES = ("auto", "always", "skip")
logger = logging.getLogger(__name__)
OPEN_ENDED_TERMS = (
    "最好",
    "主流",
    "头部",
    "类似产品",
    "有哪些",
    "top tools",
    "best tools",
    "leading tools",
    "which tools",
    "推荐几个",
)
CONFIRM_TERMS = ("先确认", "先让我确认", "不要直接开始", "confirm first", "review first")
BYPASS_TERMS = ("直接开始", "不用确认", "跳过确认", "start immediately", "skip confirmation")
PRODUCT_SPLIT_RE = re.compile(r"\s*(?:,|，|、|\s+vs\s+|\s+VS\s+|\s+和\s+|\s+与\s+|\s+and\s+)\s*", re.I)


class BriefExtraction(BaseModel):
    """Strict, small schema accepted from the optional BriefBuilder model."""

    model_config = ConfigDict(extra="ignore")

    target_products: list[str] = Field(default_factory=list, max_length=10)
    objective: str = Field(default="", max_length=500)
    market_scope: str = Field(default="", max_length=120)
    audience: str = ""
    dimensions: list[str] = Field(default_factory=list, max_length=5)
    complexity: str = ""
    output_focus: list[str] = Field(default_factory=list, max_length=8)


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalize_products(products: list[str] | None) -> list[str]:
    """Trim, split accidental delimiter-packed values, and deduplicate."""
    result: list[str] = []
    seen: set[str] = set()
    for raw in products or []:
        for candidate in PRODUCT_SPLIT_RE.split(str(raw).strip()):
            candidate = _clean_text(candidate, 80)
            if not candidate:
                continue
            key = candidate.casefold()
            if key not in seen:
                seen.add(key)
                result.append(candidate)
    return result[:10]


def extract_explicit_products(query: str) -> list[str]:
    """Extract likely named products without network access.

    The heuristic is intentionally conservative: quoted names, `A vs B`, and
    common comparison delimiters are accepted; generic nouns are not invented.
    """
    text = _clean_text(query, 2000)
    quoted = re.findall(r"[\"“‘']([^\"”’']{1,80})[\"”’']", text)
    if len(quoted) >= 2:
        return normalize_products(quoted)
    match = re.search(
        r"(.{1,100}?)\s+(?:vs\.?|versus|对比|比较|区别于|和|与)\s+(.{1,100}?)(?:[，。,.!?！？]|$)",
        text,
        flags=re.I,
    )
    if match:
        left = re.sub(r"^(?:比较|对比|分析|请)\s*", "", match.group(1)).strip()
        right = re.sub(r"(?:哪个好|哪个更好|进行比较|对比分析)\s*$", "", match.group(2)).strip()
        left = re.sub(r"^(?:深度|全面|详细)?\s*(?:比较|对比|分析)?\s*", "", left).strip()
        right = re.split(r"\s*(?:的|，|,|。|！|!|？|\?)\s*", right, maxsplit=1)[0].strip()
        candidates = normalize_products([left, right])
        if len(candidates) >= 2 and all(len(item) <= 80 for item in candidates):
            return candidates
    return []


def detect_confirmation_mode(query: str, requested: str = "auto") -> Literal["auto", "always", "skip"]:
    if requested not in CONFIRMATION_MODES:
        requested = "auto"
    if requested != "auto":
        return requested  # explicit API field wins
    text = query.casefold()
    has_confirm = any(term.casefold() in text for term in CONFIRM_TERMS)
    has_bypass = any(term.casefold() in text for term in BYPASS_TERMS)
    if has_confirm:
        return "always"  # safer when phrases conflict
    if has_bypass:
        return "skip"
    return "auto"


def _default_dimensions(query: str, complexity: str) -> list[BriefDimension]:
    selected = ["features", "pricing", "users", "market"]
    if complexity == "quick":
        selected = ["features", "pricing"]
    elif any(term in query.casefold() for term in ("技术", "架构", "integration", "api", "技术栈")):
        selected.append("technology")
    weight = round(1.0 / len(selected), 4)
    dims = [BriefDimension(id=item, label=BRIEF_DIMENSION_LABELS[item], weight=weight) for item in selected]
    dims[-1].weight = round(1.0 - sum(item.weight for item in dims[:-1]), 4)
    return dims


def _complexity(query: str, products: list[str]) -> str:
    text = query.casefold()
    deep_terms = ("深度", "全面", "预测", "战略", "市场格局", "详细", "deep", "forecast", "strategic")
    if len(products) >= 5 or len(query) > 200 or sum(term in text for term in deep_terms) >= 2:
        return "deep"
    if len(products) >= 3 or len(query) > 80 or any(term in text for term in deep_terms):
        return "standard"
    return "quick" if len(products) >= 2 and any(term in text for term in ("对比", "比较", "vs", "compare")) else "standard"


def _time_range() -> BriefTimeRange:
    now = datetime.now(UTC)
    start = (now - timedelta(days=365)).date().isoformat()
    end = now.date().isoformat()
    return BriefTimeRange(mode="last_12_months", label="最近12个月", start=start, end=end)


def _objective(query: str, products: list[str]) -> str:
    explicit = _clean_text(query, 500)
    if explicit:
        return explicit
    return f"比较 {', '.join(products)} 的关键差异并形成可执行建议" if products else "竞品分析"


def _ambiguous(products: list[str], query: str, confidence: float) -> list[BriefAmbiguity]:
    result: list[BriefAmbiguity] = []
    open_ended = any(term in query.casefold() for term in OPEN_ENDED_TERMS)
    if len(products) < 2:
        result.append(BriefAmbiguity(field="target_products", question="请确认要比较的至少两个具体产品。", required=True))
    elif open_ended:
        result.append(BriefAmbiguity(field="target_products", question="这是开放式选品，请确认具体竞品名单。", required=True))
    if confidence < 0.7:
        result.append(BriefAmbiguity(field="objective", question="请确认本次比较要支持的具体决策目标。", required=True))
    return result[:8]


def canonical_editable_payload(brief: AnalysisBrief) -> str:
    """Stable JSON used by DB idempotency and race handling."""
    return json.dumps(brief.editable_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_brief(
    query: str,
    target_products: list[str] | None = None,
    industry: str = "general",
    persona: str = "pm",
    extracted: BriefExtraction | dict | None = None,
    editable: AnalysisBrief | dict | None = None,
) -> AnalysisBrief:
    """Build a server-owned Brief from request or client-edited fields."""
    if editable is not None:
        raw = editable if isinstance(editable, AnalysisBrief) else AnalysisBrief.model_validate(editable)
        products = normalize_products(raw.target_products)
        dimensions: list[BriefDimension] = []
        for item in raw.dimensions:
            dimensions.append(BriefDimension(id=item.id, label=BRIEF_DIMENSION_LABELS[item.id], weight=item.weight))
        if dimensions:
            total = sum(item.weight for item in dimensions)
            for item in dimensions:
                item.weight = round(item.weight / total, 4)
            dimensions[-1].weight = round(1 - sum(item.weight for item in dimensions[:-1]), 4)
        return raw.model_copy(
            update={
                "revision": raw.revision,
                "target_products": products,
                "objective": _clean_text(raw.objective, 500) or "竞品分析",
                "market_scope": _clean_text(raw.market_scope, 120) or "Global / unspecified",
                "dimensions": dimensions,
                "output_focus": list(dict.fromkeys(_clean_text(item, 120) for item in raw.output_focus if _clean_text(item, 120)))[:8],
                "assumptions": [],
                "inferred_fields": [],
                "confirmation_source": None,
                "confirmed_at": None,
                "readiness": "ready" if len(products) >= 2 and bool(dimensions) else "needs_confirmation",
                "ambiguities": [],
                "confidence": 1.0,
            }
        )

    extracted_model = extracted if isinstance(extracted, BriefExtraction) else BriefExtraction.model_validate(extracted or {})
    products = normalize_products(target_products) or normalize_products(extracted_model.target_products) or extract_explicit_products(query)
    complexity = extracted_model.complexity if extracted_model.complexity in ("quick", "standard", "deep") else _complexity(query, products)
    dimensions = _default_dimensions(query, complexity)
    if extracted_model.dimensions:
        known = [item for item in extracted_model.dimensions if item in BRIEF_DIMENSION_LABELS]
        if known:
            weight = round(1 / len(known), 4)
            dimensions = [BriefDimension(id=item, label=BRIEF_DIMENSION_LABELS[item], weight=weight) for item in known]
            dimensions[-1].weight = round(1 - sum(item.weight for item in dimensions[:-1]), 4)
    confidence = 1.0
    if not target_products and not products:
        confidence -= 0.25
    if not target_products and products:
        confidence -= 0.25
    if not _clean_text(query, 500):
        confidence -= 0.15
    explicit_in_query = extract_explicit_products(query)
    open_ended = any(term in query.casefold() for term in OPEN_ENDED_TERMS) and not target_products and not explicit_in_query
    if open_ended:
        confidence -= 0.20
    confidence = max(0.0, min(1.0, confidence))
    ambiguities = _ambiguous(products, query, confidence)
    if open_ended and not ambiguities:
        ambiguities = [BriefAmbiguity(field="target_products", question="请确认具体竞品名单。", required=True)]
    return AnalysisBrief(
        objective=_clean_text(extracted_model.objective, 500) or _objective(query, products),
        target_products=products,
        audience=("executive" if persona == "entrepreneur" else "product"),
        market_scope=_clean_text(extracted_model.market_scope, 120) or "Global / unspecified",
        time_range=_time_range(),
        dimensions=dimensions,
        complexity=complexity,
        evidence_policy="official_preferred",
        output_focus=list(dict.fromkeys(extracted_model.output_focus or ["关键差异", "可执行建议"]))[:8],
        assumptions=["未指定市场时使用 Global / unspecified", "未指定时间时使用最近12个月"],
        inferred_fields=["market_scope", "time_range"],
        readiness="ready" if len(products) >= 2 and not ambiguities and confidence >= 0.7 else "needs_confirmation",
        ambiguities=ambiguities,
        confidence=confidence,
    )


def validate_confirmation_brief(brief: AnalysisBrief | dict) -> AnalysisBrief:
    """Apply confirmation-only validation and server metadata."""
    if not isinstance(brief, AnalysisBrief):
        brief = AnalysisBrief.model_validate(brief)
    dimension_ids = [item.id for item in brief.dimensions]
    if len(dimension_ids) != len(set(dimension_ids)):
        raise ValueError("分析维度不能重复")
    if brief.time_range.mode == "custom":
        if not brief.time_range.start or not brief.time_range.end:
            raise ValueError("自定义时间范围必须提供开始和结束日期")
        try:
            if date.fromisoformat(brief.time_range.start) > date.fromisoformat(brief.time_range.end):
                raise ValueError("自定义时间范围的开始日期不能晚于结束日期")
        except ValueError as exc:
            if "不能晚于" in str(exc):
                raise
            raise ValueError("自定义时间范围必须使用有效的 ISO 日期") from exc
    normalized = normalize_brief(brief.objective, editable=brief)
    if len(normalized.target_products) < 2:
        raise ValueError("至少需要两个具体竞品")
    if not normalized.dimensions:
        raise ValueError("至少选择一个分析维度")
    normalized = normalized.model_copy(
        update={
            "readiness": "ready",
            "confidence": 1.0,
            "ambiguities": [],
            "confirmation_source": "user",
            "confirmed_at": datetime.now(UTC).isoformat(),
            "revision": brief.revision + 1,
        }
    )
    return normalized


def brief_from_request(
    query: str,
    target_products: list[str] | None = None,
    industry: str = "general",
    persona: str = "pm",
    model_output: dict | None = None,
) -> AnalysisBrief:
    """Public builder entry point; invalid optional model output degrades safely."""
    extracted: BriefExtraction | None = None
    if model_output:
        try:
            extracted = BriefExtraction.model_validate(model_output)
        except ValidationError:
            extracted = None
    return normalize_brief(query, target_products, industry, persona, extracted=extracted)


def brief_from_request_with_optional_model(
    query: str,
    target_products: list[str] | None = None,
    industry: str = "general",
    persona: str = "pm",
) -> AnalysisBrief:
    """Build a Brief and make at most one bounded extraction call when needed.

    Explicit product input and deterministic two-product comparisons never call
    a model. For ambiguous, product-free requests the model may suggest names,
    but readiness remains conservative and still requires confirmation.
    """
    deterministic = brief_from_request(query, target_products, industry, persona)
    if target_products or len(deterministic.target_products) >= 2:
        return deterministic

    try:
        from pathlib import Path

        from competition.executor import execute_structured_agent

        prompt_path = Path(__file__).parent / "prompts" / "brief_builder.md"
        system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ("Extract only concrete products and scope as one JSON object.")
        output, _tokens = execute_structured_agent(
            system_prompt,
            query,
            agent_name="BriefBuilder",
            disable_thinking=True,
            timeout_seconds=30,
            max_retries=0,
            temperature=0.0,
            max_tokens=700,
        )
        if isinstance(output, dict):
            return brief_from_request(query, target_products, industry, persona, model_output=output)
    except Exception:
        logger.warning("Optional BriefBuilder call failed; using deterministic draft", exc_info=True)
    return deterministic
