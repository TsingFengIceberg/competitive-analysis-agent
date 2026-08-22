"""Tests for the durable competitive-intelligence pool (P0-A)."""

from __future__ import annotations

from competition.db import init_db
from competition.intelligence import build_intelligence_item, canonicalize_url, source_domain
from competition.intelligence_repo import IntelligenceRepository


def _point(value="20"):
    return {
        "product": "Cursor",
        "category": "pricing",
        "label": "Pro monthly price",
        "value": value,
        "confidence": 0.9,
        "source_url": "https://www.example.com/pricing?utm_source=test&plan=pro#plans",
        "source_type": "pricing",
        "collected_at": "2026-08-22T00:00:00+00:00",
        "published_at": "2026-08-20T00:00:00+00:00",
    }


def test_url_normalization_removes_tracking_and_domain_prefix():
    canonical = canonicalize_url(_point()["source_url"])
    assert canonical == "https://example.com/pricing?plan=pro"
    assert source_domain(canonical) == "example.com"


def test_item_identity_is_stable_and_scoped():
    first = build_intelligence_item(_point(), scope="Global")
    same = build_intelligence_item(_point(), scope="Global")
    other_scope = build_intelligence_item(_point(), scope="China")
    assert first.item_key == same.item_key
    assert first.content_hash == same.content_hash
    assert first.item_key != other_scope.item_key


def test_repository_deduplicates_and_versions_changed_content():
    conn = init_db(":memory:")
    repository = IntelligenceRepository(conn=conn)
    try:
        first = repository.ingest_collected_points([_point()], scope="Global")
        assert first["inserted"] == 1
        assert first["versions_created"] == 1

        unchanged = repository.ingest_collected_points([_point()], scope="Global")
        assert unchanged["unchanged"] == 1
        assert unchanged["versions_created"] == 0

        changed = repository.ingest_collected_points([_point("25")], scope="Global")
        assert changed["updated"] == 1
        assert changed["versions_created"] == 1

        items = repository.list_items(product="Cursor", dimension="pricing")
        assert len(items) == 1
        assert items[0]["value"] == "25"
        versions = repository.get_versions(items[0]["item_key"])
        assert len(versions) == 2
        assert versions[0]["payload"]["value"] == "20"
        assert versions[1]["payload"]["value"] == "25"
    finally:
        repository.close()
