"""SQLite repository for the durable competitive-intelligence pool (P0-A)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from competition.db import DEFAULT_DB_PATH, init_db
from competition.intelligence import IntelligenceItem, build_intelligence_item


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class IntelligenceRepository:
    """Persistence boundary for sources, current facts and fact versions."""

    def __init__(self, conn=None, db_path=DEFAULT_DB_PATH):
        self._owned = conn is None
        self.conn = conn or init_db(db_path)

    def close(self) -> None:
        if self._owned:
            self.conn.close()

    def __enter__(self) -> IntelligenceRepository:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def ingest_collected_points(self, points: list[dict], *, scope: str = "Global / unspecified") -> dict[str, Any]:
        """Upsert points and create a new version only when content changes."""
        stats = {"inserted": 0, "updated": 0, "unchanged": 0, "versions_created": 0, "source_count": 0, "item_keys": []}
        source_keys: set[str] = set()
        for point in points:
            item = build_intelligence_item(point, scope=scope)
            source_key = self._upsert_source(item)
            source_keys.add(source_key)
            row = self.conn.execute(
                "SELECT content_hash, first_seen_at, last_seen_at, status FROM intelligence_items WHERE item_key = ?",
                (item.item_key,),
            ).fetchone()
            if row is None:
                self._insert_item(item)
                self._insert_version(item, 1)
                stats["inserted"] += 1
                stats["versions_created"] += 1
            elif row[0] == item.content_hash:
                self.conn.execute(
                    "UPDATE intelligence_items SET last_seen_at = ?, fetched_at = ?, confidence = ?, status = 'available' WHERE item_key = ?",
                    (item.fetched_at, item.fetched_at, item.confidence, item.item_key),
                )
                stats["unchanged"] += 1
            else:
                version = self._next_version(item.item_key)
                self.conn.execute(
                    """UPDATE intelligence_items SET value = ?, published_at = ?, fetched_at = ?, last_seen_at = ?,
                       content_hash = ?, confidence = ?, status = 'available', payload_json = ? WHERE item_key = ?""",
                    (str(item.value), item.published_at, item.fetched_at, item.fetched_at, item.content_hash,
                     item.confidence, json.dumps(item.payload, ensure_ascii=False, default=str), item.item_key),
                )
                self._insert_version(item, version)
                stats["updated"] += 1
                stats["versions_created"] += 1
            stats["item_keys"].append(item.item_key)
        self.conn.commit()
        stats["source_count"] = len(source_keys)
        return stats

    def list_items(self, *, product: str | None = None, dimension: str | None = None,
                   source_type: str | None = None, status: str | None = None,
                   scope: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        for field, value in (("product", product), ("dimension", dimension), ("source_type", source_type), ("status", status), ("scope", scope)):
            if value:
                clauses.append(f"{field} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        rows = self.conn.execute(
            f"SELECT item_key, product, dimension, label, value, source_url, canonical_url, "
            f"source_type, source_domain, scope, published_at, fetched_at, first_seen_at, "
            f"last_seen_at, content_hash, confidence, credibility_tier, status, payload_json "
            f"FROM intelligence_items {where} ORDER BY last_seen_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [self._decode_item(row) for row in rows]

    def get_versions(self, item_key: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT version_no, content_hash, payload_json, observed_at FROM intelligence_item_versions WHERE item_key = ? ORDER BY version_no ASC",
            (item_key,),
        ).fetchall()
        return [{"version": row[0], "content_hash": row[1], "payload": json.loads(row[2]), "observed_at": row[3]} for row in rows]

    def _upsert_source(self, item: IntelligenceItem) -> str:
        source_key = "|".join((item.canonical_url, item.source_type, item.product.lower(), item.scope.lower()))
        now = _now_iso()
        self.conn.execute(
            """INSERT INTO intelligence_sources (
                source_key, canonical_url, source_url, source_domain, source_type,
                product, scope, status, last_success_at, last_fetched_at,
                failure_count, created_at, updated_at
            )
               VALUES (?, ?, ?, ?, ?, ?, ?, 'healthy', ?, ?, 0, ?, ?)
               ON CONFLICT(source_key) DO UPDATE SET
                 source_url = excluded.source_url,
                 last_success_at = excluded.last_success_at,
                 last_fetched_at = excluded.last_fetched_at,
                 status = 'healthy', failure_count = 0,
                 updated_at = excluded.updated_at""",
            (
                source_key, item.canonical_url, item.source_url, item.source_domain,
                item.source_type, item.product, item.scope, now, now, now, now,
            ),
        )
        return source_key

    def _insert_item(self, item: IntelligenceItem) -> None:
        self.conn.execute(
            """INSERT INTO intelligence_items (
                item_key, product, dimension, label, value, source_url, canonical_url,
                source_type, source_domain, scope, published_at, fetched_at,
                first_seen_at, last_seen_at, content_hash, confidence,
                credibility_tier, status, payload_json
            )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.item_key, item.product, item.dimension, item.label,
                str(item.value), item.source_url, item.canonical_url,
                item.source_type, item.source_domain, item.scope, item.published_at,
                item.fetched_at, item.first_seen_at, item.last_seen_at,
                item.content_hash, item.confidence, item.credibility_tier,
                item.status, json.dumps(item.payload, ensure_ascii=False, default=str),
            ),
        )

    def _insert_version(self, item: IntelligenceItem, version: int) -> None:
        self.conn.execute(
            "INSERT INTO intelligence_item_versions (item_key, version_no, content_hash, payload_json, observed_at) VALUES (?, ?, ?, ?, ?)",
            (item.item_key, version, item.content_hash, json.dumps(item.payload, ensure_ascii=False, default=str), item.fetched_at),
        )

    def _next_version(self, item_key: str) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(version_no), 0) FROM intelligence_item_versions WHERE item_key = ?", (item_key,)).fetchone()
        return int(row[0] or 0) + 1

    @staticmethod
    def _decode_item(row) -> dict:
        keys = (
            "item_key", "product", "dimension", "label", "value", "source_url",
            "canonical_url", "source_type", "source_domain", "scope", "published_at",
            "fetched_at", "first_seen_at", "last_seen_at", "content_hash",
            "confidence", "credibility_tier", "status", "payload",
        )
        data = dict(zip(keys, row, strict=True))
        data["payload"] = json.loads(data["payload"]) if data["payload"] else {}
        return data
