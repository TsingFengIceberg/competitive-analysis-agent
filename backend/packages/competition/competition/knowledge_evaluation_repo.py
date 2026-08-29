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


def _load(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback
