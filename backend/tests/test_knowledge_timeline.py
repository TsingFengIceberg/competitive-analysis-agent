from competition.knowledge_timeline import build_knowledge_timeline


def _event(document_id: str, value: str, *, authority: str, current: bool) -> dict:
    return {
        "document_id": document_id,
        "version_no": 1,
        "current_version": 1,
        "title": document_id,
        "product": "Cursor",
        "dimension": "pricing",
        "source_uri": f"https://{document_id}.example/pricing",
        "authority_tier": authority,
        "content_hash": f"hash-{document_id}",
        "valid_from": "2026-08-27T00:00:00+00:00",
        "valid_to": None,
        "is_current": current,
        "excerpt": value,
    }


def test_timeline_detects_numeric_source_conflicts_and_prefers_authority():
    result = build_knowledge_timeline(
        [
            _event("official", "Cursor Pro costs $20 monthly", authority="primary", current=True),
            _event("review", "Cursor Pro costs $25 monthly", authority="third_party", current=True),
        ]
    )
    assert result["summary"]["conflict_count"] == 1
    conflict = result["conflicts"][0]
    assert conflict["type"] == "numeric_source_conflict"
    assert conflict["resolution"] == {
        "status": "resolved",
        "strategy": "higher_authority",
        "preferred_document_id": "official",
    }


def test_timeline_uses_full_version_text_without_exposing_it():
    official = _event(
        "official",
        "Controlled fixture without a numeric claim.",
        authority="primary",
        current=True,
    )
    official["comparison_text"] = "Disclaimer\n\nCursor Pro costs $20 monthly"
    review = _event(
        "review",
        "Independent review without a numeric claim.",
        authority="third_party",
        current=True,
    )
    review["comparison_text"] = "Disclaimer\n\nCursor Pro costs $25 monthly"

    result = build_knowledge_timeline([official, review])

    assert result["summary"]["conflict_count"] == 1
    assert all("comparison_text" not in event for event in result["events"])


def test_timeline_numeric_values_exclude_dates_and_unit_prefixes():
    official = _event(
        "official",
        "Published 2026-06-15. The plan costs USD 30 per user monthly.",
        authority="primary",
        current=True,
    )
    review = _event(
        "review",
        "Published 2026-07-01. The plan costs USD 25 per user monthly.",
        authority="third_party",
        current=True,
    )

    result = build_knowledge_timeline([official, review])

    assert result["events"][0]["numeric_values"] == ["30"]
    assert result["events"][1]["numeric_values"] == ["25"]
    assert result["conflicts"][0]["left"]["values"] == ["30"]
    assert result["conflicts"][0]["right"]["values"] == ["25"]


def test_timeline_links_document_versions_without_calling_them_source_conflicts():
    old = _event("official", "Cursor Pro costs $20 monthly", authority="primary", current=False)
    current = _event("official", "Cursor Pro costs $25 monthly", authority="primary", current=True)
    current.update(
        {
            "version_no": 2,
            "current_version": 2,
            "content_hash": "hash-v2",
            "valid_from": "2026-09-01T00:00:00+00:00",
        }
    )
    result = build_knowledge_timeline([current, old])
    newest = result["events"][0]
    assert newest["change_type"] == "version_changed"
    assert newest["previous_version_no"] == 1
    assert result["conflicts"] == []
