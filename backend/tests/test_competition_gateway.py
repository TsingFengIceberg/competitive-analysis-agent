"""Tests for app/gateway/routers/competition.py — API endpoints."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request


@pytest_asyncio.fixture
async def client(monkeypatch):
    """Create an async HTTP client for the competition router."""
    from types import SimpleNamespace

    from fastapi import FastAPI

    import app.competition_router as competition_router

    monkeypatch.setattr(
        competition_router,
        "_resolve_and_run_graph",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        competition_router,
        "asyncio",
        SimpleNamespace(
            get_event_loop=lambda: SimpleNamespace(
                run_in_executor=lambda *_args, **_kwargs: None,
            ),
        ),
    )

    app = FastAPI()
    app.include_router(competition_router.router)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


class TestPostAnalyze:
    @pytest.mark.asyncio
    async def test_basic_request(self, client):
        response = await client.post("/api/competition/analyze", json={
            "query": "analyze Cursor vs Copilot",
            "target_products": ["Cursor", "Copilot"],
            "persona": "pm",
        })
        assert response.status_code == 200
        data = response.json()
        assert "thread_id" in data
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_with_industry(self, client):
        response = await client.post("/api/competition/analyze", json={
            "query": "analyze",
            "target_products": ["A"],
            "industry": "devtools",
        })
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_entrepreneur_persona(self, client):
        response = await client.post("/api/competition/analyze", json={
            "query": "analyze",
            "target_products": ["A"],
            "persona": "entrepreneur",
        })
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_missing_required_field(self, client):
        response = await client.post("/api/competition/analyze", json={
            "target_products": [],
        })
        assert response.status_code == 422  # Validation error


class TestGetReport:
    @pytest.mark.asyncio
    async def test_not_found(self, client):
        response = await client.get("/api/competition/report/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_running_report(self, client):
        # Create an analysis first
        create = await client.post("/api/competition/analyze", json={
            "query": "test", "target_products": ["A"],
        })
        thread_id = create.json()["thread_id"]

        response = await client.get(f"/api/competition/report/{thread_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "awaiting_confirmation"
        assert data["analysis_brief"]["target_products"] == ["A"]


class TestStream:
    @pytest.mark.asyncio
    async def test_not_found(self, client):
        response = await client.get("/api/competition/stream/nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_stream_response(self, client):
        import app.competition_router as competition_router

        create = await client.post("/api/competition/analyze", json={
            "query": "test", "target_products": ["A"],
        })
        thread_id = create.json()["thread_id"]
        request = Request({"type": "http", "headers": []})
        with pytest.raises(Exception) as exc_info:
            await competition_router.stream(thread_id, request)
        assert getattr(exc_info.value, "status_code", None) == 409

    @pytest.mark.asyncio
    async def test_confirm_starts_same_thread(self, client, monkeypatch):
        import app.competition_router as competition_router

        submitted = []
        monkeypatch.setattr(
            competition_router,
            "_start_analysis_worker",
            lambda *args, **kwargs: submitted.append((args, kwargs)),
        )
        create = await client.post("/api/competition/analyze", json={
            "query": "最好的 AI 编程工具有哪些？",
        })
        assert create.json()["status"] == "awaiting_confirmation"
        thread_id = create.json()["thread_id"]
        brief = create.json()["analysis_brief"]
        brief["target_products"] = ["Cursor", "Copilot"]
        response = await client.post(f"/api/competition/{thread_id}/confirm", json={
            "expected_revision": brief["revision"],
            "brief": brief,
        })
        assert response.status_code == 200
        assert response.json()["thread_id"] == thread_id
        assert response.json()["status"] == "running"
        assert len(submitted) == 1

    @pytest.mark.asyncio
    async def test_duplicate_confirmation_is_idempotent(self, client, monkeypatch):
        import app.competition_router as competition_router
        starts = []
        monkeypatch.setattr(competition_router, "_start_analysis_worker", lambda *args, **kwargs: starts.append(args))
        create = await client.post("/api/competition/analyze", json={"query": "最好的 AI 工具有哪些？"})
        thread_id = create.json()["thread_id"]
        brief = create.json()["analysis_brief"]
        brief["target_products"] = ["A", "B"]
        payload = {"expected_revision": brief["revision"], "brief": brief}
        first = await client.post(f"/api/competition/{thread_id}/confirm", json=payload)
        second = await client.post(f"/api/competition/{thread_id}/confirm", json=payload)
        assert first.status_code == second.status_code == 200
        assert len(starts) == 1

    @pytest.mark.asyncio
    async def test_stale_confirmation_is_rejected(self, client):
        create = await client.post("/api/competition/analyze", json={"query": "最好的 AI 工具有哪些？"})
        thread_id = create.json()["thread_id"]
        brief = create.json()["analysis_brief"]
        brief["target_products"] = ["A", "B"]
        response = await client.post(f"/api/competition/{thread_id}/confirm", json={"expected_revision": 99, "brief": brief})
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_waiting_persists_interrupted(self, client):
        create = await client.post("/api/competition/analyze", json={"query": "最好的 AI 工具有哪些？"})
        thread_id = create.json()["thread_id"]
        response = await client.post(f"/api/competition/{thread_id}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "interrupted"
        report = await client.get(f"/api/competition/report/{thread_id}")
        assert report.json()["status"] == "interrupted"

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
    @pytest.mark.asyncio
    async def test_empty_history(self, client):
        response = await client.get("/api/competition/history")
        assert response.status_code == 200
        data = response.json()
        assert "history" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_after_analysis(self, client):
        await client.post("/api/competition/analyze", json={
            "query": "test", "target_products": ["A"],
        })
        response = await client.get("/api/competition/history")
        assert response.json()["total"] >= 1
