from __future__ import annotations


def test_build_worker_registers_durable_handlers(monkeypatch):
    monkeypatch.setenv("CI_AGENT_TASK_LEASE_SECONDS", "30")
    from app.task_worker import build_worker

    worker = build_worker()
    try:
        assert set(worker.handlers) == {
            "observation.run",
            "knowledge.ingest",
            "knowledge.source_sync",
            "knowledge.source_item_sync",
        }
        assert worker.lease_seconds == 30
    finally:
        worker.stop()
