"""Tests for the P0-B AnalysisContextPack read model."""

from datetime import UTC, datetime, timedelta

from competition.context_pack import build_analysis_context_pack
from competition.nodes.analyst import _build_analyst_task

NOW = datetime(2026, 8, 22, tzinfo=UTC)


def _item(*, product="Cursor", dimension="pricing", value="$20", domain="cursor.com", source_type="official", observed=None, label="Pro"):
    observed = observed or (NOW - timedelta(days=10)).isoformat()
    return {
        "item_key": f"{product}-{dimension}-{label}-{value}-{domain}",
        "product": product,
        "dimension": dimension,
        "label": label,
        "value": value,
        "source_url": f"https://{domain}/{dimension}",
        "canonical_url": f"https://{domain}/{dimension}",
        "source_type": source_type,
        "source_domain": domain,
        "scope": "Global / unspecified",
        "published_at": observed,
        "fetched_at": observed,
        "first_seen_at": observed,
        "last_seen_at": observed,
        "confidence": 0.9,
        "credibility_tier": "official" if source_type == "official" else "secondary",
        "status": "available",
        "payload": {},
    }


class Repo:
    def __init__(self, items):
        self.items = items

    def list_items(self, **_kwargs):
        return list(self.items)


def _state(**brief):
    return {
        "target_products": ["Cursor", "Codex"],
        "analysis_brief": {
            "target_products": ["Cursor", "Codex"],
            "market_scope": "Global / unspecified",
            "effective_dimensions": [
                {"id": "pricing", "label": "定价"},
                {"id": "features", "label": "功能"},
            ],
            "evidence_policy": "balanced",
            **brief,
        },
        "collected_data": [],
    }


def test_filters_products_dimensions_scope_and_time_window():
    items = [
        _item(product="Cursor", dimension="pricing"),
        _item(product="Cursor", dimension="market"),
        _item(product="Other", dimension="pricing"),
        _item(product="Cursor", dimension="pricing", observed=(NOW - timedelta(days=400)).isoformat()),
    ]
    state = _state(time_range={"mode": "last_12_months", "start": "2026-01-01", "end": "2026-08-22"})
    pack = build_analysis_context_pack(state, repository=Repo(items), now=NOW)
    assert pack["quality"]["evidence_count"] == 1
    assert len(pack["dimensions"]["pricing"]["items"]) == 1
    assert pack["dimensions"]["features"]["quality_state"] == "missing"


def test_strict_policy_marks_single_source_partial_and_official_preferred_fallback():
    item = _item(source_type="review", domain="review.example")
    strict = build_analysis_context_pack(_state(evidence_policy="strict_multi_source"), repository=Repo([item]), now=NOW)
    assert strict["dimensions"]["pricing"]["quality_state"] == "partial"
    assert "独立来源" in strict["dimensions"]["pricing"]["fallback_reason"]

    preferred = build_analysis_context_pack(_state(evidence_policy="official_preferred"), repository=Repo([item]), now=NOW)
    assert preferred["dimensions"]["pricing"]["quality_state"] == "fallback"
    assert preferred["quality"]["quality_state"] == "partial"


def test_stale_and_conflict_quality_states_are_explicit():
    stale = _item(observed=(NOW - timedelta(days=181)).isoformat())
    pack = build_analysis_context_pack(_state(), repository=Repo([stale]), now=NOW)
    assert pack["dimensions"]["pricing"]["quality_state"] == "stale"
    assert pack["quality"]["stale_evidence_count"] == 1

    conflict = build_analysis_context_pack(
        _state(),
        repository=Repo([_item(value="$20", domain="a.example"), _item(value="$25", domain="b.example")]),
        now=NOW,
    )
    assert conflict["dimensions"]["pricing"]["quality_state"] == "conflict"
    assert conflict["quality"]["quality_state"] == "conflict"
    assert conflict["quality"]["conflicts"]


def test_current_run_evidence_is_merged_and_overrides_durable_item():
    state = _state()
    state["collected_data"] = [{
        "id": "dp-current", "product": "Cursor", "category": "pricing", "label": "Pro",
        "value": "$22", "source_url": "https://cursor.com/pricing", "source_type": "pricing",
        "confidence": 0.95, "collected_at": NOW.isoformat(),
    }]
    pack = build_analysis_context_pack(state, repository=Repo([_item(value="$20")]), now=NOW)
    pricing = pack["dimensions"]["pricing"]["items"]
    assert len(pricing) == 1
    assert pricing[0]["value"] == "$22"
    assert pricing[0]["id"] == "dp-current"


def test_repository_failure_degrades_to_current_run_or_fetch_failed():
    class BrokenRepo:
        def list_items(self, **_kwargs):
            raise RuntimeError("database unavailable")

    state = _state()
    pack = build_analysis_context_pack(state, repository=BrokenRepo(), now=NOW)
    assert pack["quality"]["quality_state"] == "fetch_failed"
    assert "database unavailable" in pack["quality"]["fetch_error"]


def test_analyst_task_carries_context_quality_and_evidence_contract():
    task = _build_analyst_task({
        "target_products": ["Cursor"],
        "analysis_context_pack": {
            "quality": {"quality_state": "partial", "missing_dimensions": ["features"]},
            "scope": {"evidence_policy": "strict_multi_source"},
            "evidence": [{"id": "dp-1", "product": "Cursor", "dimension": "pricing", "value": "$20"}],
        },
    })
    assert "STRUCTURED ANALYSIS CONTEXT PACK" in task
    assert "strict_multi_source" in task
    assert "dp-1" in task
