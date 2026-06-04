"""Pydantic schemas for the CI-Agent competitive intelligence system.

Three-layer schema design per COMPETITION_PLAN.md §3.10:

Layer 1 — 竞品知识 Schema (FeatureTree / PricingModel / UserPersona)
    Required by competition spec: "定义竞品知识 Schema，Agent 产出必须符合 Schema"

Layer 2 — Agent 间通信 Schema (§3.13)
    CollectedDataPoint / AnalysisResult / ReviewVerdict / ReviewGap /
    ReviewPackage / ReportData / HitlDecision / ForecastResult

Layer 3 — 校验工具
    validate_agent_output() — model_validate() + 2 retries + degrade
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1: 竞品知识 Schema（开题材料 §2 课题介绍）
# ═══════════════════════════════════════════════════════════════════════════════


class FeatureNode(BaseModel):
    """A single feature within a product category."""

    name: str = Field(..., description="Feature name, e.g. 'Tab 补全'")
    description: str = Field(..., description="What this feature does")
    supported: bool = Field(..., description="Whether the product supports this feature")
    differentiation_score: int = Field(
        default=1, ge=1, le=5, description="1-5: how differentiated this feature is vs competitors"
    )


class FeatureCategory(BaseModel):
    """A category grouping related features."""

    category_name: str = Field(..., description="e.g. '代码补全' / '协作功能' / '安全合规'")
    features: list[FeatureNode] = Field(default_factory=list)


class FeatureTree(BaseModel):
    """Complete feature tree for one product."""

    product_name: str
    schema_version: int = Field(default=1, description="Schema version for backward compatibility")
    categories: list[FeatureCategory] = Field(default_factory=list)


class PricingTier(BaseModel):
    """A single pricing tier."""

    tier_name: str = Field(..., description="'免费版' / '专业版' / '企业版'")
    price: float = Field(..., description="Price in the given currency")
    currency: str = Field(default="USD")
    billing_cycle: Literal["monthly", "yearly", "one-time"] = "monthly"
    features_included: list[str] = Field(default_factory=list)
    target_segment: str = Field(default="", description="'个人开发者' / '小团队' / '企业'")


class PricingModel(BaseModel):
    """Pricing model for one product."""

    product_name: str
    schema_version: int = Field(default=1, description="Schema version for backward compatibility")
    tiers: list[PricingTier] = Field(default_factory=list)
    free_tier_available: bool = False
    pricing_strategy: str = Field(default="", description="'freemium' / 'subscription' / 'usage-based'")


class UserSegment(BaseModel):
    """A user segment and its relationship to the product."""

    segment_name: str = Field(..., description="'专业开发者' / '技术管理者' / '学生'")
    primary_needs: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    why_choose: list[str] = Field(default_factory=list, description="Why this segment chooses this product")
    why_leave: list[str] = Field(default_factory=list, description="Why this segment leaves/rejects this product")
    estimated_share: float = Field(default=0.0, ge=0.0, le=1.0, description="Estimated share of user base")


class UserPersona(BaseModel):
    """User persona model for one product."""

    product_name: str
    primary_segments: list[UserSegment] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2: 6-Edge Agent Communication Schemas (§3.13)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Edge ①: Collector → Analyst (§3.13.2) ──


class CollectedDataPoint(BaseModel):
    """A single structured data point from Collector to Analyst."""

    id: str = Field(..., description="Unique ID: dp-{timestamp}-{seq}")
    product: str = Field(..., description="Target product name")
    category: Literal["features", "pricing", "users", "market"] = Field(
        ..., description="Data category"
    )
    label: str = Field(..., description="One-line description, e.g. 'Cursor Pro 月费'")
    value: str | float = Field(..., description="The actual data value")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="LLM or API confidence score")
    source_url: str = Field(..., description="Mandatory source URL (§3.15.1 citation enforcement)")
    source_type: Literal[
        "official", "review", "news", "interview", "social",
        "comparison", "pricing", "stats", "docs", "blog", "estimated",
    ] = Field(
        ..., description="Source classification"
    )
    collected_at: str = Field(..., description="ISO 8601 timestamp")


# ── Edge ②: Analyst → Reviewer (§3.13.3) ──


class ComparisonCell(BaseModel):
    """One cell in the comparison matrix."""

    product: str
    dimension: str
    rating: int | None = Field(default=None, ge=1, le=5, description="1-5 or None if no data")
    evidence: str = Field(default="", description="Fact supporting this rating")
    source_data_point_ids: list[str] = Field(default_factory=list)


class ComparisonMatrix(BaseModel):
    """Analyst-produced comparison matrix."""

    products: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    cells: list[ComparisonCell] = Field(default_factory=list)
    summary: str = Field(default="", description="One-line overview")


class SWOTItem(BaseModel):
    """A single SWOT entry — must reference ≥1 DataPoint per §3.5.3."""

    category: Literal["strength", "weakness", "opportunity", "threat"]
    statement: str
    evidence: str = Field(default="")
    source_data_point_ids: list[str] = Field(default_factory=list)


class SWOTAnalysis(BaseModel):
    """SWOT analysis for one product."""

    product: str
    items: list[SWOTItem] = Field(default_factory=list)


class TrendFinding(BaseModel):
    """A single trend insight."""

    dimension: str = Field(..., description="'市场份额' / '定价趋势' / '功能演进'")
    direction: Literal["up", "down", "stable", "unclear"] = "unclear"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: str = Field(default="")
    source_data_point_ids: list[str] = Field(default_factory=list)


class ForecastItem(BaseModel):
    """A single forecast for one product × dimension — §3.5.7."""

    dimension: str
    product: str
    current_state: str = Field(default="")
    trend_direction: Literal["up", "down", "stable", "uncertain"] = "uncertain"
    trend_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    forecast_6m: str = Field(default="", description="6-month forecast")
    forecast_12m: str = Field(default="", description="12-month forecast")
    rationale: str = Field(default="")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_data_point_ids: list[str] = Field(default_factory=list)


class ForecastResult(BaseModel):
    """Analyst → Writer forecast payload (§3.5.7)."""

    items: list[ForecastItem] = Field(default_factory=list)
    summary: str = Field(default="")
    disclaimer: str = Field(
        default="以下预测基于公开数据趋势外推，不构成投资建议"
    )


class AnalysisResult(BaseModel):
    """Analyst → Reviewer, written to State.analysis_result (§3.13.3)."""

    comparison_matrix: ComparisonMatrix = Field(default_factory=ComparisonMatrix)
    swot: dict[str, SWOTAnalysis] = Field(default_factory=dict)
    trends: list[TrendFinding] = Field(default_factory=list)
    forecast: ForecastResult | None = None
    visualization_paths: list[str] = Field(default_factory=list)
    extra_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-adaptive fields (§3.17.3). Analyst identifies industry-specific "
        "dimensions (e.g. SaaS→integration_count, hardware→chip_model) and stores them here. "
        "Reviewer validates that extra_fields entries have source citations.",
    )


# ── Edge ③: Reviewer → Writer (§3.13.4) ──


class QualitySummary(BaseModel):
    """Data quality overview from Reviewer to Writer."""

    total_data_points: int = 0
    verified_count: int = 0
    multi_source_count: int = 0
    single_source_count: int = 0
    fact_errors_count: int = 0
    unresolved_gaps: list[str] = Field(default_factory=list)
    overall_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    improvement_ratio: float | None = None


class ReviewVerdict(BaseModel):
    """Reviewer → Writer, written to State.review_verdict (§3.13.4)."""

    passed: bool = False
    round: int = 0
    gaps: list[ReviewGap] = Field(default_factory=list)  # forward-ref handled below
    fact_errors: list[dict] = Field(default_factory=list)
    quality_summary: QualitySummary = Field(default_factory=QualitySummary)
    reviewer_notes: str = Field(default="")


# ── Edge ⑤: Reviewer → Collector (gap feedback) (§3.13.6) ──


class ReviewGap(BaseModel):
    """A gap discovered by Reviewer — directed re-collection task for Collector."""

    gap_id: str = Field(..., description="Unique: gap-{round}-{seq}")
    type: Literal["missing_data", "fact_error", "source_conflict", "outdated"] = Field(
        ..., description="Gap classification per §3.6.1 G1-G8"
    )
    check_method: str = Field(default="", description="e.g. 'multi_source_consistency' / 'url_reachability'")
    description: str = Field(default="")
    evidence: str = Field(default="")
    target_collect_task: str = Field(..., description="Precise re-collection task for Collector")
    severity: Literal["critical", "major", "minor"] = "major"
    related_data_point_ids: list[str] = Field(default_factory=list)


# ── Edge ④: Writer → HITL Gate (§3.13.5) ──


class DataStats(BaseModel):
    """Data statistics summary for the approval card."""

    total_data_points: int = 0
    products_covered: dict[str, int] = Field(default_factory=dict)
    categories_covered: dict[str, int] = Field(default_factory=dict)
    source_types: dict[str, int] = Field(default_factory=dict)


class ReviewPackage(BaseModel):
    """Writer → HITL Gate, written to State.review_package (§3.13.5)."""

    executive_summary: str = Field(default="", description="≤500 chars")
    key_findings: list[str] = Field(default_factory=list, description="3-5 items")
    data_stats: DataStats = Field(default_factory=DataStats)
    quality_summary: QualitySummary = Field(default_factory=QualitySummary)
    unresolved_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    pm_report_preview: str = Field(default="")
    entrepreneur_report_preview: str = Field(default="")


# ── Edge ⑥: HITL Gate → target node (§3.13.7) ──


class HitlDecision(BaseModel):
    """HITL Gate routing decision, written to State.hitl_decision."""

    action: Literal["approve", "replan", "reanalyze", "rewrite"] = Field(
        ..., description="Target node for the feedback loop"
    )
    comment: str | None = None
    target_focus: list[str] | None = Field(
        default=None, description="Specific dimensions/sections to focus on"
    )
    timestamp: str = Field(default="", description="ISO 8601")


# ── Writer Output: ReportData (§3.7.2) ──


class ReportSection(BaseModel):
    """A single section in the interactive report."""

    id: str = Field(..., description="'sec-executive-summary' / 'sec-comparison' / ...")
    title: str
    content: str = Field(default="", description="Markdown text rendered by frontend engine")
    content_type: Literal["text", "table", "chart", "what-if-form"] = "text"
    source_ids: list[str] = Field(default_factory=list)
    chart_path: str | None = None
    subsections: list[ReportSection] | None = None


class ReportData(BaseModel):
    """Writer output — frontend-native interactive report (§3.7.2)."""

    persona: Literal["pm", "entrepreneur"] = "pm"
    title: str = ""
    generated_at: str = Field(default="", description="ISO 8601")
    products: list[str] = Field(default_factory=list)
    sections: list[ReportSection] = Field(default_factory=list)
    traceability_map: dict[str, dict] = Field(default_factory=dict)
    quality_summary: QualitySummary = Field(default_factory=QualitySummary)
    forecast: ForecastResult | None = None
    metrics: dict = Field(default_factory=dict)
    extra_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-adaptive fields from AnalysisResult (§3.17.3). "
        "Included in the report as an appendix section.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 3: Schema 强制校验 (§3.11)
# ═══════════════════════════════════════════════════════════════════════════════

logger = logging.getLogger(__name__)

# ── Agent → target Pydantic model mapping ──
AGENT_SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "collector": CollectedDataPoint,
    "analyst": AnalysisResult,
    "reviewer": ReviewVerdict,
    "writer": ReportData,
}

MAX_VALIDATION_RETRIES = 2


class SchemaValidationFailed(Exception):
    """Raised when schema validation fails after all retries."""

    def __init__(self, agent_name: str, errors: list[dict], original_output: Any):
        self.agent_name = agent_name
        self.errors = errors
        self.original_output = original_output
        super().__init__(f"{agent_name} output failed schema validation after {MAX_VALIDATION_RETRIES} retries")


def validate_agent_output(
    agent_name: str,
    raw_output: str | dict,
    target_model: type[BaseModel] | None = None,
    retries: int = MAX_VALIDATION_RETRIES,
) -> BaseModel:
    """Validate Agent LLM output against its Pydantic schema.

    Per §3.11: model_validate() → 2 retries (with ValidationError feedback) → degrade.

    Args:
        agent_name: One of 'collector' / 'analyst' / 'reviewer' / 'writer'.
        raw_output: LLM output — JSON string or parsed dict.
        target_model: Override auto-detected model (for list inputs like [CollectedDataPoint]).
        retries: Max retry count (default 2).

    Returns:
        Validated Pydantic model instance.

    Raises:
        SchemaValidationFailed: All retries exhausted — caller must degrade.
    """
    model = target_model or AGENT_SCHEMA_MAP.get(agent_name)
    if model is None:
        raise ValueError(f"Unknown agent: {agent_name}. Must provide target_model.")

    # Parse JSON string if needed
    if isinstance(raw_output, str):
        try:
            raw_output = json.loads(raw_output)
        except json.JSONDecodeError as e:
            logger.warning("%s output is not valid JSON: %s", agent_name, e)
            raw_output = {"_parse_error": str(e), "_raw": raw_output}

    last_errors: list[dict] = []

    for attempt in range(1, retries + 2):  # 1 initial + N retries
        try:
            if isinstance(raw_output, list):
                # Collector may return list[CollectedDataPoint]
                return [model.model_validate(item) for item in raw_output]  # type: ignore[return-value]
            return model.model_validate(raw_output)
        except ValidationError as e:
            last_errors = [
                {"loc": " → ".join(str(p) for p in err["loc"]), "msg": err["msg"], "type": err["type"]}
                for err in e.errors()
            ]
            logger.warning(
                "%s validation attempt %d/%d failed: %d errors",
                agent_name, attempt, retries + 1, len(last_errors),
            )
            if attempt <= retries:
                # Give LLM actionable feedback for next retry
                raise SchemaValidationRetry(
                    agent_name=agent_name,
                    errors=last_errors,
                    attempt=attempt,
                ) from e

    raise SchemaValidationFailed(
        agent_name=agent_name,
        errors=last_errors,
        original_output=raw_output,
    )


class SchemaValidationRetry(Exception):
    """Actionable retry signal — caller catches this, re-prompts LLM with error details."""

    def __init__(self, agent_name: str, errors: list[dict], attempt: int):
        self.agent_name = agent_name
        self.errors = errors
        self.attempt = attempt
        detail = "\n".join(f"  • {e['loc']}: {e['msg']}" for e in errors[:5])
        super().__init__(f"{agent_name} validation failed (attempt {attempt}), retry with fixes:\n{detail}")


def format_validation_error_for_llm(errors: list[dict]) -> str:
    """Format ValidationError details as human-readable feedback for LLM retry prompt."""
    lines = ["Schema 校验失败，请修正以下字段后重新输出："]
    for e in errors[:10]:
        lines.append(f"  • {e['loc']}: {e['msg']} (type={e['type']})")
    return "\n".join(lines)
