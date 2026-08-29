from __future__ import annotations

from pathlib import Path

import pytest
from test_competition_knowledge import build_service

from competition.knowledge_evaluation_repo import KnowledgeEvaluationRepository, compare_evaluation_metrics
from competition.knowledge_repo import KnowledgeRepository
from competition.knowledge_retrieval import RetrievalStrategy, adaptive_strategy, classify_query, explain_retrieval, feedback_adjustment, reciprocal_rank_fusion
from competition.knowledge_sources import (
    KnowledgeSourceConnector,
    SourceFetchResult,
    SourceRepository,
    parse_feed_items,
    parse_json_api_items,
    parse_sitemap_urls,
    sync_source,
    validate_source_uri,
)
from competition.knowledge_types import RetrievalFilters
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


def test_source_formats_are_normalized_and_private_hosts_are_rejected():
    feed = b"""<rss><channel><item><title>Release</title><description>New feature</description><link>https://example.test/release</link></item></channel></rss>"""
    items = parse_feed_items(feed, source_uri="https://example.test/feed")
    assert items[0]["title"] == "Release"
    assert items[0]["source_uri"].endswith("/release")

    sitemap = b"""<urlset><url><loc>https://example.test/a</loc><lastmod>2026-08-30</lastmod></url></urlset>"""
    assert parse_sitemap_urls(sitemap, source_uri="https://example.test/sitemap.xml")[0]["published_at"] == "2026-08-30"

    payload = b'{"results":[{"id":"p1","name":"Cursor","description":"Editor"}]}'
    assert parse_json_api_items(payload, source_uri="https://example.test/api")[0]["entry_id"] == "p1"
    with pytest.raises(ValueError, match="Private or local"):
        validate_source_uri("http://127.0.0.1/internal")


def test_adaptive_retrieval_and_feedback_prior_are_bounded():
    classification = classify_query("Compare the latest Cursor and Codex pricing", RetrievalFilters(products=("Cursor", "Codex")))
    assert classification.intent == "temporal"
    strategy = adaptive_strategy("Compare the latest Cursor and Codex pricing", RetrievalFilters(products=("Cursor", "Codex")))
    assert strategy.ranking_profile == "freshness"
    assert strategy.candidate_limit == 64
    assert feedback_adjustment(relevant=8, citation_used=8) <= 0.12
    assert feedback_adjustment(not_relevant=8) >= -0.12


def test_source_sync_tasks_dispatch_without_ingestion_job(monkeypatch):
    import app.competition_router as router

    called = []
    monkeypatch.setattr(router, "_run_background_source_sync_task", lambda task: called.append(task) or {"status": "queued"})
    result = router._run_background_knowledge_task({"payload": {"operation": "source_sync", "source_id": "source-1"}})
    assert result == {"status": "queued"}
    assert called and called[0]["payload"]["source_id"] == "source-1"


def test_online_metrics_and_entity_alias_governance(tmp_path: Path):
    service = build_service(tmp_path)
    space = service.create_space("owner", name="Entities", require_approval=False)
    with KnowledgeRepository(db_path=service.db_path) as repository:
        first = repository.upsert_entity(
            entity_id="entity-1",
            space_id=space["space_id"],
            canonical_name="Cursor",
            normalized_key="cursor",
            alias="Cursor",
        )
        repository.upsert_entity(
            entity_id="entity-2",
            space_id=space["space_id"],
            canonical_name="Codex",
            normalized_key="codex",
            alias="Codex",
        )
    updated = service.add_entity_alias("owner", first["entity_id"], "Cursor IDE")
    assert any(alias["alias"] == "Cursor IDE" for alias in updated["aliases"])
    with pytest.raises(ValueError, match="already assigned"):
        service.add_entity_alias("owner", "entity-2", "Cursor IDE")

    from competition.knowledge_evaluation_repo import KnowledgeEvaluationRepository

    with KnowledgeEvaluationRepository(db_path=tmp_path / "metrics.db") as repository:
        repository.record_online_metric(user_id="owner", metric_name="retrieval.latency_ms", value=10, sample_count=2)
        repository.record_online_metric(user_id="owner", metric_name="retrieval.latency_ms", value=20, sample_count=1)
        summary = repository.online_metric_summary("owner")
    assert summary["metrics"]["retrieval.latency_ms"]["weighted_mean"] == 13.333333
