"""API and runtime coverage for the competition monitoring workspace."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from competition.alerts import AlertRepository
from competition.db import init_db
from competition.intelligence_repo import IntelligenceRepository
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

            repository.record_run(
                schedule_id,
                status="completed",
                started_at="2026-08-23T02:00:00+00:00",
                finished_at="2026-08-23T02:03:00+00:00",
                summary={
                    "material_changes": 3,
                    "change_events": [{"large": "payload must not be projected"}],
                    "deep_analysis": {"thread_id": "comp-watch-report-1", "status": "completed"},
                },
            )
            reports = await client.get("/api/competition/observation/reports")
            assert reports.status_code == 200
            assert reports.json()["total"] == 1
            assert reports.json()["limit"] == 100
            assert reports.json()["offset"] == 0
            assert reports.json()["reports"] == [{
                "run_id": reports.json()["reports"][0]["run_id"],
                "schedule_id": schedule_id,
                "schedule_name": "Updated AI tools",
                "started_at": "2026-08-23T02:00:00+00:00",
                "finished_at": "2026-08-23T02:03:00+00:00",
                "status": "completed",
                "material_changes": 3,
                "thread_id": "comp-watch-report-1",
                "report_status": "completed",
            }]

            repository.record_run(
                schedule_id,
                status="completed",
                started_at="2026-08-23T03:00:00+00:00",
                finished_at="2026-08-23T03:03:00+00:00",
                summary={
                    "material_changes": 2,
                    "deep_analysis": {"thread_id": "comp-watch-report-2", "status": "completed"},
                },
            )
            older_report = await client.get("/api/competition/observation/reports?limit=1&offset=1")
            assert older_report.status_code == 200
            assert older_report.json()["total"] == 2
            assert older_report.json()["reports"][0]["thread_id"] == "comp-watch-report-1"

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
            other_user_reports = (await client.get("/api/competition/observation/reports")).json()
            assert other_user_reports["reports"] == []
            assert other_user_reports["total"] == 0
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


def test_observation_brief_uses_complete_current_contract():
    import app.competition_router as competition_router
    from competition.schema import AnalysisBrief

    brief = competition_router._build_observation_brief(
        {
            "products": ["Cursor", "Codex"],
            "dimensions": ["features", "pricing", "market"],
            "market_scope": "AI coding tools",
        },
        complexity="standard",
    )

    validated = AnalysisBrief.model_validate(brief)
    assert validated.objective == "定期观察竞品：Cursor, Codex"
    assert validated.confirmation_source == "bypass"
    assert validated.time_range.mode == "latest"
    assert sum(item.weight for item in validated.dimensions) == pytest.approx(1.0)


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


def test_intelligence_change_detail_includes_current_item_and_versions(tmp_path: Path):
    repository = IntelligenceRepository(db_path=str(tmp_path / "intelligence.db"))
    point = {
        "product": "Codex",
        "category": "market",
        "label": "Usage share",
        "value": "10%",
        "source_url": "https://example.com/report",
        "source_type": "official",
    }
    try:
        first = repository.ingest_collected_points([point])
        change_id = first["change_events"][0]["change_id"]
        repository.ingest_collected_points([{**point, "value": "12%"}])

        detail = repository.get_change_detail(change_id)
        assert detail is not None
        assert detail["change"]["old_value"] is None
        assert detail["change"]["new_value"] == "10%"
        assert detail["item"]["value"] == "12%"
        assert len(detail["versions"]) == 2
        assert detail["sources"][0]["source_domain"] == "example.com"
        assert repository.get_change_detail("missing-change") is None
    finally:
        repository.close()
