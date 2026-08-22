"""Focused tests for P1 observation, alerts, and notification contracts."""

from datetime import UTC, datetime

from competition.alerts import AlertEngine, AlertRepository, AlertRule
from competition.db import init_db
from competition.intelligence_repo import IntelligenceRepository
from competition.notifications import NotificationMessage, NotificationRouter
from competition.observation_scheduler import ObservationScheduler, ScheduleRepository, ScheduleSpec


def _point(value="20", *, source_type="pricing"):
    return {
        "product": "Cursor", "category": "pricing", "label": "Pro monthly price", "value": value,
        "confidence": 0.9, "source_url": "https://cursor.com/pricing", "source_type": source_type,
        "published_at": "2026-08-22T00:00:00+00:00",
    }


def test_intelligence_repo_classifies_material_and_page_changes():
    conn = init_db(":memory:")
    repository = IntelligenceRepository(conn=conn)
    try:
        first = repository.ingest_collected_points([_point()])
        assert first["material_changes"] == 1
        assert first["change_events"][0]["change_type"] == "new_fact"

        page = _point()
        page["published_at"] = "2026-08-21T00:00:00+00:00"
        second = repository.ingest_collected_points([page])
        assert second["material_changes"] == 0
        assert second["change_events"][0]["change_type"] == "page_changed"

        third = repository.ingest_collected_points([_point("25")])
        assert third["material_changes"] == 1
        assert third["change_events"][0]["change_type"] == "fact_changed"
        assert len(repository.list_changes(material_only=True)) == 2
    finally:
        repository.close()


def test_schedule_calculates_next_run_and_skips_without_material_change():
    conn = init_db(":memory:")
    repository = ScheduleRepository(conn=conn)
    now = datetime(2026, 8, 22, 8, 30, tzinfo=UTC)
    scheduler = ObservationScheduler(repository=repository, runner=lambda _schedule: {"material_changes": 0}, clock=lambda: now)
    try:
        spec = ScheduleSpec(name="Daily watch", products=["Cursor"], daily_times=["08:00", "09:00"])
        saved = scheduler.add_schedule(spec)
        assert saved["next_run_at"].startswith("2026-08-22T09:00")
        result = scheduler.run_now(spec.schedule_id)
        assert result["status"] == "skipped"
        assert result["skip_reason"] == "no_material_change"
        assert repository.get(spec.schedule_id)["last_status"] == "skipped"
    finally:
        repository.close()


def test_scheduler_global_lock_records_skip():
    conn = init_db(":memory:")
    repository = ScheduleRepository(conn=conn)
    spec = ScheduleSpec(name="Locked", interval_minutes=10)
    scheduler = ObservationScheduler(repository=repository, runner=lambda _schedule: {"material_changes": 1})
    scheduler.add_schedule(spec)
    try:
        ObservationScheduler._global_run_lock.acquire()
        result = scheduler.run_now(spec.schedule_id)
        assert result["status"] == "skipped"
        assert "already running" in result["skip_reason"]
    finally:
        ObservationScheduler._global_run_lock.release()
        repository.close()


def test_scheduler_only_calls_deep_runner_after_material_change():
    conn = init_db(":memory:")
    repository = ScheduleRepository(conn=conn)
    calls = []
    spec = ScheduleSpec(name="Incremental", interval_minutes=10)
    scheduler = ObservationScheduler(
        repository=repository,
        runner=lambda _schedule: {"material_changes": 1},
        deep_runner=lambda _schedule, result: calls.append(result) or {"status": "completed"},
    )
    scheduler.add_schedule(spec)
    try:
        result = scheduler.run_now(spec.schedule_id)
        assert result["status"] == "completed"
        assert len(calls) == 1
    finally:
        repository.close()


def test_alert_engine_applies_severity_cooldown_dedupe_and_quiet_hours():
    conn = init_db(":memory:")
    repository = AlertRepository(conn=conn)
    now = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)  # 02:00 in Asia/Shanghai
    rule = AlertRule(name="Pricing watch", event_types=["fact_changed"], products=["Cursor"], min_severity="major", quiet_start="00:00", quiet_end="08:00")
    repository.save_rule(rule)
    engine = AlertEngine(repository, clock=lambda: now)
    change = {"change_type": "fact_changed", "product": "Cursor", "dimension": "pricing", "item_key": "item-1", "new_hash": "hash-1", "new_value": "$25", "material": True}
    first = engine.evaluate([change])
    assert first[0]["status"] == "suppressed"
    assert first[0]["suppressed_reason"] == "quiet_hours"
    assert engine.evaluate([change]) == []
    assert repository.list_events()[0]["status"] == "suppressed"
    repository.close()


class _GoodChannel:
    name = "good"

    def send(self, _message):
        return True


class _BrokenChannel:
    name = "broken"

    def send(self, _message):
        raise RuntimeError("offline")


def test_notification_router_isolates_channel_failures():
    router = NotificationRouter([_GoodChannel(), _BrokenChannel()])
    result = router.dispatch(NotificationMessage(route="alert", title="Changed", body="Pricing changed"))
    assert result["results"]["good"]["status"] == "sent"
    assert result["results"]["broken"]["status"] == "failed"
