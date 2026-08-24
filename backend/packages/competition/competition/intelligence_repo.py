"""SQLite repository for the durable competitive-intelligence pool (P0-A)."""

from __future__ import annotations

import hashlib
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
        stats = {
            "inserted": 0, "updated": 0, "unchanged": 0, "versions_created": 0,
            "source_count": 0, "item_keys": [], "material_changes": 0,
            "change_events": [],
        }
        source_keys: set[str] = set()
        for point in points:
            item = build_intelligence_item(point, scope=scope)
            source_key = self._upsert_source(item)
            source_keys.add(source_key)
            row = self.conn.execute(
                "SELECT content_hash, value, label, published_at, payload_json FROM intelligence_items WHERE item_key = ?",
                (item.item_key,),
            ).fetchone()
            if row is None:
                self._insert_item(item)
                self._insert_version(item, 1)
                change = self._record_change(item, change_type="new_fact", material=True)
                stats["inserted"] += 1
                stats["versions_created"] += 1
                stats["material_changes"] += 1
                stats["change_events"].append(change)
            elif row[0] == item.content_hash:
                self.conn.execute(
                    "UPDATE intelligence_items SET last_seen_at = ?, fetched_at = ?, confidence = ?, status = 'available' WHERE item_key = ?",
                    (item.fetched_at, item.fetched_at, item.confidence, item.item_key),
                )
                stats["unchanged"] += 1
            else:
                version = self._next_version(item.item_key)
                old_value = row[1]
                old_payload = json.loads(row[4]) if row[4] else {}
                material = str(old_value) != str(item.value) or str(row[2]) != str(item.label)
                change_type = "fact_changed" if material else "page_changed"
                self.conn.execute(
                    """UPDATE intelligence_items SET label = ?, value = ?, published_at = ?, fetched_at = ?, last_seen_at = ?,
                       content_hash = ?, confidence = ?, status = 'available', payload_json = ? WHERE item_key = ?""",
                    (item.label, str(item.value), item.published_at, item.fetched_at, item.fetched_at, item.content_hash,
                     item.confidence, json.dumps(item.payload, ensure_ascii=False, default=str), item.item_key),
                )
                self._insert_version(item, version)
                change = self._record_change(
                    item, change_type=change_type, material=material,
                    old_hash=row[0], old_value=old_value,
                    old_payload=old_payload,
                )
                stats["updated"] += 1
                stats["versions_created"] += 1
                stats["material_changes"] += int(material)
                stats["change_events"].append(change)
            stats["item_keys"].append(item.item_key)
        self.conn.commit()
        stats["source_count"] = len(source_keys)
        return stats

    def list_changes(self, *, product: str | None = None, dimension: str | None = None,
                     material_only: bool = False, limit: int = 100, offset: int = 0) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if product:
            clauses.append("product = ?")
            params.append(product)
        if dimension:
            clauses.append("dimension = ?")
            params.append(dimension)
        if material_only:
            clauses.append("material = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        rows = self.conn.execute(
            f"SELECT change_id, item_key, product, dimension, source_domain, change_type, material, "
            f"old_hash, new_hash, old_value, new_value, detected_at, payload_json "
            f"FROM intelligence_changes {where} ORDER BY detected_at DESC LIMIT ? OFFSET ?", params,
        ).fetchall()
        keys = ("change_id", "item_key", "product", "dimension", "source_domain", "change_type", "material",
                "old_hash", "new_hash", "old_value", "new_value", "detected_at", "payload")
        result = []
        for row in rows:
            item = dict(zip(keys, row, strict=True))
            item["material"] = bool(item["material"])
            item["payload"] = json.loads(item["payload"]) if item["payload"] else {}
            result.append(item)
        return result

    def get_change_detail(self, change_id: str) -> dict | None:
        """Return one change with its current fact, evidence, and version history."""
        row = self.conn.execute(
            """SELECT change_id, item_key, product, dimension, source_domain, change_type,
                      material, old_hash, new_hash, old_value, new_value, detected_at, payload_json
               FROM intelligence_changes WHERE change_id = ?""",
            (change_id,),
        ).fetchone()
        if row is None:
            return None

        keys = (
            "change_id", "item_key", "product", "dimension", "source_domain", "change_type",
            "material", "old_hash", "new_hash", "old_value", "new_value", "detected_at", "payload",
        )
        change = dict(zip(keys, row, strict=True))
        change["material"] = bool(change["material"])
        change["payload"] = json.loads(change["payload"]) if change["payload"] else {}

        item_row = self.conn.execute(
            """SELECT item_key, product, dimension, label, value, source_url, canonical_url,
                      source_type, source_domain, scope, published_at, fetched_at, first_seen_at,
                      last_seen_at, content_hash, confidence, credibility_tier, status, payload_json
               FROM intelligence_items WHERE item_key = ?""",
            (change["item_key"],),
        ).fetchone()
        item = self._decode_item(item_row) if item_row else None
        versions = self.get_versions(change["item_key"])

        return {
            "change": change,
            "item": item,
            "versions": versions,
            "sources": self._detail_sources(item) if item else [],
        }

    def mark_source_failure(self, source_key: str, error: str, *, cooldown_status: str = "degraded") -> None:
        now = _now_iso()
        self.conn.execute(
            """UPDATE intelligence_sources SET status = ?, failure_count = failure_count + 1,
               last_error = ?, updated_at = ? WHERE source_key = ?""",
            (cooldown_status, str(error)[:500], now, source_key),
        )
        self.conn.commit()

    def _record_change(self, item: IntelligenceItem, *, change_type: str, material: bool,
                       old_hash: str | None = None, old_value: Any = None,
                       old_payload: dict | None = None) -> dict:
        now = item.fetched_at or _now_iso()
        raw_id = f"{item.item_key}|{item.content_hash}|{change_type}|{now}"
        change_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
        payload = {
            "source_url": item.source_url,
            "canonical_url": item.canonical_url,
            "old_payload": old_payload or {},
            "new_payload": item.payload,
        }
        self.conn.execute(
            """INSERT OR IGNORE INTO intelligence_changes (
               change_id, item_key, product, dimension, source_domain, change_type,
               material, old_hash, new_hash, old_value, new_value, detected_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (change_id, item.item_key, item.product, item.dimension, item.source_domain,
             change_type, int(material), old_hash, item.content_hash, str(old_value) if old_value is not None else None,
             str(item.value), now, json.dumps(payload, ensure_ascii=False, default=str)),
        )
        return {
            "change_id": change_id, "item_key": item.item_key, "product": item.product,
            "dimension": item.dimension, "source_domain": item.source_domain,
            "change_type": change_type, "material": material, "old_hash": old_hash,
            "new_hash": item.content_hash, "old_value": old_value, "new_value": item.value,
            "detected_at": now, "payload": payload,
        }

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

    def _detail_sources(self, item: dict) -> list[dict]:
        """Return source metadata related to the current fact for the detail view."""
        rows = self.conn.execute(
            """SELECT source_key, source_url, canonical_url, source_domain, source_type,
                      product, scope, status, last_success_at, last_fetched_at, failure_count
               FROM intelligence_sources
               WHERE product = ? AND scope = ? AND source_domain = ?
               ORDER BY last_fetched_at DESC""",
            (item["product"], item["scope"], item["source_domain"]),
        ).fetchall()
        keys = (
            "source_key", "source_url", "canonical_url", "source_domain", "source_type",
            "product", "scope", "status", "last_success_at", "last_fetched_at", "failure_count",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

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
