from __future__ import annotations

from pathlib import Path

from competition.knowledge_evaluation_repo import KnowledgeEvaluationRepository, compare_evaluation_metrics
from competition.knowledge_retrieval import RetrievalStrategy, explain_retrieval, reciprocal_rank_fusion
from competition.knowledge_sources import (
    KnowledgeSourceConnector,
    SourceFetchResult,
    SourceRepository,
    sync_source,
)
from competition.rag_context import build_agent_evidence_bundle


def test_weighted_rrf_and_retrieval_explanation_are_deterministic():
    fused = reciprocal_rank_fusion(
        {"dense": ["a", "b"], "sparse": ["b", "c"]},
        weights={"dense": 0.7, "sparse": 0.3},
    )
    assert fused[0][0] == "b"
    assert {item_id for item_id, _ in fused[:2]} == {"a", "b"}
    explanation = explain_retrieval(
        strategy=RetrievalStrategy(mode="hybrid", dense_weight=0.7, sparse_weight=0.3),
        recall_score=0.8,
        rerank_score=0.9,
        authority_score=0.95,
        freshness_score=0.7,
    )
    assert explanation["dense_weight"] == 0.7
    assert explanation["reranked"] is True


def test_source_sync_uses_content_hash_and_queues_only_changes(tmp_path: Path):
    with SourceRepository(db_path=tmp_path / "sources.db") as repository:
        source = KnowledgeSourceConnector(name="Docs", uri="https://example.test/docs", user_id="owner")
        saved = repository.save(source)
        calls: list[dict] = []

        def register(**kwargs):
            calls.append(kwargs)
            return {"job": {"job_id": "job-1"}, "unchanged": False}

        result = sync_source(
            saved,
            user_id="owner",
            repository=repository,
            fetcher=lambda _source: SourceFetchResult(status="changed", data=b"# Docs", media_type="text/markdown", content_hash="hash-1"),
            register=register,
        )
        assert result["changed"] is True
        assert calls and calls[0]["filename"].endswith(".md")

        current = repository.get(source.source_id, "owner")
        assert current and current["content_hash"] == "hash-1"
        unchanged = sync_source(
            current,
            user_id="owner",
            repository=repository,
            fetcher=lambda _source: SourceFetchResult(status="changed", data=b"# Docs", media_type="text/markdown", content_hash="hash-1"),
            register=register,
        )
        assert unchanged["status"] == "unchanged"
        assert len(calls) == 1


def test_rag_context_is_budgeted_and_marks_report_memory_non_citable():
    bundle = build_agent_evidence_bundle(
        {
            "analysis_context_pack": {"quality": {"quality_state": "available"}, "evidence": []},
            "collected_data": [
                {"id": "dp-1", "product": "Cursor", "category": "pricing", "value": "price", "source_url": "https://example.test", "confidence": 0.9},
                {"id": "dp-2", "product": "Codex", "category": "pricing", "value": "other", "source_url": "https://example.test", "confidence": 0.8},
            ],
        },
        role="analyst",
        max_tokens=10,
    )
    assert bundle["selected_count"] >= 1
    assert bundle["used_tokens"] <= 10
    assert all(item["citation_eligible"] for item in bundle["evidence"])


def test_evaluation_feedback_and_regression_are_persisted(tmp_path: Path):
    with KnowledgeEvaluationRepository(db_path=tmp_path / "evaluation.db") as repository:
        first = repository.save(
            user_id="owner",
            dataset_name="golden",
            status="passed",
            metrics={"retrieval": {"recall_at_5": 0.9}},
            failures=[],
            case_count=1,
        )
        previous = repository.previous("owner", "golden")
        assert previous and previous["run_id"] == first["run_id"]
        comparison = compare_evaluation_metrics({"retrieval": {"recall_at_5": 0.8}}, previous)
        assert comparison["status"] == "regressed"
        feedback = repository.save_feedback(user_id="owner", query="price", chunk_id="chunk-1", action="relevant")
        assert feedback["action"] == "relevant"
        assert repository.feedback_summary("owner")["relevance_rate"] == 1.0
