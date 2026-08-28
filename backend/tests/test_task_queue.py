from __future__ import annotations

from pathlib import Path

from competition.task_queue import BackgroundTaskWorker, TaskRepository


def test_queue_is_idempotent_and_claim_is_atomic(tmp_path: Path):
    db_path = tmp_path / "tasks.db"
    first = TaskRepository(db_path=db_path)
    try:
        task = first.enqueue(
            user_id="u1",
            task_type="demo",
            payload={"value": 1},
            idempotency_key="demo:1",
        )
        duplicate = first.enqueue(
            user_id="u1",
            task_type="demo",
            payload={"value": 2},
            idempotency_key="demo:1",
        )
        assert duplicate["task_id"] == task["task_id"]
        assert first.claim(worker_id="worker-a")["task_id"] == task["task_id"]
    finally:
        first.close()
    second = TaskRepository(db_path=db_path)
    try:
        assert second.claim(worker_id="worker-b") is None
        assert second.succeed(task["task_id"], {"done": True})["status"] == "succeeded"
    finally:
        second.close()


def test_worker_retries_then_dead_letters_and_can_cancel(tmp_path: Path):
    db_path = tmp_path / "worker.db"
    repository = TaskRepository(db_path=db_path)
    try:
        failing = repository.enqueue(user_id="u1", task_type="fail", max_attempts=2)
        cancelled = repository.enqueue(user_id="u1", task_type="cancel")
        assert repository.cancel(cancelled["task_id"], "u1")["status"] == "cancelled"
    finally:
        repository.close()

    attempts = {"count": 0}

    def fail_handler(_task):
        attempts["count"] += 1
        raise RuntimeError("boom")

    worker = BackgroundTaskWorker(
        db_path=db_path,
        handlers={"fail": fail_handler},
        poll_seconds=0.01,
        lease_seconds=5,
    )
    assert worker.run_once()["status"] == "queued"
    # Make the retry immediately available for this deterministic test.
    retry_repo = TaskRepository(db_path=db_path)
    try:
        retry_repo.conn.execute("UPDATE background_tasks SET available_at = ? WHERE task_id = ?", ("1970-01-01T00:00:00+00:00", failing["task_id"]))
        retry_repo.conn.commit()
    finally:
        retry_repo.close()
    assert worker.run_once()["status"] == "dead_letter"
    assert attempts["count"] == 2


def test_expired_running_task_is_recovered(tmp_path: Path):
    db_path = tmp_path / "recover.db"
    repository = TaskRepository(db_path=db_path)
    try:
        task = repository.enqueue(user_id="u1", task_type="demo")
        repository.claim(worker_id="crashed", lease_seconds=5)
        repository.conn.execute("UPDATE background_tasks SET lease_until = ? WHERE task_id = ?", ("1970-01-01T00:00:00+00:00", task["task_id"]))
        repository.conn.commit()
        assert repository.recover_expired() == 1
        assert repository.get(task["task_id"])["status"] == "queued"
    finally:
        repository.close()
