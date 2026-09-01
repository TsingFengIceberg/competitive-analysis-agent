"""Application service for ingestion, indexing, retrieval, and evidence export."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from competition.db import DEFAULT_DB_PATH
from competition.knowledge_chunking import build_chunks
from competition.knowledge_governance import (
    REVIEW_ROLES,
    SPACE_ROLES,
    WRITE_ROLES,
    assess_intelligence_item,
    assess_report,
    retention_deadline,
)
from competition.knowledge_graph import build_relation_candidates, graph_tokens, plan_graph_retrieval
from competition.knowledge_index import KnowledgeIndex
from competition.knowledge_intelligence import (
    build_event_candidate,
    build_long_term_insights,
    entity_key,
    event_similarity,
)
from competition.knowledge_parser import SUPPORTED_SUFFIXES, DocumentParser
from competition.knowledge_query import (
    RetrievalPlan,
    build_analysis_queries,
    build_bridge_query,
    canonical_product,
    expand_query_variants,
    normalize_query_text,
    plan_retrieval_query,
    rewrite_query_with_aliases,
)
from competition.knowledge_repo import KnowledgeRepository
from competition.knowledge_retrieval import RetrievalStrategy, adaptive_strategy, explain_retrieval, feedback_adjustment
from competition.knowledge_types import AUTHORITY_PRIORS, KnowledgeChunk, KnowledgeHit, RetrievalFilters

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_KNOWLEDGE_ROOT = Path(os.getenv("CI_AGENT_KNOWLEDGE_ROOT", str(_PROJECT_ROOT / ".ci-agent/knowledge")))
MAX_UPLOAD_BYTES = int(os.getenv("CI_AGENT_RAG_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
MIN_RETRIEVAL_SCORE = float(os.getenv("CI_AGENT_RAG_MIN_SCORE", "0.08"))
RESULT_CACHE_TTL_SECONDS = max(0, int(os.getenv("CI_AGENT_RAG_RESULT_CACHE_TTL_SECONDS", "300")))
RESULT_CACHE_SIZE = max(0, int(os.getenv("CI_AGENT_RAG_RESULT_CACHE_SIZE", "256")))
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._\-\u3400-\u9fff]+")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_filename(value: str) -> str:
    name = Path(value or "document").name.strip().replace("\x00", "")
    safe = _SAFE_FILENAME.sub("_", name).strip("._")
    return safe[:180] or "document.txt"


def _user_segment(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


def _source_key(
    *,
    source_uri: str,
    filename: str,
    product: str,
    dimension: str,
    namespace: str = "",
) -> str:
    identity = source_uri.strip() or filename.casefold()
    return hashlib.sha256(f"{namespace}|{identity}|{product.casefold()}|{dimension}".encode()).hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class KnowledgeService:
    def __init__(
        self,
        *,
        db_path: str | Path = DEFAULT_DB_PATH,
        root: str | Path = DEFAULT_KNOWLEDGE_ROOT,
        parser: DocumentParser | None = None,
        index: KnowledgeIndex | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.inbox = self.root / "inbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.parser = parser or DocumentParser()
        self.index = index or KnowledgeIndex(path=self.root / "indexes" / "qdrant")
        self._registration_lock = threading.RLock()
        self._ingestion_slot = threading.BoundedSemaphore(1)
        self._cache_lock = threading.RLock()
        self._result_cache: OrderedDict[tuple[Any, ...], tuple[float, tuple[KnowledgeHit, ...]]] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_invalidations = 0
        self._warmup_status: dict[str, Any] = {"status": "not_started"}

    def _repo(self) -> KnowledgeRepository:
        return KnowledgeRepository(db_path=self.db_path)

    def _resolve_space(self, user_id: str, space_id: str | None, *, roles: frozenset[str] = frozenset(SPACE_ROLES)) -> dict[str, Any]:
        with self._repo() as repository:
            personal = repository.ensure_personal_space(user_id)
            space = repository.get_space(space_id or personal["space_id"], user_id)
        if space is None or space.get("role") not in roles:
            raise PermissionError("Knowledge space not found or permission denied")
        return space

    def register_bytes(
        self,
        *,
        user_id: str,
        filename: str,
        data: bytes,
        title: str = "",
        media_type: str = "application/octet-stream",
        source_type: str = "upload",
        source_uri: str = "",
        product: str = "",
        dimension: str = "",
        market_scope: str = "Global / unspecified",
        authority_tier: str = "third_party",
        published_at: str | None = None,
        observed_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        space_id: str | None = None,
        approval_status: str | None = None,
    ) -> dict[str, Any]:
        if not data:
            raise ValueError("Document is empty")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(f"Document exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
        safe_name = _safe_filename(filename)
        suffix = Path(safe_name).suffix.casefold()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported document type: {suffix or 'no extension'}")
        if authority_tier not in {"primary", "structured_fact", "change_event", "third_party", "report"}:
            raise ValueError(f"Unsupported authority tier: {authority_tier}")
        if approval_status not in {None, "approved", "pending"}:
            raise ValueError("Approval status must be approved or pending")
        digest = hashlib.sha256(data).hexdigest()
        space = self._resolve_space(user_id, space_id, roles=WRITE_ROLES)
        source_identity = _source_key(
            source_uri=source_uri,
            filename=safe_name,
            product=product,
            dimension=dimension,
            namespace=space["space_id"],
        )
        with self._registration_lock, self._repo() as repository:
            existing = repository.find_document_by_source(user_id, source_identity, space["space_id"])
            if existing and existing.get("content_hash") == digest and existing.get("status") in {"indexed", "partial"}:
                job_id = f"kjob-{uuid.uuid4().hex}"
                repository.create_job(
                    job_id=job_id,
                    user_id=user_id,
                    document_id=existing["document_id"],
                    operation="ingest",
                    metadata={"unchanged": True, "content_hash": digest},
                )
                repository.update_job(job_id, status="completed", progress=100, started_at=_now(), finished_at=_now())
                return {"document": existing, "job": repository.get_job(job_id, user_id), "unchanged": True}

            document_id = existing["document_id"] if existing else f"kdoc-{uuid.uuid4().hex}"
            version_numbers = [int(version.get("version_no") or 0) for version in repository.list_versions(document_id)] if existing else []
            version_no = max([int(existing.get("current_version", 0) if existing else 0), *version_numbers]) + 1
            original_path = self.root / "originals" / _user_segment(user_id) / document_id / f"v{version_no}-{safe_name}"
            _write_atomic(original_path, data)
            candidate_fields = {
                "title": title.strip() or Path(safe_name).stem,
                "filename": safe_name,
                "media_type": media_type,
                "source_type": source_type,
                "source_uri": source_uri,
                "product": product.strip(),
                "dimension": dimension.strip(),
                "market_scope": market_scope.strip() or "Global / unspecified",
                "authority_tier": authority_tier,
                "size_bytes": len(data),
                "published_at": published_at,
                "observed_at": observed_at or _now(),
                "metadata": metadata or {},
                "space_id": space["space_id"],
                "approval_status": "pending" if space.get("require_approval") else (approval_status or "approved"),
                "retention_until": retention_deadline(int(space.get("retention_days") or 0)),
            }
            values = {
                "document_id": document_id,
                "user_id": user_id,
                "source_key": source_identity,
                "space_id": space["space_id"],
                **candidate_fields,
                "status": "queued",
                "current_version": 0,
                "content_hash": "",
                "file_path": str(original_path),
                "approval_status": candidate_fields["approval_status"],
                "approved_by": None if candidate_fields["approval_status"] == "pending" else user_id,
                "approved_at": None if candidate_fields["approval_status"] == "pending" else _now(),
                "retention_until": candidate_fields["retention_until"],
            }
            if existing:
                repository.update_document(
                    document_id,
                    status="queued",
                    error=None,
                    approval_status=candidate_fields["approval_status"],
                    approved_by=None,
                    approved_at=None,
                    retention_until=candidate_fields["retention_until"],
                )
            else:
                repository.create_document(values)
            repository.create_version(
                document_id=document_id,
                version_no=version_no,
                content_hash=digest,
                file_path=str(original_path),
                metadata={"media_type": media_type, "document_fields": candidate_fields},
                valid_from=observed_at,
            )
            job_id = f"kjob-{uuid.uuid4().hex}"
            repository.create_job(
                job_id=job_id,
                user_id=user_id,
                document_id=document_id,
                operation="ingest",
                metadata={
                    "version_no": version_no,
                    "file_path": str(original_path),
                    "content_hash": digest,
                    "document_fields": candidate_fields,
                },
            )
            document = repository.get_document(document_id, user_id)
            return {"document": document, "job": repository.get_job(job_id, user_id), "unchanged": False}

    def register_inbox_path(self, *, user_id: str, relative_path: str, **metadata: Any) -> dict[str, Any]:
        candidate = (self.inbox / relative_path).resolve()
        if not _within(candidate, self.inbox) or not candidate.is_file():
            raise ValueError("Path must identify a file inside the knowledge inbox")
        return self.register_bytes(
            user_id=user_id,
            filename=candidate.name,
            data=candidate.read_bytes(),
            source_uri=f"local:{candidate.relative_to(self.inbox).as_posix()}",
            source_type="local",
            **metadata,
        )

    def process_job(self, job_id: str) -> dict[str, Any]:
        with self._ingestion_slot, self._repo() as repository:
            job = repository.get_job(job_id)
            if job is None:
                raise KeyError(f"Knowledge job not found: {job_id}")
            if job["status"] == "completed":
                return job
            document = repository.get_document(job.get("document_id"))
            if document is None:
                repository.update_job(job_id, status="failed", progress=100, error="Document no longer exists", finished_at=_now())
                result = repository.get_job(job_id)
                assert result is not None
                return result

            job_metadata = job.get("metadata", {})
            version_no = int(job_metadata.get("version_no") or document.get("current_version") or 0)
            file_path = Path(job_metadata.get("file_path") or document.get("file_path") or "")
            candidate_fields = job_metadata.get("document_fields")
            if not isinstance(candidate_fields, dict):
                candidate_fields = {}
            document_for_chunks = {**document, **candidate_fields}
            repository.update_job(job_id, status="running", progress=10, started_at=_now(), error=None)
            repository.update_document(document["document_id"], status="processing", error=None)

        try:
            parsed = self.parser.parse(file_path, document_for_chunks.get("media_type"))
            normalized_path = self.root / "normalized" / _user_segment(document["user_id"]) / document["document_id"] / f"v{version_no}.md"
            _write_atomic(normalized_path, parsed.markdown.encode("utf-8"))
            with self._repo() as repository:
                repository.update_job(job_id, progress=40)
                repository.update_version(
                    document["document_id"],
                    version_no,
                    normalized_path=str(normalized_path),
                    char_count=len(parsed.markdown),
                    status="processing",
                    metadata={
                        "warnings": parsed.warnings,
                        "media_type": parsed.media_type,
                        "document_fields": candidate_fields,
                    },
                )
            document_for_chunks["title"] = document_for_chunks.get("title") or parsed.title
            chunks = build_chunks(parsed, document=document_for_chunks, version_no=version_no)
            if not chunks:
                raise ValueError("Document parser produced no indexable content")
            with self._repo() as repository:
                stale_chunks = repository.list_chunks(document_id=document["document_id"], active_only=True)
                version_record = next(
                    (item for item in repository.list_versions(document["document_id"]) if int(item["version_no"]) == version_no),
                    {},
                )
                repository.update_job(job_id, progress=55)
            self.index.replace_document(
                document_for_chunks,
                chunks,
                valid_from=version_record.get("created_at"),
            )
            with self._repo() as repository:
                repository.update_job(job_id, progress=90)
                repository.replace_chunks(document["document_id"], version_no, chunks)
                status = "indexed" if not parsed.warnings else "partial"
                repository.update_version(
                    document["document_id"],
                    version_no,
                    normalized_path=str(normalized_path),
                    char_count=len(parsed.markdown),
                    chunk_count=len(chunks),
                    status=status,
                    error=None,
                    metadata={
                        "warnings": parsed.warnings,
                        "media_type": parsed.media_type,
                        "document_fields": candidate_fields,
                    },
                )
                repository.activate_version(
                    document["document_id"],
                    version_no,
                    superseded_at=version_record.get("created_at"),
                )
                repository.update_document(
                    document["document_id"],
                    title=document_for_chunks["title"],
                    filename=document_for_chunks.get("filename", ""),
                    media_type=document_for_chunks.get("media_type", parsed.media_type),
                    source_type=document_for_chunks.get("source_type", "upload"),
                    source_uri=document_for_chunks.get("source_uri", ""),
                    product=document_for_chunks.get("product", ""),
                    dimension=document_for_chunks.get("dimension", ""),
                    market_scope=document_for_chunks.get("market_scope", "Global / unspecified"),
                    authority_tier=document_for_chunks.get("authority_tier", "third_party"),
                    status=status,
                    current_version=version_no,
                    content_hash=job_metadata.get("content_hash", ""),
                    file_path=str(file_path),
                    normalized_path=str(normalized_path),
                    size_bytes=int(document_for_chunks.get("size_bytes") or 0),
                    published_at=document_for_chunks.get("published_at"),
                    observed_at=document_for_chunks.get("observed_at"),
                    error=None,
                    metadata=document_for_chunks.get("metadata") or {},
                )
                repository.update_job(
                    job_id,
                    status="completed",
                    progress=100,
                    finished_at=_now(),
                    metadata={**job_metadata, "chunk_count": len(chunks), "warnings": parsed.warnings},
                )
                result = repository.get_job(job_id)
                assert result is not None
            new_point_ids = {chunk.qdrant_point_id for chunk in chunks}
            stale_point_ids = [str(item["qdrant_point_id"]) for item in stale_chunks if int(item.get("version_no") or 0) == version_no and str(item["qdrant_point_id"]) not in new_point_ids]
            try:
                self.index.delete_points(stale_point_ids)
            except Exception:
                # SQLite active-chunk filtering keeps stale points invisible;
                # rebuild can reclaim them later without failing ingestion.
                logger.warning("Stale knowledge point cleanup degraded for %s", document["document_id"], exc_info=True)
            self._invalidate_result_cache()
            if document_for_chunks.get("approval_status") == "approved":
                self._sync_version_event(document_for_chunks, version_no, chunks[0])
            return result
        except Exception as exc:
            logger.exception("Knowledge ingestion failed for %s", job_id)
            error = str(exc)[:1000]
            with self._repo() as repository:
                old_chunks = repository.list_chunks(document_id=document["document_id"], active_only=True)
                repository.update_version(document["document_id"], version_no, status="failed", error=error)
                repository.update_document(
                    document["document_id"],
                    status="partial" if old_chunks else "failed",
                    error=error,
                )
                repository.update_job(job_id, status="failed", progress=100, error=error, finished_at=_now())
                result = repository.get_job(job_id)
                assert result is not None
                return result

    def queue_reindex(self, document_id: str, user_id: str) -> dict[str, Any]:
        with self._repo() as repository:
            document = repository.get_document(document_id, user_id)
            if document is None:
                raise KeyError(f"Knowledge document not found: {document_id}")
            if document.get("space_role") not in WRITE_ROLES:
                raise PermissionError("Knowledge-space write permission is required")
            if not document.get("current_version") or not document.get("file_path"):
                raise ValueError("Document has no completed version to reindex")
            job_id = f"kjob-{uuid.uuid4().hex}"
            return repository.create_job(
                job_id=job_id,
                user_id=user_id,
                document_id=document_id,
                operation="reindex",
                metadata={
                    "version_no": int(document["current_version"]),
                    "file_path": document["file_path"],
                    "content_hash": document.get("content_hash", ""),
                },
            )

    def queue_rebuild(self, user_id: str) -> dict[str, Any]:
        with self._repo() as repository:
            job_id = f"kjob-{uuid.uuid4().hex}"
            return repository.create_job(
                job_id=job_id,
                user_id=user_id,
                operation="rebuild",
                metadata={},
            )

    def queue_intelligence_history(
        self,
        *,
        user_id: str,
        item: dict[str, Any],
        title: str,
        authority_tier: str,
        space_id: str | None = None,
        approval_status: str | None = None,
        governance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Queue one observation fact's complete immutable version series."""
        job_metadata = {
            "item": item,
            "title": title,
            "authority_tier": authority_tier,
            "space_id": self._resolve_space(user_id, space_id, roles=WRITE_ROLES)["space_id"],
            "approval_status": approval_status,
            "governance": governance or {},
        }
        if (governance or {}).get("trigger") == "observation":
            job_metadata["idempotency_key"] = f"intelligence:{item.get('item_key') or ''}:{item.get('content_hash') or item.get('last_seen_at') or ''}"
        with self._repo() as repository:
            return repository.create_job(
                job_id=f"kjob-{uuid.uuid4().hex}",
                user_id=user_id,
                operation="import_history",
                metadata=job_metadata,
            )

    def queue_governed_intelligence_history(
        self,
        *,
        user_id: str,
        item: dict[str, Any],
        title: str,
        space_id: str | None = None,
        trigger: str = "observation",
    ) -> dict[str, Any]:
        """Queue an observed fact with source-quality admission metadata."""
        from competition.db import get_credibility, init_db

        conn = init_db(self.db_path)
        try:
            credibility = get_credibility(str(item.get("source_domain") or ""), conn)
        finally:
            conn.close()
        governance = assess_intelligence_item(item, source_credibility=credibility)
        governance["trigger"] = trigger
        return self.queue_intelligence_history(
            user_id=user_id,
            item=item,
            title=title,
            authority_tier="structured_fact",
            space_id=space_id,
            approval_status=str(governance["approval_status"]),
            governance=governance,
        )

    def register_report_snapshot(
        self,
        *,
        user_id: str,
        thread_id: str,
        version: int,
        report_data: dict[str, Any],
        analysis_brief: dict[str, Any] | None = None,
        generation_id: str | None = None,
        space_id: str | None = None,
    ) -> dict[str, Any]:
        """Register one immutable analysis report version under governed approval."""
        import json

        governance = assess_report(report_data)
        products = [str(value) for value in report_data.get("products") or [] if str(value).strip()]
        title = str(report_data.get("title") or f"Analysis report {thread_id}")
        payload = {
            "thread_id": thread_id,
            "report_version": version,
            "report": report_data,
            "analysis_brief": analysis_brief or {},
        }
        generated_at = str(report_data.get("generated_at") or _now())
        return self.register_bytes(
            user_id=user_id,
            filename=f"{thread_id}.json",
            data=json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode(),
            title=title,
            media_type="application/json",
            source_type="analysis_report",
            source_uri=f"analysis://{thread_id}",
            product=" / ".join(products),
            dimension="report",
            authority_tier="report",
            published_at=generated_at,
            observed_at=_now(),
            metadata={
                "auto_ingestion": governance,
                "lineage": {
                    "thread_id": thread_id,
                    "report_version": version,
                    "generation_id": generation_id,
                },
            },
            space_id=space_id,
            approval_status=str(governance["approval_status"]),
        )

    def process_intelligence_history_job(self, job_id: str) -> dict[str, Any]:
        """Import observation versions serially so validity intervals remain ordered."""
        with self._repo() as repository:
            job = repository.get_job(job_id)
            if job is None:
                raise KeyError(f"Knowledge job not found: {job_id}")
            if job["status"] == "completed":
                return job
            repository.update_job(job_id, status="running", progress=5, started_at=_now(), error=None)
        metadata = job.get("metadata") or {}
        item = metadata.get("item") or {}
        versions = list(item.get("versions") or [])
        if not versions:
            versions = [
                {
                    "version": 1,
                    "content_hash": item.get("content_hash") or "",
                    "payload": {
                        "product": item.get("product"),
                        "dimension": item.get("dimension"),
                        "label": item.get("label"),
                        "value": item.get("value"),
                        "source_url": item.get("source_url"),
                        "source_type": item.get("source_type"),
                        "published_at": item.get("published_at"),
                        "scope": item.get("scope"),
                    },
                    "observed_at": item.get("fetched_at") or _now(),
                }
            ]
        versions.sort(key=lambda value: (str(value.get("observed_at") or ""), int(value.get("version") or 0)))
        source_uri = f"intelligence://{item['item_key']}"
        source_identity = _source_key(
            source_uri=source_uri,
            filename=f"{item['item_key']}.md",
            product=str(item.get("product") or ""),
            dimension=str(item.get("dimension") or ""),
            namespace=str(metadata.get("space_id") or ""),
        )
        with self._repo() as repository:
            existing = repository.find_document_by_source(job["user_id"], source_identity, str(metadata.get("space_id") or ""))
            imported_hashes = (
                {str((((version.get("metadata") or {}).get("document_fields") or {}).get("metadata") or {}).get("intelligence_content_hash") or "") for version in repository.list_versions(existing["document_id"])} if existing else set()
            )

        imported = 0
        skipped = 0
        failures: list[dict[str, str]] = []
        document_id: str | None = existing.get("document_id") if existing else None
        for index, version in enumerate(versions):
            content_hash = str(version.get("content_hash") or "")
            if content_hash and content_hash in imported_hashes:
                skipped += 1
                continue
            payload = version.get("payload") or {}
            observed_at = str(version.get("observed_at") or _now())
            markdown = (
                f"# {payload.get('label') or item.get('label') or 'Observed fact'}\n\n"
                f"- Product: {payload.get('product') or item.get('product') or ''}\n"
                f"- Dimension: {payload.get('dimension') or item.get('dimension') or ''}\n"
                f"- Source: {payload.get('source_url') or item.get('source_url') or ''}\n"
                f"- Published: {payload.get('published_at') or 'unknown'}\n"
                f"- Observed: {observed_at}\n"
                f"- Observation version: {version.get('version') or index + 1}\n\n"
                f"## Fact\n\n{payload.get('value', item.get('value', ''))}\n"
            )
            registration = self.register_bytes(
                user_id=job["user_id"],
                filename=f"{item['item_key']}.md",
                data=markdown.encode(),
                title=f"{metadata.get('title') or 'Intelligence history'}: {payload.get('label') or item.get('label') or ''}",
                media_type="text/markdown",
                source_type="intelligence",
                source_uri=source_uri,
                product=str(payload.get("product") or item.get("product") or ""),
                dimension=str(payload.get("dimension") or item.get("dimension") or ""),
                market_scope=str(payload.get("scope") or item.get("scope") or "Global / unspecified"),
                authority_tier=str(metadata.get("authority_tier") or "structured_fact"),
                published_at=payload.get("published_at"),
                observed_at=observed_at,
                metadata={
                    "intelligence_item_key": item["item_key"],
                    "intelligence_version": version.get("version") or index + 1,
                    "intelligence_content_hash": content_hash,
                    "original_source_url": payload.get("source_url") or item.get("source_url"),
                    "auto_ingestion": metadata.get("governance") or {},
                    "lineage": {
                        "intelligence_item_key": item["item_key"],
                        "intelligence_version": version.get("version") or index + 1,
                    },
                },
                space_id=str(metadata.get("space_id") or "") or None,
                approval_status=metadata.get("approval_status"),
            )
            document_id = (registration.get("document") or {}).get("document_id") or document_id
            child = registration.get("job") or {}
            completed = child if child.get("status") == "completed" else self.process_job(child["job_id"])
            if completed.get("status") == "completed":
                imported += 1
                imported_hashes.add(content_hash)
            else:
                failures.append(
                    {
                        "version": str(version.get("version") or index + 1),
                        "error": str(completed.get("error") or "ingestion failed")[:300],
                    }
                )
            with self._repo() as repository:
                repository.update_job(
                    job_id,
                    document_id=document_id,
                    progress=min(95, 5 + int((index + 1) / max(1, len(versions)) * 90)),
                )

        with self._repo() as repository:
            repository.update_job(
                job_id,
                document_id=document_id,
                status="failed" if failures else "completed",
                progress=100,
                error="Some observation versions failed to import" if failures else None,
                finished_at=_now(),
                metadata={
                    **metadata,
                    "item_key": item.get("item_key"),
                    "versions_requested": len(versions),
                    "versions_imported": imported,
                    "versions_skipped": skipped,
                    "failures": failures,
                },
            )
            result = repository.get_job(job_id)
            assert result is not None
            return result

    def retry_job(self, job_id: str, user_id: str) -> dict[str, Any]:
        """Create an auditable retry without mutating the failed job."""
        with self._repo() as repository:
            original = repository.get_job(job_id, user_id)
            if original is None:
                raise KeyError(f"Knowledge job not found: {job_id}")
            if original.get("status") != "failed":
                raise ValueError("Only failed knowledge jobs can be retried")
            operation = str(original.get("operation") or "")
            if operation not in {"ingest", "reindex", "rebuild", "import_history"}:
                raise ValueError(f"Unsupported retry operation: {operation}")
            document_id = original.get("document_id")
            if document_id:
                document = repository.get_document(str(document_id), user_id)
                if document is None or document.get("space_role") not in WRITE_ROLES:
                    raise PermissionError("Knowledge-space write permission is required")
            metadata = dict(original.get("metadata") or {})
            metadata["retry_of"] = job_id
            metadata["retry_attempt"] = int(metadata.get("retry_attempt") or 0) + 1
            return repository.create_job(
                job_id=f"kjob-{uuid.uuid4().hex}",
                user_id=user_id,
                document_id=document_id,
                operation=operation,
                metadata=metadata,
            )

    def process_rebuild_job(self, job_id: str) -> dict[str, Any]:
        with self._repo() as repository:
            job = repository.get_job(job_id)
            if job is None:
                raise KeyError(f"Knowledge job not found: {job_id}")
            repository.update_job(job_id, status="running", progress=10, started_at=_now(), error=None)
        try:
            result = self.rebuild_user_index(job["user_id"])
            status = "failed" if result["failures"] and result["chunks_indexed"] == 0 else "completed"
            with self._repo() as repository:
                repository.update_job(
                    job_id,
                    status=status,
                    progress=100,
                    error="Some documents could not be rebuilt" if result["failures"] else None,
                    finished_at=_now(),
                    metadata={**(job.get("metadata") or {}), **result},
                )
                completed = repository.get_job(job_id)
                assert completed is not None
                self._invalidate_result_cache(job["user_id"])
                return completed
        except Exception as exc:
            with self._repo() as repository:
                repository.update_job(
                    job_id,
                    status="failed",
                    progress=100,
                    error=str(exc)[:1000],
                    finished_at=_now(),
                )
                failed = repository.get_job(job_id)
                assert failed is not None
                return failed

    def search(
        self,
        query: str,
        *,
        user_id: str,
        filters: RetrievalFilters | None = None,
        limit: int = 12,
        ranking_profile: str = "balanced",
        retrieval_mode: str = "hybrid",
        rerank: bool = True,
    ) -> list[KnowledgeHit]:
        from competition.knowledge_quota import quota

        quota.check(user_id, "search")
        if retrieval_mode == "auto":
            strategy = adaptive_strategy(query, filters, preferred_profile=ranking_profile)
            retrieval_mode = strategy.mode
            ranking_profile = strategy.ranking_profile
            rerank = strategy.rerank
        kwargs: dict[str, Any] = {"user_id": user_id, "ranking_profile": ranking_profile}
        if retrieval_mode != "hybrid" or not rerank:
            kwargs.update({"retrieval_mode": retrieval_mode, "rerank": rerank})
        return self.search_many([(query, filters or RetrievalFilters(), limit)], **kwargs)[0]

    def search_many(
        self,
        requests: list[tuple[str, RetrievalFilters, int]],
        *,
        user_id: str,
        ranking_profile: str = "balanced",
        retrieval_mode: str = "hybrid",
        rerank: bool = True,
    ) -> list[list[KnowledgeHit]]:
        """Retrieve several scoped queries with batch inference and result caching."""
        if not requests:
            return []
        with self._repo() as repository:
            accessible = set(repository.accessible_space_ids(user_id))
            feedback_scores = repository.retrieval_feedback_scores(user_id)
            alias_map = repository.entity_alias_map(user_id)
            from competition.db import get_all_credibilities

            credibility_scores = get_all_credibilities(repository.conn)
        scoped_requests: list[tuple[str, RetrievalFilters, int] | None] = []
        for query, filters, limit in requests:
            query = rewrite_query_with_aliases(query, alias_map)
            requested = set(filters.space_ids)
            allowed = accessible.intersection(requested) if requested else accessible
            scoped_requests.append((query, replace(filters, space_ids=tuple(sorted(allowed))), limit) if allowed else None)
        started = time.monotonic()
        output: list[list[KnowledgeHit] | None] = [None] * len(requests)
        missing: list[tuple[int, str, RetrievalFilters, int, tuple[Any, ...]]] = []
        for index, scoped in enumerate(scoped_requests):
            if scoped is None:
                output[index] = []
                continue
            query, filters, limit = scoped
            normalized = normalize_query_text(query)
            effective_mode = retrieval_mode if retrieval_mode in {"hybrid", "dense", "sparse"} else "hybrid"
            cache_key = self._cache_key(user_id, normalized, filters, limit, ranking_profile, effective_mode, rerank)
            cached = self._get_cached(cache_key)
            if cached is not None:
                output[index] = cached
                self._log_retrieval(
                    user_id=user_id,
                    query=normalized,
                    filters=filters,
                    hits=cached,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    cache_hit=True,
                )
            else:
                missing.append((index, normalized, filters, limit, cache_key))
        if not missing:
            return [hits or [] for hits in output]
        try:
            index_requests = [(query, user_id, filters, limit, max(24, limit * 3)) for _, query, filters, limit, _ in missing]
            if hasattr(self.index, "search_many_ids"):
                try:
                    recalled_groups = self.index.search_many_ids(index_requests, retrieval_mode=retrieval_mode)
                except TypeError:
                    # Third-party/test indexes may implement the original
                    # five-item request contract; retain compatibility.
                    recalled_groups = self.index.search_many_ids(index_requests)
            else:
                recalled_groups = [
                    self.index.search_ids(
                        query,
                        user_id=request_user,
                        filters=request_filters,
                        limit=request_limit,
                        candidate_limit=candidate_limit,
                        retrieval_mode=retrieval_mode,
                    )
                    for query, request_user, request_filters, request_limit, candidate_limit in index_requests
                ]
            all_chunk_ids = list(dict.fromkeys(chunk_id for recalled in recalled_groups for chunk_id, _ in recalled))
            include_historical = any(filters.temporal_mode != "current" for _, _, filters, _, _ in missing)
            with self._repo() as repository:
                rows_by_id = repository.get_chunks_by_ids(
                    all_chunk_ids,
                    user_id,
                    include_historical=include_historical,
                    space_ids=tuple(sorted(accessible)),
                )
            candidate_groups = [[(rows_by_id[chunk_id], score) for chunk_id, score in recalled if chunk_id in rows_by_id] for recalled in recalled_groups]
            rerank_groups = [(query, [row["contextual_text"] for row, _ in candidates]) for (_, query, _, _, _), candidates in zip(missing, candidate_groups, strict=True)]
            if rerank and hasattr(self.index, "rerank_many"):
                score_groups = self.index.rerank_many(rerank_groups)
            elif rerank:
                score_groups = [self.index.rerank(query, texts) for query, texts in rerank_groups]
            else:
                score_groups = [[None for _ in texts] for _, texts in rerank_groups]
            for request, candidates, rerank_scores in zip(missing, candidate_groups, score_groups, strict=True):
                index, query, filters, limit, cache_key = request
                hits = self._build_hits(
                    candidates,
                    rerank_scores,
                    limit,
                    ranking_profile=ranking_profile,
                    retrieval_mode=retrieval_mode,
                    rerank=rerank,
                    feedback_scores=feedback_scores,
                    credibility_scores=credibility_scores,
                )
                output[index] = hits
                self._put_cached(cache_key, hits)
                self._log_retrieval(
                    user_id=user_id,
                    query=query,
                    filters=filters,
                    hits=hits,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    cache_hit=False,
                )
            return [hits or [] for hits in output]
        except Exception as exc:
            # Keep an already-ingested knowledge base useful when local model
            # weights or the semantic index are unavailable. The fallback is
            # bounded, deterministic, and visible in retrieval diagnostics.
            from competition.knowledge_index import KnowledgeUnavailableError

            if isinstance(exc, KnowledgeUnavailableError) and os.getenv("CI_AGENT_RAG_LEXICAL_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}:
                duration_ms = int((time.monotonic() - started) * 1000)
                with self._repo() as repository:
                    for index, query, filters, limit, cache_key in missing:
                        lexical = repository.search_chunks_lexical(query, user_id, filters=filters, limit=limit)
                        hits = self._build_hits(
                            lexical,
                            [None] * len(lexical),
                            limit,
                            ranking_profile=ranking_profile,
                            retrieval_mode="sparse",
                            rerank=False,
                            feedback_scores=feedback_scores,
                            credibility_scores=credibility_scores,
                        )
                        output[index] = hits
                        self._put_cached(cache_key, hits)
                        self._log_retrieval(
                            user_id=user_id,
                            query=query,
                            filters=filters,
                            hits=hits,
                            duration_ms=duration_ms,
                            status="degraded",
                            error=f"semantic index unavailable; lexical fallback used: {str(exc)[:300]}",
                        )
                return [hits or [] for hits in output]

            duration_ms = int((time.monotonic() - started) * 1000)
            for _, query, filters, _, _ in missing:
                self._log_retrieval(
                    user_id=user_id,
                    query=query,
                    filters=filters,
                    hits=[],
                    duration_ms=duration_ms,
                    status="failed",
                    error=str(exc)[:1000],
                )
            raise

    def _build_hits(
        self,
        candidates: list[tuple[dict[str, Any], float]],
        rerank_scores: list[float],
        limit: int,
        ranking_profile: str = "balanced",
        retrieval_mode: str = "hybrid",
        rerank: bool = True,
        feedback_scores: dict[str, dict[str, int]] | None = None,
        credibility_scores: dict[str, float] | None = None,
    ) -> list[KnowledgeHit]:
        hits: list[KnowledgeHit] = []
        profile = ranking_profile if ranking_profile in {"balanced", "freshness", "authority"} else "balanced"
        normalized_mode = retrieval_mode if retrieval_mode in {"hybrid", "dense", "sparse"} else "hybrid"
        effective_rerank = rerank and any(value is not None for value in rerank_scores)
        safe_rerank_scores = [float(value or 0.0) for value in rerank_scores]
        if effective_rerank:
            ranked: list[tuple[dict[str, Any], float, float | None]] = []
            for (row, recall_score), rerank_score in zip(candidates, safe_rerank_scores, strict=True):
                authority_score = self._authority_score(row, credibility_scores)
                final_score = 0.72 * max(0.0, min(1.0, rerank_score)) + 0.16 * max(0.0, min(1.0, recall_score)) + 0.12 * authority_score
                counts = (feedback_scores or {}).get(str(row.get("chunk_id")), {})
                final_score += feedback_adjustment(
                    relevant=counts.get("relevant", 0),
                    not_relevant=counts.get("not_relevant", 0),
                    citation_used=counts.get("citation_used", 0),
                )
                ranked.append((row, round(final_score, 6), rerank_score))
            ranked.sort(key=lambda item: item[1], reverse=True)
        else:
            ranked = [(row, score, None) for row, score in sorted(candidates, key=lambda item: item[1], reverse=True)]
        for row, score, rerank_score in ranked:
            if score < MIN_RETRIEVAL_SCORE:
                continue
            authority = self._authority_score(row, credibility_scores)
            freshness = self._freshness_score(row)
            if profile == "freshness":
                score = round(0.68 * score + 0.20 * freshness + 0.12 * authority, 6)
            elif profile == "authority":
                score = round(0.68 * score + 0.20 * authority + 0.12 * freshness, 6)
            explanation = explain_retrieval(
                strategy=RetrievalStrategy(
                    mode=normalized_mode,
                    ranking_profile=profile,
                    rerank=effective_rerank,
                ),
                recall_score=float(row.get("recall_score") or score),
                rerank_score=rerank_score,
                authority_score=authority,
                freshness_score=freshness,
            )
            hits.append(
                KnowledgeHit(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    version_no=int(row["version_no"]),
                    title=row.get("title") or row.get("filename") or "Knowledge document",
                    text=row["text"],
                    contextual_text=row["contextual_text"],
                    source_uri=row.get("source_uri") or "",
                    source_type=row.get("source_type") or "upload",
                    authority_tier=row.get("authority_tier") or "third_party",
                    product=row.get("product") or "",
                    dimension=row.get("dimension") or "",
                    market_scope=row.get("market_scope") or "Global / unspecified",
                    section_path=row.get("section_path") or "",
                    page_no=row.get("page_no"),
                    published_at=row.get("published_at"),
                    observed_at=row.get("observed_at"),
                    valid_from=row.get("valid_from"),
                    valid_to=row.get("valid_to"),
                    temporal_status=row.get("temporal_status") or ("current" if row.get("active") else "historical"),
                    score=score,
                    retrieval_sources=(
                        (("dense", "sparse") if normalized_mode == "hybrid" else (normalized_mode,))
                        + (("reranker",) if effective_rerank else ())
                        + (("lexical_fallback",) if row.get("retrieval_source") == "lexical_fallback" else ())
                    ),
                    metadata={
                        **(row.get("metadata") or {}),
                        "version_metadata": row.get("version_metadata") or {},
                        "ranking_profile": profile,
                        "freshness_score": freshness,
                        "authority_score": authority,
                        "source_credibility": (credibility_scores or {}).get(self._source_domain(row.get("source_uri") or "")),
                        "retrieval_explanation": explanation,
                        "degraded": row.get("retrieval_source") == "lexical_fallback",
                        "feedback_prior": feedback_adjustment(
                            relevant=(feedback_scores or {}).get(str(row.get("chunk_id")), {}).get("relevant", 0),
                            not_relevant=(feedback_scores or {}).get(str(row.get("chunk_id")), {}).get("not_relevant", 0),
                            citation_used=(feedback_scores or {}).get(str(row.get("chunk_id")), {}).get("citation_used", 0),
                        ),
                    },
                )
            )
            if len(hits) >= limit:
                break
        return hits

    @staticmethod
    def _freshness_score(row: dict[str, Any]) -> float:
        """Return a bounded, deterministic freshness score for ranking profiles."""
        value = row.get("published_at") or row.get("observed_at") or row.get("fetched_at")
        if not value:
            return 0.35
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            age_days = max(0.0, (datetime.now(UTC) - stamp.astimezone(UTC)).total_seconds() / 86400)
            score = math.exp(-age_days / 365.0)
            valid_to = row.get("valid_to")
            if valid_to:
                try:
                    expiry = datetime.fromisoformat(str(valid_to).replace("Z", "+00:00"))
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=UTC)
                    if expiry.astimezone(UTC) <= datetime.now(UTC):
                        score *= 0.35
                except (TypeError, ValueError, OverflowError):
                    pass
            return round(max(0.0, min(1.0, score)), 6)
        except (TypeError, ValueError, OverflowError):
            return 0.35

    @staticmethod
    def _source_domain(uri: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(str(uri or ""))
        return (parsed.hostname or parsed.netloc or "").casefold()

    @staticmethod
    def _authority_score(row: dict[str, Any], credibility_scores: dict[str, float] | None = None) -> float:
        prior = AUTHORITY_PRIORS.get(str(row.get("authority_tier")), 0.5)
        domain = KnowledgeService._source_domain(row.get("source_uri") or "")
        credibility = (credibility_scores or {}).get(domain)
        if credibility is None:
            return prior
        return round(max(0.0, min(1.0, 0.72 * prior + 0.28 * float(credibility))), 6)

    def _cache_key(
        self,
        user_id: str,
        query: str,
        filters: RetrievalFilters,
        limit: int,
        ranking_profile: str = "balanced",
        retrieval_mode: str = "hybrid",
        rerank: bool = True,
    ) -> tuple[Any, ...]:
        values = filters.to_dict()
        return (
            user_id,
            query.casefold(),
            tuple(values["products"]),
            tuple(values["dimensions"]),
            values["market_scope"],
            tuple(values["source_types"]),
            tuple(values["authority_tiers"]),
            values["published_after"],
            values["published_before"],
            values["include_reports"],
            values["temporal_mode"],
            values["as_of"],
            tuple(values["space_ids"]),
            limit,
            ranking_profile,
            retrieval_mode,
            bool(rerank),
        )

    def search_planned(
        self,
        query: str,
        *,
        user_id: str,
        filters: RetrievalFilters | None = None,
        limit: int = 12,
        query_expansion: bool | None = None,
        ranking_profile: str = "balanced",
        retrieval_mode: str = "hybrid",
        rerank: bool = True,
    ) -> tuple[list[KnowledgeHit], RetrievalPlan]:
        from competition.knowledge_quota import quota

        quota.check(user_id, "search")
        if retrieval_mode == "auto":
            strategy = adaptive_strategy(query, filters, preferred_profile=ranking_profile)
            retrieval_mode = strategy.mode
            ranking_profile = strategy.ranking_profile
            rerank = strategy.rerank
        result = self.search_planned_many(
            [(query, filters or RetrievalFilters(), limit)],
            user_id=user_id,
            query_expansion=query_expansion,
            ranking_profile=ranking_profile,
            retrieval_mode=retrieval_mode,
            rerank=rerank,
        )
        return result[0]

    def search_planned_many(
        self,
        requests: list[tuple[str, RetrievalFilters, int]],
        *,
        user_id: str,
        query_expansion: bool | None = None,
        ranking_profile: str = "balanced",
        retrieval_mode: str = "hybrid",
        rerank: bool = True,
    ) -> list[tuple[list[KnowledgeHit], RetrievalPlan]]:
        """Execute cost-routed multi-query plans with one batch per hop."""
        if not requests:
            return []
        with self._repo() as repository:
            aliases = repository.entity_alias_map(user_id)
        requests = [(rewrite_query_with_aliases(query, aliases), filters, limit) for query, filters, limit in requests]
        plans = [plan_retrieval_query(query, filters) for query, filters, _ in requests]
        flat: list[tuple[str, RetrievalFilters, int]] = []
        owners: list[int] = []
        for owner, ((_, filters, limit), plan) in enumerate(zip(requests, plans, strict=True)):
            per_step = max(limit, min(24, limit * 2))
            for step in plan.steps:
                if step.hop != 1:
                    continue
                flat.append((step.query, filters, per_step))
                owners.append(owner)
            classification = plan.metadata.get("classification") or {}
            adaptive_expansion = classification.get("complexity") in {"medium", "high"} or classification.get("needs_multi_hop")
            expansion_enabled = query_expansion if query_expansion is not None else (
                adaptive_expansion
                or os.getenv("CI_AGENT_RAG_QUERY_EXPANSION", "false").lower() in {"1", "true", "yes", "on"}
            )
            if expansion_enabled:
                for variant in plan.metadata.get("query_expansions") or expand_query_variants(plan.normalized_query):
                    flat.append((variant, filters, per_step))
                    owners.append(owner)
        search_kwargs: dict[str, Any] = {"user_id": user_id}
        if ranking_profile != "balanced":
            search_kwargs["ranking_profile"] = ranking_profile
        if retrieval_mode != "hybrid" or not rerank:
            search_kwargs.update({"retrieval_mode": retrieval_mode, "rerank": rerank})
        groups = self.search_many(flat, **search_kwargs)
        accumulated: list[list[KnowledgeHit]] = [[] for _ in requests]
        for owner, hits in zip(owners, groups, strict=True):
            accumulated[owner].extend(hits)
        bridge_requests: list[tuple[str, RetrievalFilters, int]] = []
        bridge_owners: list[int] = []
        for owner, ((_, filters, limit), plan) in enumerate(zip(requests, plans, strict=True)):
            if plan.route != "multi_hop" or not accumulated[owner]:
                continue
            bridge_requests.append((build_bridge_query(plan, accumulated[owner][:5]), filters, max(limit, limit * 2)))
            bridge_owners.append(owner)
        if bridge_requests:
            bridge_groups = self.search_many(bridge_requests, **search_kwargs)
            for owner, hits in zip(bridge_owners, bridge_groups, strict=True):
                accumulated[owner].extend(hits)
        output: list[tuple[list[KnowledgeHit], RetrievalPlan]] = []
        for hits, plan, (_, _, limit) in zip(accumulated, plans, requests, strict=True):
            output.append((self._fuse_planned_hits(hits, limit), plan))
        return output

    @staticmethod
    def _fuse_planned_hits(hits: list[KnowledgeHit], limit: int) -> list[KnowledgeHit]:
        grouped: dict[str, list[KnowledgeHit]] = {}
        for hit in hits:
            grouped.setdefault(hit.chunk_id, []).append(hit)
        fused: list[KnowledgeHit] = []
        for candidates in grouped.values():
            best = max(candidates, key=lambda item: item.score)
            coverage_bonus = min(0.08, max(0, len(candidates) - 1) * 0.02)
            fused.append(
                replace(
                    best,
                    score=round(min(1.0, best.score + coverage_bonus), 6),
                    retrieval_sources=tuple(dict.fromkeys((*best.retrieval_sources, "query_planner"))),
                    metadata={**best.metadata, "query_match_count": len(candidates)},
                )
            )
        return sorted(fused, key=lambda item: item.score, reverse=True)[:limit]

    def _get_cached(self, key: tuple[Any, ...]) -> list[KnowledgeHit] | None:
        if RESULT_CACHE_SIZE == 0 or RESULT_CACHE_TTL_SECONDS == 0:
            self._cache_misses += 1
            return None
        with self._cache_lock:
            item = self._result_cache.get(key)
            if item is None or time.monotonic() - item[0] > RESULT_CACHE_TTL_SECONDS:
                if item is not None:
                    self._result_cache.pop(key, None)
                self._cache_misses += 1
                return None
            self._result_cache.move_to_end(key)
            self._cache_hits += 1
            return list(item[1])

    def _put_cached(self, key: tuple[Any, ...], hits: list[KnowledgeHit]) -> None:
        if RESULT_CACHE_SIZE == 0 or RESULT_CACHE_TTL_SECONDS == 0:
            return
        with self._cache_lock:
            self._result_cache[key] = (time.monotonic(), tuple(hits))
            self._result_cache.move_to_end(key)
            while len(self._result_cache) > RESULT_CACHE_SIZE:
                self._result_cache.popitem(last=False)

    def _invalidate_result_cache(self, user_id: str | None = None) -> None:
        with self._cache_lock:
            if user_id is None:
                removed = len(self._result_cache)
                self._result_cache.clear()
            else:
                keys = [key for key in self._result_cache if key[0] == user_id]
                for key in keys:
                    self._result_cache.pop(key, None)
                removed = len(keys)
            self._cache_invalidations += removed

    def invalidate_retrieval_cache(self, user_id: str) -> None:
        """Invalidate cached hits after a caller feedback update."""
        self._invalidate_result_cache(user_id)

    def _log_retrieval(
        self,
        *,
        user_id: str,
        query: str,
        filters: RetrievalFilters,
        hits: list[KnowledgeHit],
        duration_ms: int,
        cache_hit: bool = False,
        status: str = "completed",
        error: str | None = None,
    ) -> None:
        logged_filters = {**filters.to_dict(), "cache_hit": cache_hit}
        with self._repo() as repository:
            repository.log_retrieval(
                retrieval_id=f"kret-{uuid.uuid4().hex}",
                user_id=user_id,
                query=query,
                filters=logged_filters,
                chunk_ids=[hit.chunk_id for hit in hits],
                duration_ms=duration_ms,
                status=status,
                error=error,
            )
            # Keep a small online metric stream for latency/result regressions;
            # detailed traces remain in knowledge_retrieval_logs.
            if status in {"completed", "degraded"}:
                now = _now()
                for metric_name, value in (
                    ("retrieval.latency_ms", float(duration_ms)),
                    ("retrieval.result_count", float(len(hits))),
                    ("retrieval.cache_hit", 1.0 if cache_hit else 0.0),
                    ("retrieval.degraded", 1.0 if status == "degraded" else 0.0),
                ):
                    repository.conn.execute(
                        """INSERT INTO knowledge_online_metrics (
                            metric_id, user_id, metric_name, value, sample_count,
                            dimensions_json, observed_at, created_at
                        ) VALUES (?, ?, ?, ?, 1, '{}', ?, ?)""",
                        (f"kmetric-{uuid.uuid4().hex}", user_id, metric_name, value, now, now),
                    )
                repository.conn.commit()

    def retrieve_for_analysis(self, state: dict[str, Any], limit: int = 16) -> list[dict[str, Any]]:
        user_id = str(state.get("user_id") or "default")
        queries = build_analysis_queries(state)
        brief = state.get("analysis_brief") or {}
        retrieval_mode = str(state.get("rag_retrieval_mode") or brief.get("retrieval_mode") or "hybrid")
        ranking_profile = str(state.get("rag_ranking_profile") or brief.get("ranking_profile") or "balanced")
        products = list(dict.fromkeys(query.product for query in queries if query.product))
        hits: list[tuple[KnowledgeHit, str, str]] = []
        per_pair = max(2, min(4, limit // max(1, len(queries)) + 1))
        requests = [(query.query, query.filters, per_pair) for query in queries]
        result_groups = self.search_planned_many(
            requests,
            user_id=user_id,
            retrieval_mode=retrieval_mode,
            ranking_profile=ranking_profile,
        )
        for planned, (result, retrieval_plan) in zip(queries, result_groups, strict=True):
            hits.extend((hit, planned.dimension, retrieval_plan.route) for hit in result)
        unique: dict[tuple[str, str], tuple[KnowledgeHit, str, str]] = {}
        for hit, requested_dimension, route in sorted(hits, key=lambda value: value[0].score, reverse=True):
            unique.setdefault((hit.chunk_id, hit.dimension or requested_dimension), (hit, requested_dimension, route))
        points: list[dict[str, Any]] = []
        for hit, requested_dimension, route in list(unique.values())[:limit]:
            source_url = hit.source_uri if hit.source_uri.startswith(("http://", "https://")) else f"knowledge://{hit.document_id}/{hit.chunk_id}"
            source_type = _agent_source_type(hit)
            points.append(
                {
                    "id": f"rag-{hit.chunk_id}",
                    "product": hit.product or (products[0] if len(products) == 1 else "Shared evidence"),
                    "category": hit.dimension or requested_dimension,
                    "label": f"{hit.title} - {hit.section_path}".strip(" -"),
                    "value": hit.text,
                    "confidence": hit.confidence,
                    "source_url": source_url,
                    "source_type": source_type,
                    "collected_at": hit.observed_at or _now(),
                    "published_at": hit.published_at,
                    "knowledge_document_id": hit.document_id,
                    "knowledge_chunk_id": hit.chunk_id,
                    "source_authority": hit.authority_tier,
                    "section_path": hit.section_path,
                    "page_no": hit.page_no,
                    "retrieval_score": hit.score,
                    "source_title": hit.title,
                    "knowledge_version_no": hit.version_no,
                    "knowledge_valid_from": hit.valid_from,
                    "knowledge_valid_to": hit.valid_to,
                    "knowledge_temporal_status": hit.temporal_status,
                    "knowledge_query_route": route,
                    "knowledge_retrieval_mode": retrieval_mode,
                    "knowledge_ranking_profile": ranking_profile,
                }
            )
        return points

    def retrieve_analysis_memory(self, state: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
        """Retrieve historical reports as non-citable planning memory."""
        user_id = str(state.get("user_id") or "default")
        brief = state.get("analysis_brief") or {}
        query = normalize_query_text(str(state.get("user_request") or brief.get("objective") or "competitive analysis history"))
        filters = RetrievalFilters(
            source_types=("analysis_report",),
            authority_tiers=("report",),
            include_reports=True,
            temporal_mode="current",
        )
        hits, plan = self.search_planned(query, user_id=user_id, filters=filters, limit=max(limit * 2, 8))
        current_thread = str(state.get("thread_id") or "")
        target_products = {canonical_product(str(value)).casefold() for value in (state.get("target_products") or brief.get("target_products") or []) if str(value).strip()}
        memories: list[dict[str, Any]] = []
        seen_documents: set[str] = set()
        for hit in hits:
            version_metadata = hit.metadata.get("version_metadata") or {}
            fields = version_metadata.get("document_fields") or {}
            document_metadata = fields.get("metadata") or {}
            lineage = document_metadata.get("lineage") or {}
            source_thread = str(lineage.get("thread_id") or "")
            if current_thread and source_thread == current_thread:
                continue
            if hit.document_id in seen_documents:
                continue
            hit_products = {canonical_product(value.strip()).casefold() for value in re.split(r"\s*/\s*|\s*,\s*|\s*，\s*", hit.product) if value.strip()}
            if target_products and hit_products and not target_products.intersection(hit_products):
                continue
            governance = document_metadata.get("auto_ingestion") or {}
            memories.append(
                {
                    "id": f"memory-{hit.chunk_id}",
                    "context_role": "historical_analysis_memory",
                    "citation_eligible": False,
                    "title": hit.title,
                    "summary": hit.text[:2400],
                    "products": sorted(hit_products) if hit_products else [hit.product] if hit.product else [],
                    "report_thread_id": source_thread,
                    "report_version": lineage.get("report_version") or hit.version_no,
                    "generated_at": hit.published_at or hit.observed_at,
                    "retrieval_score": hit.score,
                    "quality_score": governance.get("quality_score"),
                    "knowledge_document_id": hit.document_id,
                    "knowledge_chunk_id": hit.chunk_id,
                    "query_route": plan.route,
                    "usage_policy": "planning_only_not_factual_evidence",
                }
            )
            seen_documents.add(hit.document_id)
            if len(memories) >= limit:
                break
        return memories

    def rebuild_user_index(self, user_id: str) -> dict[str, Any]:
        indexed = 0
        failed: list[dict[str, str]] = []
        self.index.delete_user(user_id)
        with self._repo() as repository:
            documents = repository.list_documents(user_id, limit=500)
        for document in documents:
            if not document.get("current_version"):
                continue
            try:
                with self._repo() as repository:
                    rows = repository.list_chunks(document_id=document["document_id"], active_only=False)
                    versions = {int(item["version_no"]): item for item in repository.list_versions(document["document_id"]) if item.get("status") in {"indexed", "partial"}}
                rows_by_version: dict[int, list[dict[str, Any]]] = {}
                for row in rows:
                    version_no = int(row["version_no"])
                    if version_no in versions:
                        rows_by_version.setdefault(version_no, []).append(row)
                for version_no in sorted(rows_by_version):
                    version = versions[version_no]
                    version_fields = (version.get("metadata") or {}).get("document_fields") or {}
                    version_document = {**document, **version_fields}
                    chunks = [_chunk_from_row(row) for row in rows_by_version[version_no]]
                    self.index.replace_document(
                        version_document,
                        chunks,
                        is_current=version_no == int(document.get("current_version") or 0),
                        valid_from=version.get("created_at"),
                        valid_to=version.get("superseded_at"),
                        deactivate_previous=False,
                    )
                    indexed += len(chunks)
            except Exception as exc:
                failed.append({"document_id": document["document_id"], "error": str(exc)[:300]})
        self._invalidate_result_cache()
        return {"documents": len(documents), "chunks_indexed": indexed, "failures": failed}

    def delete_document(self, document_id: str, user_id: str) -> bool:
        with self._repo() as repository:
            document = repository.get_document(document_id, user_id)
            if document is None or document.get("space_role") not in WRITE_ROLES:
                return False
            deleted = repository.soft_delete_document(document_id, user_id)
        if deleted is None:
            return False
        try:
            self.index.delete_document(document_id)
        except Exception:
            logger.warning("Knowledge index cleanup degraded for %s", document_id, exc_info=True)
        self._remove_document_files(deleted)
        self._invalidate_result_cache()
        return True

    def _remove_document_files(self, deleted: dict[str, Any]) -> None:
        for value in [deleted.get("file_path"), deleted.get("normalized_path")]:
            path = Path(value) if value else None
            if path and _within(path, self.root):
                path.unlink(missing_ok=True)
        for version in deleted.get("versions", []):
            for key in ("file_path", "normalized_path"):
                value = version.get(key)
                path = Path(value) if value else None
                if path and _within(path, self.root):
                    path.unlink(missing_ok=True)

    def create_space(
        self,
        user_id: str,
        *,
        name: str,
        description: str = "",
        require_approval: bool = True,
        retention_days: int = 0,
    ) -> dict[str, Any]:
        with self._repo() as repository:
            return repository.create_space(
                owner_id=user_id,
                name=name.strip(),
                description=description.strip(),
                require_approval=require_approval,
                retention_days=retention_days,
            )

    def list_spaces(self, user_id: str) -> list[dict[str, Any]]:
        with self._repo() as repository:
            return repository.list_spaces(user_id)

    def list_entities(
        self,
        user_id: str,
        *,
        space_id: str | None = None,
        entity_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if space_id:
            self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            return repository.list_entities(user_id, space_id=space_id, entity_type=entity_type, limit=limit)

    def add_entity_alias(self, user_id: str, entity_id: str, alias: str) -> dict[str, Any]:
        with self._repo() as repository:
            return repository.add_entity_alias(entity_id, user_id=user_id, alias=alias)

    def merge_entities(self, user_id: str, source_entity_id: str, target_entity_id: str, *, reason: str = "") -> dict[str, Any]:
        with self._repo() as repository:
            merged = repository.merge_entities(source_entity_id, target_entity_id, user_id=user_id, reason=reason)
        self._invalidate_result_cache(user_id)
        return merged

    def list_entity_merge_audits(self, user_id: str, *, space_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if space_id:
            self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            return repository.list_entity_merge_audits(user_id, space_id=space_id, limit=limit)

    def update_space(self, user_id: str, space_id: str, **values: Any) -> dict[str, Any]:
        self._resolve_space(user_id, space_id, roles=REVIEW_ROLES)
        with self._repo() as repository:
            repository.update_space(space_id, **values)
            updated = repository.get_space(space_id, user_id)
        assert updated is not None
        return updated

    def list_space_members(self, user_id: str, space_id: str) -> list[dict[str, Any]]:
        self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            return repository.list_space_members(space_id)

    def set_space_member(self, user_id: str, space_id: str, member_id: str, role: str) -> list[dict[str, Any]]:
        self._resolve_space(user_id, space_id, roles=REVIEW_ROLES)
        if role not in {"editor", "viewer"}:
            raise ValueError("Member role must be editor or viewer")
        if member_id == user_id:
            raise ValueError("The space owner role cannot be replaced")
        with self._repo() as repository:
            repository.upsert_space_member(space_id, member_id, role)
            return repository.list_space_members(space_id)

    def remove_space_member(self, user_id: str, space_id: str, member_id: str) -> bool:
        self._resolve_space(user_id, space_id, roles=REVIEW_ROLES)
        with self._repo() as repository:
            return repository.remove_space_member(space_id, member_id)

    def review_document(
        self,
        user_id: str,
        document_id: str,
        decision: str,
        *,
        feedback_type: str | None = None,
        reason: str = "",
        correction: str = "",
    ) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Decision must be approved or rejected")
        allowed_feedback = {"verified", "conflict", "error", "outdated"}
        resolved_feedback = feedback_type or ("verified" if decision == "approved" else "error")
        if resolved_feedback not in allowed_feedback:
            raise ValueError("Feedback type must be verified, conflict, error, or outdated")
        if decision == "approved" and resolved_feedback != "verified":
            raise ValueError("Approved documents must use verified feedback")
        if decision == "rejected" and resolved_feedback == "verified":
            raise ValueError("Rejected documents require conflict, error, or outdated feedback")
        with self._repo() as repository:
            document = repository.get_document(document_id, user_id)
            if document is None or document.get("space_role") not in REVIEW_ROLES:
                raise PermissionError("Only the knowledge-space owner can review documents")
            updated = repository.set_document_approval(document_id, status=decision, reviewer_id=user_id)
            chunks = repository.list_chunks(document_id=document_id, active_only=True)
        from competition.db import get_credibility, init_db, update_credibility
        from competition.intelligence import source_domain

        metadata = dict(document.get("metadata") or {})
        original_url = str(metadata.get("original_source_url") or document.get("source_uri") or "")
        domain = source_domain(original_url) if original_url.startswith(("http://", "https://")) else ""
        credibility_before: float | None = None
        credibility_after: float | None = None
        if domain:
            conn = init_db(self.db_path)
            try:
                credibility_before = get_credibility(domain, conn)
                credibility_after = update_credibility(domain, resolved_feedback, conn)
            finally:
                conn.close()
        review_summary = {
            "decision": decision,
            "feedback_type": resolved_feedback,
            "reason": reason.strip()[:1000],
            "correction": correction.strip()[:2000],
            "source_domain": domain,
            "credibility_before": credibility_before,
            "credibility_after": credibility_after,
            "reviewed_by": user_id,
            "reviewed_at": _now(),
        }
        metadata["latest_human_review"] = review_summary
        metadata["human_review_count"] = int(metadata.get("human_review_count") or 0) + 1
        with self._repo() as repository:
            repository.update_document(document_id, metadata=metadata)
            feedback = repository.record_review_feedback(
                document_id=document_id,
                space_id=str(document.get("space_id") or ""),
                reviewer_id=user_id,
                decision=decision,
                feedback_type=resolved_feedback,
                reason=review_summary["reason"],
                correction=review_summary["correction"],
                source_domain=domain,
                credibility_before=credibility_before,
                credibility_after=credibility_after,
            )
            updated = repository.get_document(document_id, user_id)
        assert updated is not None
        if decision == "approved" and chunks:
            try:
                self.index.replace_document(updated, [_chunk_from_row(item) for item in chunks])
            except Exception:
                logger.warning("Approval payload refresh degraded for %s", document_id, exc_info=True)
            self._sync_version_event(updated, int(updated.get("current_version") or 0), chunks[0])
        else:
            try:
                self.index.delete_document(document_id)
            except Exception:
                logger.warning("Rejected-document index cleanup degraded for %s", document_id, exc_info=True)
        self._invalidate_result_cache()
        updated["review_feedback"] = feedback
        return updated

    def list_review_feedback(
        self,
        user_id: str,
        *,
        space_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if space_id:
            self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            return repository.list_review_feedback(user_id, space_id=space_id, limit=limit)

    def retrieval_logs(self, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._repo() as repository:
            return repository.list_retrieval_logs(user_id, limit=limit)

    def governance_stats(self, user_id: str, *, space_id: str | None = None) -> dict[str, Any]:
        if space_id:
            self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            return repository.governance_stats(user_id, space_id=space_id)

    def purge_expired(self, *, actor_id: str = "system") -> dict[str, Any]:
        with self._repo() as repository:
            expired = repository.list_expired_documents()
        purged: list[str] = []
        for document in expired:
            with self._repo() as repository:
                deleted = repository.soft_delete_document(
                    document["document_id"],
                    actor_id,
                    reason="retention_expired",
                    internal=True,
                )
            if deleted is None:
                continue
            try:
                self.index.delete_document(document["document_id"])
            except Exception:
                logger.warning("Expired-document index cleanup degraded for %s", document["document_id"], exc_info=True)
            self._remove_document_files(deleted)
            purged.append(document["document_id"])
        if purged:
            self._invalidate_result_cache()
        return {"purged": purged, "count": len(purged), "actor_id": actor_id}

    def deletion_audit(self, user_id: str, *, space_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if space_id:
            self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            return repository.list_deletion_audit(user_id, space_id=space_id, limit=limit)

    def _sync_version_event(self, document: dict[str, Any], version_no: int, chunk: KnowledgeChunk | dict[str, Any]) -> dict[str, Any] | None:
        if not document.get("space_id") or not version_no:
            return None
        chunk_data = (
            chunk
            if isinstance(chunk, dict)
            else {
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "created_at": document.get("observed_at"),
            }
        )
        candidate = build_event_candidate(document, version_no=version_no, chunk=chunk_data)
        if not candidate.get("statement"):
            return None
        with self._repo() as repository:
            entity = repository.upsert_entity(
                entity_id=candidate["entity_id"],
                space_id=candidate["space_id"],
                canonical_name=candidate["entity_name"],
                normalized_key=entity_key(candidate["entity_name"]),
                alias=candidate["entity_alias"],
            )
            candidate["entity_id"] = entity["entity_id"]
            existing = repository.find_event_candidates(
                space_id=candidate["space_id"],
                entity_id=candidate["entity_id"],
                dimension=candidate["dimension"],
            )
            match = next((item for item in existing if event_similarity(item, candidate) >= 0.58), None)
            if match:
                candidate["cluster_key"] = match["cluster_key"]
                candidate["event_id"] = match["event_id"]
            event = repository.upsert_event(candidate)
            updated_event = repository.add_event_evidence(
                event["event_id"],
                {
                    **candidate,
                    "authority_tier": candidate["authority_tier"],
                    "observed_at": candidate.get("occurred_at") or _now(),
                },
            )
            events = repository.list_events(
                str(document.get("user_id") or "default"),
                space_id=candidate["space_id"],
                limit=1000,
            )
            repository.replace_insights(
                candidate["space_id"],
                build_long_term_insights(events, space_id=candidate["space_id"]),
            )
        self._sync_graph_relations(
            document,
            version_no=version_no,
            chunk=chunk_data,
            event=updated_event,
        )
        return updated_event

    def graph(
        self,
        user_id: str,
        *,
        space_id: str | None = None,
        entity_id: str | None = None,
        relation_type: str | None = None,
        temporal_mode: str = "current",
        as_of: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        if space_id:
            self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            return repository.graph_snapshot(
                user_id,
                space_id=space_id,
                entity_id=entity_id,
                relation_type=relation_type,
                temporal_mode=temporal_mode,
                as_of=as_of,
                limit=limit,
            )

    def rebuild_graph(self, user_id: str, space_id: str) -> dict[str, Any]:
        self._resolve_space(user_id, space_id, roles=WRITE_ROLES)
        with self._repo() as repository:
            events = repository.list_events(user_id, space_id=space_id, limit=2000)
            repository.clear_relations(space_id)
        rebuilt = 0
        skipped = 0
        for event in events:
            for evidence in event.get("evidence") or []:
                with self._repo() as repository:
                    document = repository.get_document(str(evidence["document_id"]))
                    if document is None or document.get("deleted_at") or document.get("approval_status") != "approved":
                        skipped += 1
                        continue
                    version_no = int(evidence.get("version_no") or 0)
                    version = next(
                        (item for item in repository.list_versions(document["document_id"]) if int(item["version_no"]) == version_no),
                        None,
                    )
                    if version:
                        fields = (version.get("metadata") or {}).get("document_fields") or {}
                        document = {**document, **fields}
                    chunks = repository.list_chunks(document_id=document["document_id"], active_only=False)
                    chunk = next(
                        (item for item in chunks if item.get("chunk_id") == evidence.get("chunk_id") or (not evidence.get("chunk_id") and int(item.get("version_no") or 0) == version_no)),
                        None,
                    )
                if chunk is None:
                    skipped += 1
                    continue
                version_event = {
                    **event,
                    "statement": chunk.get("text") or event.get("statement") or "",
                    "occurred_at": (document.get("published_at") or document.get("observed_at") or evidence.get("observed_at") or event.get("occurred_at")),
                }
                self._sync_graph_relations(
                    document,
                    version_no=version_no,
                    chunk=chunk,
                    event=version_event,
                )
                rebuilt += 1
        return {
            "space_id": space_id,
            "events_processed": len(events),
            "evidence_rebuilt": rebuilt,
            "evidence_skipped": skipped,
            "graph": self.graph(user_id, space_id=space_id, temporal_mode="all"),
        }

    def review_relation(self, user_id: str, relation_id: str, **values: Any) -> dict[str, Any]:
        """Apply an auditable human decision without deleting automatic evidence."""
        with self._repo() as repository:
            result = repository.review_relation(relation_id, user_id=user_id, **values)
        self._invalidate_result_cache(user_id)
        return result

    def relation_audits(self, user_id: str, *, relation_id: str | None = None, space_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if space_id:
            self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            return repository.list_relation_audits(user_id, relation_id=relation_id, space_id=space_id, limit=limit)

    def create_hypothesis(self, user_id: str, **values: Any) -> dict[str, Any]:
        space = self._resolve_space(user_id, values.get("space_id"), roles=WRITE_ROLES)
        relation_id = values.get("relation_id")
        if relation_id:
            with self._repo() as repository:
                relation = repository.get_relation(str(relation_id), user_id)
            if relation is None or relation.get("space_id") != space["space_id"]:
                raise ValueError("relation_id must belong to the selected knowledge space")
        values = {**values, "space_id": space["space_id"], "created_by": user_id}
        with self._repo() as repository:
            return repository.create_hypothesis(values)

    def list_hypotheses(self, user_id: str, *, space_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if space_id:
            self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            return repository.list_hypotheses(user_id, space_id=space_id, status=status, limit=limit)

    def transition_hypothesis(self, user_id: str, hypothesis_id: str, status: str, *, notes: str | None = None) -> dict[str, Any]:
        with self._repo() as repository:
            return repository.transition_hypothesis(hypothesis_id, user_id, status, notes=notes)

    def _sync_graph_relations(
        self,
        document: dict[str, Any],
        *,
        version_no: int,
        chunk: dict[str, Any],
        event: dict[str, Any],
    ) -> None:
        graph = build_relation_candidates(document, event=event, chunk=chunk)
        with self._repo() as repository:
            resolved_entities: dict[str, str] = {}
            for graph_entity in graph["entities"]:
                resolved = repository.upsert_entity(
                    entity_id=graph_entity["entity_id"],
                    space_id=graph_entity["space_id"],
                    canonical_name=graph_entity["canonical_name"],
                    normalized_key=graph_entity["normalized_key"],
                    alias=graph_entity["alias"],
                    entity_type=graph_entity["entity_type"],
                    metadata=graph_entity.get("metadata") or {},
                )
                resolved_entities[graph_entity["entity_id"]] = resolved["entity_id"]
            for relation in graph["relations"]:
                relation["source_entity_id"] = resolved_entities.get(relation["source_entity_id"], relation["source_entity_id"])
                relation["target_entity_id"] = resolved_entities.get(relation["target_entity_id"], relation["target_entity_id"])
                stored = repository.upsert_relation(relation)
                repository.close_document_relations(
                    document_id=document["document_id"],
                    source_entity_id=stored["source_entity_id"],
                    relation_type=stored["relation_type"],
                    current_relation_id=stored["relation_id"],
                    valid_to=stored.get("valid_from"),
                )
                repository.add_relation_evidence(
                    stored["relation_id"],
                    {
                        "document_id": document["document_id"],
                        "version_no": version_no,
                        "chunk_id": chunk.get("chunk_id"),
                        "event_id": event.get("event_id"),
                        "source_uri": ((document.get("metadata") or {}).get("original_source_url") or document.get("source_uri") or ""),
                        "authority_tier": document.get("authority_tier") or "third_party",
                        "stance": "supporting",
                        "observed_at": event.get("occurred_at") or _now(),
                    },
                )

    def retrieve_relationship_context(
        self,
        state: dict[str, Any],
        evidence_points: list[dict[str, Any]],
        *,
        limit: int = 12,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        plan = plan_graph_retrieval(state)
        if not plan.use_graph:
            return [], plan.to_dict()
        user_id = str(state.get("user_id") or "default")
        query = str(state.get("user_request") or (state.get("analysis_brief") or {}).get("objective") or "")
        query_terms = graph_tokens(query)
        products = {canonical_product(str(value)).casefold() for value in (state.get("target_products") or (state.get("analysis_brief") or {}).get("target_products") or [])}
        point_ids_by_chunk = {str(point.get("knowledge_chunk_id") or ""): str(point.get("id") or "") for point in evidence_points if point.get("knowledge_chunk_id")}
        temporal_mode = "all" if "temporal_relationship_intent" in plan.reasons else "current"
        snapshot = self.graph(user_id, temporal_mode=temporal_mode, limit=1000)
        current_thread = str(state.get("thread_id") or "")
        ranked: list[tuple[float, dict[str, Any]]] = []
        for relation in snapshot["relations"]:
            metadata = relation.get("metadata") or {}
            if current_thread and metadata.get("report_thread_id") == current_thread:
                continue
            source_name = str(relation.get("source_name") or "")
            searchable = " ".join(
                str(relation.get(key) or "")
                for key in (
                    "source_name",
                    "target_name",
                    "relation_type",
                    "dimension",
                    "statement",
                )
            )
            relation_terms = graph_tokens(searchable)
            overlap = len(query_terms.intersection(relation_terms)) / max(1, len(query_terms))
            product_boost = 0.5 if source_name.casefold() in products else 0.0
            score = overlap + product_boost + 0.15 * float(relation.get("confidence") or 0.0)
            if score <= 0.05:
                continue
            evidence_chunk_ids = [str(item.get("chunk_id") or "") for item in relation.get("evidence") or [] if item.get("chunk_id")]
            linked_point_ids = [point_ids_by_chunk[value] for value in evidence_chunk_ids if value in point_ids_by_chunk]
            citation_eligible = bool(relation.get("citation_eligible") and linked_point_ids)
            ranked.append(
                (
                    score,
                    {
                        "id": f"graph-{relation['relation_id']}",
                        "context_role": "relationship_graph",
                        "source_entity": source_name,
                        "source_entity_type": relation.get("source_type"),
                        "relation_type": relation.get("relation_type"),
                        "target_entity": relation.get("target_name"),
                        "target_entity_type": relation.get("target_type"),
                        "dimension": relation.get("dimension"),
                        "statement": relation.get("statement"),
                        "confidence": relation.get("confidence"),
                        "status": relation.get("status"),
                        "valid_from": relation.get("valid_from"),
                        "valid_to": relation.get("valid_to"),
                        "citation_eligible": citation_eligible,
                        "evidence_status": "linked" if linked_point_ids else "navigation_only",
                        "source_data_point_ids": linked_point_ids,
                        "supporting_knowledge_chunk_ids": evidence_chunk_ids,
                        "query_route": plan.route,
                        "usage_policy": ("factual_only_through_linked_source_data_point_ids" if citation_eligible else "planning_only_until_source_evidence_is_retrieved"),
                    },
                )
            )
        context = [item for _, item in sorted(ranked, key=lambda value: value[0], reverse=True)[:limit]]
        return context, {
            **plan.to_dict(),
            "relationship_count": len(context),
            "linked_relationship_count": sum(item["evidence_status"] == "linked" for item in context),
        }

    def list_events(self, user_id: str, *, space_id: str | None = None, entity_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if space_id:
            self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            return repository.list_events(user_id, space_id=space_id, entity_id=entity_id, limit=limit)

    def refresh_insights(self, user_id: str, space_id: str) -> list[dict[str, Any]]:
        self._resolve_space(user_id, space_id, roles=WRITE_ROLES)
        with self._repo() as repository:
            events = repository.list_events(user_id, space_id=space_id, limit=1000)
            insights = build_long_term_insights(events, space_id=space_id)
            repository.replace_insights(space_id, insights)
            return repository.list_insights(user_id, space_id=space_id)

    def list_insights(self, user_id: str, *, space_id: str | None = None) -> list[dict[str, Any]]:
        if space_id:
            self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            return repository.list_insights(user_id, space_id=space_id)

    def insights_for_analysis(
        self,
        state: dict[str, Any],
        retrieved_points: list[dict[str, Any]],
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        user_id = str(state.get("user_id") or "default")
        targets = {entity_key(str(value)) for value in (state.get("target_products") or []) if str(value).strip()}
        point_ids_by_chunk = {str(item.get("knowledge_chunk_id")): str(item.get("id")) for item in retrieved_points if item.get("knowledge_chunk_id") and item.get("id")}
        with self._repo() as repository:
            insights = repository.list_insights(user_id)
            events = repository.list_events(user_id, limit=1000)
        events_by_id = {str(item.get("event_id")): item for item in events}
        output: list[dict[str, Any]] = []
        for insight in insights:
            if targets and entity_key(str(insight.get("entity_name") or "")) not in targets:
                continue
            source_ids: list[str] = []
            for event_id in insight.get("evidence_event_ids") or []:
                event = events_by_id.get(str(event_id)) or {}
                for evidence in event.get("evidence") or []:
                    point_id = point_ids_by_chunk.get(str(evidence.get("chunk_id") or ""))
                    if point_id and point_id not in source_ids:
                        source_ids.append(point_id)
            output.append(
                {
                    "insight_id": insight["insight_id"],
                    "entity_name": insight.get("entity_name") or "",
                    "insight_type": insight.get("insight_type") or "hypothesis",
                    "title": insight.get("title") or "",
                    "summary": insight.get("summary") or "",
                    "confidence": insight.get("confidence") or 0.0,
                    "period_start": insight.get("period_start"),
                    "period_end": insight.get("period_end"),
                    "evidence_event_ids": list(insight.get("evidence_event_ids") or []),
                    "source_data_point_ids": source_ids,
                    "evidence_status": "linked" if source_ids else "context_only",
                    "requires_human_review": bool((insight.get("metadata") or {}).get("requires_human_review")),
                }
            )
            if len(output) >= limit:
                break
        return output

    def list_documents(self, user_id: str, **filters: Any) -> list[dict[str, Any]]:
        with self._repo() as repository:
            return repository.list_documents(user_id, **filters)

    def document_detail(self, document_id: str, user_id: str) -> dict[str, Any] | None:
        with self._repo() as repository:
            document = repository.get_document(document_id, user_id)
            if document is None:
                return None
            chunks = repository.list_chunks(document_id=document_id, active_only=True)
            document["versions"] = repository.list_versions(document_id)
            document["reviews"] = repository.list_document_reviews(document_id, user_id)
            document["chunks"] = [
                {
                    **chunk,
                    "text": chunk["text"][:1200],
                    "contextual_text": chunk["contextual_text"][:1600],
                }
                for chunk in chunks
            ]
            return document

    def get_chunk(self, chunk_id: str, user_id: str) -> dict[str, Any] | None:
        with self._repo() as repository:
            return repository.get_chunks_by_ids([chunk_id], user_id, include_historical=True).get(chunk_id)

    def timeline(
        self,
        user_id: str,
        *,
        product: str | None = None,
        dimension: str | None = None,
        space_id: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        from competition.knowledge_timeline import build_knowledge_timeline

        if space_id:
            self._resolve_space(user_id, space_id)
        with self._repo() as repository:
            events = repository.list_timeline(
                user_id,
                product=product,
                dimension=dimension,
                space_id=space_id,
                limit=limit,
            )
        return build_knowledge_timeline(events)

    def get_job(self, job_id: str, user_id: str) -> dict[str, Any] | None:
        with self._repo() as repository:
            return repository.get_job(job_id, user_id)

    def list_jobs(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._repo() as repository:
            return repository.list_jobs(user_id, limit)

    def status(self, user_id: str) -> dict[str, Any]:
        from competition.knowledge_quota import quota

        with self._repo() as repository:
            database = repository.stats(user_id)
            spaces = repository.list_spaces(user_id)
        index_status = self.index.status()
        return {
            "database": database,
            "spaces": spaces,
            "index": index_status,
            "retrieval": {
                "semantic_index_available": bool(index_status.get("available")),
                "lexical_fallback_enabled": os.getenv("CI_AGENT_RAG_LEXICAL_FALLBACK", "true").lower() in {"1", "true", "yes", "on"},
            },
            "supported_extensions": sorted(SUPPORTED_SUFFIXES),
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "inbox": str(self.inbox),
            "result_cache": {
                "size": len(self._result_cache),
                "capacity": RESULT_CACHE_SIZE,
                "ttl_seconds": RESULT_CACHE_TTL_SECONDS,
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "invalidations": self._cache_invalidations,
            },
            "warmup": dict(self._warmup_status),
            "quota": quota.status(user_id),
        }

    def warmup(self) -> dict[str, Any]:
        self._warmup_status = {"status": "running", "started_at": _now()}
        try:
            retention = self.purge_expired()
            result = self.index.warmup()
            self._warmup_status = {**result, "retention": retention, "finished_at": _now()}
        except Exception as exc:
            self._warmup_status = {
                "status": "degraded",
                "error": str(exc)[:300],
                "finished_at": _now(),
            }
            logger.warning("Local RAG model warmup degraded: %s", exc)
        return dict(self._warmup_status)

    def close(self) -> None:
        self.index.close()


def _chunk_from_row(row: dict[str, Any]) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        version_no=int(row["version_no"]),
        user_id=row["user_id"],
        ordinal=int(row["ordinal"]),
        text=row["text"],
        contextual_text=row["contextual_text"],
        section_path=row.get("section_path") or "",
        page_no=row.get("page_no"),
        token_count=int(row.get("token_count") or 0),
        qdrant_point_id=row["qdrant_point_id"],
        metadata=row.get("metadata") or {},
    )


def _agent_source_type(hit: KnowledgeHit) -> str:
    source = hit.source_type.casefold()
    if source in {"official", "review", "news", "interview", "social", "comparison", "pricing", "stats", "docs", "blog"}:
        return source
    if hit.authority_tier in {"primary", "structured_fact", "change_event"}:
        return "docs"
    if hit.authority_tier == "report":
        return "comparison"
    return "review"


_service: KnowledgeService | None = None
_service_lock = threading.Lock()


def get_knowledge_service() -> KnowledgeService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = KnowledgeService()
    return _service


def close_knowledge_service() -> None:
    """Release the embedded Qdrant client without creating it during shutdown."""
    global _service
    with _service_lock:
        if _service is not None:
            _service.close()
            _service = None
