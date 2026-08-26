"""SQLite persistence for knowledge documents, versions, chunks, and jobs."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from competition.db import DEFAULT_DB_PATH, init_db
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

    def find_document_by_source(self, user_id: str, source_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM knowledge_documents WHERE user_id = ? AND source_key = ?",
            (user_id, source_key),
        ).fetchone()
        return _document_row(row)

    def get_document(self, document_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT * FROM knowledge_documents WHERE document_id = ?"
        params: list[Any] = [document_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        return _document_row(self.conn.execute(sql, params).fetchone())

    def create_document(self, values: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        self.conn.execute(
            """INSERT INTO knowledge_documents (
                   document_id, user_id, source_key, title, filename, media_type,
                   source_type, source_uri, product, dimension, market_scope,
                   authority_tier, status, current_version, content_hash, file_path,
                   normalized_path, size_bytes, published_at, observed_at, created_at,
                   updated_at, error, metadata_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                values["document_id"],
                values.get("user_id", "default"),
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
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = ["user_id = ?"]
        params: list[Any] = [user_id]
        for field, value in (("status", status), ("product", product), ("source_type", source_type)):
            if value:
                where.append(f"{field} = ?")
                params.append(value)
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        rows = self.conn.execute(
            f"SELECT * FROM knowledge_documents WHERE {' AND '.join(where)} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
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
    ) -> None:
        now = _now()
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

    def activate_version(self, document_id: str, version_no: int) -> None:
        """Mark older versions superseded only after the new index is usable."""
        now = _now()
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

    def get_chunks_by_ids(self, chunk_ids: list[str], user_id: str) -> dict[str, dict[str, Any]]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = self.conn.execute(
            f"""SELECT c.*, d.title, d.source_uri, d.source_type, d.authority_tier,
                       d.product, d.dimension, d.market_scope, d.published_at,
                       d.observed_at, d.filename, d.media_type
                  FROM knowledge_chunks c
                  JOIN knowledge_documents d ON d.document_id = c.document_id
                 WHERE c.chunk_id IN ({placeholders}) AND c.user_id = ? AND c.active = 1""",
            [*chunk_ids, user_id],
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = _chunk_row(row)
            result[item["chunk_id"]] = item
        return result

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

    def delete_document(self, document_id: str, user_id: str) -> dict[str, Any] | None:
        document = self.get_document(document_id, user_id)
        if document is None:
            return None
        document["versions"] = self.list_versions(document_id)
        document["chunks"] = self.list_chunks(document_id=document_id, active_only=False)
        self.conn.execute(
            "DELETE FROM knowledge_documents WHERE document_id = ? AND user_id = ?",
            (document_id, user_id),
        )
        self.conn.commit()
        return document

    def stats(self, user_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """SELECT COUNT(*) AS documents,
                      SUM(CASE WHEN status = 'indexed' THEN 1 ELSE 0 END) AS indexed,
                      SUM(CASE WHEN status IN ('failed', 'partial') THEN 1 ELSE 0 END) AS degraded,
                      COALESCE(SUM(size_bytes), 0) AS size_bytes
                 FROM knowledge_documents WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        chunks = self.conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE user_id = ? AND active = 1",
            (user_id,),
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
        }
