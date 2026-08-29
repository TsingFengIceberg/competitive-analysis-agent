"""Durable SQLite-backed task queue used by long-running competition work.

The queue deliberately has no external broker dependency.  Claiming is done
inside a short ``BEGIN IMMEDIATE`` transaction, so multiple API processes can
share the same database without executing one task twice.  Handlers should be
idempotent because a process can still die after doing work and before marking
the task successful.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from competition.db import DEFAULT_DB_PATH, init_db

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


def _decode(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for column in ("payload_json", "result_json"):
        key = column.removesuffix("_json")
        try:
            item[key] = json.loads(item.pop(column) or "{}")
        except (TypeError, ValueError):
            item[key] = {}
    return item


class TaskRepository:
    """Persistence and atomic lifecycle operations for background tasks."""

    def __init__(self, conn=None, db_path: str | None = None):
        self._owned = conn is None
        self.conn = conn or init_db(db_path or DEFAULT_DB_PATH)
        self.conn.row_factory = getattr(self.conn, "row_factory", None) or __import__("sqlite3").Row

    def close(self) -> None:
        if self._owned:
            self.conn.close()

    def enqueue(
        self,
        *,
        user_id: str,
        task_type: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        available_at: str | None = None,
        priority: int = 50,
    ) -> dict[str, Any]:
        task_id = f"task-{uuid.uuid4().hex}"
        now = _iso()
        try:
            self.conn.execute(
                """INSERT INTO background_tasks (
                    task_id, user_id, task_type, idempotency_key, status,
                    priority, payload_json, result_json, attempts, max_attempts,
                    available_at, created_at
                ) VALUES (?, ?, ?, ?, 'queued', ?, ?, '{}', 0, ?, ?, ?)""",
                (
                    task_id,
                    user_id,
                    task_type,
                    idempotency_key,
                    max(0, min(int(priority), 1000)),
                    json.dumps(payload or {}, ensure_ascii=False, default=str),
                    max(1, min(int(max_attempts), 20)),
                    available_at or now,
                    now,
                ),
            )
            self.conn.commit()
        except Exception as exc:
            if idempotency_key and "UNIQUE" in str(exc).upper():
                existing = self.get_by_idempotency(user_id, idempotency_key)
                if existing is not None:
                    return existing
            raise
        result = self.get(task_id)
        assert result is not None
        return result

    def get_by_idempotency(self, user_id: str, idempotency_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM background_tasks WHERE user_id = ? AND idempotency_key = ?",
            (user_id, idempotency_key),
        ).fetchone()
        return _decode(row)

    def get(self, task_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT * FROM background_tasks WHERE task_id = ?"
        params: list[Any] = [task_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        return _decode(self.conn.execute(sql, params).fetchone())

    def list(self, user_id: str, *, limit: int = 50, statuses: list[str] | None = None) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)
        params.append(max(1, min(int(limit), 500)))
        rows = self.conn.execute(
            f"SELECT * FROM background_tasks WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_decode(row) for row in rows if row is not None]

    def claim(self, *, worker_id: str, lease_seconds: int = 120) -> dict[str, Any] | None:
        now = _now()
        now_iso = _iso(now)
        lease = _iso(now + timedelta(seconds=max(5, int(lease_seconds))))
        if self.conn.in_transaction:
            self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                """SELECT * FROM background_tasks
                   WHERE (status = 'queued' AND available_at <= ?)
                      OR (status = 'running' AND lease_until IS NOT NULL AND lease_until <= ?)
                   ORDER BY priority DESC, available_at ASC, created_at ASC LIMIT 1""",
                (now_iso, now_iso),
            ).fetchone()
            if row is None:
                self.conn.commit()
                return None
            task_id = str(row["task_id"] if hasattr(row, "keys") else row[0])
            self.conn.execute(
                """UPDATE background_tasks SET status = 'running', attempts = attempts + 1,
                       started_at = COALESCE(started_at, ?), heartbeat_at = ?, lease_until = ?, error = NULL
                   WHERE task_id = ?""",
                (now_iso, now_iso, lease, task_id),
            )
            self.conn.commit()
            return self.get(task_id)
        except Exception:
            self.conn.rollback()
            raise

    def heartbeat(self, task_id: str, *, lease_seconds: int = 120) -> bool:
        now = _now()
        cursor = self.conn.execute(
            """UPDATE background_tasks SET heartbeat_at = ?, lease_until = ?
               WHERE task_id = ? AND status = 'running'""",
            (_iso(now), _iso(now + timedelta(seconds=max(5, int(lease_seconds)))), task_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def is_cancelled(self, task_id: str) -> bool:
        row = self.conn.execute("SELECT status FROM background_tasks WHERE task_id = ?", (task_id,)).fetchone()
        return bool(row and row[0] == "cancelled")

    def succeed(self, task_id: str, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
        self.conn.execute(
            """UPDATE background_tasks SET status = 'succeeded', result_json = ?, progress = 100,
                   finished_at = ?, lease_until = NULL, heartbeat_at = NULL, error = NULL
               WHERE task_id = ? AND status = 'running'""",
            (json.dumps(result or {}, ensure_ascii=False, default=str), _iso(), task_id),
        )
        self.conn.commit()
        return self.get(task_id)

    def fail(self, task_id: str, error: str, *, retry_delay_seconds: int = 30) -> dict[str, Any] | None:
        current = self.get(task_id)
        if current is None:
            return None
        if current["status"] == "cancelled":
            return current
        terminal = int(current.get("attempts") or 0) >= int(current.get("max_attempts") or 1)
        status = "dead_letter" if terminal else "queued"
        available = _iso(_now() + timedelta(seconds=max(1, int(retry_delay_seconds))))
        self.conn.execute(
            """UPDATE background_tasks SET status = ?, error = ?, available_at = ?,
                   finished_at = CASE WHEN ? THEN ? ELSE NULL END,
                   lease_until = NULL, heartbeat_at = NULL
               WHERE task_id = ? AND status = 'running'""",
            (status, str(error)[:2000], available, int(terminal), _iso(), task_id),
        )
        self.conn.commit()
        return self.get(task_id)

    def cancel(self, task_id: str, user_id: str) -> dict[str, Any] | None:
        self.conn.execute(
            """UPDATE background_tasks SET status = 'cancelled', cancelled_at = ?, finished_at = ?,
                   lease_until = NULL, heartbeat_at = NULL
               WHERE task_id = ? AND user_id = ? AND status IN ('queued', 'running', 'failed')""",
            (_iso(), _iso(), task_id, user_id),
        )
        self.conn.commit()
        return self.get(task_id, user_id)

    def retry(self, task_id: str, user_id: str) -> dict[str, Any] | None:
        self.conn.execute(
            """UPDATE background_tasks SET status = 'queued', error = NULL, available_at = ?,
                   attempts = 0, finished_at = NULL, cancelled_at = NULL, lease_until = NULL, heartbeat_at = NULL
               WHERE task_id = ? AND user_id = ? AND status IN ('failed', 'dead_letter', 'cancelled')""",
            (_iso(), task_id, user_id),
        )
        self.conn.commit()
        return self.get(task_id, user_id)

    def recover_expired(self, *, lease_seconds: int = 120) -> int:
        """Make leases from a crashed worker retryable on process startup."""
        cursor = self.conn.execute(
            """UPDATE background_tasks SET status = 'queued', available_at = ?, lease_until = NULL,
                   heartbeat_at = NULL, error = COALESCE(error, 'worker lease expired')
               WHERE status = 'running' AND lease_until IS NOT NULL AND lease_until <= ?""",
            (_iso(), _iso(),),
        )
        self.conn.commit()
        return cursor.rowcount


TaskHandler = Callable[[dict[str, Any]], dict[str, Any] | None]


class BackgroundTaskWorker:
    """Small cooperative worker suitable for one or more API processes."""

    def __init__(self, *, db_path=DEFAULT_DB_PATH, handlers: dict[str, TaskHandler] | None = None, poll_seconds: float = 1.0, lease_seconds: int = 120):
        self.db_path = db_path
        self.handlers = handlers or {}
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.lease_seconds = max(5, int(lease_seconds))
        self.worker_id = f"worker-{uuid.uuid4().hex[:12]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> dict[str, Any] | None:
        repository = TaskRepository(db_path=self.db_path)
        try:
            task = repository.claim(worker_id=self.worker_id, lease_seconds=self.lease_seconds)
            if task is None:
                return None
            handler = self.handlers.get(str(task["task_type"]))
            if handler is None:
                repository.fail(task["task_id"], f"No handler registered for {task['task_type']}", retry_delay_seconds=1)
                return repository.get(task["task_id"])
            if repository.is_cancelled(task["task_id"]):
                return repository.get(task["task_id"])
            try:
                heartbeat_stop = threading.Event()

                def heartbeat_loop() -> None:
                    while not heartbeat_stop.wait(max(1, self.lease_seconds // 3)):
                        try:
                            repository.heartbeat(task["task_id"], lease_seconds=self.lease_seconds)
                        except Exception:
                            logger.warning("Task heartbeat failed for %s", task["task_id"], exc_info=True)

                heartbeat_thread = threading.Thread(target=heartbeat_loop, name=f"ci-task-heartbeat-{task['task_id'][-8:]}", daemon=True)
                heartbeat_thread.start()
                try:
                    result = handler(task)
                finally:
                    heartbeat_stop.set()
                    heartbeat_thread.join(timeout=1)
                if repository.is_cancelled(task["task_id"]):
                    return repository.get(task["task_id"])
                return repository.succeed(task["task_id"], result or {})
            except Exception as exc:
                logger.exception("Background task %s failed", task["task_id"])
                return repository.fail(task["task_id"], str(exc))
        finally:
            repository.close()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        repository = TaskRepository(db_path=self.db_path)
        try:
            repository.recover_expired()
        finally:
            repository.close()

        def loop() -> None:
            while not self._stop.is_set():
                try:
                    result = self.run_once()
                    if result is None:
                        self._stop.wait(self.poll_seconds)
                except Exception:
                    logger.exception("Background task worker iteration failed")
                    self._stop.wait(self.poll_seconds)

        self._thread = threading.Thread(target=loop, name=f"ci-task-worker-{self.worker_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        self._thread = None


__all__ = ["BackgroundTaskWorker", "TaskRepository"]
