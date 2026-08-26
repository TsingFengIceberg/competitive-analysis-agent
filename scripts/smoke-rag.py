#!/usr/bin/env python3
"""Offline smoke check for local embedding, sparse recall, and reranking."""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("ORT_DISABLE_TELEMETRY", "true")

from qdrant_client import QdrantClient

from competition.knowledge_index import KnowledgeIndex, LocalModelProvider
from competition.knowledge_types import KnowledgeChunk, RetrievalFilters


def make_chunk(chunk_id: str, text: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id=f"doc-{chunk_id}",
        version_no=1,
        user_id="smoke-user",
        ordinal=0,
        text=text,
        contextual_text=f"Document: local smoke fixture\nProduct: Cursor\nDimension: pricing\n\n{text}",
        section_path="Pricing",
        page_no=1,
        token_count=32,
        qdrant_point_id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id)),
    )


def main() -> int:
    client = QdrantClient(location=":memory:")
    index = KnowledgeIndex(
        client=client,
        provider=LocalModelProvider(),
        collection="competition_knowledge_smoke",
    )
    relevant = make_chunk("smoke-cursor", "Cursor Pro costs twenty dollars per month.")
    unrelated = make_chunk("smoke-other", "The weather is sunny today.")
    index.replace_document(
        {
            "document_id": relevant.document_id,
            "product": "Cursor",
            "dimension": "pricing",
            "authority_tier": "primary",
        },
        [relevant],
    )
    index.replace_document(
        {
            "document_id": unrelated.document_id,
            "product": "Other",
            "dimension": "features",
            "authority_tier": "third_party",
        },
        [unrelated],
    )
    recalled = index.search_ids(
        "Cursor pricing per month",
        user_id="smoke-user",
        filters=RetrievalFilters(products=("Cursor",), dimensions=("pricing",)),
        limit=4,
    )
    if not recalled or recalled[0][0] != relevant.chunk_id:
        raise RuntimeError(f"Hybrid recall returned an unexpected result: {recalled}")
    reranked = index.rerank(
        "What does Cursor Pro cost per month?",
        [relevant.contextual_text, unrelated.contextual_text],
    )
    if len(reranked) != 2 or reranked[0] <= reranked[1]:
        raise RuntimeError(f"Reranker returned an unexpected order: {reranked}")
    index.close()
    print(f"RAG offline smoke passed: recall={recalled[0][1]:.4f}, rerank={reranked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
