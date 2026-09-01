"""Local dense/sparse Qdrant index and cross-encoder reranking."""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from competition.knowledge_retrieval import RETRIEVAL_MODES
from competition.knowledge_types import KnowledgeChunk, RetrievalFilters

logger = logging.getLogger(__name__)

# All RAG inference is intentionally local. Disable ONNX telemetry before
# FastEmbed or an ONNX-backed parser initializes its runtime.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "true")

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_EMBEDDING_PATH = Path(os.getenv("CI_AGENT_RAG_EMBEDDING_PATH", str(_PROJECT_ROOT / ".ci-agent/models/embeddings/bge-m3")))
DEFAULT_RERANKER_PATH = Path(os.getenv("CI_AGENT_RAG_RERANKER_PATH", str(_PROJECT_ROOT / ".ci-agent/models/rerankers/bge-reranker-v2-m3")))
DEFAULT_FASTEMBED_PATH = Path(os.getenv("CI_AGENT_RAG_FASTEMBED_PATH", str(_PROJECT_ROOT / ".ci-agent/models/fastembed")))
DEFAULT_QDRANT_PATH = Path(os.getenv("CI_AGENT_RAG_QDRANT_PATH", str(_PROJECT_ROOT / ".ci-agent/knowledge/indexes/qdrant")))
DEFAULT_COLLECTION = os.getenv("CI_AGENT_RAG_COLLECTION", "competition_knowledge_v1")
DEFAULT_QUERY_CACHE_SIZE = max(0, int(os.getenv("CI_AGENT_RAG_QUERY_VECTOR_CACHE_SIZE", "256")))


class KnowledgeUnavailableError(RuntimeError):
    pass


def _contains_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def _lexical_text(text: str) -> str:
    if not _contains_cjk(text):
        return text
    import jieba

    return " ".join(token.strip() for token in jieba.cut(text) if token.strip())


def _timestamp(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return None


class LocalModelProvider:
    """Lazy CPU model loader; importing the API never loads model weights."""

    def __init__(
        self,
        embedding_path: str | Path = DEFAULT_EMBEDDING_PATH,
        reranker_path: str | Path = DEFAULT_RERANKER_PATH,
        sparse_cache_path: str | Path = DEFAULT_FASTEMBED_PATH,
    ) -> None:
        self.embedding_path = Path(embedding_path)
        self.reranker_path = Path(reranker_path)
        self.sparse_cache_path = Path(sparse_cache_path)
        self._dense_model: Any | None = None
        self._reranker: Any | None = None
        self._sparse_model: Any | None = None
        self._lock = threading.RLock()
        self._query_cache_size = DEFAULT_QUERY_CACHE_SIZE
        self._dense_query_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._sparse_query_cache: OrderedDict[str, Any] = OrderedDict()
        self._query_cache_hits = 0
        self._query_cache_misses = 0

    def embedding_dimension(self) -> int:
        """Return the configured dense vector size without loading model weights."""
        loaded = getattr(self, "_configured_embedding_dimension", None)
        if loaded:
            return int(loaded)
        configured = os.getenv("CI_AGENT_RAG_EMBEDDING_DIM", "1024")
        try:
            return max(1, int(configured))
        except ValueError:
            return 1024

    def readiness(self) -> dict[str, Any]:
        return {
            "embedding_model": self.embedding_path.exists(),
            "reranker_model": self.reranker_path.exists(),
            "sparse_model": self.sparse_cache_path.exists(),
            "embedding_path": str(self.embedding_path),
            "reranker_path": str(self.reranker_path),
            "sparse_cache_path": str(self.sparse_cache_path),
            "embedding_dimension": self.embedding_dimension(),
            "loaded": {
                "embedding_model": self._dense_model is not None,
                "reranker_model": self._reranker is not None,
                "sparse_model": self._sparse_model is not None,
            },
            "query_vector_cache": {
                "size": len(self._dense_query_cache),
                "capacity": self._query_cache_size,
                "hits": self._query_cache_hits,
                "misses": self._query_cache_misses,
            },
        }

    def _dense(self) -> Any:
        if self._dense_model is not None:
            return self._dense_model
        with self._lock:
            if self._dense_model is None:
                if not self.embedding_path.exists():
                    raise KnowledgeUnavailableError(f"Embedding model not found: {self.embedding_path}")
                from sentence_transformers import SentenceTransformer

                self._dense_model = SentenceTransformer(str(self.embedding_path), device="cpu", local_files_only=True)
                try:
                    self._configured_embedding_dimension = int(self._dense_model.get_sentence_embedding_dimension())
                except (AttributeError, TypeError, ValueError):
                    self._configured_embedding_dimension = self.embedding_dimension()
        return self._dense_model

    def _cross_encoder(self) -> Any:
        if self._reranker is not None:
            return self._reranker
        with self._lock:
            if self._reranker is None:
                if not self.reranker_path.exists():
                    raise KnowledgeUnavailableError(f"Reranker model not found: {self.reranker_path}")
                from sentence_transformers import CrossEncoder

                self._reranker = CrossEncoder(
                    str(self.reranker_path),
                    device="cpu",
                    max_length=512,
                    local_files_only=True,
                )
        return self._reranker

    def _sparse(self) -> Any:
        if self._sparse_model is not None:
            return self._sparse_model
        with self._lock:
            if self._sparse_model is None:
                from fastembed import SparseTextEmbedding

                self.sparse_cache_path.mkdir(parents=True, exist_ok=True)
                try:
                    self._sparse_model = SparseTextEmbedding(
                        model_name="Qdrant/bm25",
                        cache_dir=str(self.sparse_cache_path),
                        local_files_only=True,
                    )
                except Exception as exc:
                    raise KnowledgeUnavailableError(f"Sparse model unavailable: {exc}") from exc
        return self._sparse_model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._dense().encode(
            texts,
            batch_size=max(1, min(16, len(texts))),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]

    def sparse_embed(self, texts: list[str]) -> list[Any]:
        if not texts:
            return []
        return list(self._sparse().embed([_lexical_text(text) for text in texts]))

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """Embed queries in one batch and reuse vectors for repeated normalized text."""
        if not texts:
            return []
        if self._query_cache_size == 0:
            return self.embed(texts)
        keys = [" ".join(text.split()) for text in texts]
        missing: list[str] = []
        with self._lock:
            for key in dict.fromkeys(keys):
                if key in self._dense_query_cache:
                    self._query_cache_hits += keys.count(key)
                    self._dense_query_cache.move_to_end(key)
                else:
                    self._query_cache_misses += 1
                    missing.append(key)
        if missing:
            vectors = self.embed(missing)
            with self._lock:
                for key, vector in zip(missing, vectors, strict=True):
                    self._dense_query_cache[key] = vector
                    self._dense_query_cache.move_to_end(key)
                    while len(self._dense_query_cache) > self._query_cache_size:
                        self._dense_query_cache.popitem(last=False)
        with self._lock:
            return [list(self._dense_query_cache[key]) for key in keys]

    def sparse_embed_queries(self, texts: list[str]) -> list[Any]:
        if not texts:
            return []
        if self._query_cache_size == 0:
            return self.sparse_embed(texts)
        keys = [" ".join(text.split()) for text in texts]
        missing: list[str] = []
        with self._lock:
            for key in dict.fromkeys(keys):
                if key in self._sparse_query_cache:
                    self._sparse_query_cache.move_to_end(key)
                else:
                    missing.append(key)
        if missing:
            vectors = self.sparse_embed(missing)
            with self._lock:
                for key, vector in zip(missing, vectors, strict=True):
                    self._sparse_query_cache[key] = vector
                    self._sparse_query_cache.move_to_end(key)
                    while len(self._sparse_query_cache) > self._query_cache_size:
                        self._sparse_query_cache.popitem(last=False)
        with self._lock:
            return [self._sparse_query_cache[key] for key in keys]

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        scores = self._cross_encoder().predict(
            [[query, text] for text in texts],
            batch_size=max(1, min(8, len(texts))),
            show_progress_bar=False,
        )
        return [float(value) for value in scores]

    def rerank_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        scores = self._cross_encoder().predict(
            [[query, text] for query, text in pairs],
            batch_size=max(1, min(8, len(pairs))),
            show_progress_bar=False,
        )
        return [float(value) for value in scores]

    def warmup(self) -> dict[str, Any]:
        """Load all local models and execute one minimal inference per model."""
        started = time.perf_counter()
        self.embed_queries(["competitive intelligence model warmup"])
        dense_ms = int((time.perf_counter() - started) * 1000)
        sparse_started = time.perf_counter()
        self.sparse_embed_queries(["competitive intelligence model warmup"])
        sparse_ms = int((time.perf_counter() - sparse_started) * 1000)
        rerank_started = time.perf_counter()
        self.rerank("competitive intelligence", ["competitive intelligence evidence"])
        rerank_ms = int((time.perf_counter() - rerank_started) * 1000)
        return {
            "status": "ready",
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "dense_ms": dense_ms,
            "sparse_ms": sparse_ms,
            "reranker_ms": rerank_ms,
        }


class KnowledgeIndex:
    """Persist named dense and sparse vectors in a local Qdrant collection."""

    def __init__(
        self,
        *,
        path: str | Path = DEFAULT_QDRANT_PATH,
        collection: str = DEFAULT_COLLECTION,
        provider: Any | None = None,
        client: Any | None = None,
    ) -> None:
        self.path = Path(path)
        self.collection = collection
        self.provider = provider or LocalModelProvider()
        self._client = client
        self._lock = threading.RLock()

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is None:
                from qdrant_client import QdrantClient

                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._client = QdrantClient(path=str(self.path))
        return self._client

    def ensure_collection(self) -> None:
        from qdrant_client import models

        client = self._get_client()
        dimension = (
            self.provider.embedding_dimension()
            if hasattr(self.provider, "embedding_dimension")
            else 1024
        )
        with self._lock:
            if client.collection_exists(self.collection):
                return
            client.create_collection(
                collection_name=self.collection,
                vectors_config={
                    "dense": models.VectorParams(size=dimension, distance=models.Distance.COSINE),
                },
                sparse_vectors_config={
                    "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF),
                },
            )

    def replace_document(
        self,
        document: dict[str, Any],
        chunks: list[KnowledgeChunk],
        *,
        stale_point_ids: list[str] | None = None,
        is_current: bool = True,
        valid_from: str | None = None,
        valid_to: str | None = None,
        deactivate_previous: bool = True,
    ) -> None:
        from qdrant_client import models

        self.ensure_collection()
        client = self._get_client()
        validity_start = _timestamp(valid_from) or _timestamp(document.get("observed_at")) or int(time.time())
        validity_end = _timestamp(valid_to)
        dense_vectors = self.provider.embed([chunk.contextual_text for chunk in chunks])
        sparse_vectors = self.provider.sparse_embed([chunk.contextual_text for chunk in chunks])
        points: list[Any] = []
        for chunk, dense, sparse in zip(chunks, dense_vectors, sparse_vectors, strict=True):
            payload = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "version_no": chunk.version_no,
                "user_id": chunk.user_id,
                "space_id": document.get("space_id", ""),
                "approval_status": document.get("approval_status", "approved"),
                "active": is_current,
                "is_current": is_current,
                "valid_from_ts": validity_start,
                "valid_to_ts": validity_end,
                "product": document.get("product", ""),
                "product_key": str(document.get("product", "")).casefold(),
                "dimension": document.get("dimension", ""),
                "market_scope": document.get("market_scope", "Global / unspecified"),
                "source_type": document.get("source_type", "upload"),
                "authority_tier": document.get("authority_tier", "third_party"),
                "published_ts": _timestamp(document.get("published_at")),
                "observed_ts": _timestamp(document.get("observed_at")),
            }
            points.append(
                models.PointStruct(
                    id=chunk.qdrant_point_id,
                    vector={
                        "dense": dense,
                        "sparse": models.SparseVector(
                            indices=[int(value) for value in sparse.indices.tolist()],
                            values=[float(value) for value in sparse.values.tolist()],
                        ),
                    },
                    payload=payload,
                )
            )
        with self._lock:
            for start in range(0, len(points), 64):
                client.upsert(
                    collection_name=self.collection,
                    points=points[start : start + 64],
                    wait=True,
                )
            if deactivate_previous:
                client.set_payload(
                    collection_name=self.collection,
                    payload={
                        "active": False,
                        "is_current": False,
                        "valid_to_ts": validity_start,
                    },
                    points=models.FilterSelector(
                        filter=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="document_id",
                                    match=models.MatchValue(value=document.get("document_id") or chunks[0].document_id),
                                ),
                                models.FieldCondition(
                                    key="active",
                                    match=models.MatchValue(value=True),
                                ),
                            ],
                            must_not=[
                                models.FieldCondition(
                                    key="version_no",
                                    match=models.MatchValue(value=chunks[0].version_no),
                                )
                            ],
                        )
                    ),
                    wait=True,
                )
            if stale_point_ids:
                new_ids = {chunk.qdrant_point_id for chunk in chunks}
                stale = [value for value in stale_point_ids if value not in new_ids]
                if stale:
                    client.delete(
                        collection_name=self.collection,
                        points_selector=models.PointIdsList(points=stale),
                        wait=True,
                    )

    def delete_document(self, document_id: str, *, ensure: bool = True) -> None:
        from qdrant_client import models

        client = self._get_client()
        if ensure and not client.collection_exists(self.collection):
            return
        if not client.collection_exists(self.collection):
            return
        with self._lock:
            client.delete(
                collection_name=self.collection,
                points_selector=models.FilterSelector(filter=models.Filter(must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))])),
                wait=True,
            )

    def _filter(self, user_id: str, filters: RetrievalFilters) -> Any:
        from qdrant_client import models

        must: list[Any] = []
        if filters.space_ids:
            must.append(
                models.Filter(
                    should=[
                        models.FieldCondition(key="space_id", match=models.MatchAny(any=list(filters.space_ids))),
                        models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
                    ]
                )
            )
        else:
            must.append(models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)))
        should: list[Any] = []
        temporal_mode = filters.temporal_mode if filters.temporal_mode in {"current", "historical", "all", "as_of"} else "current"
        if temporal_mode == "current":
            # ``active`` keeps pre-temporal indexes readable until their next rebuild.
            must.append(models.FieldCondition(key="active", match=models.MatchValue(value=True)))
        elif temporal_mode == "historical":
            must.append(models.FieldCondition(key="active", match=models.MatchValue(value=False)))
        elif temporal_mode == "as_of":
            as_of = _timestamp(filters.as_of)
            if as_of is not None:
                must.append(models.FieldCondition(key="valid_from_ts", range=models.Range(lte=as_of)))
                should.extend(
                    [
                        models.FieldCondition(key="active", match=models.MatchValue(value=True)),
                        models.FieldCondition(key="valid_to_ts", range=models.Range(gte=as_of)),
                    ]
                )
        if filters.products:
            must.append(
                models.FieldCondition(
                    key="product_key",
                    match=models.MatchAny(any=[value.casefold() for value in filters.products] + [""]),
                )
            )
        if filters.dimensions:
            must.append(models.FieldCondition(key="dimension", match=models.MatchAny(any=list(filters.dimensions) + [""])))
        if filters.market_scope:
            must.append(
                models.FieldCondition(
                    key="market_scope",
                    match=models.MatchAny(any=[filters.market_scope, "Global / unspecified"]),
                )
            )
        if filters.source_types:
            must.append(models.FieldCondition(key="source_type", match=models.MatchAny(any=list(filters.source_types))))
        if filters.authority_tiers:
            must.append(models.FieldCondition(key="authority_tier", match=models.MatchAny(any=list(filters.authority_tiers))))
        must_not: list[Any] = []
        if not filters.include_reports:
            must_not.append(models.FieldCondition(key="authority_tier", match=models.MatchValue(value="report")))
        time_range: dict[str, int] = {}
        after = _timestamp(filters.published_after)
        before = _timestamp(filters.published_before)
        if after is not None:
            time_range["gte"] = after
        if before is not None:
            time_range["lte"] = before
        if time_range:
            # A missing publication date means freshness is unknown, not that
            # the evidence is outside the requested range. Keep those records
            # available so the quality layer can surface the uncertainty.
            must.append(
                models.Filter(
                    should=[
                        models.FieldCondition(key="published_ts", range=models.Range(**time_range)),
                        models.IsEmptyCondition(is_empty=models.PayloadField(key="published_ts")),
                    ]
                )
            )
        return models.Filter(must=must, must_not=must_not or None, should=should or None)

    def search_ids(
        self,
        query: str,
        *,
        user_id: str,
        filters: RetrievalFilters,
        limit: int = 12,
        candidate_limit: int = 40,
        retrieval_mode: str = "hybrid",
    ) -> list[tuple[str, float]]:
        return self.search_many_ids(
            [(query, user_id, filters, limit, candidate_limit)],
            retrieval_mode=retrieval_mode,
        )[0]

    def search_many_ids(
        self,
        requests: list[tuple[str, str, RetrievalFilters, int, int]],
        *,
        retrieval_mode: str = "hybrid",
    ) -> list[list[tuple[str, float]]]:
        """Batch query encoding while retaining request-specific Qdrant filters."""
        from qdrant_client import models

        retrieval_mode = retrieval_mode if retrieval_mode in RETRIEVAL_MODES else "hybrid"

        if not requests:
            return []
        queries = [query.strip() for query, *_ in requests]
        nonempty = [query for query in queries if query]
        if not nonempty:
            return [[] for _ in requests]
        self.ensure_collection()
        dense_vectors = self.provider.embed_queries(queries) if hasattr(self.provider, "embed_queries") else self.provider.embed(queries)
        sparse_vectors = self.provider.sparse_embed_queries(queries) if hasattr(self.provider, "sparse_embed_queries") else self.provider.sparse_embed(queries)
        output: list[list[tuple[str, float]]] = []
        for dense, sparse, (_, user_id, filters, limit, candidate_limit) in zip(dense_vectors, sparse_vectors, requests, strict=True):
            query_filter = self._filter(user_id, filters)
            sparse_query = models.SparseVector(
                indices=[int(value) for value in sparse.indices.tolist()],
                values=[float(value) for value in sparse.values.tolist()],
            )
            query_limit = max(limit, candidate_limit)
            if retrieval_mode == "dense":
                result = self._get_client().query_points(
                    collection_name=self.collection,
                    query=dense,
                    using="dense",
                    query_filter=query_filter,
                    limit=query_limit,
                    with_payload=True,
                )
            elif retrieval_mode == "sparse":
                result = self._get_client().query_points(
                    collection_name=self.collection,
                    query=sparse_query,
                    using="sparse",
                    query_filter=query_filter,
                    limit=query_limit,
                    with_payload=True,
                )
            else:
                result = self._get_client().query_points(
                    collection_name=self.collection,
                    prefetch=[
                        models.Prefetch(query=dense, using="dense", filter=query_filter, limit=query_limit),
                        models.Prefetch(query=sparse_query, using="sparse", filter=query_filter, limit=query_limit),
                    ],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    limit=query_limit,
                    with_payload=True,
                )
            output.append([(str(point.payload.get("chunk_id")), float(point.score)) for point in result.points if point.payload and point.payload.get("chunk_id")])
        return output

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        scores = self.provider.rerank(query, texts)
        return [score if 0.0 <= score <= 1.0 else 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, score)))) for score in scores]

    def rerank_many(self, groups: list[tuple[str, list[str]]]) -> list[list[float]]:
        pairs = [(query, text) for query, texts in groups for text in texts]
        if hasattr(self.provider, "rerank_pairs"):
            raw = self.provider.rerank_pairs(pairs)
        else:
            raw = [score for query, texts in groups for score in self.provider.rerank(query, texts)]
        normalized = [score if 0.0 <= score <= 1.0 else 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, score)))) for score in raw]
        output: list[list[float]] = []
        offset = 0
        for _, texts in groups:
            output.append(normalized[offset : offset + len(texts)])
            offset += len(texts)
        return output

    def warmup(self) -> dict[str, Any]:
        return self.provider.warmup() if hasattr(self.provider, "warmup") else {"status": "unsupported"}

    def delete_points(self, point_ids: list[str]) -> None:
        if not point_ids:
            return
        from qdrant_client import models

        client = self._get_client()
        if not client.collection_exists(self.collection):
            return
        with self._lock:
            client.delete(
                collection_name=self.collection,
                points_selector=models.PointIdsList(points=point_ids),
                wait=True,
            )

    def delete_user(self, user_id: str) -> None:
        from qdrant_client import models

        client = self._get_client()
        if not client.collection_exists(self.collection):
            return
        with self._lock:
            client.delete(
                collection_name=self.collection,
                points_selector=models.FilterSelector(filter=models.Filter(must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))])),
                wait=True,
            )

    def status(self) -> dict[str, Any]:
        model_status = self.provider.readiness() if hasattr(self.provider, "readiness") else {}
        try:
            client = self._get_client()
            exists = client.collection_exists(self.collection)
            points = int(client.get_collection(self.collection).points_count or 0) if exists else 0
            return {
                "available": all(model_status.get(key, True) for key in ("embedding_model", "reranker_model", "sparse_model")),
                "collection": self.collection,
                "collection_exists": exists,
                "points": points,
                **model_status,
            }
        except Exception as exc:
            return {"available": False, "collection": self.collection, "error": str(exc), **model_status}

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            self._client.close()


def merge_scores(
    candidates: Iterable[tuple[dict[str, Any], float]],
    rerank_scores: list[float],
) -> list[tuple[dict[str, Any], float]]:
    """Blend semantic relevance, RRF recall, source authority, and freshness."""
    from competition.knowledge_types import AUTHORITY_PRIORS

    rows = list(candidates)
    output: list[tuple[dict[str, Any], float]] = []
    for (row, recall_score), rerank_score in zip(rows, rerank_scores, strict=True):
        authority = AUTHORITY_PRIORS.get(str(row.get("authority_tier")), 0.5)
        final = 0.72 * max(0.0, min(1.0, rerank_score)) + 0.16 * max(0.0, min(1.0, recall_score)) + 0.12 * authority
        output.append((row, round(final, 6)))
    return sorted(output, key=lambda item: item[1], reverse=True)
