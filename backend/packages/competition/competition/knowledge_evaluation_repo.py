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

    def build_feedback_dataset(
        self,
        user_id: str,
        *,
        dataset_name: str = "feedback-derived",
        version: str = "v1",
        limit: int = 500,
    ) -> dict[str, Any]:
        """Materialize judged retrieval feedback as reproducible eval cases."""
        rows = self.conn.execute(
            """SELECT retrieval_id, query, chunk_id, action, note, created_at
                 FROM knowledge_retrieval_feedback
                WHERE user_id = ?
                ORDER BY created_at ASC LIMIT ?""",
            (user_id, max(1, min(int(limit), 5000))),
        ).fetchall()
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            retrieval_id = str(row[0] or f"feedback:{row[1]}")
            query = str(row[1] or "").strip()
            if not query:
                continue
            entry = grouped.setdefault((retrieval_id, query), {"relevant": set(), "not_relevant": set(), "notes": []})
            chunk_id = str(row[2] or "")
            if not chunk_id:
                continue
            if row[3] in {"relevant", "citation_used"}:
                entry["relevant"].add(chunk_id)
            elif row[3] == "not_relevant":
                entry["not_relevant"].add(chunk_id)
            if row[4]:
                entry["notes"].append(str(row[4])[:500])
        cases: list[dict[str, Any]] = []
        for (retrieval_id, query), entry in grouped.items():
            relevant = sorted(entry["relevant"] - entry["not_relevant"])
            if not relevant:
                continue
            ranked = [{"label": chunk_id, "chunk_id": chunk_id, "document_id": "feedback"} for chunk_id in relevant]
            cases.append({
                "id": f"feedback-{len(cases) + 1}",
                "query": query,
                "retrieval_id": retrieval_id,
                "relevant": relevant,
                "ranked": ranked,
                "metadata": {"source": "user_feedback", "notes": entry["notes"][-5:]},
            })
        return self.save_dataset(
            user_id=user_id,
            dataset_name=dataset_name,
            version=version,
            cases=cases,
            metadata={"source": "knowledge_retrieval_feedback", "feedback_count": len(rows)},
        )

    def record_online_metric(
        self,
        *,
        user_id: str,
        metric_name: str,
        value: float,
        sample_count: int = 1,
        dimensions: dict[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        """Persist one bounded online retrieval/grounding metric sample."""
        metric_name = str(metric_name).strip()[:120]
        if not metric_name:
            raise ValueError("metric_name is required")
        if not isinstance(value, (int, float)):
            raise ValueError("metric value must be numeric")
        metric_id = f"kmetric-{uuid.uuid4().hex}"
        timestamp = observed_at or _now()
        self.conn.execute(
            """INSERT INTO knowledge_online_metrics (
                metric_id, user_id, metric_name, value, sample_count,
                dimensions_json, observed_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                metric_id,
                user_id,
                metric_name,
                float(value),
                max(1, min(int(sample_count), 1_000_000)),
                json.dumps(dimensions or {}, ensure_ascii=False, default=str),
                timestamp,
                _now(),
            ),
        )
        self.conn.commit()
        return {
            "metric_id": metric_id,
            "user_id": user_id,
            "metric_name": metric_name,
            "value": float(value),
            "sample_count": max(1, min(int(sample_count), 1_000_000)),
            "dimensions": dimensions or {},
            "observed_at": timestamp,
        }

    def online_metric_summary(self, user_id: str, *, limit: int = 200) -> dict[str, Any]:
        rows = self.conn.execute(
            """SELECT metric_name, value, sample_count, dimensions_json, observed_at
                 FROM knowledge_online_metrics
                WHERE user_id = ?
                ORDER BY observed_at DESC LIMIT ?""",
            (user_id, max(1, min(int(limit), 1000))),
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            dimensions = _load(row[3], {})
            grouped.setdefault(str(row[0]), []).append({
                "value": float(row[1]),
                "sample_count": int(row[2] or 1),
                "dimensions": dimensions,
                "observed_at": row[4],
            })
        summary: dict[str, Any] = {}
        for name, samples in grouped.items():
            weight = sum(item["sample_count"] for item in samples)
            summary[name] = {
                "weighted_mean": round(sum(item["value"] * item["sample_count"] for item in samples) / max(1, weight), 6),
                "sample_count": weight,
                "latest": samples[0],
            }
        return {"metrics": summary, "sample_count": sum(item["sample_count"] for values in grouped.values() for item in values)}

    def list_online_metrics(self, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT metric_id, user_id, metric_name, value, sample_count,
                       dimensions_json, observed_at, created_at
                 FROM knowledge_online_metrics
                WHERE user_id = ? ORDER BY observed_at DESC LIMIT ?""",
            (user_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [
            {**dict(row), "dimensions": _load(row["dimensions_json"], {})}
            | {"dimensions_json": None}
            for row in rows
        ]

    def online_metric_trend(self, user_id: str, metric_name: str, *, limit: int = 30) -> list[dict[str, Any]]:
        """Aggregate online samples by UTC day for a compact trend view."""
        rows = self.conn.execute(
            """SELECT substr(observed_at, 1, 10) AS day, value, sample_count
                 FROM knowledge_online_metrics
                WHERE user_id = ? AND metric_name = ?
                ORDER BY day DESC LIMIT ?""",
            (user_id, str(metric_name).strip()[:120], max(1, min(int(limit) * 100, 5000))),
        ).fetchall()
        grouped: dict[str, list[tuple[float, int]]] = {}
        for row in rows:
            grouped.setdefault(str(row[0]), []).append((float(row[1]), max(1, int(row[2] or 1))))
        trend: list[dict[str, Any]] = []
        for day, samples in sorted(grouped.items(), reverse=True)[: max(1, min(int(limit), 365))]:
            weight = sum(count for _, count in samples)
            trend.append({"day": day, "weighted_mean": round(sum(value * count for value, count in samples) / max(1, weight), 6), "sample_count": weight})
        return trend

    def save_dataset(
        self,
        *,
        user_id: str,
        dataset_name: str,
        version: str,
        cases: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a versioned golden set without mixing it into the KB."""
        name = str(dataset_name).strip()[:120]
        version = str(version).strip()[:40]
        if not name or not version:
            raise ValueError("dataset_name and version are required")
        now = _now()
        dataset_id = f"kds-{uuid.uuid4().hex}"
        self.conn.execute(
            """INSERT INTO knowledge_evaluation_datasets (
                   dataset_id, user_id, dataset_name, version, cases_json,
                   metadata_json, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, dataset_name, version) DO UPDATE SET
                   cases_json=excluded.cases_json, metadata_json=excluded.metadata_json,
                   updated_at=excluded.updated_at""",
            (dataset_id, user_id, name, version, json.dumps(cases[:1000], ensure_ascii=False, default=str), json.dumps(metadata or {}, ensure_ascii=False, default=str), now, now),
        )
        self.conn.commit()
        return self.get_dataset(user_id, name, version) or {"dataset_id": dataset_id, "user_id": user_id, "dataset_name": name, "version": version, "cases": cases[:1000], "metadata": metadata or {}, "updated_at": now}

    def get_dataset(self, user_id: str, dataset_name: str, version: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM knowledge_evaluation_datasets WHERE user_id = ? AND dataset_name = ? AND version = ?",
            (user_id, dataset_name, version),
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["cases"] = _load(item.pop("cases_json", "[]"), [])
        item["metadata"] = _load(item.pop("metadata_json", "{}"), {})
        return item

    def list_datasets(self, user_id: str, *, dataset_name: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if dataset_name:
            clauses.append("dataset_name = ?")
            params.append(dataset_name)
        params.append(max(1, min(int(limit), 500)))
        rows = self.conn.execute(
            f"SELECT * FROM knowledge_evaluation_datasets WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["cases"] = _load(item.pop("cases_json", "[]"), [])
            item["metadata"] = _load(item.pop("metadata_json", "{}"), {})
            result.append(item)
        return result

    def save_experiment(
        self,
        *,
        user_id: str,
        name: str,
        baseline: dict[str, Any],
        candidate: dict[str, Any],
        metrics: dict[str, Any],
        status: str = "completed",
    ) -> dict[str, Any]:
        now = _now()
        experiment_id = f"kexp-{uuid.uuid4().hex}"
        self.conn.execute(
            """INSERT INTO knowledge_retrieval_experiments (
                   experiment_id, user_id, name, status, baseline_json,
                   candidate_json, metrics_json, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                experiment_id,
                user_id,
                str(name).strip()[:160],
                status,
                json.dumps(baseline or {}, ensure_ascii=False, default=str),
                json.dumps(candidate or {}, ensure_ascii=False, default=str),
                json.dumps(metrics or {}, ensure_ascii=False, default=str),
                now,
                now,
            ),
        )
        self.conn.commit()
        return {"experiment_id": experiment_id, "user_id": user_id, "name": str(name).strip()[:160], "status": status, "baseline": baseline or {}, "candidate": candidate or {}, "metrics": metrics or {}, "created_at": now, "updated_at": now}

    def list_experiments(self, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM knowledge_retrieval_experiments WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, max(1, min(int(limit), 500))),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["baseline"] = _load(item.pop("baseline_json", "{}"), {})
            item["candidate"] = _load(item.pop("candidate_json", "{}"), {})
            item["metrics"] = _load(item.pop("metrics_json", "{}"), {})
            result.append(item)
        return result


def _load(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


_LOWER_IS_BETTER = ("latency", "error", "unsupported", "cost", "failure", "abstention_loss")


def _metric_direction(path: str) -> str:
    lowered = path.casefold()
    return "lower" if any(token in lowered for token in _LOWER_IS_BETTER) else "higher"


def compare_evaluation_metrics(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """Compare scalar metrics with metric-aware directionality."""
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
    regressions = [
        key
        for key, delta in deltas.items()
        if (delta > 0.000001 if _metric_direction(key) == "lower" else delta < -0.000001)
    ]
    improvements = [
        key
        for key, delta in deltas.items()
        if (delta < -0.000001 if _metric_direction(key) == "lower" else delta > 0.000001)
    ]
    return {
        "status": "regressed" if regressions else ("improved" if improvements else "stable"),
        "previous_run_id": previous.get("run_id"),
        "deltas": deltas,
        "regressions": regressions,
        "improvements": improvements,
        "directions": {key: _metric_direction(key) for key in deltas},
    }
