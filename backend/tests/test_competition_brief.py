"""Pure tests for the P1.1 Analysis Brief builder."""

from __future__ import annotations

import pytest

from competition.brief import (
    brief_from_request,
    brief_from_request_with_optional_model,
    canonical_editable_payload,
    detect_confirmation_mode,
    extract_explicit_products,
    normalize_brief,
    normalize_products,
    validate_confirmation_brief,
)
from competition.schema import AnalysisBrief, BriefDimension


def test_explicit_comparison_is_ready():
    brief = brief_from_request("比较 Cursor 和 Copilot 的功能和定价")
    assert brief.target_products == ["Cursor", "Copilot"]
    assert brief.readiness == "ready"
    assert brief.ambiguities == []


def test_open_ended_request_needs_confirmation():
    brief = brief_from_request("最好的 AI 编程工具有哪些？")
    assert brief.readiness == "needs_confirmation"
    assert any(item.field == "target_products" for item in brief.ambiguities)


def test_product_normalization_is_stable():
    assert normalize_products([" Cursor, Copilot ", "cursor", "  "]) == ["Cursor", "Copilot"]
    assert extract_explicit_products("深度比较 Cursor vs Copilot") == ["Cursor", "Copilot"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [("先确认后开始 Cursor vs Copilot", "always"), ("先确认 Cursor vs Copilot，直接开始", "always"), ("Cursor vs Copilot，不用确认，直接开始", "skip")],
)
def test_confirmation_phrase_precedence(query, expected):
    assert detect_confirmation_mode(query) == expected


def test_explicit_confirmation_mode_wins():
    assert detect_confirmation_mode("Cursor vs Copilot，直接开始", "always") == "always"
    assert detect_confirmation_mode("Cursor vs Copilot", "skip") == "skip"


def test_confirmation_normalizes_and_increments_revision():
    draft = normalize_brief(
        "",
        editable=AnalysisBrief(
            target_products=["A", "B"],
            dimensions=[BriefDimension(id="features", weight=0.2), BriefDimension(id="pricing", weight=0.8)],
        ),
    )
    confirmed = validate_confirmation_brief(draft)
    assert confirmed.revision == draft.revision + 1
    assert confirmed.confirmation_source == "user"
    assert sum(item.weight for item in confirmed.dimensions) == pytest.approx(1.0)


def test_confirmation_rejects_too_few_products():
    draft = AnalysisBrief(target_products=["A"], dimensions=[BriefDimension(id="features", weight=1.0)])
    with pytest.raises(ValueError):
        validate_confirmation_brief(draft)


def test_confirmation_rejects_duplicate_dimensions():
    draft = AnalysisBrief(
        target_products=["A", "B"],
        dimensions=[
            BriefDimension(id="features", weight=0.5),
            BriefDimension(id="features", weight=0.5),
        ],
    )
    with pytest.raises(ValueError, match="不能重复"):
        validate_confirmation_brief(draft)


def test_confirmation_rejects_inverted_custom_dates():
    draft = AnalysisBrief(target_products=["A", "B"], dimensions=[BriefDimension(id="features", weight=1.0)])
    draft.time_range.mode = "custom"
    draft.time_range.start = "2026-08-14"
    draft.time_range.end = "2026-08-13"
    with pytest.raises(ValueError, match="开始日期"):
        validate_confirmation_brief(draft)


def test_canonical_payload_ignores_server_metadata():
    left = brief_from_request("Cursor vs Copilot")
    right = left.model_copy(update={"revision": 99, "confidence": 0.1, "readiness": "needs_confirmation"})
    assert canonical_editable_payload(left) == canonical_editable_payload(right)


def test_invalid_model_output_degrades_to_deterministic_defaults():
    brief = brief_from_request("Cursor vs Copilot", model_output={"dimensions": ["unknown"]})
    assert brief.target_products == ["Cursor", "Copilot"]
    assert brief.dimensions


def test_optional_model_call_is_bounded_and_open_ended_stays_waiting(monkeypatch):
    calls = []

    def fake_structured(*args, **kwargs):
        calls.append(kwargs)
        return ({"target_products": ["A", "B"]}, 12)

    monkeypatch.setattr("competition.executor.execute_structured_agent", fake_structured)
    brief = brief_from_request_with_optional_model("最好的 AI 编程工具有哪些？")
    assert calls[0]["agent_name"] == "BriefBuilder"
    assert calls[0]["timeout_seconds"] == 30
    assert calls[0]["max_retries"] == 0
    assert brief.readiness == "needs_confirmation"
