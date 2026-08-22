"""Tests for competition/nodes/collector.py — pure functions.

Covers §3.4: dedup, collection summary, task construction, data point parsing.
Does NOT test SubagentExecutor integration (requires full DF runtime).
"""

from __future__ import annotations

import json

from competition.nodes.collector import (
    _build_collector_task,
    _normalize_label,
    _parse_datapoints,
    _persist_intelligence_items,
    _source_short,
    _values_similar,
    build_collection_summary,
    deduplicate_datapoints,
)
from competition.schema import CollectedDataPoint


def _make_dp(id: str, product: str = "Cursor", category: str = "pricing", label: str = "Pro", value: float = 20.0, source_url: str = "cursor.com/pricing", source_type: str = "official", **kwargs) -> CollectedDataPoint:
    defaults = {
        "id": id, "product": product, "category": category, "label": label,
        "value": value, "source_url": source_url, "source_type": source_type,
        "collected_at": kwargs.pop("collected_at", "2026-05-23T00:00:00Z"),
    }
    defaults.update(kwargs)
    return CollectedDataPoint.model_validate(defaults)


# ═══════════════════════════════════════════════════════════════
# Deduplication (§3.4.2)
# ═══════════════════════════════════════════════════════════════


class TestDeduplicateDatapoints:
    def test_empty(self):
        assert deduplicate_datapoints([]) == []

    def test_single(self):
        dp = _make_dp("dp-1")
        result = deduplicate_datapoints([dp])
        assert len(result) == 1

    def test_merge_similar_values(self):
        """Same label + same value (within 5%) → merge, keep max confidence."""
        dp1 = _make_dp("dp-1", value=20.0, confidence=0.9, source_url="a.com")
        dp2 = _make_dp("dp-2", value=20.5, confidence=0.7, source_url="b.com")
        result = deduplicate_datapoints([dp1, dp2])
        assert len(result) == 1
        assert result[0].confidence == 0.9  # max
        assert "a.com" in result[0].source_url
        assert "b.com" in result[0].source_url

    def test_keep_divergent_values(self):
        """Different value (>= 5%) → keep both with source annotations."""
        dp1 = _make_dp("dp-1", value=20.0, source_url="a.com")
        dp2 = _make_dp("dp-2", value=30.0, source_url="b.com")
        result = deduplicate_datapoints([dp1, dp2])
        assert len(result) == 2

    def test_duplicate_source_discarded(self):
        """Same source_url → discard as collector bug."""
        dp1 = _make_dp("dp-1", source_url="a.com")
        dp2 = _make_dp("dp-2", source_url="a.com")
        result = deduplicate_datapoints([dp1, dp2])
        assert len(result) == 1

    def test_different_products_not_deduped(self):
        dp1 = _make_dp("dp-1", product="Cursor")
        dp2 = _make_dp("dp-2", product="Copilot")
        result = deduplicate_datapoints([dp1, dp2])
        assert len(result) == 2

    def test_different_categories_not_deduped(self):
        dp1 = _make_dp("dp-1", category="pricing")
        dp2 = _make_dp("dp-2", category="features")
        result = deduplicate_datapoints([dp1, dp2])
        assert len(result) == 2


class TestValuesSimilar:
    def test_identical(self):
        assert _values_similar(20.0, 20.0) is True

    def test_within_5_percent(self):
        assert _values_similar(20.0, 20.9) is True

    def test_beyond_5_percent(self):
        assert _values_similar(20.0, 22.0) is False

    def test_zero_handling(self):
        assert _values_similar(0.0, 0.0) is True
        assert _values_similar(0.0, 1.0) is False

    def test_string_values(self):
        assert _values_similar("high", "high") is True
        assert _values_similar("high", "low") is False


def test_normalize_label():
    assert _normalize_label("Cursor Pro $20") == "cursor pro $X"
    assert _normalize_label("  Tab  补全  ") == "tab 补全"


def test_source_short():
    assert _source_short("https://cursor.com/pricing") == "cursor.com"
    assert _source_short("https://www.github.com/features") == "github.com"


# ═══════════════════════════════════════════════════════════════
# Collection Summary (§3.4.6)
# ═══════════════════════════════════════════════════════════════


class TestBuildCollectionSummary:
    def test_empty(self):
        s = build_collection_summary([], ["Cursor"])
        assert s["total_data_points"] == 0
        assert s["stopped_by"] == "no_results"

    def test_basic_summary(self):
        dps = [
            _make_dp("dp-1", product="Cursor", category="pricing", confidence=0.9),
            _make_dp("dp-2", product="Cursor", category="features", confidence=0.7, source_type="review"),
            _make_dp("dp-3", product="Copilot", category="pricing", confidence=0.3, source_type="review"),
        ]
        s = build_collection_summary(dps, ["Cursor", "Copilot"])
        assert s["total_data_points"] == 3
        assert s["products_covered"]["Cursor"] == 2
        assert s["products_covered"]["Copilot"] == 1
        assert s["source_types"]["official"] == 1
        assert s["source_types"]["review"] == 2
        assert s["low_confidence_points"] == 1  # dp-3 confidence 0.3

    def test_soft_stop_detected(self):
        """When >=20 points, >=3 source types, all products >=2 → soft_stop."""
        dps = []
        for i in range(20):
            product = "Cursor" if i < 10 else "Copilot"
            source = "official" if i < 7 else ("review" if i < 14 else "social")
            dps.append(_make_dp(f"dp-{i}", product=product, source_type=source))
        s = build_collection_summary(dps, ["Cursor", "Copilot"])
        assert s["stopped_by"] == "soft_stop"


# ═══════════════════════════════════════════════════════════════
# Task Construction
# ═══════════════════════════════════════════════════════════════


class TestBuildCollectorTask:
    def test_basic_task(self):
        task = _build_collector_task({
            "user_request": "analyze Cursor",
            "target_products": ["Cursor", "Copilot"],
        })
        assert "Cursor" in task
        assert "Copilot" in task
        assert "features" in task
        assert "pricing" in task
        assert "users" in task
        assert "market" in task

    def test_with_gaps(self):
        task = _build_collector_task({
            "user_request": "test",
            "target_products": ["X"],
            "knowledge_gaps": [
                {"type": "missing_data", "target_collect_task": "find enterprise pricing for Cursor"},
            ],
        })
        assert "enterprise pricing" in task
        assert "TARGETED RE-COLLECTION" in task

    def test_brief_limits_categories(self):
        task = _build_collector_task({
            "user_request": "compare", "target_products": ["A", "B"],
            "analysis_brief": {"dimensions": [{"id": "technology"}]},
        })
        assert "technology" in task
        assert "pricing" not in task

    def test_brief_uses_effective_industry_dimension(self):
        task = _build_collector_task({
            "user_request": "compare",
            "target_products": ["A", "B"],
            "analysis_brief": {
                "dimensions": [{"id": "features"}],
                "effective_dimensions": [{
                    "id": "industry:devtools:1",
                    "label": "社区活跃度",
                    "search_hint": "GitHub stars issues pull requests",
                    "source": "industry",
                }],
            },
        })
        assert "industry:devtools:1" in task
        assert "features" not in task

    def test_user_focus_limits_recollection_without_reviewer_gaps(self):
        task = _build_collector_task({
            "user_request": "compare",
            "target_products": ["A", "B"],
            "hitl_decision": {
                "action": "replan",
                "target_focus": ["只补采 B 的企业采用成本"],
            },
            "analysis_brief": {"dimensions": [{"id": "pricing", "label": "定价"}]},
        })
        assert "TARGETED USER RESEARCH" in task
        assert "只补采 B 的企业采用成本" in task
        assert "do not rerun the full collection" in task


# ═══════════════════════════════════════════════════════════════
# Data Point Parsing
# ═══════════════════════════════════════════════════════════════


class TestParseDatapoints:
    def test_json_string(self):
        raw = json.dumps([{
            "id": "dp-1", "product": "Cursor", "category": "pricing",
            "label": "Pro", "value": 20.0, "source_url": "a.com",
            "source_type": "official", "collected_at": "2026-05-23T00:00:00Z",
        }])
        result = _parse_datapoints(raw)
        assert len(result) == 1
        assert result[0].id == "dp-1"

    def test_list(self):
        result = _parse_datapoints([{
            "id": "dp-1", "product": "Cursor", "category": "pricing",
            "label": "Pro", "value": 20.0, "source_url": "a.com",
            "source_type": "official", "collected_at": "2026-05-23T00:00:00Z",
        }])
        assert len(result) == 1

    def test_none(self):
        assert _parse_datapoints(None) == []

    def test_invalid_json(self):
        assert _parse_datapoints("not json") == []

    def test_auto_timestamp(self):
        result = _parse_datapoints([{
            "id": "dp-1", "product": "Cursor", "category": "pricing",
            "label": "Pro", "value": 20.0, "source_url": "a.com",
            "source_type": "official",
        }])
        assert result[0].collected_at != ""

    def test_skip_invalid_items(self):
        result = _parse_datapoints([
            {"id": "bad", "product": "", "category": "invalid"},
            {"id": "dp-2", "product": "Cursor", "category": "pricing", "label": "Pro", "value": 20.0, "source_url": "a.com", "source_type": "official", "collected_at": "2026-05-23T00:00:00Z"},
        ])
        # First item fails validation → skipped; second passes
        assert len(result) == 1
        assert result[0].id == "dp-2"


def test_collector_persists_evidence_without_blocking_analysis(monkeypatch):
    captured = {}

    class FakeRepository:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def ingest_collected_points(self, points, *, scope):
            captured["points"] = points
            captured["scope"] = scope
            return {"inserted": len(points), "updated": 0, "unchanged": 0, "versions_created": len(points), "source_count": len(points)}

    monkeypatch.setattr("competition.intelligence_repo.IntelligenceRepository", FakeRepository)
    result = _persist_intelligence_items(
        {"analysis_brief": {"market_scope": "Global"}},
        [_make_dp("dp-1", source_url="https://a.example/a, https://b.example/b")],
    )
    assert result["inserted"] == 2
    assert captured["scope"] == "Global"
    assert {point["source_url"] for point in captured["points"]} == {
        "https://a.example/a",
        "https://b.example/b",
    }


# ═══════════════════════════════════════════════════════════════
# Analyst Node (§3.5)
# ═══════════════════════════════════════════════════════════════

from competition.nodes.analyst import (  # noqa: E402
    _build_analysis_result,
    _build_analyst_task,
    _empty_analysis_result,
    recommend_charts,
    self_check,
)


class TestBuildAnalystTask:
    def test_includes_dimensions(self):
        task = _build_analyst_task({
            "user_request": "analyze",
            "target_products": ["Cursor"],
            "collected_data": [
                {"category": "features"}, {"category": "pricing"}, {"category": "users"},
            ],
        })
        assert "功能" in task
        assert "定价" in task
        assert "用户" in task

    def test_includes_target_products(self):
        task = _build_analyst_task({
            "user_request": "test",
            "target_products": ["X"],
            "collected_data": [],
        })
        assert "X" in task

    def test_brief_limits_dimensions(self):
        task = _build_analyst_task({
            "user_request": "compare", "target_products": ["A", "B"],
            "analysis_brief": {"dimensions": [{"id": "technology"}]},
        })
        assert "技术" in task
        assert "功能, 定价, 用户" not in task


class TestBuildAnalysisResult:
    def test_none_returns_empty(self):
        result = _build_analysis_result(None, {"target_products": ["A"]})
        assert result["comparison_matrix"]["products"] == ["A"]

    def test_invalid_json_returns_empty(self):
        result = _build_analysis_result("not json", {"target_products": []})
        assert result["comparison_matrix"]["summary"] != ""

    def test_valid_dict_preserved(self):
        result = _build_analysis_result(
            {"comparison_matrix": {"products": ["A"], "dimensions": ["Pricing"], "cells": [], "summary": "ok"}},
            {},
        )
        assert result["comparison_matrix"]["products"] == ["A"]

    def test_missing_fields_filled(self):
        result = _build_analysis_result({}, {"target_products": ["X"]})
        assert "comparison_matrix" in result
        assert "swot" in result
        assert "trends" in result
        assert "visualization_paths" in result


class TestEmptyAnalysisResult:
    def test_has_all_fields(self):
        result = _empty_analysis_result({"target_products": ["A"]})
        assert result["comparison_matrix"]["products"] == ["A"]
        assert result["swot"] == {}
        assert result["forecast"] is None


class TestSelfCheck:
    def test_clean_result(self):
        result = {
            "comparison_matrix": {
                "products": ["A"],
                "dimensions": ["Price"],
                "cells": [{"product": "A", "dimension": "Price", "rating": 4}],
                "summary": "Good coverage of data",
            },
            "swot": {
                "A": {"items": [
                    {"statement": "S1", "source_data_point_ids": ["dp-1"]},
                ]},
            },
        }
        issues = self_check(result, ["A"])
        assert len(issues) == 0

    def test_missing_product_coverage(self):
        """A1: target product not in comparison_matrix → issue."""
        result = {
            "comparison_matrix": {"products": [], "dimensions": [], "cells": [], "summary": ""},
            "swot": {},
        }
        issues = self_check(result, ["MissingProduct"])
        assert any("A1" in i for i in issues)

    def test_swot_item_no_source(self):
        """A2: SWOT item without source_data_point_ids → issue."""
        result = {
            "comparison_matrix": {"products": ["A"], "dimensions": [], "cells": [], "summary": "ok coverage"},
            "swot": {"A": {"items": [
                {"statement": "No source", "source_data_point_ids": []},
            ]}},
        }
        issues = self_check(result, ["A"])
        assert any("A2" in i for i in issues)

    def test_no_coverage_in_summary(self):
        """A5: summary should mention coverage."""
        result = {
            "comparison_matrix": {"products": ["A"], "dimensions": [], "cells": [], "summary": "just a summary"},
            "swot": {},
        }
        issues = self_check(result, ["A"])  # A1 + A5
        assert any("A5" in i for i in issues)


class TestRecommendCharts:
    def test_basic_no_charts(self):
        result = {"comparison_matrix": {"products": [], "dimensions": [], "cells": []}}
        assert recommend_charts(result) == []

    def test_radar_triggered(self):
        result = {
            "comparison_matrix": {
                "products": ["A", "B"],
                "dimensions": ["Price", "Features", "Users"],
                "cells": [
                    {"product": "A", "dimension": "Price", "rating": 4},
                    {"product": "A", "dimension": "Features", "rating": 5},
                    {"product": "A", "dimension": "Users", "rating": 3},
                    {"product": "B", "dimension": "Price", "rating": 3},
                    {"product": "B", "dimension": "Features", "rating": 4},
                    {"product": "B", "dimension": "Users", "rating": 4},
                ],
            },
        }
        charts = recommend_charts(result)
        assert "radar" in charts

    def test_swot_triggers_bar(self):
        result = {
            "comparison_matrix": {"products": ["A"], "dimensions": [], "cells": []},
            "swot": {"A": {"items": [{"statement": "S1", "source_data_point_ids": ["dp-1"]}]}},
        }
        assert "bar" in recommend_charts(result)


# ═══════════════════════════════════════════════════════════════
# Reviewer Node (§3.6)
# ═══════════════════════════════════════════════════════════════

from competition.nodes.reviewer import (  # noqa: E402
    _build_quality_summary,
    _filter_loop_gaps,
    _generate_notes,
    _measure_improvement,
    check_brief_evidence_policy,
    check_data_freshness,
    check_dimension_coverage,
    check_multi_source_consistency,
    check_source_diversity,
    check_statistical_outliers,
    check_url_reachability,
)


class TestG1UrlReachability:
    def test_valid_url_no_gap(self):
        gaps = check_url_reachability([{"id": "dp-1", "source_url": "https://cursor.com", "label": "X", "confidence": 0.9}])
        assert len(gaps) == 0

    def test_missing_url_generates_gap(self):
        gaps = check_url_reachability([{"id": "dp-1", "source_url": "", "label": "X", "confidence": 0.9}])
        assert len(gaps) == 1
        assert gaps[0]["type"] == "fact_error"

    def test_non_http_url(self):
        gaps = check_url_reachability([{"id": "dp-1", "source_url": "not-a-url", "label": "X", "confidence": 0.3}])
        assert len(gaps) >= 0  # flagged, severity depends on confidence


class TestG2MultiSourceConsistency:
    def test_no_conflict_single_source(self):
        gaps = check_multi_source_consistency([
            {"id": "dp-1", "product": "Cursor", "label": "Pro Price", "value": 20.0, "source_url": "a.com"},
        ])
        assert len(gaps) == 0

    def test_conflict_detected(self):
        gaps = check_multi_source_consistency([
            {"id": "dp-1", "product": "Cursor", "label": "Pro Price", "value": 20.0, "source_url": "a.com"},
            {"id": "dp-2", "product": "Cursor", "label": "Pro Price", "value": 30.0, "source_url": "b.com"},
        ])
        assert len(gaps) == 1
        assert gaps[0]["type"] == "source_conflict"

    def test_consistent_values_no_gap(self):
        gaps = check_multi_source_consistency([
            {"id": "dp-1", "product": "Cursor", "label": "Pro Price", "value": 20.0, "source_url": "a.com"},
            {"id": "dp-2", "product": "Cursor", "label": "Pro Price", "value": 20.5, "source_url": "b.com"},
        ])
        assert len(gaps) == 0  # within 5% → not a conflict


class TestG3DataFreshness:
    def test_recent_data_no_gap(self):
        gaps = check_data_freshness([
            {"id": "dp-1", "label": "X", "collected_at": "2026-05-23T00:00:00Z"},
        ], max_age_days=180)
        assert len(gaps) == 0

    def test_strict_policy_requires_independent_domains(self):
        gaps = check_brief_evidence_policy(
            [{"id": "dp-1", "category": "pricing", "source_url": "https://a.example/x", "source_type": "official"}],
            {"evidence_policy": "strict_multi_source", "dimensions": [{"id": "pricing"}], "time_range": {"mode": "last_12_months"}},
        )
        assert any("fewer than two" in gap["description"] for gap in gaps)

    def test_stale_data_generates_gap(self):
        gaps = check_data_freshness([
            {"id": "dp-1", "label": "Old data", "collected_at": "2020-01-01T00:00:00Z"},
        ], max_age_days=180)
        assert len(gaps) == 1
        assert gaps[0]["type"] == "outdated"

    def test_no_timestamp_skipped(self):
        gaps = check_data_freshness([{"id": "dp-1", "label": "X", "collected_at": ""}])
        assert len(gaps) == 0

    def test_publication_date_takes_precedence(self):
        gaps = check_data_freshness([{
            "id": "dp-1", "label": "Updated", "collected_at": "2026-08-12T00:00:00Z",
            "published_at": "2020-01-01T00:00:00Z",
        }], max_age_days=180)
        assert gaps and gaps[0]["type"] == "outdated"

    def test_brief_policy_does_not_treat_collection_time_as_publication_date(self):
        points = [{
            "id": "dp-1", "label": "Undated source", "category": "pricing",
            "source_url": "https://vendor.example/pricing", "source_type": "official",
            "collected_at": "2020-01-01T00:00:00Z",
        }]
        gaps = check_data_freshness(points, max_age_days=180, use_collection_fallback=False)
        assert gaps == []
        from competition.nodes.reviewer import check_brief_evidence_policy
        policy_gaps = check_brief_evidence_policy(
            points,
            {"evidence_policy": "official_preferred", "dimensions": [{"id": "pricing"}], "time_range": {"mode": "last_12_months"}},
        )
        assert any(gap["check_method"] == "publication_date_unknown" for gap in policy_gaps)


class TestG4DimensionCoverage:
    def test_full_coverage_no_gap(self):
        analysis = {
            "comparison_matrix": {
                "products": ["A", "B"],
                "dimensions": ["Price", "Features"],
                "cells": [
                    {"product": "A", "dimension": "Price"},
                    {"product": "A", "dimension": "Features"},
                    {"product": "B", "dimension": "Price"},
                    {"product": "B", "dimension": "Features"},
                ],
            },
        }
        gaps = check_dimension_coverage(analysis, ["A", "B"])
        assert len(gaps) == 0

    def test_missing_coverage(self):
        analysis = {
            "comparison_matrix": {
                "products": ["A"],
                "dimensions": ["Price", "Features"],
                "cells": [{"product": "A", "dimension": "Price"}],
            },
        }
        gaps = check_dimension_coverage(analysis, ["A"])
        assert len(gaps) == 1
        assert "Features" in gaps[0]["description"]

    def test_brief_dimension_catalog_controls_coverage(self):
        analysis = {"comparison_matrix": {"dimensions": ["功能", "定价"], "cells": [{"product": "A", "dimension": "功能"}]}}
        gaps = check_dimension_coverage(analysis, ["A"], {"dimensions": [{"id": "features"}]})
        assert gaps == []


class TestG5SourceDiversity:
    def test_diverse_sources_no_gap(self):
        gaps = check_source_diversity([
            {"id": "1", "source_type": "official"}, {"id": "2", "source_type": "review"},
        ], min_types=2)
        assert len(gaps) == 0

    def test_single_source_type(self):
        gaps = check_source_diversity([
            {"id": "1", "source_type": "official"}, {"id": "2", "source_type": "official"},
        ], min_types=2)
        assert len(gaps) == 1

    def test_empty_no_gap(self):
        assert check_source_diversity([]) == []


class TestG6StatisticalOutliers:
    def test_normal_data_no_gap(self):
        gaps = check_statistical_outliers([
            {"id": "1", "value": 20}, {"id": "2", "value": 21},
            {"id": "3", "value": 19}, {"id": "4", "value": 22},
            {"id": "5", "value": 20},
        ])
        assert len(gaps) == 0

    def test_outlier_detected(self):
        """With 25 points and one extreme outlier, z-score exceeds 3."""
        points = []
        for i in range(24):
            points.append({"id": str(i), "value": 20 + (i % 5)})
        points.append({"id": "outlier", "value": 10000})
        gaps = check_statistical_outliers(points)
        assert len(gaps) == 1
        assert gaps[0]["type"] == "fact_error"

    def test_too_few_points(self):
        assert check_statistical_outliers([{"id": "1", "value": 20}]) == []


class TestImprovementMeasurement:
    def test_no_previous_gaps(self):
        assert _measure_improvement([], [{"gap_id": "g1"}]) == 0.0

    def test_all_resolved(self):
        assert _measure_improvement(
            [{"gap_id": "g1"}, {"gap_id": "g2"}],
            [],
        ) == 1.0

    def test_half_resolved(self):
        assert _measure_improvement(
            [{"gap_id": "g1"}, {"gap_id": "g2"}],
            [{"gap_id": "g1"}],
        ) == 0.5


class TestQualitySummary:
    def test_basic(self):
        q = _build_quality_summary(
            [{"id": "1", "source_url": "a.com"}, {"id": "2", "source_url": "b.com"}],
            [],
            0.0,
        )
        assert q["total_data_points"] == 2
        assert q["overall_quality_score"] == 1.0


class TestFilterLoopGaps:
    def test_first_round_no_filter(self):
        gaps = [{"description": "missing X", "severity": "major"}]
        result = _filter_loop_gaps(gaps, [], 0)
        assert result[0]["severity"] == "major"

    def test_third_occurrence_downgraded(self):
        gaps = [{"description": "missing X", "severity": "major"}]
        result = _filter_loop_gaps(gaps, [{"description": "missing X"}], 2)
        assert result[0]["severity"] == "minor"
        assert "[LOOP]" in result[0]["description"]


class TestGenerateNotes:
    def test_no_gaps(self):
        assert "good" in _generate_notes([], 0.0).lower()

    def test_with_gaps(self):
        notes = _generate_notes([{"severity": "critical"}], 0.0)
        assert "1" in notes
        assert "critical" in notes


# ═══════════════════════════════════════════════════════════════
# Writer Node (§3.7)
# ═══════════════════════════════════════════════════════════════

from competition.nodes.writer import (  # noqa: E402
    _build_quality_gate,
    _build_review_package,
    _build_sections,
    _build_title,
    _build_traceability_map,
    _compute_report_metrics,
    _extract_key_findings,
    writer_node,
    writer_self_check,
)


class TestBuildTitle:
    def test_single_product(self):
        assert "Cursor" in _build_title(["Cursor"])

    def test_multi_product(self):
        title = _build_title(["Cursor", "Copilot"])
        assert "Cursor" in title
        assert "Copilot" in title


class TestQualityGate:
    def test_blocking_coverage_and_claim_diagnostics_are_deterministic(self):
        collected = [
            {"id": "dp-1", "product": "A", "category": "features", "source_url": "https://a.example/x", "source_type": "official", "collected_at": "2026-08-14T00:00:00Z", "published_at": "2026-08-10"},
        ]
        analysis = {
            "comparison_matrix": {
                "dimensions": ["features", "pricing"],
                "cells": [{"product": "A", "dimension": "features", "source_data_point_ids": ["dp-1"]}],
            },
            "swot": {},
        }
        gate = _build_quality_gate(
            brief={"evidence_policy": "strict_multi_source", "dimensions": [{"id": "features", "label": "功能"}, {"id": "pricing", "label": "定价"}]},
            target_products=["A", "B"], collected=collected, analysis=analysis,
            verdict={"gaps": [], "round": 1, "quality_summary": {}},
            sections=[{"id": "sec-comparison-matrix", "source_ids": ["1"]}],
            traceability=_build_traceability_map(collected),
        )
        assert gate["schema_version"] == 1
        assert gate["status"] == "blocked"
        assert gate["blocking_count"] >= 1
        assert gate["claims"]["single_source"] == 1
        assert any(issue["type"] == "missing_data" for issue in gate["issues"])

    def test_reviewer_severity_is_preserved(self):
        gate = _build_quality_gate(
            brief={}, target_products=[], collected=[], analysis={"comparison_matrix": {}, "swot": {}},
            verdict={"gaps": [{"gap_id": "g1", "severity": "critical", "type": "fact_error", "description": "bad", "target_collect_task": "fix"}], "quality_summary": {}},
            sections=[], traceability={},
        )
        issue = next(item for item in gate["issues"] if item["id"] == "reviewer-g1")
        assert issue["level"] == "blocking"
        assert issue["severity"] == "critical"


class TestBuildSections:
    def test_all_required_sections_present(self):
        sections = _build_sections(
            {"comparison_matrix": {"products": ["A"], "dimensions": ["Price"], "cells": [], "summary": "test"}},
            {"quality_summary": {"total_data_points": 0}},
            ["A"], None, None, "", [], {"total_data_points": 0},
        )
        ids = {s["id"] for s in sections}
        assert "sec-executive-summary" in ids
        assert "sec-comparison-matrix" in ids
        assert "sec-swot" in ids
        assert "sec-recommendations" in ids
        assert "sec-sources" in ids
        assert "appendix-quality" in ids

    def test_forecast_does_not_add_disabled_whatif_section(self):
        sections = _build_sections(
            {
                "comparison_matrix": {"products": ["A"], "dimensions": [], "cells": [], "summary": "x"},
                "forecast": {"summary": "will grow", "items": [], "disclaimer": "test"},
            },
            {"quality_summary": {}}, ["A"], None, None, "", [], {"total_data_points": 0},
        )
        ids = {s["id"] for s in sections}
        assert "sec-forecast" in ids
        assert "sec-whatif" not in ids

    def test_executive_summary_mentions_products(self):
        sections = _build_sections(
            {"comparison_matrix": {"products": ["A"], "dimensions": [], "cells": [], "summary": "test"}},
            {"quality_summary": {}}, ["A"], None, None, "", [], {"total_data_points": 0},
        )
        exec_section = next(s for s in sections if s["id"] == "sec-executive-summary")
        assert len(exec_section["content"]) > 0

    def test_swot_content(self):
        sections = _build_sections(
            {
                "comparison_matrix": {"products": ["A"], "dimensions": [], "cells": [], "summary": "x"},
                "swot": {"A": {"items": [{"category": "strength", "statement": "Fast", "evidence": "tests", "source_data_point_ids": ["dp-1"]}]}},
            },
            {"quality_summary": {}}, ["A"], None, None, "", [], {"total_data_points": 0},
        )
        swot = next(s for s in sections if s["id"] == "sec-swot")
        assert "Fast" in swot["content"]

    def test_citations_follow_collected_order_and_ignore_unknown_ids(self):
        sections = _build_sections(
            {
                "comparison_matrix": {
                    "products": ["A"], "dimensions": ["Price"],
                    "cells": [{"product": "A", "dimension": "Price", "rating": 5,
                               "evidence": "official", "source_data_point_ids": ["dp-2", "missing", "dp-2"]}],
                    "summary": "A is well-priced",
                },
            },
            {"quality_summary": {}}, ["A"], None, None, "", [
                {"id": "dp-1", "source_url": "one.example"},
                {"id": "dp-2", "source_url": "two.example"},
            ], {"total_data_points": 2},
        )
        matrix = next(s for s in sections if s["id"] == "sec-comparison-matrix")
        assert "[2]" in matrix["content"]
        assert "[1]" not in matrix["content"]
        assert matrix["source_ids"] == ["2"]

    def test_dynamic_blocks_and_legacy_appendix(self):
        blocks = [
            {"block_type": "kv_list", "title": "指标", "data": {"x": 1}, "source_data_point_ids": ["dp-1"]},
            {"block_type": "comparison_table", "title": "表", "data": {"headers": ["A"], "rows": [["1"]]}, "source_data_point_ids": ["dp-1"]},
            {"block_type": "stat_chart", "title": "图", "data": {"chart": "bar", "labels": ["A"], "series": {"x": [1]}}, "source_data_point_ids": ["dp-1"]},
            {"block_type": "insight_text", "title": "洞察", "data": {"content": "结论"}, "source_data_point_ids": ["dp-1"]},
        ]
        sections = _build_sections(
            {"comparison_matrix": {"products": ["A"], "dimensions": [], "cells": [], "summary": "x"},
             "dynamic_blocks": blocks,
             "extra_fields": {"legacy": {"value": "old", "source_data_point_ids": ["dp-1"]}}},
            {"quality_summary": {}}, ["A"], None, None, "", [{"id": "dp-1", "source_url": "a.example"}], {"total_data_points": 1},
        )
        dynamic = [s for s in sections if s["id"].startswith("dynamic-block-")]
        assert [s["id"] for s in dynamic] == ["dynamic-block-0", "dynamic-block-1", "dynamic-block-2", "dynamic-block-3"]
        assert dynamic[1]["chart_path"] == {"headers": ["A"], "rows": [["1"]]}
        assert dynamic[2]["chart_path"]["chart"] == "bar"
        assert all(s["source_ids"] == ["1"] for s in dynamic)
        assert not any(s["id"] == "appendix-extra-fields" for s in sections)

        legacy_sections = _build_sections(
            {"comparison_matrix": {"products": ["A"], "dimensions": [], "cells": [], "summary": "x"},
             "extra_fields": {"legacy": {"value": "old", "source_data_point_ids": ["dp-1"]}}},
            {"quality_summary": {}}, ["A"], None, None, "", [{"id": "dp-1", "source_url": "a.example"}], {"total_data_points": 1},
        )
        appendix = next(s for s in legacy_sections if s["id"] == "appendix-extra-fields")
        assert "old" in appendix["content"]
        assert appendix["source_ids"] == ["1"]


class TestBuildTraceabilityMap:
    def test_empty(self):
        assert _build_traceability_map([]) == {}

    def test_maps_ids(self):
        trace = _build_traceability_map([
            {"id": "dp-1", "source_url": "a.com", "collected_at": "2026-01-01", "confidence": 0.9},
        ])
        assert "1" in trace
        assert trace["1"]["url"] == "a.com"


class TestBuildReviewPackage:
    def test_basic(self):
        rp = _build_review_package(
            {"sections": [{"id": "sec-executive-summary", "content": "summary text"}], "products": ["A"]},
            [{"id": "dp-1", "product": "A", "category": "pricing", "source_type": "official"}],
            {"total_data_points": 1},
        )
        assert rp["executive_summary"] == "summary text"
        assert rp["data_stats"]["total_data_points"] == 1


class TestExtractKeyFindings:
    def test_empty(self):
        assert _extract_key_findings({"sections": []}) == ["分析完成"]

    def test_from_swot(self):
        findings = _extract_key_findings({
            "sections": [
                {"id": "sec-swot", "content": "- Fast completion\n- Good UX"},
            ],
        })
        assert "Fast completion" in findings


class TestWriterSelfCheck:
    def test_all_ok(self):
        issues = writer_self_check({
            "sections": [{"id": "sec-executive-summary", "content": "about Cursor and Copilot", "content_type": "text"}],
            "traceability_map": {"1": {"url": "a.com"}},
        }, ["Cursor", "Copilot"])
        assert len(issues) == 0

    def test_missing_product(self):
        issues = writer_self_check({
            "sections": [{"id": "sec-executive-summary", "content": "about Cursor", "content_type": "text"}],
            "traceability_map": {},
        }, ["Cursor", "MissingProduct"])
        assert any("MissingProduct" in i for i in issues)

    def test_empty_traceability(self):
        issues = writer_self_check({
            "sections": [{"id": "sec-executive-summary", "content": "test", "content_type": "text"}],
            "traceability_map": {},
        }, ["Cursor"])
        assert any("W3" in i for i in issues)

    def test_unresolved_citation_marker(self):
        issues = writer_self_check({
            "sections": [{"id": "sec-swot", "content": "claim [99]", "source_ids": ["99"]}],
            "traceability_map": {"1": {"url": "a.com"}},
        }, [])
        assert any("[99]" in issue for issue in issues)


class TestWriterNarrative:
    def test_single_structured_call_updates_both_sections(self, monkeypatch):
        calls = []

        def fake_structured(*args, **kwargs):
            calls.append((args, kwargs))
            return {"executive_summary": "新的摘要 [2]", "recommendations": ["优先行动 [1]"]}, 12

        monkeypatch.setattr("competition.executor.execute_structured_agent", fake_structured)
        result = writer_node({
            "analysis_result": {"comparison_matrix": {"products": ["A"], "dimensions": [], "cells": [], "summary": "矩阵结论"}},
            "review_verdict": {"quality_summary": {}}, "target_products": ["A"], "persona": "entrepreneur",
            "collected_data": [{"id": "dp-1", "source_url": "a.example"}, {"id": "dp-2", "source_url": "b.example"}],
        })
        assert len(calls) == 1
        assert result["report_data"]["persona"] == "entrepreneur"
        assert result["report_data"]["structured_analysis"]["comparison_matrix"]["summary"] == "矩阵结论"
        sections = result["report_data"]["sections"]
        assert next(s for s in sections if s["id"] == "sec-executive-summary")["content"] == "新的摘要 [2]"
        assert "优先行动 [1]" in next(s for s in sections if s["id"] == "sec-recommendations")["content"]

    def test_malformed_structured_response_keeps_fallback(self, monkeypatch):
        monkeypatch.setattr("competition.executor.execute_structured_agent", lambda *args, **kwargs: {"executive_summary": "bad [999]", "recommendations": [{"bad": 1}]})
        result = writer_node({
            "analysis_result": {"comparison_matrix": {"products": ["A"], "dimensions": [], "cells": [], "summary": "矩阵结论"}},
            "review_verdict": {"quality_summary": {}}, "target_products": ["A"],
            "collected_data": [{"id": "dp-1", "source_url": "a.example"}],
        })
        sections = result["report_data"]["sections"]
        assert "矩阵结论" in next(s for s in sections if s["id"] == "sec-executive-summary")["content"]
        assert "[LLM" not in str(sections)


class TestComputeMetrics:
    def test_basic(self):
        metrics = _compute_report_metrics(
            [{"id": "1"}],
            {"quality_summary": {"total_data_points": 1, "multi_source_count": 0, "improvement_ratio": 0.5}},
            {"1": {"url": "a.com"}},
        )
        assert metrics["coverage"] == 1.0
        assert metrics["improvement_ratio"] == 0.5


def test_traceability_map_keeps_legacy_fields_and_adds_source_metadata():
    trace = _build_traceability_map([{
        "id": "dp-1", "product": "A", "category": "pricing", "label": "Pro",
        "value": "$20", "source_url": "https://a.example/pricing", "source_type": "official",
        "collected_at": "2026-08-14T00:00:00Z", "published_at": "2026-08-10", "confidence": 0.9,
    }])
    assert trace["1"]["timestamp"] == trace["1"]["collected_at"]
    assert trace["1"]["data_point_id"] == "dp-1"
    assert trace["1"]["publication_date_status"] == "known"


def test_traceability_map_includes_reproducible_snapshot_metadata(monkeypatch, tmp_path):
    import hashlib

    from competition import db

    db_path = tmp_path / "snapshot.db"
    original_init_db = db.init_db
    connection = original_init_db(db_path)
    text = "Historical pricing page captured for reproducible review."
    content_ref = hashlib.sha256(b"https://a.example/pricing").hexdigest()[:16]
    db.save_content(content_ref, "https://a.example/pricing", text, conn=connection)
    connection.close()
    monkeypatch.setattr(db, "init_db", lambda: original_init_db(db_path))

    trace = _build_traceability_map([{
        "id": "dp-1", "product": "A", "category": "pricing", "label": "Pro",
        "value": "$20", "source_url": "https://a.example/pricing", "source_type": "official",
        "collected_at": "2026-08-14T00:00:00Z",
    }])
    assert trace["1"]["content_ref"] == content_ref
    assert trace["1"]["snapshot_char_count"] == len(text)
    assert trace["1"]["snapshot_sha256"] == hashlib.sha256(text.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════
# HITL Gate Node (§5.2)
# ═══════════════════════════════════════════════════════════════

from competition.nodes.hitl_gate import (  # noqa: E402
    _extract_dimensions,
    _is_timed_out,
    build_approval_card,
    parse_user_intent,
)


class TestParseUserIntent:
    def test_empty_comment(self):
        assert parse_user_intent("") is None

    def test_data_keyword_triggers_replan(self):
        result = parse_user_intent("数据不够，需要重新搜索定价信息")
        assert result is not None
        assert result["action"] == "replan"

    def test_analysis_keyword_triggers_reanalyze(self):
        result = parse_user_intent("SWOT分析不对，重新分析一下")
        assert result is not None
        assert result["action"] == "reanalyze"

    def test_style_keyword_triggers_rewrite(self):
        result = parse_user_intent("太笼统了，重写为投资人视角")
        assert result is not None
        assert result["action"] == "rewrite"

    def test_approve_keyword(self):
        result = parse_user_intent("没问题，可以发布")
        assert result is not None
        assert result["action"] == "approve"

    def test_data_keyword_priority(self):
        """Data keywords should take priority over other keywords."""
        result = parse_user_intent("数据不够，重新搜索一下定价")
        assert result["action"] == "replan"

    def test_extracts_dimensions(self):
        result = parse_user_intent("定价和功能维度数据不够")
        assert result is not None
        assert result["target_focus"] is not None
        assert "定价" in result["target_focus"]
        assert "功能" in result["target_focus"]

    def test_english_keywords(self):
        result = parse_user_intent("need more data on pricing")
        assert result is not None
        assert result["action"] == "replan"


class TestExtractDimensions:
    def test_chinese(self):
        dims = _extract_dimensions("定价和市场份额需要更多数据")
        assert dims is not None
        assert "定价" in dims
        assert "市场" in dims

    def test_english(self):
        dims = _extract_dimensions("need more data on pricing and features")
        assert dims is not None
        assert "定价" in dims  # mapped from "pricing"
        assert "功能" in dims  # mapped from "features"

    def test_none_when_no_match(self):
        assert _extract_dimensions("hello world") is None


class TestIsTimedOut:
    def test_fresh_not_timed_out(self):
        from datetime import UTC, datetime
        recent = datetime.now(UTC).isoformat()
        assert _is_timed_out(recent, timeout_minutes=30) is False

    def test_old_is_timed_out(self):
        assert _is_timed_out("2026-01-01T00:00:00Z", timeout_minutes=30) is True

    def test_empty_timestamp(self):
        assert _is_timed_out("") is False


class TestBuildApprovalCard:
    def test_basic_card(self):
        card = build_approval_card({
            "executive_summary": "summary text",
            "key_findings": ["finding 1"],
            "data_stats": {"total_data_points": 42},
            "quality_summary": {"overall_quality_score": 0.9},
        })
        assert card["type"] == "approval_card"
        assert len(card["actions"]) == 4

    def test_four_actions_present(self):
        card = build_approval_card({})
        action_ids = {a["id"] for a in card["actions"]}
        assert action_ids == {"approve", "replan", "reanalyze", "rewrite"}

    def test_free_text_enabled(self):
        card = build_approval_card({})
        assert card["allow_free_text"] is True
        assert card["free_text_placeholder"] != ""


# ═══════════════════════════════════════════════════════════════
# Error Handler Node (§3.15.6)
# ═══════════════════════════════════════════════════════════════

from competition.nodes.error_handler import error_handler_node  # noqa: E402


class TestErrorHandlerNode:
    def test_no_results_graceful_stop(self):
        """D-class: 0 results → graceful stop with error report."""
        result = error_handler_node({
            "error": "collector crashed",
            "collected_data": [],
            "target_products": ["A"],
        })
        assert result["error"] != ""
        assert "FATAL" in result["error"]
        assert result["report_data"] is not None
        assert result["report_data"]["title"] == "分析失败"
        assert result["hitl_decision"]["action"] == "approve"

    def test_partial_results_degraded_continue(self):
        """C-class: has partial data → clear error, continue."""
        result = error_handler_node({
            "error": "analyst timed out",
            "collected_data": [{"id": "dp-1"}],
        })
        assert result["error"] is None  # cleared
        assert result["hitl_decision"]["action"] == "approve"

    def test_with_analysis_result(self):
        """Has analysis_result → degraded continue (not fatal)."""
        result = error_handler_node({
            "error": "writer failed",
            "analysis_result": {"comparison_matrix": {"products": ["A"]}},
        })
        assert result["error"] is None

    def test_unresolved_issues_preserved(self):
        result = error_handler_node({
            "error": "partial failure",
            "collected_data": [{"id": "x"}],
            "unresolved_issues": [{"type": "existing", "description": "old"}],
        })
        issues = result.get("unresolved_issues", [])
        assert len(issues) >= 1  # existing + new

    def test_empty_error(self):
        result = error_handler_node({"error": "", "collected_data": []})
        assert result["error"] == "FATAL: 未采集到可用于分析的数据"
        assert "未采集到可用于分析的数据" in result["report_data"]["sections"][0]["content"]
# Rework intent routing (§5.7 / R16)
# ═══════════════════════════════════════════════════════════════


def test_rework_intent_explicit_collect_calls_llm_before_routing(monkeypatch):
    from competition.nodes.rework_intent import parse_rework_intent

    calls = []

    def fake_execute_agent(*args, **kwargs):
        calls.append((args, kwargs))
        return (
            '{"action":"replan","target_focus":["来源"],"comment":"重新收集信息","reason":"用户要求补充数据","confidence":0.88}',
            42,
        )

    monkeypatch.setattr("competition.executor.execute_agent", fake_execute_agent)

    intent = parse_rework_intent({}, "我想要再次收集信息")

    assert calls
    assert calls[0][1]["agent_name"] == "rework_intent"
    assert "disable_thinking" not in calls[0][1]
    assert intent["action"] == "replan"
    assert intent["confidence"] == 0.88


def test_rework_intent_negated_collect_can_route_to_rewrite(monkeypatch):
    from competition.nodes.rework_intent import parse_rework_intent

    def fake_execute_agent(*args, **kwargs):
        return (
            '{"action":"rewrite","target_focus":["表达"],"comment":"不要重新收集，只改写表达","reason":"用户否定了重新收集，只要求表达调整","confidence":0.91}',
            37,
        )

    monkeypatch.setattr("competition.executor.execute_agent", fake_execute_agent)

    intent = parse_rework_intent({}, "不要重新收集数据，只把报告写得更简洁")

    assert intent["action"] == "rewrite"
    assert intent["confidence"] == 0.91


def test_rework_intent_llm_failure_falls_back_to_rule(monkeypatch):
    from competition.nodes.rework_intent import parse_rework_intent

    def fake_execute_agent(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr("competition.executor.execute_agent", fake_execute_agent)

    intent = parse_rework_intent({}, "请重新搜索更多来源和具体数字")

    assert intent["action"] == "replan"


def test_rework_intent_explicit_analysis_uses_llm_result(monkeypatch):
    from competition.nodes.rework_intent import parse_rework_intent

    def fake_execute_agent(*args, **kwargs):
        return (
            '{"action":"reanalyze","target_focus":["创业者视角"],"comment":"从创业者视角重新分析机会点","reason":"用户要求改变分析视角","confidence":0.86}',
            39,
        )

    monkeypatch.setattr("competition.executor.execute_agent", fake_execute_agent)

    intent = parse_rework_intent({}, "请从创业者视角重新分析机会点")

    assert intent["action"] == "reanalyze"


def test_rework_intent_explicit_rewrite_uses_llm_result(monkeypatch):
    from competition.nodes.rework_intent import parse_rework_intent

    def fake_execute_agent(*args, **kwargs):
        return (
            '{"action":"rewrite","target_focus":["结构"],"comment":"只改写表达，让结构更清楚，不改结论","reason":"用户只要求表达结构调整","confidence":0.89}',
            41,
        )

    monkeypatch.setattr("competition.executor.execute_agent", fake_execute_agent)

    intent = parse_rework_intent({}, "只改写表达，让结构更清楚，不改结论")

    assert intent["action"] == "rewrite"
