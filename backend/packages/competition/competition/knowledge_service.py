"""Application service for ingestion, indexing, retrieval, and evidence export."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from competition.db import DEFAULT_DB_PATH
from competition.knowledge_chunking import build_chunks
from competition.knowledge_index import KnowledgeIndex, merge_scores
from competition.knowledge_parser import SUPPORTED_SUFFIXES, DocumentParser
from competition.knowledge_repo import KnowledgeRepository
from competition.knowledge_types import KnowledgeChunk, KnowledgeHit, RetrievalFilters

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_KNOWLEDGE_ROOT = Path(
    os.getenv("CI_AGENT_KNOWLEDGE_ROOT", str(_PROJECT_ROOT / ".ci-agent/knowledge"))
)
MAX_UPLOAD_BYTES = int(os.getenv("CI_AGENT_RAG_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
MIN_RETRIEVAL_SCORE = float(os.getenv("CI_AGENT_RAG_MIN_SCORE", "0.08"))
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._\-\u3400-\u9fff]+")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_filename(value: str) -> str:
    name = Path(value or "document").name.strip().replace("\x00", "")
    safe = _SAFE_FILENAME.sub("_", name).strip("._")
    return safe[:180] or "document.txt"


def _user_segment(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


def _source_key(*, source_uri: str, filename: str, product: str, dimension: str) -> str:
    identity = source_uri.strip() or filename.casefold()
    return hashlib.sha256(f"{identity}|{product.casefold()}|{dimension}".encode()).hexdigest()


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

    def _repo(self) -> KnowledgeRepository:
        return KnowledgeRepository(db_path=self.db_path)

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
        digest = hashlib.sha256(data).hexdigest()
        source_identity = _source_key(
            source_uri=source_uri,
            filename=safe_name,
            product=product,
            dimension=dimension,
        )
        with self._registration_lock, self._repo() as repository:
            existing = repository.find_document_by_source(user_id, source_identity)
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
            version_numbers = [
                int(version.get("version_no") or 0)
                for version in repository.list_versions(document_id)
            ] if existing else []
            version_no = max(
                [int(existing.get("current_version", 0) if existing else 0), *version_numbers]
            ) + 1
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
            }
            values = {
                "document_id": document_id,
                "user_id": user_id,
                "source_key": source_identity,
                **candidate_fields,
                "status": "queued",
                "current_version": 0,
                "content_hash": "",
                "file_path": str(original_path),
            }
            if existing:
                repository.update_document(document_id, status="queued", error=None)
            else:
                repository.create_document(values)
            repository.create_version(
                document_id=document_id,
                version_no=version_no,
                content_hash=digest,
                file_path=str(original_path),
                metadata={"media_type": media_type, "document_fields": candidate_fields},
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
                repository.update_job(job_id, progress=55)
            self.index.replace_document(
                document_for_chunks,
                chunks,
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
                repository.activate_version(document["document_id"], version_no)
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
            stale_point_ids = [str(item["qdrant_point_id"]) for item in stale_chunks if str(item["qdrant_point_id"]) not in new_point_ids]
            try:
                self.index.delete_points(stale_point_ids)
            except Exception:
                # SQLite active-chunk filtering keeps stale points invisible;
                # rebuild can reclaim them later without failing ingestion.
                logger.warning("Stale knowledge point cleanup degraded for %s", document["document_id"], exc_info=True)
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
                    metadata=result,
                )
                completed = repository.get_job(job_id)
                assert completed is not None
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
    ) -> list[KnowledgeHit]:
        started = time.monotonic()
        retrieval_id = f"kret-{uuid.uuid4().hex}"
        effective_filters = filters or RetrievalFilters()
        try:
            recalled = self.index.search_ids(
                query,
                user_id=user_id,
                filters=effective_filters,
                limit=limit,
                candidate_limit=max(24, limit * 3),
            )
            with self._repo() as repository:
                rows_by_id = repository.get_chunks_by_ids([chunk_id for chunk_id, _ in recalled], user_id)
            candidates = [(rows_by_id[chunk_id], score) for chunk_id, score in recalled if chunk_id in rows_by_id]
            rerank_scores = self.index.rerank(query, [row["contextual_text"] for row, _ in candidates])
            ranked = merge_scores(candidates, rerank_scores)
            hits: list[KnowledgeHit] = []
            for row, score in ranked:
                if score < MIN_RETRIEVAL_SCORE:
                    continue
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
                        score=score,
                        retrieval_sources=("dense", "sparse", "reranker"),
                        metadata=row.get("metadata") or {},
                    )
                )
                if len(hits) >= limit:
                    break
            duration_ms = int((time.monotonic() - started) * 1000)
            with self._repo() as repository:
                repository.log_retrieval(
                    retrieval_id=retrieval_id,
                    user_id=user_id,
                    query=query,
                    filters=effective_filters.to_dict(),
                    chunk_ids=[hit.chunk_id for hit in hits],
                    duration_ms=duration_ms,
                )
            return hits
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            with self._repo() as repository:
                repository.log_retrieval(
                    retrieval_id=retrieval_id,
                    user_id=user_id,
                    query=query,
                    filters=effective_filters.to_dict(),
                    chunk_ids=[],
                    duration_ms=duration_ms,
                    status="failed",
                    error=str(exc)[:1000],
                )
            raise

    def retrieve_for_analysis(self, state: dict[str, Any], limit: int = 16) -> list[dict[str, Any]]:
        user_id = str(state.get("user_id") or "default")
        brief = state.get("analysis_brief") or {}
        products = [str(value) for value in state.get("target_products") or brief.get("target_products") or []]
        dimensions = [str(item.get("id")) for item in (brief.get("effective_dimensions") or brief.get("dimensions") or []) if isinstance(item, dict) and item.get("id")] or ["features", "pricing", "users", "market", "technology"]
        time_range = brief.get("time_range") if isinstance(brief.get("time_range"), dict) else {}
        base_query = str(state.get("user_request") or brief.get("objective") or "competitive intelligence")
        pairs = [(product, dimension) for product in products for dimension in dimensions]
        if not pairs:
            pairs = [("", dimension) for dimension in dimensions]
        hits: list[tuple[KnowledgeHit, str]] = []
        per_pair = max(2, min(4, limit // max(1, len(pairs)) + 1))
        for product, dimension in pairs[:20]:
            query = " ".join(value for value in (base_query, product, dimension) if value)
            filters = RetrievalFilters(
                products=(product,) if product else (),
                dimensions=(dimension,),
                market_scope=str(brief.get("market_scope") or ""),
                published_after=time_range.get("start"),
                published_before=time_range.get("end"),
                include_reports=False,
            )
            for hit in self.search(query, user_id=user_id, filters=filters, limit=per_pair):
                hits.append((hit, dimension))
        unique: dict[tuple[str, str], tuple[KnowledgeHit, str]] = {}
        for hit, requested_dimension in sorted(hits, key=lambda value: value[0].score, reverse=True):
            unique.setdefault((hit.chunk_id, hit.dimension or requested_dimension), (hit, requested_dimension))
        points: list[dict[str, Any]] = []
        for hit, requested_dimension in list(unique.values())[:limit]:
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
                }
            )
        return points

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
                    rows = repository.list_chunks(document_id=document["document_id"], active_only=True)
                chunks = [_chunk_from_row(row) for row in rows]
                self.index.replace_document(document, chunks)
                indexed += len(chunks)
            except Exception as exc:
                failed.append({"document_id": document["document_id"], "error": str(exc)[:300]})
        return {"documents": len(documents), "chunks_indexed": indexed, "failures": failed}

    def delete_document(self, document_id: str, user_id: str) -> bool:
        with self._repo() as repository:
            deleted = repository.delete_document(document_id, user_id)
        if deleted is None:
            return False
        try:
            self.index.delete_document(document_id)
        except Exception:
            logger.warning("Knowledge index cleanup degraded for %s", document_id, exc_info=True)
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
        return True

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
            return repository.get_chunks_by_ids([chunk_id], user_id).get(chunk_id)

    def get_job(self, job_id: str, user_id: str) -> dict[str, Any] | None:
        with self._repo() as repository:
            return repository.get_job(job_id, user_id)

    def list_jobs(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._repo() as repository:
            return repository.list_jobs(user_id, limit)

    def status(self, user_id: str) -> dict[str, Any]:
        with self._repo() as repository:
            database = repository.stats(user_id)
        return {
            "database": database,
            "index": self.index.status(),
            "supported_extensions": sorted(SUPPORTED_SUFFIXES),
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "inbox": str(self.inbox),
        }


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
            _service.index.close()
            _service = None
