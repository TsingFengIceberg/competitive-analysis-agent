from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from competition.knowledge_chunking import build_chunks
from competition.knowledge_eval import (
    EvaluationThresholds,
    check_thresholds,
    compute_planning_metrics,
    compute_retrieval_metrics,
    compute_verification_metrics,
)
from competition.knowledge_parser import DocumentParser
from competition.knowledge_query import build_analysis_queries, canonical_product, normalize_query_text
from competition.knowledge_service import KnowledgeService
from competition.knowledge_types import KnowledgeChunk, ParsedBlock, ParsedDocument, RetrievalFilters


class FakeKnowledgeIndex:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[dict[str, Any], Any]] = {}
        self.closed = False
        self.search_calls = 0
        self.batch_search_calls = 0
        self.batch_rerank_calls = 0

    def replace_document(
        self,
        document,
        chunks,
        *,
        stale_point_ids=None,
        is_current=True,
        valid_from=None,
        valid_to=None,
        deactivate_previous=True,
    ) -> None:
        del stale_point_ids
        if deactivate_previous:
            for previous, _ in self.rows.values():
                if previous["document_id"] == document["document_id"] and previous.get("_is_current"):
                    previous["_is_current"] = False
                    previous["_valid_to"] = valid_from
        for chunk in chunks:
            stored = {
                **document,
                "_is_current": is_current,
                "_valid_from": valid_from,
                "_valid_to": valid_to,
            }
            self.rows[chunk.chunk_id] = (stored, chunk)

    def search_ids(self, query, *, user_id, filters, limit=12, candidate_limit=40):
        del candidate_limit
        self.search_calls += 1
        query_terms = set(query.casefold().split())
        matches = []
        for chunk_id, (document, chunk) in self.rows.items():
            if filters.space_ids:
                if document.get("space_id") not in filters.space_ids:
                    continue
            elif chunk.user_id != user_id:
                continue
            if filters.temporal_mode == "current" and not document.get("_is_current", True):
                continue
            if filters.temporal_mode == "historical" and document.get("_is_current", True):
                continue
            if filters.products and document.get("product", "").casefold() not in {
                "",
                *(value.casefold() for value in filters.products),
            }:
                continue
            if filters.dimensions and document.get("dimension", "") not in {"", *filters.dimensions}:
                continue
            if not filters.include_reports and document.get("authority_tier") == "report":
                continue
            overlap = len(query_terms.intersection(chunk.contextual_text.casefold().split()))
            matches.append((chunk_id, 0.6 + min(overlap, 3) * 0.1))
        return matches[:limit]

    def search_many_ids(self, requests):
        self.batch_search_calls += 1
        return [
            self.search_ids(
                query,
                user_id=user_id,
                filters=filters,
                limit=limit,
                candidate_limit=candidate_limit,
            )
            for query, user_id, filters, limit, candidate_limit in requests
        ]

    def rerank(self, query, texts):
        del query
        return [0.95 - index * 0.05 for index, _ in enumerate(texts)]

    def rerank_many(self, groups):
        self.batch_rerank_calls += 1
        return [self.rerank(query, texts) for query, texts in groups]

    def delete_document(self, document_id, *, ensure=True):
        del ensure
        for chunk_id in [key for key, (doc, _) in self.rows.items() if doc["document_id"] == document_id]:
            self.rows.pop(chunk_id)

    def delete_points(self, point_ids):
        point_ids = set(point_ids)
        for chunk_id in [key for key, (_, chunk) in self.rows.items() if chunk.qdrant_point_id in point_ids]:
            self.rows.pop(chunk_id)

    def delete_user(self, user_id):
        for chunk_id in [key for key, (_, chunk) in self.rows.items() if chunk.user_id == user_id]:
            self.rows.pop(chunk_id)

    def status(self):
        return {"available": True, "collection_exists": True, "points": len(self.rows)}

    def close(self):
        self.closed = True

    def warmup(self):
        return {"status": "ready", "duration_ms": 1}


def build_service(tmp_path: Path) -> KnowledgeService:
    return KnowledgeService(
        db_path=tmp_path / "competition.db",
        root=tmp_path / "knowledge",
        index=FakeKnowledgeIndex(),
    )


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("notes.md", b"# Pricing\n\nPro costs $20", "Pricing"),
        ("facts.txt", "中文竞品资料".encode(), "中文竞品资料"),
        ("page.html", b"<title>Cursor</title><h1>Features</h1><p>Fast completion</p>", "Fast completion"),
        ("facts.csv", b"product,price\nCursor,20", "Cursor"),
        ("facts.json", json.dumps({"product": "Codex", "price": 20}).encode(), "Codex"),
    ],
)
def test_lightweight_document_parsers(tmp_path: Path, filename: str, content: bytes, expected: str):
    path = tmp_path / filename
    path.write_bytes(content)
    parsed = DocumentParser().parse(path)
    assert expected in parsed.markdown
    assert parsed.blocks


def test_contextual_chunking_is_deterministic_and_preserves_scope():
    parsed = ParsedDocument(
        title="Pricing report",
        markdown="# Plans\n" + "Enterprise details. " * 80,
        blocks=[ParsedBlock(text="Enterprise details. " * 80, section_path="Plans", page_no=3)],
        media_type="text/markdown",
    )
    document = {
        "document_id": "kdoc-1",
        "user_id": "user-a",
        "title": "Pricing report",
        "product": "Cursor",
        "dimension": "pricing",
        "market_scope": "Global / unspecified",
    }
    first = build_chunks(parsed, document=document, version_no=1, max_chars=300, overlap_chars=40)
    second = build_chunks(parsed, document=document, version_no=1, max_chars=300, overlap_chars=40)
    assert len(first) > 1
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert all(chunk.page_no == 3 and "Product: Cursor" in chunk.contextual_text for chunk in first)


def test_ingestion_versioning_retrieval_and_user_isolation(tmp_path: Path):
    service = build_service(tmp_path)
    first = service.register_bytes(
        user_id="user-a",
        filename="cursor.md",
        data=b"# Pricing\n\nCursor Pro costs $20 monthly.",
        product="Cursor",
        dimension="pricing",
        authority_tier="primary",
    )
    completed = service.process_job(first["job"]["job_id"])
    assert completed["status"] == "completed"
    detail = service.document_detail(first["document"]["document_id"], "user-a")
    assert detail is not None
    assert detail["current_version"] == 1
    assert detail["status"] == "indexed"
    assert detail["chunks"]

    unchanged = service.register_bytes(
        user_id="user-a",
        filename="cursor.md",
        data=b"# Pricing\n\nCursor Pro costs $20 monthly.",
        product="Cursor",
        dimension="pricing",
        authority_tier="primary",
    )
    assert unchanged["unchanged"] is True
    assert unchanged["job"]["status"] == "completed"

    updated = service.register_bytes(
        user_id="user-a",
        filename="cursor.md",
        data=b"# Pricing\n\nCursor Pro now costs $25 monthly.",
        title="Updated pricing",
        product="Cursor",
        dimension="pricing",
        authority_tier="third_party",
        metadata={"approval": "accepted-v2"},
    )
    service.process_job(updated["job"]["job_id"])
    detail = service.document_detail(first["document"]["document_id"], "user-a")
    assert detail is not None and detail["current_version"] == 2
    assert len(detail["versions"]) == 2
    assert detail["title"] == "Updated pricing"
    assert detail["authority_tier"] == "third_party"
    assert detail["metadata"] == {"approval": "accepted-v2"}
    assert service.document_detail(first["document"]["document_id"], "user-b") is None

    hits = service.search(
        "Cursor pricing",
        user_id="user-a",
        filters=RetrievalFilters(products=("Cursor",), dimensions=("pricing",)),
    )
    assert hits and "$25" in hits[0].text
    assert service.search("Cursor", user_id="user-b") == []

    historical = service.search(
        "Cursor pricing",
        user_id="user-a",
        filters=RetrievalFilters(
            products=("Cursor",),
            dimensions=("pricing",),
            temporal_mode="historical",
        ),
    )
    assert historical and "$20" in historical[0].text
    assert historical[0].temporal_status == "historical"
    old_chunk = service.get_chunk(historical[0].chunk_id, "user-a")
    assert old_chunk is not None and old_chunk["temporal_status"] == "historical"
    timeline = service.timeline("user-a", product="Cursor", dimension="pricing")
    assert timeline["summary"]["event_count"] == 2
    assert timeline["summary"]["historical_count"] == 1
    assert [event["version_no"] for event in timeline["events"]] == [2, 1]


def test_timeline_detects_conflicts_outside_the_first_chunk(tmp_path: Path):
    service = build_service(tmp_path)
    sources = [
        ("official.md", "primary", b"# Pricing\n\nDisclaimer without a number.\n\n## Current price\n\nCursor Pro costs $20 monthly."),
        ("review.md", "third_party", b"# Pricing\n\nIndependent summary without a number.\n\n## Reported price\n\nCursor Pro costs $25 monthly."),
    ]
    for filename, authority, content in sources:
        registered = service.register_bytes(
            user_id="user-a",
            filename=filename,
            data=content,
            product="Cursor",
            dimension="pricing",
            authority_tier=authority,
        )
        assert service.process_job(registered["job"]["job_id"])["status"] == "completed"

    timeline = service.timeline("user-a", product="Cursor", dimension="pricing")

    assert timeline["summary"]["conflict_count"] == 1
    assert timeline["conflicts"][0]["resolution"]["strategy"] == "higher_authority"
    assert all("comparison_text" not in event for event in timeline["events"])


def test_failed_replacement_keeps_previous_version_active(tmp_path: Path):
    service = build_service(tmp_path)
    first = service.register_bytes(
        user_id="user-a",
        filename="cursor.md",
        data=b"# Pricing\n\nCursor Pro costs $20 monthly.",
        title="Current pricing",
        product="Cursor",
        dimension="pricing",
        authority_tier="primary",
        metadata={"approval": "accepted"},
    )
    assert service.process_job(first["job"]["job_id"])["status"] == "completed"

    replacement = service.register_bytes(
        user_id="user-a",
        filename="cursor.md",
        data=b"# Pricing\n\nCursor Pro costs $99 monthly.",
        title="Unverified replacement",
        product="Cursor",
        dimension="pricing",
        authority_tier="third_party",
        metadata={"approval": "pending"},
    )

    def fail_index(*args, **kwargs):
        raise RuntimeError("synthetic index failure")

    service.index.replace_document = fail_index
    failed = service.process_job(replacement["job"]["job_id"])
    assert failed["status"] == "failed"
    detail = service.document_detail(first["document"]["document_id"], "user-a")
    assert detail is not None
    assert detail["current_version"] == 1
    assert detail["status"] == "partial"
    assert detail["title"] == "Current pricing"
    assert detail["authority_tier"] == "primary"
    assert detail["metadata"] == {"approval": "accepted"}
    assert "$20" in detail["chunks"][0]["text"]
    assert detail["versions"][0]["status"] == "failed"
    assert detail["versions"][1]["superseded_at"] is None

    third = service.register_bytes(
        user_id="user-a",
        filename="cursor.md",
        data=b"# Pricing\n\nCursor Pro costs $30 monthly.",
        product="Cursor",
        dimension="pricing",
    )
    assert third["job"]["metadata"]["version_no"] == 3


def test_observation_history_import_preserves_original_validity_and_is_idempotent(tmp_path: Path):
    service = build_service(tmp_path)
    item = {
        "item_key": "fact-1",
        "product": "Cursor",
        "dimension": "pricing",
        "label": "Pro price",
        "value": "$25",
        "source_url": "https://cursor.com/pricing",
        "scope": "Global",
        "versions": [
            {
                "version": 1,
                "content_hash": "fact-v1",
                "observed_at": "2026-07-01T00:00:00+00:00",
                "payload": {
                    "product": "Cursor",
                    "dimension": "pricing",
                    "label": "Pro price",
                    "value": "$20",
                    "source_url": "https://cursor.com/pricing",
                    "source_type": "official",
                    "scope": "Global",
                },
            },
            {
                "version": 2,
                "content_hash": "fact-v2",
                "observed_at": "2026-08-01T00:00:00+00:00",
                "payload": {
                    "product": "Cursor",
                    "dimension": "pricing",
                    "label": "Pro price",
                    "value": "$25",
                    "source_url": "https://cursor.com/pricing",
                    "source_type": "official",
                    "scope": "Global",
                },
            },
        ],
    }
    queued = service.queue_intelligence_history(
        user_id="user-a",
        item=item,
        title="Observed pricing",
        authority_tier="structured_fact",
    )
    completed = service.process_intelligence_history_job(queued["job_id"])
    assert completed["status"] == "completed"
    assert completed["metadata"]["versions_imported"] == 2
    timeline = service.timeline("user-a")
    assert [event["valid_from"] for event in reversed(timeline["events"])] == [
        "2026-07-01T00:00:00+00:00",
        "2026-08-01T00:00:00+00:00",
    ]
    assert timeline["events"][1]["valid_to"] == "2026-08-01T00:00:00+00:00"

    repeated = service.queue_intelligence_history(
        user_id="user-a",
        item=item,
        title="Observed pricing",
        authority_tier="structured_fact",
    )
    repeated_result = service.process_intelligence_history_job(repeated["job_id"])
    assert repeated_result["metadata"]["versions_imported"] == 0
    assert repeated_result["metadata"]["versions_skipped"] == 2
    assert service.timeline("user-a")["summary"]["event_count"] == 2


def test_inbox_rejects_path_traversal(tmp_path: Path):
    service = build_service(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    with pytest.raises(ValueError, match="inside the knowledge inbox"):
        service.register_inbox_path(user_id="default", relative_path="../../secret.txt")


def test_knowledge_api_contract_is_registered():
    from app.competition_router import router

    contracts = {(route.path, method) for route in router.routes for method in route.methods or []}
    assert ("/api/competition/knowledge/upload", "POST") in contracts
    assert ("/api/competition/knowledge/search", "POST") in contracts
    assert ("/api/competition/knowledge/timeline", "GET") in contracts
    assert ("/api/competition/knowledge/documents/{document_id}", "GET") in contracts
    assert ("/api/competition/knowledge/documents/{document_id}", "DELETE") in contracts
    assert ("/api/competition/knowledge/chunks/{chunk_id}", "GET") in contracts


def test_local_knowledge_citation_is_valid_and_traceable():
    from competition.nodes.reviewer import check_url_reachability
    from competition.nodes.writer import _build_traceability_map

    point = {
        "id": "rag-kch-1",
        "product": "Cursor",
        "category": "pricing",
        "label": "Enterprise price",
        "value": "$40",
        "confidence": 0.9,
        "source_url": "knowledge://kdoc-1/kch-1",
        "source_type": "docs",
        "collected_at": "2026-08-26T00:00:00+00:00",
        "knowledge_document_id": "kdoc-1",
        "knowledge_chunk_id": "kch-1",
        "source_authority": "primary",
        "source_title": "Pricing guide",
        "section_path": "Plans > Enterprise",
        "page_no": 4,
        "retrieval_score": 0.88,
    }
    assert check_url_reachability([point]) == []
    citation = _build_traceability_map([point])["1"]
    assert citation["is_local_knowledge"] is True
    assert citation["knowledge_chunk_id"] == "kch-1"
    assert citation["page_no"] == 4


def test_hybrid_qdrant_recall_respects_user_and_scope_filters():
    from qdrant_client import QdrantClient

    from competition.knowledge_index import KnowledgeIndex

    class Values(list):
        def tolist(self):
            return list(self)

    class SparseVector:
        def __init__(self, index: int):
            self.indices = Values([index])
            self.values = Values([1.0])

    class Provider:
        @staticmethod
        def embed(texts):
            vectors = []
            for text in texts:
                vector = [0.0] * 1024
                vector[0 if "cursor" in text.casefold() else 1] = 1.0
                vectors.append(vector)
            return vectors

        @staticmethod
        def sparse_embed(texts):
            return [SparseVector(7 if "cursor" in text.casefold() else 9) for text in texts]

        @staticmethod
        def rerank(query, texts):
            return [0.95 if "cursor" in query.casefold() and "cursor" in text.casefold() else 0.2 for text in texts]

        @staticmethod
        def readiness():
            return {"embedding_model": True, "reranker_model": True, "sparse_model": True}

    client = QdrantClient(location=":memory:")
    index = KnowledgeIndex(client=client, provider=Provider(), collection="knowledge-test")

    def chunk(chunk_id: str, user_id: str, text: str, version_no: int = 1) -> KnowledgeChunk:
        import uuid

        return KnowledgeChunk(
            chunk_id=chunk_id,
            document_id=f"doc-{chunk_id}",
            version_no=version_no,
            user_id=user_id,
            ordinal=0,
            text=text,
            contextual_text=text,
            section_path="Overview",
            page_no=None,
            token_count=10,
            qdrant_point_id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id)),
        )

    index.replace_document(
        {
            "document_id": "doc-cursor",
            "product": "Cursor",
            "dimension": "pricing",
            "authority_tier": "primary",
        },
        [chunk("cursor", "user-a", "Cursor pricing is twenty dollars")],
        valid_from="2026-07-01T00:00:00+00:00",
    )
    index.replace_document(
        {
            "document_id": "doc-codex",
            "product": "Codex",
            "dimension": "features",
            "authority_tier": "primary",
        },
        [chunk("codex", "user-a", "Codex supports cloud tasks")],
    )
    index.replace_document(
        {
            "document_id": "doc-private",
            "product": "Cursor",
            "dimension": "pricing",
            "authority_tier": "primary",
        },
        [chunk("private", "user-b", "Cursor private enterprise price")],
    )
    results = index.search_ids(
        "Cursor pricing",
        user_id="user-a",
        filters=RetrievalFilters(products=("Cursor",), dimensions=("pricing",)),
    )
    assert [chunk_id for chunk_id, _ in results] == ["cursor"]

    index.replace_document(
        {
            "document_id": "doc-cursor",
            "product": "Cursor",
            "dimension": "pricing",
            "authority_tier": "primary",
        },
        [chunk("cursor-v2", "user-a", "Cursor pricing is now twenty five dollars", 2)],
        valid_from="2026-08-27T00:00:00+00:00",
    )
    current = index.search_ids(
        "Cursor pricing",
        user_id="user-a",
        filters=RetrievalFilters(products=("Cursor",), dimensions=("pricing",)),
    )
    historical = index.search_ids(
        "Cursor pricing",
        user_id="user-a",
        filters=RetrievalFilters(
            products=("Cursor",),
            dimensions=("pricing",),
            temporal_mode="historical",
        ),
    )
    as_of = index.search_ids(
        "Cursor pricing",
        user_id="user-a",
        filters=RetrievalFilters(
            products=("Cursor",),
            dimensions=("pricing",),
            temporal_mode="as_of",
            as_of="2026-08-01T00:00:00+00:00",
        ),
    )
    index.replace_document(
        {
            "document_id": "doc-cursor-old-source",
            "product": "Cursor",
            "dimension": "pricing",
            "authority_tier": "primary",
            "published_at": "2025-01-01T00:00:00+00:00",
        },
        [chunk("cursor-old-source", "user-a", "Cursor old pricing source")],
    )
    recent = index.search_ids(
        "Cursor pricing",
        user_id="user-a",
        filters=RetrievalFilters(
            products=("Cursor",),
            dimensions=("pricing",),
            published_after="2026-01-01T00:00:00+00:00",
        ),
    )
    assert [chunk_id for chunk_id, _ in current] == ["cursor-v2"]
    assert [chunk_id for chunk_id, _ in historical] == ["cursor"]
    assert [chunk_id for chunk_id, _ in as_of] == ["cursor"]
    assert [chunk_id for chunk_id, _ in recent] == ["cursor-v2"]
    index.close()


def test_collector_merges_local_knowledge_without_repersisting_it(monkeypatch: pytest.MonkeyPatch):
    from competition.nodes import collector

    local = {
        "id": "rag-kch-1",
        "product": "Cursor",
        "category": "features",
        "label": "Local feature",
        "value": "Agent mode",
        "confidence": 0.9,
        "source_url": "knowledge://kdoc-1/kch-1",
        "source_type": "docs",
        "collected_at": "2026-08-26T00:00:00+00:00",
        "knowledge_document_id": "kdoc-1",
        "knowledge_chunk_id": "kch-1",
    }
    persisted: list[list] = []
    monkeypatch.setattr(
        collector,
        "_retrieve_local_knowledge",
        lambda state: ([local], {"status": "available", "hit_count": 1}, [], [], []),
    )
    monkeypatch.setattr(collector, "_run_searches", lambda state: "")
    monkeypatch.setattr(collector, "_execute_collector", lambda task, state: ("[]", 0))
    monkeypatch.setattr(collector, "_get_search_info", lambda: {})
    monkeypatch.setattr(
        collector,
        "_persist_intelligence_items",
        lambda state, points: persisted.append(points) or {"inserted": 0},
    )
    result = collector.collector_node(
        {
            "user_id": "user-a",
            "user_request": "Compare Cursor",
            "target_products": ["Cursor"],
            "analysis_brief": {
                "effective_dimensions": [{"id": "features", "label": "Features"}],
            },
        }
    )
    assert result["collected_data"][0]["knowledge_chunk_id"] == "kch-1"
    assert result["analysis_memory"] == []
    assert result["relationship_context"] == []
    assert result["long_term_insights"] == []
    assert result["collection_summary"]["rag_retrieval"]["status"] == "available"
    assert persisted == [[]]


def test_collector_keeps_historical_report_memory_separate_from_evidence(monkeypatch: pytest.MonkeyPatch):
    from competition.nodes import collector

    memory = {
        "id": "memory-report-1",
        "context_role": "historical_analysis_memory",
        "citation_eligible": False,
        "title": "Prior comparison",
        "summary": "Recheck enterprise deployment assumptions.",
        "usage_policy": "planning_only_not_factual_evidence",
    }
    monkeypatch.setattr(
        collector,
        "_retrieve_local_knowledge",
        lambda state: (
            [],
            {
                "status": "empty",
                "hit_count": 0,
                "analysis_memory_count": 1,
                "report_citation_policy": "planning_only",
            },
            [],
            [memory],
            [],
        ),
    )
    monkeypatch.setattr(collector, "_run_searches", lambda state: "")
    monkeypatch.setattr(collector, "_execute_collector", lambda task, state: ("[]", 0))
    monkeypatch.setattr(collector, "_get_search_info", lambda: {})
    monkeypatch.setattr(
        collector,
        "_persist_intelligence_items",
        lambda state, points: {"inserted": 0},
    )

    result = collector.collector_node(
        {
            "user_id": "user-a",
            "user_request": "Compare Cursor and Codex",
            "target_products": ["Cursor", "OpenAI Codex"],
            "analysis_brief": {"effective_dimensions": [{"id": "features"}]},
        }
    )

    assert result["collected_data"] == []
    assert result["analysis_memory"] == [memory]
    assert result["relationship_context"] == []
    assert result["collection_summary"]["rag_retrieval"]["analysis_memory_count"] == 1


def test_broken_or_unsupported_documents_fail_cleanly(tmp_path: Path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not-json")
    with pytest.raises(json.JSONDecodeError):
        DocumentParser().parse(broken)
    unsupported = tmp_path / "archive.zip"
    unsupported.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="Unsupported document type"):
        DocumentParser().parse(unsupported)


def test_query_planner_normalizes_aliases_and_deduplicates_pairs():
    state = {
        "user_request": "  compare   codex pricing  ",
        "target_products": ["codex", "OpenAI Codex", "Cursor"],
        "analysis_brief": {
            "effective_dimensions": [
                {"id": "pricing"},
                {"id": "定价与商业模式"},
            ]
        },
    }
    queries = build_analysis_queries(state)
    assert normalize_query_text(state["user_request"]) == "compare codex pricing"
    assert canonical_product("codex") == "OpenAI Codex"
    assert [(item.product, item.dimension) for item in queries] == [
        ("OpenAI Codex", "pricing"),
        ("Cursor", "pricing"),
    ]
    assert "codex" in {value.casefold() for value in queries[0].filters.products}
    assert "定价与商业模式" in queries[0].filters.dimensions


def test_analysis_queries_include_history_for_explicit_temporal_intent():
    temporal = build_analysis_queries(
        {
            "user_request": "分析 Cursor 过去半年的价格变化趋势",
            "target_products": ["Cursor"],
            "analysis_brief": {"effective_dimensions": [{"id": "pricing"}]},
        }
    )
    current = build_analysis_queries(
        {
            "user_request": "分析 Cursor 当前企业版价格",
            "target_products": ["Cursor"],
            "analysis_brief": {"effective_dimensions": [{"id": "pricing"}]},
        }
    )

    assert {item.filters.temporal_mode for item in temporal} == {"all"}
    assert {item.filters.temporal_mode for item in current} == {"current"}


def test_search_result_cache_and_ingestion_invalidation(tmp_path: Path):
    service = build_service(tmp_path)
    registration = service.register_bytes(
        user_id="user-a",
        filename="cursor.md",
        data=b"# Pricing\n\nCursor Pro costs $20 monthly.",
        product="Cursor",
        dimension="pricing",
    )
    service.process_job(registration["job"]["job_id"])
    index = service.index
    assert isinstance(index, FakeKnowledgeIndex)
    filters = RetrievalFilters(products=("Cursor",), dimensions=("pricing",))
    first = service.search("  Cursor   pricing ", user_id="user-a", filters=filters)
    second = service.search("Cursor pricing", user_id="user-a", filters=filters)
    assert first == second
    assert index.batch_search_calls == 1
    assert service.status("user-a")["result_cache"]["hits"] == 1

    update = service.register_bytes(
        user_id="user-a",
        filename="cursor.md",
        data=b"# Pricing\n\nCursor Pro now costs $25 monthly.",
        product="Cursor",
        dimension="pricing",
    )
    service.process_job(update["job"]["job_id"])
    refreshed = service.search("Cursor pricing", user_id="user-a", filters=filters)
    assert "$25" in refreshed[0].text
    assert index.batch_search_calls == 2


def test_query_vector_cache_batches_only_unique_misses(monkeypatch: pytest.MonkeyPatch):
    from competition.knowledge_index import LocalModelProvider

    provider = LocalModelProvider()
    dense_calls: list[list[str]] = []
    sparse_calls: list[list[str]] = []

    def embed(texts: list[str]):
        dense_calls.append(texts)
        return [[float(index)] for index, _ in enumerate(texts, start=1)]

    def sparse_embed(texts: list[str]):
        sparse_calls.append(texts)
        return [{"text": text} for text in texts]

    monkeypatch.setattr(provider, "embed", embed)
    monkeypatch.setattr(provider, "sparse_embed", sparse_embed)
    first_dense = provider.embed_queries(["Cursor pricing", "Cursor pricing", "Codex features"])
    first_sparse = provider.sparse_embed_queries(["Cursor pricing", "Cursor pricing", "Codex features"])
    second_dense = provider.embed_queries(["Cursor pricing", "Codex features"])
    second_sparse = provider.sparse_embed_queries(["Cursor pricing", "Codex features"])

    assert dense_calls == [["Cursor pricing", "Codex features"]]
    assert sparse_calls == [["Cursor pricing", "Codex features"]]
    assert first_dense[:2] == [[1.0], [1.0]]
    assert first_sparse[:2] == [{"text": "Cursor pricing"}, {"text": "Cursor pricing"}]
    assert second_dense == [[1.0], [2.0]]
    assert second_sparse == [{"text": "Cursor pricing"}, {"text": "Codex features"}]


def test_analysis_retrieval_batches_deduplicated_queries(tmp_path: Path):
    service = build_service(tmp_path)
    for filename, product in (("cursor.md", "Cursor"), ("codex.md", "OpenAI Codex")):
        result = service.register_bytes(
            user_id="user-a",
            filename=filename,
            data=f"# Pricing\n\n{product} synthetic pricing evidence".encode(),
            product=product,
            dimension="pricing",
        )
        service.process_job(result["job"]["job_id"])
    index = service.index
    assert isinstance(index, FakeKnowledgeIndex)
    points = service.retrieve_for_analysis(
        {
            "user_id": "user-a",
            "user_request": "Compare coding agents",
            "target_products": ["Cursor", "cursor", "Codex"],
            "analysis_brief": {
                "effective_dimensions": [{"id": "pricing"}, {"id": "定价"}],
            },
        }
    )
    assert {point["product"] for point in points} == {"Cursor", "OpenAI Codex"}
    assert index.batch_search_calls == 2
    assert index.batch_rerank_calls == 2
    assert {point["knowledge_query_route"] for point in points} == {"multi_hop"}


def test_retrieval_evaluation_metrics_and_thresholds():
    cases = [
        {
            "relevant": ["doc-a"],
            "ranked": [
                {"label": "doc-a", "document_id": "1", "chunk_id": "a"},
                {"label": "doc-b", "document_id": "2", "chunk_id": "b"},
            ],
            "latency_ms": 10,
        },
        {"relevant": [], "ranked": [], "latency_ms": 20},
    ]
    metrics = compute_retrieval_metrics(cases, k=5)
    assert metrics["recall_at_5"] == 1.0
    assert metrics["mrr"] == 1.0
    assert metrics["ndcg_at_5"] == 1.0
    assert metrics["abstention_accuracy"] == 1.0
    assert metrics["traceability_rate"] == 1.0
    assert metrics["latency_ms"]["p95"] == 19.5
    assert check_thresholds(metrics, EvaluationThresholds(), k=5) == []


def test_retrieval_evaluation_reports_quality_and_latency_failures():
    metrics = {
        "recall_at_5": 0.5,
        "mrr": 0.5,
        "ndcg_at_5": 0.5,
        "abstention_accuracy": 0.0,
        "traceability_rate": 0.5,
        "latency_ms": {"p95": 900.0},
    }
    failures = check_thresholds(
        metrics,
        EvaluationThresholds(max_p95_latency_ms=500),
        k=5,
    )
    assert len(failures) == 6


def test_query_planning_metrics_measure_route_and_required_steps():
    metrics = compute_planning_metrics(
        [
            {
                "expected_route": "direct",
                "actual_route": "direct",
                "required_step_purposes": ["direct_lookup"],
                "actual_step_purposes": ["direct_lookup"],
                "actual_step_count": 1,
            },
            {
                "expected_route": "multi_hop",
                "actual_route": "multi_hop",
                "required_step_purposes": ["subquestion", "bridge_from_first_hop_evidence"],
                "actual_step_purposes": ["subquestion", "bridge_from_first_hop_evidence"],
                "actual_step_count": 4,
            },
        ]
    )
    assert metrics["query_route_accuracy"] == 1.0
    assert metrics["decomposition_coverage"] == 1.0
    assert metrics["average_steps"] == 2.5


def test_verification_evaluation_scores_claims_citations_numbers_and_contradictions():
    cases = [
        {
            "expected_status": "supported",
            "actual_status": "supported",
            "expected_supporting": ["doc-a"],
            "actual_supporting": ["doc-a"],
            "expected_numeric_consistency": True,
            "actual_numeric_consistency": True,
        },
        {
            "expected_status": "contradicted",
            "actual_status": "contradicted",
            "expected_supporting": [],
            "actual_supporting": [],
            "expected_numeric_consistency": False,
            "actual_numeric_consistency": False,
        },
        {
            "expected_status": "insufficient",
            "actual_status": "insufficient",
            "expected_supporting": [],
            "actual_supporting": [],
            "expected_numeric_consistency": None,
            "actual_numeric_consistency": None,
        },
    ]
    verification = compute_verification_metrics(cases)
    assert verification["claim_status_accuracy"] == 1.0
    assert verification["contradiction_recall"] == 1.0
    assert verification["citation_precision"] == 1.0
    assert verification["numeric_consistency_accuracy"] == 1.0
    assert verification["groundedness"] == pytest.approx(1 / 3, abs=1e-6)

    retrieval = {
        "recall_at_5": 1.0,
        "mrr": 1.0,
        "ndcg_at_5": 1.0,
        "abstention_accuracy": 1.0,
        "traceability_rate": 1.0,
        "latency_ms": {"p95": 10},
        "verification": {**verification, "contradiction_recall": 0.2},
    }
    failures = check_thresholds(
        retrieval,
        EvaluationThresholds(groundedness=0.3),
        k=5,
    )
    assert failures == ["verification.contradiction_recall=0.2000 is below 0.8000"]
