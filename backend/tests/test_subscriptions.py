"""Tests for durable intelligence subscriptions and alert feedback."""

from competition.alerts import AlertRepository
from competition.db import init_db
from competition.subscriptions import IntelligenceSubscription, SubscriptionRepository


def test_subscription_round_trip_and_user_isolation():
    conn = init_db(":memory:")
    repository = SubscriptionRepository(conn=conn)
    try:
        subscription = repository.save(
            IntelligenceSubscription(
                name="Pricing watch",
                products=["Cursor"],
                dimensions=["pricing"],
                channels=["in_app", "webhook"],
                user_id="alice",
            )
        )
        assert subscription["products"] == ["Cursor"]
        assert repository.list("alice")[0]["name"] == "Pricing watch"
        assert repository.list("bob") == []
        assert repository.delete(subscription["subscription_id"], "bob") is False
        assert repository.delete(subscription["subscription_id"], "alice") is True
    finally:
        repository.close()


def test_alert_feedback_upsert_requires_correction_for_corrected_action():
    conn = init_db(":memory:")
    alerts = AlertRepository(conn=conn)
    feedback = SubscriptionRepository(conn=conn)
    try:
        event = {
            "event_id": "event-1",
            "rule_id": "rule-1",
            "user_id": "alice",
            "event_type": "fact_changed",
            "severity": "major",
            "dedupe_key": "dedupe-1",
            "title": "Pricing changed",
            "message": "Price changed",
            "payload": {},
            "status": "pending",
            "first_seen_at": "2026-08-30T00:00:00+00:00",
            "last_seen_at": "2026-08-30T00:00:00+00:00",
        }
        alerts.save_event(event)
        assert alerts.get_event("event-1", user_id="bob") is None
        assert alerts.get_event("event-1", user_id="alice")["title"] == "Pricing changed"
        try:
            feedback.save_feedback(event_id="event-1", user_id="alice", action="corrected")
        except ValueError as exc:
            assert "correction" in str(exc)
        else:
            raise AssertionError("corrected feedback should require correction text")
        feedback.save_feedback(event_id="event-1", user_id="alice", action="confirmed")
        feedback.save_feedback(event_id="event-1", user_id="alice", action="corrected", correction="$30")
        assert feedback.feedback_summary("alice") == {"total": 1, "confirmed": 0, "ignored": 0, "corrected": 1, "confirmation_rate": 0.0}
    finally:
        feedback.close()
        alerts.close()

