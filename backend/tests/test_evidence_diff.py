from competition.evidence_diff import build_evidence_diff


def _snapshot(points):
    return {"report_data": {"analysis_context": {"quality": {"quality_state": "available"}}}, "collected_data": points}


def test_evidence_diff_classifies_added_removed_and_modified_facts():
    old = _snapshot([
        {"id": "old-1", "product": "Cursor", "category": "pricing", "label": "Pro", "value": "$20", "source_url": "https://cursor.com/pricing", "confidence": 0.8},
        {"id": "old-2", "product": "Cursor", "category": "features", "label": "Agent", "value": "yes", "source_url": "https://cursor.com/features", "confidence": 0.7},
    ])
    new = _snapshot([
        {"id": "new-1", "product": "Cursor", "category": "pricing", "label": "Pro", "value": "$25", "source_url": "https://cursor.com/pricing", "confidence": 0.9},
        {"id": "new-3", "product": "Cursor", "category": "market", "label": "Team", "value": "expanded", "source_url": "https://cursor.com/market", "confidence": 0.6},
    ])
    diff = build_evidence_diff(old, new, old_version=1, new_version=2)
    assert diff["schema_version"] == "evidence-diff.v1"
    assert diff["summary"] == {"added": 1, "removed": 1, "modified": 1, "unchanged": 0, "changed": 3}
    assert {item["change_type"] for item in diff["facts"]} == {"added", "removed", "modified"}
