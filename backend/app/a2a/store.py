"""SQLite persistence for A2A tasks and replayable events."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from a2a.types.a2a_pb2 import Task, TaskState
from google.protobuf.json_format import MessageToDict, ParseDict

from competition.db import DEFAULT_DB_PATH, init_db


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _task_dict(task: Task) -> dict[str, Any]:
    return MessageToDict(task, preserving_proto_field_name=False)


class A2AStore:
    def __init__(self, db_path=DEFAULT_DB_PATH):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return init_db(self.db_path)

    def create(self, task: Task, *, owner: str, tenant: str, internal_thread_id: str | None = None) -> None:
        now = _now()
        data = _task_dict(task)
        conn = self._conn()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO a2a_tasks
                   (task_id, context_id, owner_id, tenant_id, internal_thread_id,
                   status_json, history_json, artifacts_json, metadata_json, max_attempts, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task.id,
                    task.context_id,
                    owner,
                    tenant,
                    internal_thread_id,
                    json.dumps(data.get("status", {}), ensure_ascii=False),
                    json.dumps(data.get("history", []), ensure_ascii=False),
                    json.dumps(data.get("artifacts", []), ensure_ascii=False),
                    json.dumps(data.get("metadata", {}), ensure_ascii=False),
                    self.max_attempts(),
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get(self, task_id: str, owner: str, tenant: str = "") -> Task | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM a2a_tasks WHERE task_id = ? AND owner_id = ? AND tenant_id = ?",
                (task_id, owner, tenant),
            ).fetchone()
            if row is None:
                return None
            return self._decode_row(row)
        finally:
            conn.close()

    def list(self, owner: str, tenant: str = "", context_id: str = "", limit: int = 50) -> list[Task]:
        conn = self._conn()
        try:
            clauses = ["owner_id = ?", "tenant_id = ?"]
            params: list[Any] = [owner, tenant]
            if context_id:
                clauses.append("context_id = ?")
                params.append(context_id)
            params.append(max(1, min(limit, 100)))
            rows = conn.execute(
                f"SELECT * FROM a2a_tasks WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [self._decode_row(row) for row in rows]
        finally:
            conn.close()

    def save(self, task: Task, *, owner: str, tenant: str = "", internal_thread_id: str | None = None) -> bool:
        data = _task_dict(task)
        status = data.get("status", {})
        state = status.get("state", "")
        terminal = ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED")
        conn = self._conn()
        try:
            cursor = conn.execute(
                """UPDATE a2a_tasks SET context_id = ?, internal_thread_id = COALESCE(?, internal_thread_id),
                   status_json = ?, history_json = ?, artifacts_json = ?, metadata_json = ?, updated_at = ?
                   WHERE task_id = ? AND owner_id = ? AND tenant_id = ?
                     AND (json_extract(status_json, '$.state') NOT IN (?, ?, ?, ?) OR ? IN (?, ?, ?, ?))""",
                (
                    task.context_id,
                    internal_thread_id,
                    json.dumps(status, ensure_ascii=False),
                    json.dumps(data.get("history", []), ensure_ascii=False),
                    json.dumps(data.get("artifacts", []), ensure_ascii=False),
                    json.dumps(data.get("metadata", {}), ensure_ascii=False),
                    _now(),
                    task.id,
                    owner,
                    tenant,
                    *terminal,
                    state,
                    *terminal,
                ),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def internal_thread(self, task_id: str, owner: str, tenant: str = "") -> str | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT internal_thread_id FROM a2a_tasks WHERE task_id = ? AND owner_id = ? AND tenant_id = ?",
                (task_id, owner, tenant),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    @staticmethod
    def max_attempts() -> int:
        try:
            return max(1, min(int(os.getenv("CI_AGENT_A2A_MAX_ATTEMPTS", "3")), 10))
        except ValueError:
            return 3

    def recovery_candidates(self) -> list[dict[str, Any]]:
        """Return submitted/working tasks that need execution after restart."""
        conn = self._conn()
        try:
            rows = conn.execute("SELECT * FROM a2a_tasks ORDER BY created_at").fetchall()
            candidates: list[dict[str, Any]] = []
            for row in rows:
                task = self._decode_row(row)
                if task.status.state not in {
                    TaskState.TASK_STATE_SUBMITTED,
                    TaskState.TASK_STATE_WORKING,
                }:
                    continue
                candidates.append({
                    "task": task,
                    "owner_id": row[2],
                    "tenant_id": row[3],
                    "internal_thread_id": row[4],
                })
            return candidates
        finally:
            conn.close()

    def claim_execution(self, task_id: str, owner: str, tenant: str = "", lease_seconds: int = 120) -> bool:
        """Atomically acquire a lease so two provider processes do not run one task."""
        now = datetime.now(UTC)
        lease_until = (now + timedelta(seconds=max(5, int(lease_seconds)))).isoformat()
        conn = self._conn()
        try:
            cursor = conn.execute(
                """UPDATE a2a_tasks SET attempts = attempts + 1, lease_until = ?, updated_at = ?
                   WHERE task_id = ? AND owner_id = ? AND tenant_id = ?
                     AND (lease_until IS NULL OR lease_until <= ?)
                     AND json_extract(status_json, '$.state') IN ('TASK_STATE_SUBMITTED', 'TASK_STATE_WORKING')""",
                (lease_until, now.isoformat(), task_id, owner, tenant, now.isoformat()),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def execution_info(self, task_id: str, owner: str, tenant: str = "") -> dict[str, Any] | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT attempts, max_attempts, lease_until, last_error FROM a2a_tasks WHERE task_id = ? AND owner_id = ? AND tenant_id = ?",
                (task_id, owner, tenant),
            ).fetchone()
            if row is None:
                return None
            return dict(row) if hasattr(row, "keys") else dict(zip(("attempts", "max_attempts", "lease_until", "last_error"), row))
        finally:
            conn.close()

    def release_execution(self, task_id: str, owner: str, tenant: str = "", error: str | None = None) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE a2a_tasks SET lease_until = NULL, last_error = ?, updated_at = ? WHERE task_id = ? AND owner_id = ? AND tenant_id = ?",
                (str(error)[:2000] if error else None, _now(), task_id, owner, tenant),
            )
            conn.commit()
        finally:
            conn.close()

    def append_event(self, task_id: str, owner: str, tenant: str, kind: str, payload: dict[str, Any]) -> int:
        conn = self._conn()
        try:
            row = conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM a2a_task_events WHERE task_id = ?", (task_id,)).fetchone()
            sequence = int(row[0] or 0) + 1
            conn.execute(
                "INSERT INTO a2a_task_events (task_id, sequence, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (task_id, sequence, kind, json.dumps(payload, ensure_ascii=False, default=str), _now()),
            )
            conn.commit()
            return sequence
        finally:
            conn.close()

    def events(self, task_id: str, owner: str, tenant: str = "", after: int = 0) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            allowed = conn.execute("SELECT 1 FROM a2a_tasks WHERE task_id = ? AND owner_id = ? AND tenant_id = ?", (task_id, owner, tenant)).fetchone()
            if allowed is None:
                return []
            rows = conn.execute("SELECT sequence, event_type, payload_json FROM a2a_task_events WHERE task_id = ? AND sequence > ? ORDER BY sequence", (task_id, after)).fetchall()
            return [{"sequence": row[0], "kind": row[1], "payload": json.loads(row[2] or "{}")} for row in rows]
        finally:
            conn.close()

    @staticmethod
    def _decode_row(row: sqlite3.Row | tuple) -> Task:
        # sqlite3 returns tuples by default; column order follows CREATE TABLE.
        task = Task(id=row[0], context_id=row[1])
        ParseDict(json.loads(row[5] or "{}"), task.status)
        for item in json.loads(row[7] or "[]"):
            ParseDict(item, task.artifacts.add())
        for item in json.loads(row[6] or "[]"):
            ParseDict(item, task.history.add())
        task.metadata.update(json.loads(row[8] or "{}"))
        return task


__all__ = ["A2AStore"]
