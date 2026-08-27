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
