"""Standalone durable task-worker entry point for multi-process deployments."""

from __future__ import annotations

import logging
import os
import signal
import threading

from competition.task_queue import BackgroundTaskWorker

logger = logging.getLogger(__name__)


def build_worker() -> BackgroundTaskWorker:
    """Build a worker with the same handlers used by the FastAPI process."""
    from app.competition_router import (
        _run_background_knowledge_task,
        _run_background_observation_task,
        _run_background_source_item_sync_task,
        _run_background_source_sync_task,
    )

    return BackgroundTaskWorker(
        db_path=os.getenv("CI_AGENT_DB_PATH") or None,
        poll_seconds=float(os.getenv("CI_AGENT_TASK_POLL_SECONDS", "1")),
        lease_seconds=int(os.getenv("CI_AGENT_TASK_LEASE_SECONDS", "120")),
        handlers={
            "observation.run": _run_background_observation_task,
            "knowledge.ingest": _run_background_knowledge_task,
            "knowledge.source_sync": _run_background_source_sync_task,
            "knowledge.source_item_sync": _run_background_source_item_sync_task,
        },
    )


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    stop = threading.Event()
    worker = build_worker()
    signal.signal(signal.SIGTERM, lambda *_args: stop.set())
    signal.signal(signal.SIGINT, lambda *_args: stop.set())
    worker.start()
    logger.info("Standalone task worker started")
    stop.wait()
    worker.stop()
    logger.info("Standalone task worker stopped")


if __name__ == "__main__":
    main()
