from __future__ import annotations

from competition.knowledge_sources import KnowledgeSourceConnector, SourceRepository


def test_source_update_resets_conditional_state(tmp_path):
    repository = SourceRepository(db_path=tmp_path / "sources.db")
    try:
        source = KnowledgeSourceConnector(name="Docs", uri="https://example.test/docs", user_id="owner")
        created = repository.save(source)
        repository.update_result(
            created["source_id"], "owner", etag="etag-1", content_hash="hash-1", last_status="failed", failure_count=3,
            cooldown_until="2099-01-01T00:00:00+00:00",
        )
        updated = repository.update_config(created["source_id"], "owner", uri="https://example.test/new", priority=100)
        assert updated and updated["uri"] == "https://example.test/new"
        assert updated["priority"] == 100
        assert updated["etag"] is None
        assert updated["content_hash"] is None
        assert updated["failure_count"] == 0
        assert updated["last_status"] == "idle"
    finally:
        repository.close()
