from __future__ import annotations

from competition.task_queue import TaskRepository


def test_find_active_deduplicates_source_sync(tmp_path):
    repository = TaskRepository(db_path=tmp_path / "tasks.db")
    try:
        first = repository.enqueue(
            user_id="owner",
            task_type="knowledge.source_sync",
            payload={"source_id": "source-1"},
            idempotency_key="manual-1",
        )
        active = repository.find_active(
            user_id="owner",
            task_type="knowledge.source_sync",
            payload_key="source_id",
            payload_value="source-1",
        )
        assert active and active["task_id"] == first["task_id"]
        assert repository.find_active(
            user_id="other",
            task_type="knowledge.source_sync",
            payload_key="source_id",
            payload_value="source-1",
        ) is None
    finally:
        repository.close()
