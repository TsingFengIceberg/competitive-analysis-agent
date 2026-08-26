from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from competition.knowledge_chunking import build_chunks
from competition.knowledge_parser import DocumentParser
from competition.knowledge_service import KnowledgeService
from competition.knowledge_types import KnowledgeChunk, ParsedBlock, ParsedDocument, RetrievalFilters


class FakeKnowledgeIndex:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[dict[str, Any], Any]] = {}
        self.closed = False

    def replace_document(self, document, chunks, *, stale_point_ids=None) -> None:
        del stale_point_ids
        for chunk_id in [key for key, (doc, _) in self.rows.items() if doc["document_id"] == document["document_id"]]:
            self.rows.pop(chunk_id)
        for chunk in chunks:
            self.rows[chunk.chunk_id] = (dict(document), chunk)

    def search_ids(self, query, *, user_id, filters, limit=12, candidate_limit=40):
        del candidate_limit
        query_terms = set(query.casefold().split())
        matches = []
        for chunk_id, (document, chunk) in self.rows.items():
            if chunk.user_id != user_id:
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

    def rerank(self, query, texts):
        del query
        return [0.95 - index * 0.05 for index, _ in enumerate(texts)]

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

    def chunk(chunk_id: str, user_id: str, text: str) -> KnowledgeChunk:
        import uuid

        return KnowledgeChunk(
            chunk_id=chunk_id,
            document_id=f"doc-{chunk_id}",
            version_no=1,
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
        lambda state: ([local], {"status": "available", "hit_count": 1}),
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
    assert result["collection_summary"]["rag_retrieval"]["status"] == "available"
    assert persisted == [[]]


def test_broken_or_unsupported_documents_fail_cleanly(tmp_path: Path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not-json")
    with pytest.raises(json.JSONDecodeError):
        DocumentParser().parse(broken)
    unsupported = tmp_path / "archive.zip"
    unsupported.write_bytes(b"not a zip")
    with pytest.raises(ValueError, match="Unsupported document type"):
        DocumentParser().parse(unsupported)
