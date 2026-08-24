"""Regression tests for immutable report-version snapshots."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


def _entry(report: dict) -> dict:
    return {
        "status": "completed",
        "query": "compare Alpha and Beta",
        "products": ["Alpha", "Beta"],
        "token_usage": [{"label": "Writer", "tokens": 12}],
        "state": {
            "report_data": report,
            "analysis_brief": {"objective": "choose one"},
            "analysis_result": {"matrix": {"Alpha": 4}},
            "review_verdict": {"status": "pass"},
            "stage_results": [{"stage": "writer", "status": "completed"}],
            "usage_summary": {"total_tokens": 12},
            "collected_data": [{"id": "dp-1"}],
            "user_request": "compare Alpha and Beta",
        },
    }


@pytest.mark.asyncio
async def test_version_detail_returns_detached_complete_snapshot(monkeypatch, tmp_path):
    from fastapi import FastAPI

    import app.competition_router as router
    from competition.branchtree.store import BranchSnapshotStore

    store = BranchSnapshotStore(tmp_path / "versions.db")
    monkeypatch.setattr(router, "_history_store", store)
    thread_id = "version-detail-test"
    report = {"title": "Alpha vs Beta", "sections": [{"id": "s1", "content": "old"}]}
    router._store[thread_id] = _entry(report)
    version = router._persist_report_version(thread_id, "initial", generation_id="gen-1")
    assert version == 1

    # Mutating runtime state after persistence must not mutate the stored row.
    report["sections"][0]["content"] = "new"
    app = FastAPI()
    app.include_router(router.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/competition/report/{thread_id}/versions/1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot_status"] == "complete"
    assert payload["snapshot"]["report_data"]["sections"][0]["content"] == "old"
    assert payload["snapshot"]["analysis_result"] == {"matrix": {"Alpha": 4}}
    assert payload["snapshot"]["token_usage"][0]["tokens"] == 12
    router._store.pop(thread_id, None)
    store.close()


@pytest.mark.asyncio
async def test_missing_version_is_404(monkeypatch, tmp_path):
    from fastapi import FastAPI

    import app.competition_router as router
    from competition.branchtree.store import BranchSnapshotStore

    store = BranchSnapshotStore(tmp_path / "versions.db")
    monkeypatch.setattr(router, "_history_store", store)
    app = FastAPI()
    app.include_router(router.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/competition/report/missing/versions/99")
    assert response.status_code == 404
    store.close()


@pytest.mark.asyncio
async def test_human_edit_creates_child_version(monkeypatch, tmp_path):
    from fastapi import FastAPI

    import app.competition_router as router
    import competition.db as competition_db
    from competition.branchtree.store import BranchSnapshotStore

    store = BranchSnapshotStore(tmp_path / "versions.db")
    monkeypatch.setattr(router, "_history_store", store)
    monkeypatch.setattr(competition_db, "upsert_analysis", lambda **_kwargs: None)
    thread_id = "human-edit-version-test"
    router._store[thread_id] = _entry({"title": "Report", "sections": [{"id": "s1", "content": "old"}]})
    router._persist_report_version(thread_id, "initial", generation_id="gen-1")

    app = FastAPI()
    app.include_router(router.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/api/competition/report/{thread_id}/sections",
            json={"sections": [{"id": "s1", "content": "edited"}]},
        )
    assert response.status_code == 200
    assert response.json()["version"] == 2
    history = router._list_history(thread_id)
    assert [item["snapshot_status"] for item in history] == ["complete", "complete"]
    assert history[0]["report_data"]["sections"][0]["content"] == "old"
    assert history[1]["report_data"]["sections"][0]["content"] == "edited"
    router._store.pop(thread_id, None)
    store.close()


def test_legacy_metadata_is_classified_without_fabrication(monkeypatch, tmp_path):
    import app.competition_router as router
    from competition.branchtree.store import BranchSnapshotStore

    store = BranchSnapshotStore(tmp_path / "versions.db")
    monkeypatch.setattr(router, "_history_store", store)
    store.insert("legacy-test", None, "", "initial", {"report_data": {"title": "old"}})
    store.insert("legacy-test", 1, "", "rewrite", {})
    history = router._list_history("legacy-test")
    assert history[0]["snapshot_status"] == "complete"
    assert history[1]["snapshot_status"] == "unavailable"
    store.close()
