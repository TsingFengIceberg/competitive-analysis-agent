"""Persistence boundary for reproducible offline RAG evaluation runs."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from competition.db import DEFAULT_DB_PATH, init_db


def _now() -> str:
    return datetime.now(UTC).isoformat()


class KnowledgeEvaluationRepository:
    def __init__(self, conn=None, db_path=DEFAULT_DB_PATH):
        self._owned = conn is None
        self.conn = conn or init_db(db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._owned:
            self.conn.close()

    def __enter__(self) -> KnowledgeEvaluationRepository:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def save(
        self,
        *,
        user_id: str,
        dataset_name: str,
        status: str,
        metrics: dict[str, Any],
        failures: list[str],
        case_count: int,
    ) -> dict[str, Any]:
        run_id = f"keval-{uuid.uuid4().hex}"
        created_at = _now()
        self.conn.execute(
            """INSERT INTO knowledge_evaluation_runs (
                   run_id, user_id, dataset_name, status, metrics_json,
                   failures_json, case_count, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, user_id, dataset_name, status, json.dumps(metrics, ensure_ascii=False, default=str), json.dumps(failures, ensure_ascii=False), int(case_count), created_at),
        )
        self.conn.commit()
        return {"run_id": run_id, "user_id": user_id, "dataset_name": dataset_name, "status": status, "metrics": metrics, "failures": failures, "case_count": int(case_count), "created_at": created_at}

    def list(self, user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT run_id, user_id, dataset_name, status, metrics_json, failures_json, case_count, created_at FROM knowledge_evaluation_runs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, max(1, min(int(limit), 200))),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metrics"] = _load(item.pop("metrics_json", "{}"), {})
            item["failures"] = _load(item.pop("failures_json", "[]"), [])
            result.append(item)
        return result

    def previous(self, user_id: str, dataset_name: str) -> dict[str, Any] | None:
        rows = self.list(user_id, limit=50)
        for item in rows:
            if item.get("dataset_name") == dataset_name:
                return item
        return None

    def save_feedback(
        self,
        *,
        user_id: str,
        query: str,
        chunk_id: str,
        action: str,
        retrieval_id: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        if action not in {"relevant", "not_relevant", "citation_used"}:
            raise ValueError("Unsupported retrieval feedback action")
        feedback_id = f"krfb-{uuid.uuid4().hex}"
        created_at = _now()
        self.conn.execute(
            """INSERT INTO knowledge_retrieval_feedback (
                feedback_id, user_id, retrieval_id, query, chunk_id, action, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, retrieval_id, chunk_id, action) DO UPDATE SET
                note=excluded.note, created_at=excluded.created_at""",
            (feedback_id, user_id, retrieval_id, query.strip(), chunk_id, action, note.strip(), created_at),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT feedback_id, user_id, retrieval_id, query, chunk_id, action, note, created_at FROM knowledge_retrieval_feedback WHERE user_id = ? AND retrieval_id IS ? AND chunk_id = ? AND action = ?",
            (user_id, retrieval_id, chunk_id, action),
        ).fetchone()
        return (
            dict(row)
            if row
            else {
                "feedback_id": feedback_id,
                "user_id": user_id,
                "retrieval_id": retrieval_id,
                "query": query,
                "chunk_id": chunk_id,
                "action": action,
                "note": note,
                "created_at": created_at,
            }
        )

    def feedback_summary(self, user_id: str) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT action, COUNT(*) AS count FROM knowledge_retrieval_feedback WHERE user_id = ? GROUP BY action",
            (user_id,),
        ).fetchall()
        counts = {str(row[0]): int(row[1]) for row in rows}
        relevant = counts.get("relevant", 0)
        not_relevant = counts.get("not_relevant", 0)
        total_judged = relevant + not_relevant
        return {
            "total": sum(counts.values()),
            "by_action": counts,
            "judged": total_judged,
            "relevance_rate": round(relevant / total_judged, 6) if total_judged else None,
        }

    def list_feedback(self, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT feedback_id, user_id, retrieval_id, query, chunk_id, action, note, created_at FROM knowledge_retrieval_feedback WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [dict(row) for row in rows]


def _load(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def compare_evaluation_metrics(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """Compare scalar metrics against the previous run without exposing data."""
    if not previous:
        return {"status": "baseline", "previous_run_id": None, "deltas": {}}
    old_metrics = previous.get("metrics") if isinstance(previous.get("metrics"), dict) else {}
    deltas: dict[str, float] = {}

    def walk(prefix: str, current_value: Any, old_value: Any) -> None:
        if isinstance(current_value, dict) and isinstance(old_value, dict):
            for key, value in current_value.items():
                if key in old_value:
                    walk(f"{prefix}.{key}" if prefix else str(key), value, old_value[key])
        elif isinstance(current_value, (int, float)) and isinstance(old_value, (int, float)):
            deltas[prefix] = round(float(current_value) - float(old_value), 6)

    walk("", current, old_metrics)
    regressions = [key for key, delta in deltas.items() if delta < -0.000001]
    improvements = [key for key, delta in deltas.items() if delta > 0.000001]
    return {
        "status": "regressed" if regressions else ("improved" if improvements else "stable"),
        "previous_run_id": previous.get("run_id"),
        "deltas": deltas,
        "regressions": regressions,
        "improvements": improvements,
    }
