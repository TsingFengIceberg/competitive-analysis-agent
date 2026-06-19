"""Tests for app/gateway/routers/competition.py — API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a TestClient for the competition router."""
    from fastapi import FastAPI

    from app.competition_router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestPostAnalyze:
    def test_basic_request(self, client):
        response = client.post("/api/competition/analyze", json={
            "query": "analyze Cursor vs Copilot",
            "target_products": ["Cursor", "Copilot"],
            "persona": "pm",
        })
        assert response.status_code == 200
        data = response.json()
        assert "thread_id" in data
        assert data["status"] == "running"

    def test_with_deep_mode(self, client):
        response = client.post("/api/competition/analyze", json={
            "query": "analyze",
            "target_products": ["A"],
            "deep_mode": True,
        })
        assert response.status_code == 200

    def test_entrepreneur_persona(self, client):
        response = client.post("/api/competition/analyze", json={
            "query": "analyze",
            "target_products": ["A"],
            "persona": "entrepreneur",
        })
        assert response.status_code == 200

    def test_missing_required_field(self, client):
        response = client.post("/api/competition/analyze", json={
            "query": "analyze",
        })
        assert response.status_code == 422  # Validation error


class TestGetReport:
    def test_not_found(self, client):
        response = client.get("/api/competition/report/nonexistent")
        assert response.status_code == 404

    def test_running_report(self, client):
        # Create an analysis first
        create = client.post("/api/competition/analyze", json={
            "query": "test", "target_products": ["A"],
        })
        thread_id = create.json()["thread_id"]

        response = client.get(f"/api/competition/report/{thread_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("running", "completed", "failed")


class TestStream:
    def test_not_found(self, client):
        response = client.get("/api/competition/stream/nonexistent")
        assert response.status_code == 404

    def test_stream_response(self, client):
        create = client.post("/api/competition/analyze", json={
            "query": "test", "target_products": ["A"],
        })
        thread_id = create.json()["thread_id"]

        response = client.get(f"/api/competition/stream/{thread_id}")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

    def test_full_live_queue_drops_old_frame_instead_of_failing(self):
        import queue

        import app.competition_router as competition_router

        thread_id = "comp-test-full-queue"
        original_queue = competition_router._stream_queues.get(thread_id)
        try:
            q = queue.Queue(maxsize=1)
            q.put_nowait("stale-frame")
            competition_router._stream_queues[thread_id] = q

            competition_router._emit_event(thread_id, "end", {"status": "completed"})

            assert q.qsize() == 1
            frame = q.get_nowait()
            assert "event: end" in frame
            assert "stale-frame" not in frame
        finally:
            if original_queue is None:
                competition_router._stream_queues.pop(thread_id, None)
            else:
                competition_router._stream_queues[thread_id] = original_queue
            competition_router._event_buffers.pop(thread_id, None)
            competition_router._event_counters.pop(thread_id, None)


class TestHistory:
    def test_empty_history(self, client):
        response = client.get("/api/competition/history")
        assert response.status_code == 200
        data = response.json()
        assert "history" in data
        assert "total" in data

    def test_after_analysis(self, client):
        client.post("/api/competition/analyze", json={
            "query": "test", "target_products": ["A"],
        })
        response = client.get("/api/competition/history")
        assert response.json()["total"] >= 1
