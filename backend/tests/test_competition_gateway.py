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

    @pytest.mark.asyncio
    async def test_report_exposes_stage_results_for_runtime_audit(self, client):
        import app.competition_router as competition_router

        thread_id = "comp-test-stage-report"
        competition_router._store[thread_id] = {
            "status": "completed",
            "query": "test",
            "products": ["A"],
            "state": {
                "stage_results": [{
                    "stage": "writer",
                    "status": "partial",
                    "attempt": 1,
                    "token_usage": {"input_tokens": 4, "output_tokens": 6, "total_tokens": 10},
                    "llm_calls": 1,
                    "tool_calls": 0,
                }],
            },
            "token_usage": [],
        }
        try:
            response = await client.get(f"/api/competition/report/{thread_id}")
            assert response.status_code == 200
            assert response.json()["stage_results"][0]["status"] == "partial"
        finally:
            competition_router._store.pop(thread_id, None)

    @pytest.mark.asyncio
    async def test_report_normalizes_legacy_observation_brief(self, client):
        import app.competition_router as competition_router

        thread_id = "comp-watch-legacy-brief"
        competition_router._store[thread_id] = {
            "status": "completed",
            "query": "定期观察竞品：Cursor, Codex",
            "products": ["Cursor", "Codex"],
            "state": {
                "analysis_brief": {
                    "target_products": ["Cursor", "Codex"],
                    "market_scope": "Global / unspecified",
                    "dimensions": [
                        {"id": "features", "label": "features"},
                        {"id": "pricing", "label": "pricing"},
                    ],
                    "effective_dimensions": [
                        {"id": "features", "label": "features"},
                        {"id": "pricing", "label": "pricing"},
                    ],
                },
            },
            "token_usage": [],
        }
        try:
            response = await client.get(f"/api/competition/report/{thread_id}")
            assert response.status_code == 200
            brief = response.json()["analysis_brief"]
            assert brief["objective"] == "竞品分析"
            assert brief["ambiguities"] == []
            assert sum(item["weight"] for item in brief["dimensions"]) == pytest.approx(1.0)
        finally:
            competition_router._store.pop(thread_id, None)


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

    def test_sse_broadcasts_one_event_to_each_subscriber(self):
        import app.competition_router as competition_router

        thread_id = "comp-test-sse-broadcast"
        competition_router._store[thread_id] = {
            "status": "running",
            "query": "test",
            "products": ["A"],
        }
        try:
            first = competition_router._stream_events_sync(thread_id)
            assert "event: metadata" in next(first)
            assert "event: values" in next(first)

            second = competition_router._stream_events_sync(thread_id)
            assert "event: metadata" in next(second)
            assert "event: values" in next(second)

            competition_router._emit_event(thread_id, "node_end", {"node": "writer"})
            first_frame = next(first)
            second_frame = next(second)
            assert first_frame == second_frame
            assert "event: node_end" in first_frame
            assert len(competition_router._stream_subscribers[thread_id]) == 2

            first.close()
            assert len(competition_router._stream_subscribers[thread_id]) == 1
            second.close()
            assert thread_id not in competition_router._stream_subscribers
        finally:
            competition_router._store.pop(thread_id, None)
            competition_router._stream_subscribers.pop(thread_id, None)
            competition_router._stream_queues.pop(thread_id, None)
            competition_router._event_buffers.pop(thread_id, None)
            competition_router._event_counters.pop(thread_id, None)

    def test_sse_reconnect_replays_events_after_last_event_id(self):
        import app.competition_router as competition_router

        thread_id = "comp-test-sse-replay"
        competition_router._store[thread_id] = {
            "status": "running",
            "query": "test",
            "products": [],
        }
        try:
            competition_router._emit_event(thread_id, "progress", {"step": 1})
            first_id = competition_router._event_buffers[thread_id][0][1].split("id: ", 1)[1].splitlines()[0]
            competition_router._emit_event(thread_id, "end", {"status": "completed"})
            competition_router._store[thread_id]["status"] = "completed"
            replay = competition_router._stream_events_sync(thread_id, last_event_id=first_id)
            assert "event: metadata" in next(replay)
            assert "event: values" in next(replay)
            assert "event: end" in next(replay)
            with pytest.raises(StopIteration):
                next(replay)
            replay.close()

            terminal_id = competition_router._event_buffers[thread_id][-1][1].split("id: ", 1)[1].splitlines()[0]
            terminal_reconnect = competition_router._stream_events_sync(thread_id, last_event_id=terminal_id)
            assert "event: metadata" in next(terminal_reconnect)
            assert "event: values" in next(terminal_reconnect)
            with pytest.raises(StopIteration):
                next(terminal_reconnect)
            terminal_reconnect.close()
        finally:
            competition_router._store.pop(thread_id, None)
            competition_router._stream_subscribers.pop(thread_id, None)
            competition_router._stream_queues.pop(thread_id, None)
            competition_router._event_buffers.pop(thread_id, None)
            competition_router._event_counters.pop(thread_id, None)

    def test_sse_preserves_stage_runtime_fields(self):
        import app.competition_router as competition_router

        thread_id = "comp-test-sse-stage-runtime"
        competition_router._store[thread_id] = {"status": "running", "query": "test", "products": []}
        try:
            stream = competition_router._stream_events_sync(thread_id)
            next(stream)
            next(stream)
            competition_router._emit_event(thread_id, "node_end", {
                "node": "collector", "status": "partial", "tokens": 10,
                "duration_ms": 1200, "llm_calls": 2, "tool_calls": 1,
                "error_code": "coverage_warning",
            })
            frame = next(stream)
            assert "\"status\": \"partial\"" in frame
            assert "\"duration_ms\": 1200" in frame
            assert "\"tool_calls\": 1" in frame
            stream.close()
        finally:
            competition_router._store.pop(thread_id, None)
            competition_router._stream_subscribers.pop(thread_id, None)
            competition_router._stream_queues.pop(thread_id, None)
            competition_router._event_buffers.pop(thread_id, None)
            competition_router._event_counters.pop(thread_id, None)

    def test_cancelled_run_persists_stage_marker(self, monkeypatch, tmp_path):
        import app.competition_router as competition_router
        import competition.db as competition_db

        thread_id = "comp-test-cancel-persist"
        db_path = tmp_path / "competition.db"
        real_init_db = competition_db.init_db
        monkeypatch.setattr(competition_db, "init_db", lambda: real_init_db(db_path))
        monkeypatch.setattr(competition_router, "_emit_event", lambda *_args, **_kwargs: None)
        competition_router._store[thread_id] = {
            "status": "running",
            "query": "test",
            "products": ["A"],
            "state": {
                "current_stage": "collector",
                "stage_results": [{"stage": "collector", "status": "completed"}],
            },
        }
        try:
            competition_router._finalize_cancelled(thread_id)
            conn = real_init_db(db_path)
            phases = competition_db.get_phases(thread_id, conn=conn)
            conn.close()
            assert phases[0]["status"] == "cancelled"
            assert phases[0]["details"][-1]["status"] == "cancelled"
        finally:
            competition_router._store.pop(thread_id, None)

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

    def test_initial_graph_terminal_error_is_persisted_as_failed(self, monkeypatch):
        import app.competition_router as competition_router
        import competition.executor as executor_module

        thread_id = "comp-test-initial-failure"
        events = []
        persisted = []
        inserted_versions = []
        monkeypatch.setitem(competition_router._store, thread_id, {
            "status": "running",
            "state": {
                "messages": [],
                "user_request": "test",
                "target_products": ["A"],
                "collected_data": [],
            },
            "query": "test",
            "products": ["A"],
            "generation_id": "generation-failed",
        })
        monkeypatch.setattr(competition_router, "_emit_event", lambda tid, event, payload, **kwargs: events.append((event, payload)))
        monkeypatch.setattr(competition_router, "_add_token_entry", lambda *_args: None)
        monkeypatch.setattr(competition_router, "_current_db_version", lambda *_args: None)
        monkeypatch.setattr(competition_router._history_store, "insert", lambda *args, **kwargs: inserted_versions.append(args))
        monkeypatch.setattr("competition.db.save_phase", lambda **kwargs: None)
        monkeypatch.setattr("competition.db.upsert_analysis", lambda **kwargs: persisted.append(kwargs))

        class FakeGraph:
            def stream(self, initial_state, _config, stream_mode):
                assert stream_mode == ["values"]
                yield {
                    **dict(initial_state),
                    "error": "FATAL: provider authentication failed",
                    "report_data": {"title": "分析失败", "sections": [], "metrics": {}},
                }

        monkeypatch.setattr(competition_router, "_replay_saver", object())
        monkeypatch.setattr("competition.graph.build_competition_graph", lambda **kwargs: FakeGraph())
        competition_router._run_graph_sync(thread_id)

        assert competition_router._store[thread_id]["status"] == "failed"
        assert any(event == "error" and payload["status"] == "failed" for event, payload in events)
        assert not any(event == "end" and payload.get("status") == "completed" for event, payload in events)
        assert any(record["status"] == "failed" for record in persisted)
        assert not inserted_versions
        assert getattr(executor_module._tl, "stream_callback", None) is None
        assert getattr(executor_module._tl, "cancel_checker", None) is None
        assert getattr(executor_module._tl, "progress_callback", None) is None
        competition_router._store.pop(thread_id, None)

    def test_initial_graph_without_report_is_persisted_as_failed(self, monkeypatch):
        import app.competition_router as competition_router
        import competition.executor as executor_module

        thread_id = "comp-test-initial-missing-report"
        events = []
        persisted = []
        monkeypatch.setitem(competition_router._store, thread_id, {
            "status": "running",
            "state": {
                "messages": [],
                "user_request": "test",
                "target_products": ["A"],
                "collected_data": [{"product": "A"}],
            },
            "query": "test",
            "products": ["A"],
            "generation_id": "generation-missing-report",
        })
        monkeypatch.setattr(competition_router, "_emit_event", lambda tid, event, payload, **kwargs: events.append((event, payload)))
        monkeypatch.setattr(competition_router, "_add_token_entry", lambda *_args: None)
        monkeypatch.setattr(competition_router, "_current_db_version", lambda *_args: None)
        monkeypatch.setattr("competition.db.save_phase", lambda **kwargs: None)
        monkeypatch.setattr("competition.db.upsert_analysis", lambda **kwargs: persisted.append(kwargs))

        class FakeGraph:
            def stream(self, initial_state, _config, stream_mode):
                assert stream_mode == ["values"]
                yield {**dict(initial_state), "analysis_result": {"summary": "partial"}}

        monkeypatch.setattr(competition_router, "_replay_saver", object())
        monkeypatch.setattr("competition.graph.build_competition_graph", lambda **kwargs: FakeGraph())
        competition_router._run_graph_sync(thread_id)

        assert competition_router._store[thread_id]["status"] == "failed"
        assert competition_router._store[thread_id]["state"]["run_status"] == "failed"
        assert any(event == "error" and payload["status"] == "failed" for event, payload in events)
        assert not any(event == "end" and payload.get("status") == "completed" for event, payload in events)
        assert any(record["status"] == "failed" for record in persisted)
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
