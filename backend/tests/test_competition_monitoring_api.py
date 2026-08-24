"""API and runtime coverage for the competition monitoring workspace."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from competition.alerts import AlertRepository
from competition.db import init_db
from competition.observation_scheduler import ObservationScheduler, ScheduleRepository, ScheduleSpec


@pytest.mark.asyncio
async def test_monitoring_crud_and_run_history_are_user_scoped(monkeypatch):
    import app.competition_router as competition_router
    import competition.alerts as alerts_module
    import competition.observation_scheduler as observation_module

    conn = init_db(":memory:")
    current_user = {"id": "user-1"}
    monkeypatch.setattr(competition_router, "_get_user_id", lambda _request: current_user["id"])
    monkeypatch.setattr(observation_module, "ScheduleRepository", lambda: ScheduleRepository(conn=conn))
    monkeypatch.setattr(alerts_module, "AlertRepository", lambda: AlertRepository(conn=conn))

    app = FastAPI()
    app.include_router(competition_router.router)
    schedule_body = {
        "name": "Daily AI tools",
        "products": ["Cursor", "Codex"],
        "dimensions": ["features", "pricing"],
        "daily_times": ["09:00"],
    }
    rule_body = {
        "name": "Pricing changes",
        "event_types": ["fact_changed"],
        "products": ["Cursor"],
        "dimensions": ["pricing"],
    }

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/api/competition/observation/schedules", json=schedule_body)
            assert created.status_code == 200
            schedule_id = created.json()["schedule"]["schedule_id"]
            repository = ScheduleRepository(conn=conn)
            repository.record_run(
                schedule_id,
                status="skipped",
                started_at="2026-08-23T01:00:00+00:00",
                finished_at="2026-08-23T01:00:01+00:00",
                summary={"material_changes": 0},
                skip_reason="no_material_change",
            )

            updated = await client.put(
                f"/api/competition/observation/schedules/{schedule_id}",
                json={**schedule_body, "name": "Updated AI tools", "enabled": False},
            )
            assert updated.status_code == 200
            assert updated.json()["schedule"]["name"] == "Updated AI tools"
            assert updated.json()["schedule"]["enabled"] is False

            runs = await client.get("/api/competition/observation/runs")
            assert runs.status_code == 200
            assert runs.json()["runs"][0]["schedule_name"] == "Updated AI tools"
            assert runs.json()["runs"][0]["summary"]["material_changes"] == 0

            created_rule = await client.post("/api/competition/alerts/rules", json=rule_body)
            assert created_rule.status_code == 200
            rule_id = created_rule.json()["rule"]["rule_id"]
            updated_rule = await client.put(
                f"/api/competition/alerts/rules/{rule_id}",
                json={**rule_body, "min_severity": "critical", "enabled": False},
            )
            assert updated_rule.status_code == 200
            assert updated_rule.json()["rule"]["min_severity"] == "critical"

            current_user["id"] = "user-2"
            assert (
                await client.put(
                    f"/api/competition/observation/schedules/{schedule_id}",
                    json=schedule_body,
                )
            ).status_code == 404
            assert (await client.delete(f"/api/competition/alerts/rules/{rule_id}")).status_code == 404

            current_user["id"] = "user-1"
            assert (await client.delete(f"/api/competition/alerts/rules/{rule_id}")).status_code == 200
            assert (await client.delete(f"/api/competition/observation/schedules/{schedule_id}")).status_code == 200
            assert (await client.get("/api/competition/observation/runs")).json()["runs"] == []
    finally:
        conn.close()


def test_observation_runtime_reports_lifecycle(monkeypatch):
    import app.competition_router as competition_router
    import competition.observation_scheduler as observation_module

    ticked = threading.Event()

    class FakeRepository:
        def close(self):
            return None

    class FakeScheduler:
        def __init__(self, **_kwargs):
            pass

        def tick(self):
            ticked.set()
            return []

    competition_router.stop_observation_runtime()
    monkeypatch.setattr(observation_module, "ScheduleRepository", FakeRepository)
    monkeypatch.setattr(observation_module, "ObservationScheduler", FakeScheduler)
    try:
        competition_router.start_observation_runtime(poll_seconds=5)
        assert ticked.wait(timeout=1)
        assert competition_router._observation_runtime_thread is not None
        assert competition_router._observation_runtime_last_tick is not None
        assert competition_router._observation_runtime_last_error is None
    finally:
        competition_router.stop_observation_runtime()
    assert competition_router._observation_runtime_thread is None


def test_schedule_repository_filters_run_history_by_owner():
    conn = init_db(":memory:")
    repository = ScheduleRepository(conn=conn)
    scheduler = ObservationScheduler(repository=repository)
    try:
        own = ScheduleSpec(name="Own", products=["Cursor"], daily_times=["09:00"], user_id="user-1")
        other = ScheduleSpec(name="Other", products=["Codex"], daily_times=["10:00"], user_id="user-2")
        scheduler.add_schedule(own)
        scheduler.add_schedule(other)
        repository.record_run(own.schedule_id, status="completed", started_at="2026-08-23T01:00:00+00:00")
        repository.record_run(other.schedule_id, status="failed", started_at="2026-08-23T02:00:00+00:00")

        runs = repository.list_runs(user_id="user-1")
        assert [item["schedule_id"] for item in runs] == [own.schedule_id]
        assert runs[0]["schedule_name"] == "Own"
    finally:
        conn.close()


def test_run_now_creates_repository_inside_worker_thread(monkeypatch, tmp_path: Path):
    import app.competition_router as competition_router
    import competition.observation_scheduler as observation_module

    db_path = str(tmp_path / "monitoring.db")
    setup = init_db(db_path)
    setup.close()
    real_repository = observation_module.ScheduleRepository
    monkeypatch.setattr(
        observation_module,
        "ScheduleRepository",
        lambda: real_repository(db_path=db_path),
    )
    monkeypatch.setattr(competition_router, "_get_user_id", lambda _request: "user-1")
    monkeypatch.setattr(
        competition_router,
        "_run_scheduled_collection",
        lambda _schedule: {"material_changes": 0},
    )

    repository = real_repository(db_path=db_path)
    schedule_id = observation_module.ObservationScheduler(repository=repository).add_schedule(
        ScheduleSpec(
            name="Thread-safe observation",
            products=["Cursor", "Codex"],
            dimensions=["pricing"],
            daily_times=["09:00"],
            user_id="user-1",
        )
    )["schedule_id"]
    repository.close()

    result: dict = {}
    errors: list[BaseException] = []

    def run_in_worker() -> None:
        try:
            result["run"] = competition_router._run_observation_now_sync(schedule_id, "user-1")
        except BaseException as exc:  # pragma: no cover - surfaced by assertion below
            errors.append(exc)

    worker = threading.Thread(target=run_in_worker)
    worker.start()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert errors == []
    assert result["run"]["status"] == "skipped"
