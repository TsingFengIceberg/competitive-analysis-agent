"""Durable competitor-observation schedules and a small cooperative scheduler."""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from competition.db import DEFAULT_DB_PATH, init_db

logger = logging.getLogger(__name__)
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


@dataclass
class ScheduleSpec:
    name: str
    products: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    market_scope: str = "Global / unspecified"
    daily_times: list[str] = field(default_factory=list)
    interval_minutes: int | None = None
    enabled: bool = True
    schedule_id: str = ""
    user_id: str = "default"

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()[:120]
        if not self.name:
            raise ValueError("schedule name is required")
        self.daily_times = sorted(set(str(item).strip() for item in self.daily_times))
        if any(not _TIME_RE.fullmatch(item) for item in self.daily_times):
            raise ValueError("daily_times must use HH:MM")
        if self.interval_minutes is not None:
            self.interval_minutes = int(self.interval_minutes)
            if self.interval_minutes < 5:
                raise ValueError("interval_minutes must be at least 5")
        if not self.daily_times and self.interval_minutes is None:
            raise ValueError("configure daily_times or interval_minutes")
        self.products = list(dict.fromkeys(str(item).strip() for item in self.products if str(item).strip()))[:20]
        self.dimensions = list(dict.fromkeys(str(item).strip() for item in self.dimensions if str(item).strip()))[:30]
        self.schedule_id = self.schedule_id or uuid.uuid4().hex

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ScheduleSpec:
        return cls(
            name=payload.get("name", ""), products=payload.get("products") or [],
            dimensions=payload.get("dimensions") or [], market_scope=payload.get("market_scope") or "Global / unspecified",
            daily_times=payload.get("daily_times") or [], interval_minutes=payload.get("interval_minutes"),
            enabled=bool(payload.get("enabled", True)), schedule_id=str(payload.get("schedule_id") or ""),
            user_id=str(payload.get("user_id") or "default"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id, "user_id": self.user_id, "name": self.name,
            "products": self.products, "dimensions": self.dimensions, "market_scope": self.market_scope,
            "daily_times": self.daily_times, "interval_minutes": self.interval_minutes, "enabled": self.enabled,
        }


class ScheduleRepository:
    """SQLite persistence boundary for schedules and run lifecycle state."""

    def __init__(self, conn=None, db_path=DEFAULT_DB_PATH):
        self._owned = conn is None
        self.conn = conn or init_db(db_path)

    def close(self) -> None:
        if self._owned:
            self.conn.close()

    def save(self, spec: ScheduleSpec, *, next_run_at: str | None = None) -> dict:
        now = _iso(_now())
        existing = self.get(spec.schedule_id)
        self.conn.execute(
            """INSERT INTO observation_schedules (
               schedule_id, user_id, name, products_json, dimensions_json, market_scope,
               daily_times_json, interval_minutes, enabled, next_run_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(schedule_id) DO UPDATE SET user_id=excluded.user_id, name=excluded.name,
              products_json=excluded.products_json, dimensions_json=excluded.dimensions_json,
              market_scope=excluded.market_scope, daily_times_json=excluded.daily_times_json,
              interval_minutes=excluded.interval_minutes, enabled=excluded.enabled,
              next_run_at=COALESCE(excluded.next_run_at, observation_schedules.next_run_at), updated_at=excluded.updated_at""",
            (spec.schedule_id, spec.user_id, spec.name, json.dumps(spec.products, ensure_ascii=False),
             json.dumps(spec.dimensions, ensure_ascii=False), spec.market_scope, json.dumps(spec.daily_times),
             spec.interval_minutes, int(spec.enabled), next_run_at, existing.get("created_at") if existing else now, now),
        )
        self.conn.commit()
        return self.get(spec.schedule_id) or spec.to_dict()

    def get(self, schedule_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM observation_schedules WHERE schedule_id = ?", (schedule_id,)).fetchone()
        return self._decode(row) if row else None

    def list(self, *, user_id: str | None = None, enabled_only: bool = False) -> list[dict]:
        clauses, params = [], []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if enabled_only:
            clauses.append("enabled = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(f"SELECT * FROM observation_schedules {where} ORDER BY created_at ASC", params).fetchall()
        return [self._decode(row) for row in rows]

    def update_runtime(self, schedule_id: str, **fields: Any) -> None:
        allowed = {"next_run_at", "last_run_at", "last_success_at", "last_failure_at", "last_status", "last_error", "last_skip_reason", "enabled", "lease_owner", "lease_until"}
        updates = [(key, value) for key, value in fields.items() if key in allowed]
        if not updates:
            return
        updates.append(("updated_at", _iso(_now())))
        self.conn.execute(f"UPDATE observation_schedules SET {', '.join(f'{key} = ?' for key, _ in updates)} WHERE schedule_id = ?", [value for _, value in updates] + [schedule_id])
        self.conn.commit()

    def record_run(self, schedule_id: str, *, status: str, started_at: str, finished_at: str | None = None,
                   summary: dict | None = None, error: str | None = None, skip_reason: str | None = None) -> dict:
        run_id = uuid.uuid4().hex
        self.conn.execute(
            "INSERT INTO observation_runs (run_id, schedule_id, started_at, finished_at, status, summary_json, error, skip_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, schedule_id, started_at, finished_at, status, json.dumps(summary or {}, ensure_ascii=False, default=str), error, skip_reason),
        )
        self.conn.commit()
        return {"run_id": run_id, "schedule_id": schedule_id, "started_at": started_at, "finished_at": finished_at, "status": status, "summary": summary or {}, "error": error, "skip_reason": skip_reason}

    def list_runs(self, *, user_id: str | None = None, schedule_id: str | None = None, limit: int = 100) -> list[dict]:
        clauses, params = [], []
        if user_id is not None:
            clauses.append("s.user_id = ?")
            params.append(user_id)
        if schedule_id is not None:
            clauses.append("r.schedule_id = ?")
            params.append(schedule_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        rows = self.conn.execute(
            f"""SELECT r.run_id, r.schedule_id, s.name, r.started_at, r.finished_at,
                       r.status, r.summary_json, r.error, r.skip_reason
                FROM observation_runs r
                JOIN observation_schedules s ON s.schedule_id = r.schedule_id
                {where}
                ORDER BY r.started_at DESC LIMIT ?""",
            params,
        ).fetchall()
        keys = ("run_id", "schedule_id", "schedule_name", "started_at", "finished_at", "status", "summary", "error", "skip_reason")
        result = []
        for row in rows:
            item = dict(zip(keys, row, strict=True))
            item["summary"] = json.loads(item["summary"]) if item["summary"] else {}
            result.append(item)
        return result

    def claim_due(self, *, owner: str, user_id: str | None = None, limit: int = 20, now: datetime | None = None, lease_seconds: int = 300) -> list[dict]:
        """Atomically lease due schedules so multiple API processes do not duplicate runs."""
        current = now or datetime.now(UTC)
        now_iso = _iso(current)
        lease_until = _iso(current + timedelta(seconds=max(30, int(lease_seconds))))
        if self.conn.in_transaction:
            self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            where = ["enabled = 1", "next_run_at IS NOT NULL", "next_run_at <= ?", "(lease_until IS NULL OR lease_until <= ?)"]
            params: list[Any] = [now_iso, now_iso]
            if user_id:
                where.append("user_id = ?")
                params.append(user_id)
            params.append(max(1, min(int(limit), 100)))
            rows = self.conn.execute(
                f"SELECT * FROM observation_schedules WHERE {' AND '.join(where)} ORDER BY next_run_at ASC LIMIT ?",
                params,
            ).fetchall()
            claimed: list[dict] = []
            for row in rows:
                schedule_id = str(row[0])
                self.conn.execute(
                    "UPDATE observation_schedules SET lease_owner = ?, lease_until = ?, updated_at = ? WHERE schedule_id = ?",
                    (owner, lease_until, now_iso, schedule_id),
                )
                item = self._decode(self.conn.execute("SELECT * FROM observation_schedules WHERE schedule_id = ?", (schedule_id,)).fetchone())
                if item:
                    claimed.append(item)
            self.conn.commit()
            return claimed
        except Exception:
            self.conn.rollback()
            raise

    def list_report_runs(
        self,
        *,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List observation runs that produced a deep-analysis report.

        This intentionally projects only report-index fields instead of
        returning the potentially large collection summary stored per run.
        """
        clauses = ["NULLIF(json_extract(r.summary_json, '$.deep_analysis.thread_id'), '') IS NOT NULL"]
        params: list[Any] = []
        if user_id is not None:
            clauses.append("s.user_id = ?")
            params.append(user_id)
        params.extend((max(1, min(int(limit), 500)), max(0, int(offset))))
        rows = self.conn.execute(
            f"""SELECT r.run_id, r.schedule_id, s.name, r.started_at, r.finished_at,
                       r.status,
                       COALESCE(json_extract(r.summary_json, '$.material_changes'), 0),
                       json_extract(r.summary_json, '$.deep_analysis.thread_id'),
                       json_extract(r.summary_json, '$.deep_analysis.status')
                FROM observation_runs r
                JOIN observation_schedules s ON s.schedule_id = r.schedule_id
                WHERE {' AND '.join(clauses)}
                ORDER BY r.started_at DESC LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
        keys = (
            "run_id", "schedule_id", "schedule_name", "started_at", "finished_at",
            "status", "material_changes", "thread_id", "report_status",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def count_report_runs(self, *, user_id: str | None = None) -> int:
        """Count observation runs that produced a deep-analysis report."""
        clauses = ["NULLIF(json_extract(r.summary_json, '$.deep_analysis.thread_id'), '') IS NOT NULL"]
        params: list[Any] = []
        if user_id is not None:
            clauses.append("s.user_id = ?")
            params.append(user_id)
        row = self.conn.execute(
            f"""SELECT COUNT(*)
                FROM observation_runs r
                JOIN observation_schedules s ON s.schedule_id = r.schedule_id
                WHERE {' AND '.join(clauses)}""",
            params,
        ).fetchone()
        return int(row[0]) if row else 0

    def get_report_run(self, run_id: str, *, user_id: str) -> dict | None:
        """Return one report-producing observation run with its full summary."""
        row = self.conn.execute(
            """SELECT r.run_id, r.schedule_id, s.name, s.user_id, r.started_at, r.finished_at,
                       r.status, r.summary_json, r.error, r.skip_reason
                  FROM observation_runs r
                  JOIN observation_schedules s ON s.schedule_id = r.schedule_id
                 WHERE r.run_id = ? AND s.user_id = ?""",
            (run_id, user_id),
        ).fetchone()
        if not row:
            return None
        keys = ("run_id", "schedule_id", "schedule_name", "user_id", "started_at", "finished_at", "status", "summary", "error", "skip_reason")
        item = dict(zip(keys, row, strict=True))
        item["summary"] = json.loads(item["summary"]) if item["summary"] else {}
        deep = item["summary"].get("deep_analysis") or {}
        item["thread_id"] = deep.get("thread_id")
        item["report_status"] = deep.get("status")
        return item

    @staticmethod
    def _decode(row) -> dict:
        keys = (
            "schedule_id", "user_id", "name", "products", "dimensions", "market_scope", "daily_times",
            "interval_minutes", "enabled", "next_run_at", "last_run_at", "last_success_at", "last_failure_at",
            "last_status", "last_error", "last_skip_reason", "lease_owner", "lease_until", "created_at", "updated_at",
        )
        data = dict(zip(keys, row, strict=True))
        for key in ("products", "dimensions", "daily_times"):
            data[key] = json.loads(data[key]) if data[key] else []
        data["enabled"] = bool(data["enabled"])
        return data


class ObservationScheduler:
    """Thread-safe scheduler with a global lock and manual execution support."""

    _global_run_lock = threading.Lock()

    def __init__(self, repository: ScheduleRepository | None = None, runner: Callable[[dict], dict] | None = None,
                 deep_runner: Callable[[dict, dict], dict] | None = None, clock: Callable[[], datetime] = _now,
                 task_submitter: Callable[[dict, bool], dict] | None = None):
        self.repository = repository or ScheduleRepository()
        self.runner = runner
        self.deep_runner = deep_runner
        self.clock = clock
        self.task_submitter = task_submitter
        self._owner = f"scheduler-{uuid.uuid4().hex[:12]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def close(self) -> None:
        self.stop()
        self.repository.close()

    def add_schedule(self, spec: ScheduleSpec) -> dict:
        now = self.clock()
        return self.repository.save(spec, next_run_at=_iso(self.next_run(spec, now)))

    def remove_schedule(self, schedule_id: str) -> None:
        self.repository.conn.execute("DELETE FROM observation_runs WHERE schedule_id = ?", (schedule_id,))
        self.repository.conn.execute("DELETE FROM observation_schedules WHERE schedule_id = ?", (schedule_id,))
        self.repository.conn.commit()

    def list_schedules(self, *, user_id: str | None = None) -> list[dict]:
        return self.repository.list(user_id=user_id)

    def run_now(self, schedule_id: str) -> dict:
        schedule = self.repository.get(schedule_id)
        if not schedule:
            raise KeyError(schedule_id)
        return self._execute(schedule, manual=True)

    def tick(self, now: datetime | None = None, *, user_id: str | None = None) -> list[dict]:
        now = now or self.clock()
        results = []
        for schedule in self.repository.claim_due(owner=self._owner, user_id=user_id, now=now):
            results.append(self._execute(schedule, manual=False))
        return results

    def start(self, poll_seconds: int = 30) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop() -> None:
            while not self._stop.wait(max(5, int(poll_seconds))):
                try:
                    self.tick()
                except Exception:
                    logger.exception("Observation scheduler tick failed")

        self._thread = threading.Thread(target=loop, name="ci-observation-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None

    @staticmethod
    def next_run(schedule: dict | ScheduleSpec, now: datetime) -> datetime:
        values = schedule.to_dict() if isinstance(schedule, ScheduleSpec) else schedule
        interval = values.get("interval_minutes")
        if interval:
            return now + timedelta(minutes=int(interval))
        candidates = []
        for value in values.get("daily_times") or []:
            hour, minute = (int(part) for part in value.split(":", 1))
            candidates.append(now.replace(hour=hour, minute=minute, second=0, microsecond=0))
        future = [candidate for candidate in candidates if candidate > now]
        return min(future) if future else min(candidates) + timedelta(days=1)

    def _execute(self, schedule: dict, *, manual: bool) -> dict:
        if self.task_submitter is not None:
            return self.task_submitter(schedule, manual)
        now = self.clock()
        next_run = _iso(self.next_run(schedule, now))
        if not self._global_run_lock.acquire(blocking=False):
            reason = "another observation is already running"
            self.repository.update_runtime(schedule["schedule_id"], last_status="skipped", last_skip_reason=reason, next_run_at=next_run)
            return self.repository.record_run(schedule["schedule_id"], status="skipped", started_at=_iso(now) or "", finished_at=_iso(now), skip_reason=reason)
        started = _iso(now) or ""
        self.repository.update_runtime(schedule["schedule_id"], last_run_at=started, last_status="running", next_run_at=next_run, last_error="", last_skip_reason="")
        try:
            result = self.runner(schedule) if self.runner else {"status": "skipped", "skip_reason": "no runner configured"}
            result = result if isinstance(result, dict) else {"result": result}
            material = int(result.get("material_changes", 0) or 0)
            # Collection and deep analysis are deliberately separate.  A clean
            # collection never invokes the expensive callback.
            if material and self.deep_runner:
                deep_result = self.deep_runner(schedule, result)
                if isinstance(deep_result, dict):
                    result = {**result, "deep_analysis": deep_result}
            status = str(result.get("status") or ("completed" if material else "skipped"))
            skip_reason = result.get("skip_reason") or ("no_material_change" if status == "skipped" else None)
            finished = _iso(self.clock()) or started
            self.repository.update_runtime(
                schedule["schedule_id"], last_status=status, last_success_at=finished if status in {"completed", "skipped"} else None,
                last_failure_at=finished if status == "failed" else None, last_error=str(result.get("error") or ""),
                last_skip_reason=skip_reason, next_run_at=_iso(self.next_run(schedule, self.clock())),
            )
            return self.repository.record_run(schedule["schedule_id"], status=status, started_at=started, finished_at=finished, summary=result, skip_reason=skip_reason)
        except Exception as exc:
            finished = _iso(self.clock()) or started
            self.repository.update_runtime(schedule["schedule_id"], last_status="failed", last_failure_at=finished, last_error=str(exc)[:500], next_run_at=_iso(self.next_run(schedule, self.clock())))
            return self.repository.record_run(schedule["schedule_id"], status="failed", started_at=started, finished_at=finished, error=str(exc)[:500])
        finally:
            self.repository.update_runtime(schedule["schedule_id"], lease_owner=None, lease_until=None)
            self._global_run_lock.release()
