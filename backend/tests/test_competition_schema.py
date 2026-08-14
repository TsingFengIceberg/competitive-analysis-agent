"""Tests for competition/schema.py — Pydantic schemas and validation.

Covers §1.2-1.4 of the coding plan:
- Layer 1: FeatureTree / PricingModel / UserPersona (3 竞品知识 Schema)
- Layer 2: 6-edge communication schemas (18 models)
- Layer 3: validate_agent_output() + retry/degrade logic
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from competition.schema import (
    # Layer 3 — validation
    AGENT_SCHEMA_MAP,
    MAX_VALIDATION_RETRIES,
    AnalysisResult,
    # Layer 2 — edge schemas
    CollectedDataPoint,
    ComparisonCell,
    ComparisonMatrix,
    FeatureCategory,
    # Layer 1
    FeatureNode,
    FeatureTree,
    ForecastItem,
    ForecastResult,
    HitlDecision,
    PricingModel,
    PricingTier,
    QualityGateSnapshot,
    QualitySummary,
    ReportData,
    ReportSection,
    ReviewGap,
    ReviewPackage,
    ReviewVerdict,
    SchemaValidationFailed,
    SchemaValidationRetry,
    SWOTAnalysis,
    SWOTItem,
    TrendFinding,
    UserPersona,
    UserSegment,
    format_validation_error_for_llm,
    validate_agent_output,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1: 竞品知识 Schema
# ═══════════════════════════════════════════════════════════════════════════════


class TestFeatureTree:
    def test_build_complete_tree(self):
        ft = FeatureTree(
            product_name="Cursor",
            categories=[
                FeatureCategory(
                    category_name="代码补全",
                    features=[
                        FeatureNode(name="Tab 补全", description="智能 Tab", supported=True, differentiation_score=4),
                        FeatureNode(name="多行补全", description="Multi-line", supported=True, differentiation_score=3),
                    ],
                ),
                FeatureCategory(
                    category_name="协作功能",
                    features=[
                        FeatureNode(name="实时协作", description="Real-time collab", supported=False, differentiation_score=1),
                    ],
                ),
            ],
        )
        assert ft.product_name == "Cursor"
        assert len(ft.categories) == 2
        assert ft.categories[0].features[0].differentiation_score == 4

    def test_empty_tree(self):
        ft = FeatureTree(product_name="Empty")
        assert ft.categories == []

    def test_differentiation_score_bounds(self):
        with pytest.raises(PydanticValidationError):
            FeatureNode(name="X", description="Y", supported=True, differentiation_score=6)

        with pytest.raises(PydanticValidationError):
            FeatureNode(name="X", description="Y", supported=True, differentiation_score=0)


class TestPricingModel:
    def test_build_model(self):
        pm = PricingModel(
            product_name="Cursor",
            tiers=[
                PricingTier(tier_name="Hobby", price=0.0, billing_cycle="monthly", features_included=["2K completions/month"]),
                PricingTier(tier_name="Pro", price=20.0, billing_cycle="monthly", target_segment="专业开发者"),
                PricingTier(tier_name="Business", price=40.0, billing_cycle="monthly", target_segment="企业"),
            ],
            free_tier_available=True,
            pricing_strategy="freemium",
        )
        assert len(pm.tiers) == 3
        assert pm.free_tier_available is True
        assert pm.tiers[0].price == 0.0

    def test_billing_cycle_validation(self):
        with pytest.raises(PydanticValidationError):
            PricingTier(tier_name="X", price=10.0, billing_cycle="annually")  # type: ignore[arg-type]


class TestUserPersona:
    def test_build_persona(self):
        up = UserPersona(
            product_name="Cursor",
            primary_segments=[
                UserSegment(
                    segment_name="专业开发者",
                    primary_needs=["代码补全准确", "延迟低"],
                    pain_points=["多文件重构弱"],
                    why_choose=["Tab 补全业界最快"],
                    why_leave=["企业功能不足"],
                    estimated_share=0.65,
                ),
            ],
        )
        assert up.primary_segments[0].estimated_share == 0.65
        assert "代码补全准确" in up.primary_segments[0].primary_needs

    def test_share_bounds(self):
        with pytest.raises(PydanticValidationError):
            UserSegment(segment_name="X", estimated_share=1.5)


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2: 6-Edge Communication Schemas
# ═══════════════════════════════════════════════════════════════════════════════


class TestCollectedDataPoint:
    def test_valid_datapoint(self):
        dp = CollectedDataPoint(
            id="dp-001",
            product="Cursor",
            category="pricing",
            label="Pro 月费",
            value=20.0,
            source_url="https://cursor.com/pricing",
            source_type="official",
            collected_at="2026-05-23T00:00:00Z",
        )
        assert dp.confidence == 0.5  # default
        assert dp.source_type == "official"

    def test_missing_source_url_rejected(self):
        """§3.4.1: source_url is mandatory (citation enforcement)."""
        with pytest.raises(PydanticValidationError):
            CollectedDataPoint(
                id="dp-001", product="Cursor", category="pricing",
                label="X", value=1.0, source_type="official", collected_at="...",
            )  # type: ignore[arg-type]

    def test_invalid_category(self):
        with pytest.raises(PydanticValidationError):
            CollectedDataPoint(
                id="dp-001", product="Cursor", category="invalid",
                label="X", value=1.0, source_url="x.com", source_type="official", collected_at="...",
            )  # type: ignore[arg-type]


class TestComparisonMatrix:
    def test_matrix(self):
        cm = ComparisonMatrix(
            products=["Cursor", "Copilot"],
            dimensions=["代码补全", "定价"],
            cells=[
                ComparisonCell(product="Cursor", dimension="代码补全", rating=5, evidence="Tab 补全准确率 95%", source_data_point_ids=["dp-001"]),
            ],
            summary="Cursor leads in completion, Copilot in ecosystem",
        )
        assert len(cm.cells) == 1
        assert cm.cells[0].rating == 5


class TestSWOTAnalysis:
    def test_swot_with_evidence(self):
        """§3.5.3: each SWOTItem must reference ≥1 DataPoint."""
        item = SWOTItem(
            category="strength",
            statement="Tab 补全业界最快",
            evidence="用户评测中 Tab 补全准确率 95%（dp-001）",
            source_data_point_ids=["dp-001", "dp-002"],
        )
        assert len(item.source_data_point_ids) >= 1

    def test_swot_analysis_per_product(self):
        sa = SWOTAnalysis(
            product="Cursor",
            items=[
                SWOTItem(category="strength", statement="S1", evidence="E1", source_data_point_ids=["dp-001"]),
                SWOTItem(category="weakness", statement="W1", evidence="E2", source_data_point_ids=["dp-002"]),
            ],
        )
        assert len(sa.items) == 2


class TestAnalysisResult:
    def test_full_result(self):
        ar = AnalysisResult(
            comparison_matrix=ComparisonMatrix(products=["Cursor"]),
            swot={"Cursor": SWOTAnalysis(product="Cursor")},
            trends=[TrendFinding(dimension="市场份额", direction="up", confidence=0.8)],
            forecast=ForecastResult(summary="预计 Cursor 将继续增长"),
            visualization_paths=["/sandbox/radar.png"],
        )
        assert ar.forecast is not None
        assert ar.forecast.summary.startswith("预计")

    def test_no_forecast(self):
        ar = AnalysisResult(comparison_matrix=ComparisonMatrix(products=["Cursor"]))
        assert ar.forecast is None


class TestReviewVerdict:
    def test_passed_verdict(self):
        rv = ReviewVerdict(
            passed=True,
            round=1,
            gaps=[],
            quality_summary=QualitySummary(total_data_points=42, overall_quality_score=0.92),
        )
        assert rv.passed is True
        assert rv.quality_summary.overall_quality_score == 0.92

    def test_failed_verdict_with_gaps(self):
        gap = ReviewGap(gap_id="gap-1-1", type="missing_data", target_collect_task="search pricing")
        rv = ReviewVerdict(
            passed=False,
            round=1,
            gaps=[gap],
            quality_summary=QualitySummary(),
        )
        assert len(rv.gaps) == 1
        assert rv.gaps[0].type == "missing_data"


class TestReviewGap:
    def test_critical_gap(self):
        gap = ReviewGap(
            gap_id="gap-1-1",
            type="fact_error",
            check_method="url_reachability",
            description="Cursor pricing page returns 404",
            evidence="HEAD request → 404",
            target_collect_task="find alternative source for Cursor pricing",
            severity="critical",
            related_data_point_ids=["dp-005"],
        )
        assert gap.severity == "critical"

    def test_invalid_type(self):
        with pytest.raises(PydanticValidationError):
            ReviewGap(gap_id="g-1", type="unknown_gap", target_collect_task="x")  # type: ignore[arg-type]


class TestReviewPackage:
    def test_package(self):
        rp = ReviewPackage(
            executive_summary="Cursor 领先",
            key_findings=["Cursor Pro $20 vs Copilot $19"],
            recommendations=["建议批准"],
        )
        assert len(rp.key_findings) == 1


class TestHitlDecision:
    def test_approve(self):
        hd = HitlDecision(action="approve")
        assert hd.action == "approve"

    def test_replan_with_focus(self):
        hd = HitlDecision(action="replan", comment="need more pricing data", target_focus=["pricing"])
        assert hd.target_focus == ["pricing"]

    def test_invalid_action(self):
        with pytest.raises(PydanticValidationError):
            HitlDecision(action="delete")  # type: ignore[arg-type]


class TestReportData:
    def test_report_with_sections(self):
        rd = ReportData(
            persona="pm",
            title="AI 编程工具竞品分析",
            products=["Cursor", "Copilot"],
            sections=[
                ReportSection(id="sec-exec", title="执行摘要", content="...", content_type="text"),
                ReportSection(id="sec-comparison", title="对比矩阵", content="...", content_type="table"),
            ],
            traceability_map={"dp-001": {"url": "cursor.com", "timestamp": "2026-05-23", "confidence_level": "✅ 多源验证"}},
            quality_summary=QualitySummary(total_data_points=42),
        )
        assert rd.persona == "pm"
        assert len(rd.sections) == 2
        assert rd.traceability_map["dp-001"]["url"] == "cursor.com"

    def test_legacy_report_without_quality_gate_is_unknown_compatible(self):
        rd = ReportData(title="旧报告")
        assert rd.quality_gate is None

    def test_quality_gate_validates_status_and_bounds(self):
        gate = QualityGateSnapshot(status="blocked", blocking_count=1, warning_count=2)
        assert gate.status == "blocked"
        with pytest.raises(PydanticValidationError):
            QualityGateSnapshot(blocking_count=-1)

    def test_what_if_section_type(self):
        """§3.7.2: content_type supports 'what-if-form' for embedded forecast input."""
        section = ReportSection(id="sec-whatif", title="What-if", content_type="what-if-form")
        assert section.content_type == "what-if-form"

    def test_structured_dynamic_table_and_chart_sections_validate(self):
        rd = ReportData(
            products=["A"],
            sections=[
                ReportSection(id="dynamic-block-0", title="表", content="表格 [1]", content_type="table",
                              source_ids=["1"], chart_path={"headers": ["指标"], "rows": [["1"]]}),
                ReportSection(id="dynamic-block-1", title="图", content="图表 [1]", content_type="chart",
                              source_ids=["1"], chart_path={"chart": "bar", "labels": ["A"], "series": {"值": [1]}}),
            ],
            dynamic_blocks=[
                {"block_type": "kv_list", "title": "指标", "data": {"x": 1}},
                {"block_type": "comparison_table", "title": "表", "data": {"headers": ["指标"], "rows": [["1"]]}},
                {"block_type": "stat_chart", "title": "图", "data": {"chart": "bar", "labels": ["A"], "series": {"值": [1]}}},
                {"block_type": "insight_text", "title": "洞察", "data": {"content": "结论"}},
            ],
            traceability_map={"1": {"url": "a.example"}},
        )
        assert rd.sections[0].chart_path["headers"] == ["指标"]
        assert rd.sections[1].chart_path["chart"] == "bar"
        assert len(rd.dynamic_blocks) == 4


class TestForecastResult:
    def test_forecast(self):
        fr = ForecastResult(
            items=[ForecastItem(dimension="定价", product="Cursor", forecast_6m="预计维持 $20", forecast_12m="可能涨至 $25", confidence=0.7)],
            summary="价格稳定",
        )
        assert len(fr.items) == 1
        assert "不构成投资建议" in fr.disclaimer


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 3: Schema 强制校验
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateAgentOutput:
    def test_valid_single_object(self):
        dp = validate_agent_output("collector", {
            "id": "dp-1", "product": "Cursor", "category": "pricing",
            "label": "Pro", "value": 20.0, "source_url": "cursor.com",
            "source_type": "official", "collected_at": "2026-05-23T00:00:00Z",
        })
        assert isinstance(dp, CollectedDataPoint)

    def test_valid_list(self):
        dps = validate_agent_output("collector", [
            {"id": "dp-1", "product": "Cursor", "category": "pricing", "label": "P1", "value": 20.0, "source_url": "a.com", "source_type": "official", "collected_at": "..."},
            {"id": "dp-2", "product": "Copilot", "category": "pricing", "label": "P2", "value": 19.0, "source_url": "b.com", "source_type": "official", "collected_at": "..."},
        ])
        assert len(dps) == 2

    def test_retry_on_invalid(self):
        """§3.11: 1st failure → SchemaValidationRetry with error details."""
        with pytest.raises(SchemaValidationRetry) as exc:
            validate_agent_output("collector", {"id": "x", "product": "", "category": "invalid"}, retries=1)
        assert "collector" in str(exc.value)
        assert len(exc.value.errors) > 0

    def test_final_failure_after_retries(self):
        """§3.11: all retries exhausted → SchemaValidationFailed."""
        with pytest.raises(SchemaValidationFailed):
            validate_agent_output("collector", {"id": "x", "product": ""}, retries=0)

    def test_target_model_override(self):
        """Custom target_model for non-standard validation (e.g. ReviewGap)."""
        gap = validate_agent_output(None, {
            "gap_id": "gap-1-1", "type": "missing_data", "target_collect_task": "search"
        }, target_model=ReviewGap)
        assert isinstance(gap, ReviewGap)

    def test_unknown_agent_raises(self):
        with pytest.raises(ValueError, match="Unknown agent"):
            validate_agent_output("unknown_agent", {})


class TestFormatValidationError:
    def test_format(self):
        errors = [
            {"loc": "source_url", "msg": "Field required", "type": "missing"},
            {"loc": "category", "msg": "Input should be 'features', 'pricing', 'users' or 'market'", "type": "literal_error"},
        ]
        output = format_validation_error_for_llm(errors)
        assert "Schema 校验失败" in output
        assert "source_url" in output
        assert "category" in output


class TestAgentSchemaMap:
    def test_all_four_agents_mapped(self):
        assert "collector" in AGENT_SCHEMA_MAP
        assert "analyst" in AGENT_SCHEMA_MAP
        assert "reviewer" in AGENT_SCHEMA_MAP
        assert "writer" in AGENT_SCHEMA_MAP

    def test_collector_maps_to_datapoint(self):
        assert AGENT_SCHEMA_MAP["collector"] is CollectedDataPoint

    def test_analyst_maps_to_analysis_result(self):
        assert AGENT_SCHEMA_MAP["analyst"] is AnalysisResult

    def test_reviewer_maps_to_review_verdict(self):
        assert AGENT_SCHEMA_MAP["reviewer"] is ReviewVerdict

    def test_writer_maps_to_report_data(self):
        assert AGENT_SCHEMA_MAP["writer"] is ReportData


class TestMaxRetries:
    def test_max_retries_is_2(self):
        assert MAX_VALIDATION_RETRIES == 2, "Per §3.11: max 2 retries"
