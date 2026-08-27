"""SQLite persistence for knowledge documents, versions, chunks, and jobs."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from competition.db import DEFAULT_DB_PATH, init_db
from competition.knowledge_governance import personal_space_id
from competition.knowledge_types import KnowledgeChunk

_DOCUMENT_UPDATE_FIELDS = {
    "title",
    "filename",
    "media_type",
    "source_type",
    "source_uri",
    "product",
    "dimension",
    "market_scope",
    "authority_tier",
    "status",
    "current_version",
    "content_hash",
    "file_path",
    "normalized_path",
    "size_bytes",
    "published_at",
    "observed_at",
    "error",
    "metadata_json",
    "space_id",
    "approval_status",
    "approved_by",
    "approved_at",
    "retention_until",
    "deleted_at",
    "deleted_by",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def _document_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["metadata"] = _loads(result.pop("metadata_json", "{}"), {})
    return result


def _version_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = _loads(result.pop("metadata_json", "{}"), {})
    return result


def _chunk_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = _loads(result.pop("metadata_json", "{}"), {})
    result["active"] = bool(result.get("active"))
    return result


def _space_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["require_approval"] = bool(result.get("require_approval"))
    return result


def _json_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for source, target, fallback in (
        ("metadata_json", "metadata", {}),
        ("evidence_event_ids_json", "evidence_event_ids", []),
        ("snapshot_json", "snapshot", {}),
    ):
        if source in result:
            result[target] = _loads(result.pop(source), fallback)
    return result


def _apply_version_context(item: dict[str, Any]) -> dict[str, Any]:
    """Restore metadata and validity owned by the chunk's document version."""
    version_metadata = _loads(item.pop("version_metadata_json", "{}"), {})
    document_fields = version_metadata.get("document_fields") if isinstance(version_metadata, dict) else None
    if isinstance(document_fields, dict):
        for key in (
            "title",
            "filename",
            "media_type",
            "source_type",
            "source_uri",
            "product",
            "dimension",
            "market_scope",
            "authority_tier",
            "published_at",
            "observed_at",
        ):
            if key in document_fields:
                item[key] = document_fields[key]
    item["version_metadata"] = version_metadata
    item["valid_from"] = item.pop("version_created_at", item.get("created_at"))
    item["valid_to"] = item.pop("version_superseded_at", None)
    item["temporal_status"] = "current" if item.get("active") else "historical"
    return item


class KnowledgeRepository:
    """Own knowledge-base SQL while keeping the existing database authoritative."""

    def __init__(
        self,
        conn: sqlite3.Connection | None = None,
        db_path: str | Path = DEFAULT_DB_PATH,
    ) -> None:
        self._owns_connection = conn is None
        self.conn = conn or init_db(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def __enter__(self) -> KnowledgeRepository:
        return self

    def __exit__(self, *_args: object) -> None:
        if self._owns_connection:
            self.conn.close()

    def ensure_personal_space(self, user_id: str) -> dict[str, Any]:
        space_id = personal_space_id(user_id)
        now = _now()
        self.conn.execute(
            """INSERT OR IGNORE INTO knowledge_spaces (
                   space_id, owner_id, name, description, visibility,
                   require_approval, retention_days, created_at, updated_at
               ) VALUES (?, ?, 'Personal knowledge', '', 'private', 0, 0, ?, ?)""",
            (space_id, user_id, now, now),
        )
        self.conn.execute(
            """INSERT OR IGNORE INTO knowledge_space_members (
                   space_id, user_id, role, created_at, updated_at
               ) VALUES (?, ?, 'owner', ?, ?)""",
            (space_id, user_id, now, now),
        )
        self.conn.execute(
            "UPDATE knowledge_documents SET space_id = ? WHERE user_id = ? AND space_id = ''",
            (space_id, user_id),
        )
        self.conn.commit()
        result = self.get_space(space_id, user_id)
        assert result is not None
        return result

    def create_space(
        self,
        *,
        owner_id: str,
        name: str,
        description: str = "",
        require_approval: bool = True,
        retention_days: int = 0,
    ) -> dict[str, Any]:
        space_id = f"kspace-{uuid.uuid4().hex}"
        now = _now()
        self.conn.execute(
            """INSERT INTO knowledge_spaces (
                   space_id, owner_id, name, description, visibility,
                   require_approval, retention_days, created_at, updated_at
               ) VALUES (?, ?, ?, ?, 'private', ?, ?, ?, ?)""",
            (space_id, owner_id, name, description, int(require_approval), max(0, retention_days), now, now),
        )
        self.conn.execute(
            """INSERT INTO knowledge_space_members (
                   space_id, user_id, role, created_at, updated_at
               ) VALUES (?, ?, 'owner', ?, ?)""",
            (space_id, owner_id, now, now),
        )
        self.conn.commit()
        result = self.get_space(space_id, owner_id)
        assert result is not None
        return result

    def get_space(self, space_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        sql = """SELECT s.*, m.role FROM knowledge_spaces s
                 LEFT JOIN knowledge_space_members m ON m.space_id = s.space_id AND m.user_id = ?
                 WHERE s.space_id = ?"""
        actor = user_id or ""
        row = self.conn.execute(sql, (actor, space_id)).fetchone()
        result = _space_row(row)
        if result is None:
            return None
        if user_id is not None and not result.get("role"):
            return None
        return result

    def list_spaces(self, user_id: str) -> list[dict[str, Any]]:
        self.ensure_personal_space(user_id)
        rows = self.conn.execute(
            """SELECT s.*, m.role,
                      (SELECT COUNT(*) FROM knowledge_space_members sm WHERE sm.space_id = s.space_id) AS member_count,
                      (SELECT COUNT(*) FROM knowledge_documents d WHERE d.space_id = s.space_id AND d.deleted_at IS NULL) AS document_count,
                      (SELECT COUNT(*) FROM knowledge_documents d WHERE d.space_id = s.space_id AND d.deleted_at IS NULL AND d.approval_status = 'pending') AS pending_count
                 FROM knowledge_spaces s
                 JOIN knowledge_space_members m ON m.space_id = s.space_id
                WHERE m.user_id = ? ORDER BY s.updated_at DESC""",
            (user_id,),
        ).fetchall()
        return [_space_row(row) for row in rows if row is not None]

    def update_space(self, space_id: str, **values: Any) -> None:
        allowed = {"name", "description", "require_approval", "retention_days"}
        filtered = {key: value for key, value in values.items() if key in allowed}
        if "require_approval" in filtered:
            filtered["require_approval"] = int(bool(filtered["require_approval"]))
        if "retention_days" in filtered:
            filtered["retention_days"] = max(0, int(filtered["retention_days"]))
        if not filtered:
            return
        filtered["updated_at"] = _now()
        assignments = ", ".join(f"{field} = ?" for field in filtered)
        self.conn.execute(f"UPDATE knowledge_spaces SET {assignments} WHERE space_id = ?", [*filtered.values(), space_id])
        self.conn.commit()

    def upsert_space_member(self, space_id: str, user_id: str, role: str) -> None:
        now = _now()
        self.conn.execute(
            """INSERT INTO knowledge_space_members (space_id, user_id, role, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(space_id, user_id) DO UPDATE SET role = excluded.role, updated_at = excluded.updated_at""",
            (space_id, user_id, role, now, now),
        )
        self.conn.commit()

    def remove_space_member(self, space_id: str, user_id: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM knowledge_space_members WHERE space_id = ? AND user_id = ? AND role <> 'owner'",
            (space_id, user_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def list_space_members(self, space_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            "SELECT user_id, role, created_at, updated_at FROM knowledge_space_members WHERE space_id = ? ORDER BY role, created_at",
            (space_id,),
        ).fetchall()]

    def accessible_space_ids(self, user_id: str, *, roles: set[str] | None = None) -> list[str]:
        self.ensure_personal_space(user_id)
        sql = "SELECT space_id FROM knowledge_space_members WHERE user_id = ?"
        params: list[Any] = [user_id]
        if roles:
            placeholders = ",".join("?" for _ in roles)
            sql += f" AND role IN ({placeholders})"
            params.extend(sorted(roles))
        return [str(row[0]) for row in self.conn.execute(sql, params).fetchall()]

    def find_document_by_source(
        self,
        user_id: str,
        source_key: str,
        space_id: str | None = None,
    ) -> dict[str, Any] | None:
        self.ensure_personal_space(user_id)
        scope = space_id or personal_space_id(user_id)
        row = self.conn.execute(
            "SELECT * FROM knowledge_documents WHERE space_id = ? AND source_key = ? AND deleted_at IS NULL",
            (scope, source_key),
        ).fetchone()
        return _document_row(row)

    def get_document(self, document_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT d.* FROM knowledge_documents d"
        params: list[Any] = [document_id]
        if user_id is not None:
            self.ensure_personal_space(user_id)
            sql = """SELECT d.*, m.role AS space_role FROM knowledge_documents d
                     JOIN knowledge_space_members m ON m.space_id = d.space_id AND m.user_id = ?
                    WHERE d.document_id = ? AND d.deleted_at IS NULL
                      AND (d.approval_status = 'approved' OR m.role IN ('owner', 'editor'))"""
            params = [user_id, document_id]
        else:
            sql += " WHERE d.document_id = ?"
        return _document_row(self.conn.execute(sql, params).fetchone())

    def create_document(self, values: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        self.conn.execute(
            """INSERT INTO knowledge_documents (
                   document_id, user_id, space_id, source_key, title, filename, media_type,
                   source_type, source_uri, product, dimension, market_scope,
                   authority_tier, status, current_version, content_hash, file_path,
                   normalized_path, size_bytes, published_at, observed_at, created_at,
                   updated_at, error, approval_status, approved_by, approved_at,
                   retention_until, metadata_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                values["document_id"],
                values.get("user_id", "default"),
                values.get("space_id", personal_space_id(values.get("user_id", "default"))),
                values["source_key"],
                values.get("title", "Untitled"),
                values.get("filename", ""),
                values.get("media_type", "application/octet-stream"),
                values.get("source_type", "upload"),
                values.get("source_uri", ""),
                values.get("product", ""),
                values.get("dimension", ""),
                values.get("market_scope", "Global / unspecified"),
                values.get("authority_tier", "third_party"),
                values.get("status", "queued"),
                int(values.get("current_version", 0)),
                values.get("content_hash", ""),
                values.get("file_path", ""),
                values.get("normalized_path", ""),
                int(values.get("size_bytes", 0)),
                values.get("published_at"),
                values.get("observed_at"),
                now,
                now,
                values.get("error"),
                values.get("approval_status", "approved"),
                values.get("approved_by"),
                values.get("approved_at"),
                values.get("retention_until"),
                json.dumps(values.get("metadata", {}), ensure_ascii=False),
            ),
        )
        self.conn.commit()
        result = self.get_document(values["document_id"])
        assert result is not None
        return result

    def update_document(self, document_id: str, **values: Any) -> None:
        filtered = {key: value for key, value in values.items() if key in _DOCUMENT_UPDATE_FIELDS}
        if "metadata" in values:
            filtered["metadata_json"] = json.dumps(values["metadata"], ensure_ascii=False)
        if not filtered:
            return
        filtered["updated_at"] = _now()
        assignments = ", ".join(f"{field} = ?" for field in filtered)
        self.conn.execute(
            f"UPDATE knowledge_documents SET {assignments} WHERE document_id = ?",
            [*filtered.values(), document_id],
        )
        self.conn.commit()

    def list_documents(
        self,
        user_id: str,
        *,
        status: str | None = None,
        product: str | None = None,
        source_type: str | None = None,
        space_id: str | None = None,
        approval_status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.ensure_personal_space(user_id)
        where = [
            "m.user_id = ?",
            "d.deleted_at IS NULL",
            "(d.approval_status = 'approved' OR m.role IN ('owner', 'editor'))",
        ]
        params: list[Any] = [user_id]
        for field, value in (
            ("status", status),
            ("product", product),
            ("source_type", source_type),
            ("space_id", space_id),
            ("approval_status", approval_status),
        ):
            if value:
                where.append(f"d.{field} = ?")
                params.append(value)
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        rows = self.conn.execute(
            f"""SELECT d.*, m.role AS space_role FROM knowledge_documents d
                  JOIN knowledge_space_members m ON m.space_id = d.space_id
                 WHERE {' AND '.join(where)} ORDER BY d.updated_at DESC LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
        return [_document_row(row) for row in rows if row is not None]

    def create_version(
        self,
        *,
        document_id: str,
        version_no: int,
        content_hash: str,
        file_path: str,
        metadata: dict[str, Any] | None = None,
        valid_from: str | None = None,
    ) -> None:
        now = valid_from or _now()
        self.conn.execute(
            """INSERT INTO knowledge_document_versions (
                   document_id, version_no, content_hash, file_path, normalized_path,
                   char_count, chunk_count, status, created_at, metadata_json
               ) VALUES (?, ?, ?, ?, '', 0, 0, 'queued', ?, ?)""",
            (
                document_id,
                version_no,
                content_hash,
                file_path,
                now,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def activate_version(
        self,
        document_id: str,
        version_no: int,
        *,
        superseded_at: str | None = None,
    ) -> None:
        """Mark older versions superseded only after the new index is usable."""
        now = superseded_at or _now()
        self.conn.execute(
            "UPDATE knowledge_document_versions SET superseded_at = ? WHERE document_id = ? AND version_no <> ? AND superseded_at IS NULL",
            (now, document_id, version_no),
        )
        self.conn.execute(
            "UPDATE knowledge_document_versions SET superseded_at = NULL WHERE document_id = ? AND version_no = ?",
            (document_id, version_no),
        )
        self.conn.commit()

    def update_version(self, document_id: str, version_no: int, **values: Any) -> None:
        allowed = {"normalized_path", "char_count", "chunk_count", "status", "error", "metadata_json"}
        filtered = {key: value for key, value in values.items() if key in allowed}
        if "metadata" in values:
            filtered["metadata_json"] = json.dumps(values["metadata"], ensure_ascii=False)
        if not filtered:
            return
        assignments = ", ".join(f"{field} = ?" for field in filtered)
        self.conn.execute(
            f"UPDATE knowledge_document_versions SET {assignments} WHERE document_id = ? AND version_no = ?",
            [*filtered.values(), document_id, version_no],
        )
        self.conn.commit()

    def list_versions(self, document_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM knowledge_document_versions WHERE document_id = ? ORDER BY version_no DESC",
            (document_id,),
        ).fetchall()
        return [_version_row(row) for row in rows]

    def replace_chunks(
        self,
        document_id: str,
        version_no: int,
        chunks: Iterable[KnowledgeChunk],
    ) -> None:
        chunk_list = list(chunks)
        self.conn.execute("UPDATE knowledge_chunks SET active = 0 WHERE document_id = ?", (document_id,))
        self.conn.execute(
            "DELETE FROM knowledge_chunks WHERE document_id = ? AND version_no = ?",
            (document_id, version_no),
        )
        self.conn.executemany(
            """INSERT INTO knowledge_chunks (
                   chunk_id, document_id, version_no, user_id, ordinal, text,
                   contextual_text, section_path, page_no, token_count,
                   qdrant_point_id, active, created_at, metadata_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            [
                (
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.version_no,
                    chunk.user_id,
                    chunk.ordinal,
                    chunk.text,
                    chunk.contextual_text,
                    chunk.section_path,
                    chunk.page_no,
                    chunk.token_count,
                    chunk.qdrant_point_id,
                    _now(),
                    json.dumps(chunk.metadata, ensure_ascii=False),
                )
                for chunk in chunk_list
            ],
        )
        self.conn.commit()

    def list_chunks(
        self,
        *,
        document_id: str | None = None,
        user_id: str | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if document_id:
            where.append("document_id = ?")
            params.append(document_id)
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        if active_only:
            where.append("active = 1")
        sql = "SELECT * FROM knowledge_chunks"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY document_id, version_no, ordinal"
        return [_chunk_row(row) for row in self.conn.execute(sql, params).fetchall()]

    def get_chunks_by_ids(
        self,
        chunk_ids: list[str],
        user_id: str,
        *,
        include_historical: bool = False,
        space_ids: tuple[str, ...] = (),
    ) -> dict[str, dict[str, Any]]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        active_clause = "" if include_historical else " AND c.active = 1"
        allowed_spaces = list(space_ids or self.accessible_space_ids(user_id))
        if not allowed_spaces:
            return {}
        space_placeholders = ",".join("?" for _ in allowed_spaces)
        rows = self.conn.execute(
            f"""SELECT c.*, d.title, d.source_uri, d.source_type, d.authority_tier,
                       d.product, d.dimension, d.market_scope, d.published_at,
                       d.observed_at, d.filename, d.media_type, d.space_id,
                       d.approval_status,
                       v.created_at AS version_created_at,
                       v.superseded_at AS version_superseded_at,
                       v.metadata_json AS version_metadata_json
                  FROM knowledge_chunks c
                  JOIN knowledge_documents d ON d.document_id = c.document_id
                  JOIN knowledge_document_versions v
                    ON v.document_id = c.document_id AND v.version_no = c.version_no
                 WHERE c.chunk_id IN ({placeholders})
                   AND d.space_id IN ({space_placeholders})
                   AND d.approval_status = 'approved'
                   AND d.deleted_at IS NULL{active_clause}""",
            [*chunk_ids, *allowed_spaces],
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = _apply_version_context(_chunk_row(row))
            result[item["chunk_id"]] = item
        return result

    def list_timeline(
        self,
        user_id: str,
        *,
        product: str | None = None,
        dimension: str | None = None,
        space_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return version events with one representative excerpt per version."""
        spaces = [space_id] if space_id else self.accessible_space_ids(user_id)
        if not spaces:
            return []
        placeholders = ",".join("?" for _ in spaces)
        where = [f"d.space_id IN ({placeholders})", "d.approval_status = 'approved'", "d.deleted_at IS NULL", "v.status IN ('indexed', 'partial')"]
        params: list[Any] = [*spaces]
        if product:
            where.append("LOWER(d.product) = LOWER(?)")
            params.append(product)
        if dimension:
            where.append("d.dimension = ?")
            params.append(dimension)
        params.append(max(1, min(limit, 1000)))
        rows = self.conn.execute(
            f"""SELECT d.document_id, d.space_id, d.title, d.filename, d.source_uri, d.source_type,
                       d.authority_tier, d.product, d.dimension, d.market_scope,
                       d.published_at, d.observed_at, d.current_version,
                       v.version_no, v.content_hash, v.created_at AS valid_from,
                       v.superseded_at AS valid_to, v.metadata_json AS version_metadata_json,
                       c.chunk_id, c.text AS excerpt
                  FROM knowledge_document_versions v
                  JOIN knowledge_documents d ON d.document_id = v.document_id
             LEFT JOIN knowledge_chunks c
                    ON c.document_id = v.document_id AND c.version_no = v.version_no
                   AND c.ordinal = 0
                 WHERE {' AND '.join(where)}
              ORDER BY v.created_at DESC, d.document_id, v.version_no DESC
                 LIMIT ?""",
            params,
        ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            version_metadata = _loads(item.pop("version_metadata_json", "{}"), {})
            fields = version_metadata.get("document_fields") if isinstance(version_metadata, dict) else None
            if isinstance(fields, dict):
                for key in (
                    "title",
                    "filename",
                    "source_uri",
                    "source_type",
                    "authority_tier",
                    "product",
                    "dimension",
                    "market_scope",
                    "published_at",
                    "observed_at",
                ):
                    if key in fields:
                        item[key] = fields[key]
            item["is_current"] = int(item["version_no"]) == int(item["current_version"])
            item["temporal_status"] = "current" if item["is_current"] else "historical"
            item["excerpt"] = str(item.get("excerpt") or "")[:1200]
            item["metadata"] = version_metadata
            events.append(item)
        return events

    def create_job(
        self,
        *,
        job_id: str,
        user_id: str,
        operation: str,
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.conn.execute(
            """INSERT INTO knowledge_ingestion_jobs (
                   job_id, user_id, document_id, operation, status, progress,
                   created_at, metadata_json
               ) VALUES (?, ?, ?, ?, 'queued', 0, ?, ?)""",
            (job_id, user_id, document_id, operation, _now(), json.dumps(metadata or {}, ensure_ascii=False)),
        )
        self.conn.commit()
        result = self.get_job(job_id, user_id)
        assert result is not None
        return result

    def update_job(self, job_id: str, **values: Any) -> None:
        allowed = {"status", "progress", "error", "started_at", "finished_at", "document_id", "metadata_json"}
        filtered = {key: value for key, value in values.items() if key in allowed}
        if "metadata" in values:
            filtered["metadata_json"] = json.dumps(values["metadata"], ensure_ascii=False)
        if not filtered:
            return
        assignments = ", ".join(f"{field} = ?" for field in filtered)
        self.conn.execute(
            f"UPDATE knowledge_ingestion_jobs SET {assignments} WHERE job_id = ?",
            [*filtered.values(), job_id],
        )
        self.conn.commit()

    def get_job(self, job_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT * FROM knowledge_ingestion_jobs WHERE job_id = ?"
        params: list[Any] = [job_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        row = self.conn.execute(sql, params).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = _loads(result.pop("metadata_json", "{}"), {})
        return result

    def list_jobs(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM knowledge_ingestion_jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, max(1, min(limit, 200))),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = _loads(item.pop("metadata_json", "{}"), {})
            result.append(item)
        return result

    def log_retrieval(
        self,
        *,
        retrieval_id: str,
        user_id: str,
        query: str,
        filters: dict[str, Any],
        chunk_ids: list[str],
        duration_ms: int,
        status: str = "completed",
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO knowledge_retrieval_logs (
                   retrieval_id, user_id, query, filters_json, result_count,
                   selected_chunk_ids_json, duration_ms, status, error, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                retrieval_id,
                user_id,
                query,
                json.dumps(filters, ensure_ascii=False),
                len(chunk_ids),
                json.dumps(chunk_ids, ensure_ascii=False),
                duration_ms,
                status,
                error,
                _now(),
            ),
        )
        self.conn.commit()

    def soft_delete_document(
        self,
        document_id: str,
        user_id: str,
        *,
        reason: str = "manual",
        internal: bool = False,
    ) -> dict[str, Any] | None:
        document = self.get_document(document_id) if internal else self.get_document(document_id, user_id)
        if document is None:
            return None
        document["versions"] = self.list_versions(document_id)
        document["chunks"] = self.list_chunks(document_id=document_id, active_only=False)
        now = _now()
        self.conn.execute(
            """INSERT INTO knowledge_deletion_audit (
                   audit_id, space_id, document_id, user_id, title, reason,
                   deleted_at, snapshot_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"kdel-{uuid.uuid4().hex}",
                document.get("space_id") or "",
                document_id,
                user_id,
                document.get("title") or "",
                reason,
                now,
                json.dumps(
                    {
                        "source_uri": document.get("source_uri"),
                        "content_hash": document.get("content_hash"),
                        "current_version": document.get("current_version"),
                        "version_count": len(document["versions"]),
                        "chunk_count": len(document["chunks"]),
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        self.conn.execute(
            "UPDATE knowledge_documents SET status = 'deleted', deleted_at = ?, deleted_by = ?, updated_at = ? WHERE document_id = ?",
            (now, user_id, now, document_id),
        )
        self.conn.commit()
        return document

    def list_deletion_audit(self, user_id: str, *, space_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        spaces = [space_id] if space_id else self.accessible_space_ids(user_id)
        if not spaces:
            return []
        placeholders = ",".join("?" for _ in spaces)
        rows = self.conn.execute(
            f"SELECT * FROM knowledge_deletion_audit WHERE space_id IN ({placeholders}) ORDER BY deleted_at DESC LIMIT ?",
            [*spaces, max(1, min(limit, 500))],
        ).fetchall()
        return [_json_row(row) for row in rows]

    def set_document_approval(self, document_id: str, *, status: str, reviewer_id: str) -> dict[str, Any] | None:
        now = _now()
        self.conn.execute(
            """UPDATE knowledge_documents
                  SET approval_status = ?, approved_by = ?, approved_at = ?, updated_at = ?
                WHERE document_id = ? AND deleted_at IS NULL""",
            (status, reviewer_id, now if status == "approved" else None, now, document_id),
        )
        self.conn.commit()
        return self.get_document(document_id)

    def list_expired_documents(self, *, now: str | None = None) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT * FROM knowledge_documents
                WHERE deleted_at IS NULL AND retention_until IS NOT NULL AND retention_until <= ?""",
            (now or _now(),),
        ).fetchall()
        return [_document_row(row) for row in rows if row is not None]

    def upsert_entity(
        self,
        *,
        entity_id: str,
        space_id: str,
        canonical_name: str,
        normalized_key: str,
        alias: str,
    ) -> dict[str, Any]:
        now = _now()
        self.conn.execute(
            """INSERT INTO knowledge_entities (
                   entity_id, space_id, canonical_name, entity_type, normalized_key,
                   metadata_json, created_at, updated_at
               ) VALUES (?, ?, ?, 'product', ?, '{}', ?, ?)
               ON CONFLICT(space_id, normalized_key) DO UPDATE SET
                   canonical_name = excluded.canonical_name, updated_at = excluded.updated_at""",
            (entity_id, space_id, canonical_name, normalized_key, now, now),
        )
        row = self.conn.execute(
            "SELECT * FROM knowledge_entities WHERE space_id = ? AND normalized_key = ?",
            (space_id, normalized_key),
        ).fetchone()
        assert row is not None
        resolved_id = str(row["entity_id"])
        alias_key = alias.strip().casefold()
        if alias_key:
            self.conn.execute(
                """INSERT INTO knowledge_entity_aliases (space_id, alias_key, entity_id, alias, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(space_id, alias_key) DO UPDATE SET entity_id = excluded.entity_id, alias = excluded.alias""",
                (space_id, alias_key, resolved_id, alias.strip(), now),
            )
        self.conn.commit()
        return _json_row(row)

    def find_event_candidates(self, *, space_id: str, entity_id: str, dimension: str, limit: int = 40) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT * FROM knowledge_events
                WHERE space_id = ? AND entity_id = ? AND dimension = ?
                ORDER BY last_seen_at DESC LIMIT ?""",
            (space_id, entity_id, dimension, max(1, min(limit, 200))),
        ).fetchall()
        return [_json_row(row) for row in rows]

    def upsert_event(self, values: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        event_id = str(values.get("event_id") or f"kevt-{uuid.uuid4().hex}")
        self.conn.execute(
            """INSERT INTO knowledge_events (
                   event_id, space_id, entity_id, event_type, dimension, title,
                   statement, occurred_at, first_seen_at, last_seen_at, status,
                   confidence, evidence_count, cluster_key, metadata_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
               ON CONFLICT(space_id, cluster_key) DO UPDATE SET
                   last_seen_at = excluded.last_seen_at,
                   title = excluded.title,
                   statement = excluded.statement,
                   confidence = MAX(knowledge_events.confidence, excluded.confidence)""",
            (
                event_id,
                values["space_id"],
                values["entity_id"],
                values["event_type"],
                values.get("dimension", "general"),
                values.get("title", "Knowledge event"),
                values.get("statement", ""),
                values.get("occurred_at"),
                now,
                now,
                values.get("status", "observed"),
                float(values.get("confidence", 0.5)),
                values["cluster_key"],
                json.dumps(values.get("metadata", {}), ensure_ascii=False),
            ),
        )
        row = self.conn.execute(
            "SELECT * FROM knowledge_events WHERE space_id = ? AND cluster_key = ?",
            (values["space_id"], values["cluster_key"]),
        ).fetchone()
        assert row is not None
        self.conn.commit()
        return _json_row(row)

    def add_event_evidence(self, event_id: str, values: dict[str, Any]) -> dict[str, Any]:
        self.conn.execute(
            """INSERT OR IGNORE INTO knowledge_event_evidence (
                   event_id, document_id, version_no, chunk_id, source_uri,
                   authority_tier, observed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                values["document_id"],
                int(values["version_no"]),
                values.get("chunk_id"),
                values.get("source_uri", ""),
                values.get("authority_tier", "third_party"),
                values.get("observed_at") or _now(),
            ),
        )
        evidence = self.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT source_uri) FROM knowledge_event_evidence WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        count = int(evidence[0] or 0)
        source_count = int(evidence[1] or 0)
        status = "corroborated" if source_count >= 2 else "observed"
        self.conn.execute(
            "UPDATE knowledge_events SET evidence_count = ?, status = ?, last_seen_at = ? WHERE event_id = ?",
            (count, status, _now(), event_id),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM knowledge_events WHERE event_id = ?", (event_id,)).fetchone()
        assert row is not None
        return _json_row(row)

    def list_events(
        self,
        user_id: str,
        *,
        space_id: str | None = None,
        entity_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        spaces = [space_id] if space_id else self.accessible_space_ids(user_id)
        if not spaces:
            return []
        placeholders = ",".join("?" for _ in spaces)
        where = [f"e.space_id IN ({placeholders})"]
        params: list[Any] = [*spaces]
        if entity_id:
            where.append("e.entity_id = ?")
            params.append(entity_id)
        params.append(max(1, min(limit, 1000)))
        rows = self.conn.execute(
            f"""SELECT e.*, n.canonical_name AS entity_name
                  FROM knowledge_events e
                  JOIN knowledge_entities n ON n.entity_id = e.entity_id
                 WHERE {' AND '.join(where)}
                 ORDER BY COALESCE(e.occurred_at, e.last_seen_at) DESC LIMIT ?""",
            params,
        ).fetchall()
        events = [_json_row(row) for row in rows]
        for event in events:
            evidence_rows = self.conn.execute(
                "SELECT * FROM knowledge_event_evidence WHERE event_id = ? ORDER BY observed_at DESC",
                (event["event_id"],),
            ).fetchall()
            event["evidence"] = [dict(row) for row in evidence_rows]
        return events

    def replace_insights(self, space_id: str, insights: list[dict[str, Any]]) -> None:
        now = _now()
        self.conn.execute("UPDATE knowledge_insights SET status = 'superseded' WHERE space_id = ? AND status = 'active'", (space_id,))
        self.conn.executemany(
            """INSERT INTO knowledge_insights (
                   insight_id, space_id, entity_id, insight_type, title, summary,
                   confidence, status, period_start, period_end,
                   evidence_event_ids_json, generated_at, metadata_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
               ON CONFLICT(insight_id) DO UPDATE SET
                   summary = excluded.summary, confidence = excluded.confidence,
                   status = 'active', generated_at = excluded.generated_at,
                   metadata_json = excluded.metadata_json""",
            [
                (
                    item["insight_id"],
                    space_id,
                    item["entity_id"],
                    item["insight_type"],
                    item["title"],
                    item["summary"],
                    float(item.get("confidence", 0.5)),
                    item.get("period_start"),
                    item.get("period_end"),
                    json.dumps(item.get("evidence_event_ids", []), ensure_ascii=False),
                    now,
                    json.dumps(item.get("metadata", {}), ensure_ascii=False),
                )
                for item in insights
            ],
        )
        self.conn.commit()

    def list_insights(self, user_id: str, *, space_id: str | None = None, include_superseded: bool = False) -> list[dict[str, Any]]:
        spaces = [space_id] if space_id else self.accessible_space_ids(user_id)
        if not spaces:
            return []
        placeholders = ",".join("?" for _ in spaces)
        status = "" if include_superseded else " AND i.status = 'active'"
        rows = self.conn.execute(
            f"""SELECT i.*, e.canonical_name AS entity_name
                  FROM knowledge_insights i
                  JOIN knowledge_entities e ON e.entity_id = i.entity_id
                 WHERE i.space_id IN ({placeholders}){status}
                 ORDER BY CASE i.insight_type WHEN 'fact' THEN 1 WHEN 'inference' THEN 2 ELSE 3 END, i.generated_at DESC""",
            spaces,
        ).fetchall()
        return [_json_row(row) for row in rows]

    def stats(self, user_id: str) -> dict[str, Any]:
        spaces = self.accessible_space_ids(user_id)
        if not spaces:
            return {"documents": 0, "indexed": 0, "degraded": 0, "size_bytes": 0, "chunks": 0, "active_jobs": 0, "pending_approval": 0}
        placeholders = ",".join("?" for _ in spaces)
        row = self.conn.execute(
            f"""SELECT COUNT(*) AS documents,
                      SUM(CASE WHEN status = 'indexed' THEN 1 ELSE 0 END) AS indexed,
                      SUM(CASE WHEN status IN ('failed', 'partial') THEN 1 ELSE 0 END) AS degraded,
                      SUM(CASE WHEN approval_status = 'pending' THEN 1 ELSE 0 END) AS pending_approval,
                      COALESCE(SUM(size_bytes), 0) AS size_bytes
                 FROM knowledge_documents WHERE space_id IN ({placeholders}) AND deleted_at IS NULL""",
            spaces,
        ).fetchone()
        chunks = self.conn.execute(
            f"""SELECT COUNT(*) FROM knowledge_chunks c
                  JOIN knowledge_documents d ON d.document_id = c.document_id
                 WHERE d.space_id IN ({placeholders}) AND d.deleted_at IS NULL
                   AND d.approval_status = 'approved' AND c.active = 1""",
            spaces,
        ).fetchone()[0]
        jobs = self.conn.execute(
            "SELECT COUNT(*) FROM knowledge_ingestion_jobs WHERE user_id = ? AND status IN ('queued', 'running')",
            (user_id,),
        ).fetchone()[0]
        return {
            "documents": int(row["documents"] or 0),
            "indexed": int(row["indexed"] or 0),
            "degraded": int(row["degraded"] or 0),
            "size_bytes": int(row["size_bytes"] or 0),
            "chunks": int(chunks or 0),
            "active_jobs": int(jobs or 0),
            "pending_approval": int(row["pending_approval"] or 0),
        }
