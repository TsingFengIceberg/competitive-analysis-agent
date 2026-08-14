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

    def test_reanalysis_forwards_bounded_writer_progress_and_clears_hooks(self, monkeypatch):
        import app.competition_router as competition_router
        import competition.executor as executor_module
        import competition.nodes.writer as writer_module

        thread_id = "comp-test-reanalysis-progress"
        events = []
        saved_phases = []
        monkeypatch.setitem(competition_router._store, thread_id, {
            "status": "running",
            "state": {"user_request": "test", "hitl_decision": {}},
            "query": "test",
            "products": ["A"],
        })
        monkeypatch.setattr(competition_router, "_emit_event", lambda tid, event, payload, **kwargs: events.append((event, payload)))
        monkeypatch.setattr(competition_router, "_add_token_entry", lambda *_args: None)
        monkeypatch.setattr(competition_router, "_current_db_version", lambda *_args: None)
        monkeypatch.setattr(competition_router._history_store, "insert", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("competition.db.save_phase", lambda **kwargs: saved_phases.append(kwargs))

        def fake_writer(state):
            executor_module.emit_progress({
                "phase": "writer",
                "task_key": "industry:sec-industry-benchmark",
                "section_id": "sec-industry-benchmark",
                "status": "success",
                "completed": 1,
                "total": 1,
                "message": "报告章节生成进度：1/1",
                "secret": "must not escape",
            })
            return {"report_data": {"sections": []}}

        monkeypatch.setattr(writer_module, "writer_node", fake_writer)
        competition_router._reanalyze_sync(thread_id, "rewrite")

        progress = [payload for event, payload in events if event == "progress" and payload.get("phase") == "writer"]
        assert progress == [{
            "phase": "writer",
            "task_key": "industry:sec-industry-benchmark",
            "section_id": "sec-industry-benchmark",
            "status": "success",
            "completed": 1,
            "total": 1,
            "message": "报告章节生成进度：1/1",
        }]
        assert any(event == "node_end" and payload["node"] == "writer_r1" for event, payload in events)
        assert any(event == "end" and payload["status"] == "completed" for event, payload in events)
        assert saved_phases and saved_phases[0]["status"] == "completed"
        assert getattr(executor_module._tl, "stream_callback", None) is None
        assert getattr(executor_module._tl, "cancel_checker", None) is None
        assert getattr(executor_module._tl, "progress_callback", None) is None
        competition_router._store.pop(thread_id, None)

    def test_cancelled_reanalysis_does_not_mark_completed_or_save_version(self, monkeypatch):
        import app.competition_router as competition_router
        import competition.executor as executor_module
        import competition.nodes.writer as writer_module

        thread_id = "comp-test-reanalysis-cancel"
        events = []
        inserted_versions = []
        monkeypatch.setitem(competition_router._store, thread_id, {
            "status": "running",
            "state": {"user_request": "test", "hitl_decision": {}},
            "query": "test",
            "products": ["A"],
        })
        monkeypatch.setattr(competition_router, "_emit_event", lambda tid, event, payload, **kwargs: events.append((event, payload)))
        monkeypatch.setattr(competition_router, "_add_token_entry", lambda *_args: pytest.fail("cancelled run must not add token entry"))
        monkeypatch.setattr(competition_router, "_current_db_version", lambda *_args: None)
        monkeypatch.setattr(competition_router._history_store, "insert", lambda *args, **kwargs: inserted_versions.append(args))
        monkeypatch.setattr("competition.db.save_phase", lambda **kwargs: None)

        def fake_writer(state):
            competition_router._cancel_flags[thread_id] = True
            competition_router._store[thread_id]["status"] = "interrupted"
            return {"report_data": {"sections": [{"id": "should-not-persist"}]}}

        monkeypatch.setattr(writer_module, "writer_node", fake_writer)
        competition_router._reanalyze_sync(thread_id, "rewrite")

        assert competition_router._store[thread_id]["status"] == "interrupted"
        assert not any(event == "end" and payload.get("status") == "completed" for event, payload in events)
        assert not inserted_versions
        assert thread_id not in competition_router._cancel_flags
        assert getattr(executor_module._tl, "stream_callback", None) is None
        assert getattr(executor_module._tl, "cancel_checker", None) is None
        assert getattr(executor_module._tl, "progress_callback", None) is None
        competition_router._store.pop(thread_id, None)

    def test_initial_graph_forwards_writer_progress_and_cleans_hooks(self, monkeypatch):
        import app.competition_router as competition_router
        import competition.executor as executor_module
        import competition.graph as graph_module
        import competition.nodes.writer as writer_module

        thread_id = "comp-test-initial-progress"
        events = []
        saved_phases = []
        monkeypatch.setitem(competition_router._store, thread_id, {
            "status": "running",
            "state": {
                "messages": [],
                "user_request": "test",
                "target_products": ["A"],
                "collected_data": [],
                "survey_responses": [],
            },
            "query": "test",
            "products": ["A"],
            "generation_id": "generation-test",
        })
        monkeypatch.setattr(competition_router, "_emit_event", lambda tid, event, payload, **kwargs: events.append((event, payload)))
        monkeypatch.setattr(competition_router, "_add_token_entry", lambda *_args: None)
        monkeypatch.setattr(competition_router, "_current_db_version", lambda *_args: None)
        monkeypatch.setattr(competition_router._history_store, "insert", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("competition.db.save_phase", lambda **kwargs: saved_phases.append(kwargs))
        monkeypatch.setattr("competition.db.upsert_analysis", lambda **kwargs: None)

        def fake_writer(state):
            executor_module.emit_progress({
                "phase": "writer",
                "task_key": "narrative",
                "status": "success",
                "completed": 1,
                "total": 1,
                "message": "报告章节生成进度：1/1",
                "prompt": "must not escape",
            })
            return {"report_data": {"sections": []}}

        monkeypatch.setattr(writer_module, "writer_node", fake_writer)

        class FakeGraph:
            def stream(self, initial_state, _config, stream_mode):
                assert stream_mode == ["values"]
                result = graph_module._NODE_IMPLEMENTATIONS["writer"](dict(initial_state))
                yield {"report_data": result["report_data"]}

        monkeypatch.setattr(competition_router, "_replay_saver", object())
        monkeypatch.setattr("competition.graph.build_competition_graph", lambda **kwargs: FakeGraph())
        competition_router._run_graph_sync(thread_id)

        progress = [payload for event, payload in events if event == "progress" and payload.get("phase") == "writer"]
        assert progress == [{
            "phase": "writer",
            "task_key": "narrative",
            "status": "success",
            "completed": 1,
            "total": 1,
            "message": "报告章节生成进度：1/1",
        }]
        assert any(event == "node_end" and payload["node"] == "writer" for event, payload in events)
        assert any(event == "end" and payload["status"] == "completed" for event, payload in events)
        assert saved_phases and saved_phases[0]["phase_key"] == "writer"
        assert getattr(executor_module._tl, "stream_callback", None) is None
        assert getattr(executor_module._tl, "cancel_checker", None) is None
        assert getattr(executor_module._tl, "progress_callback", None) is None
        competition_router._store.pop(thread_id, None)


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
