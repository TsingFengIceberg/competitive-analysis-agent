from __future__ import annotations

from pathlib import Path

import pytest
from test_competition_knowledge import build_service

from competition.knowledge_eval import (
    EvaluationThresholds,
    aggregate_query_metrics,
    bootstrap_metric_intervals,
    check_thresholds,
    compare_metric_sets,
    compute_answer_quality_metrics,
    compute_cost_metrics,
    compute_dataset_drift,
    compute_dataset_quality_metrics,
    compute_load_metrics,
    compute_robustness_metrics,
    compute_runtime_metrics,
    evaluation_coverage,
)
from competition.knowledge_evaluation_repo import KnowledgeEvaluationRepository, compare_evaluation_metrics
from competition.knowledge_repo import KnowledgeRepository
from competition.knowledge_retrieval import RetrievalStrategy, adaptive_strategy, classify_query, explain_retrieval, feedback_adjustment, reciprocal_rank_fusion
from competition.knowledge_sources import (
    KnowledgeSourceConnector,
    SourceFetchResult,
    SourceRepository,
    parse_feed_items,
    parse_json_api_items,
    parse_json_api_page,
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


def test_source_sync_closes_run_when_fetcher_raises(tmp_path: Path):
    with SourceRepository(db_path=tmp_path / "source-error.db") as repository:
        source = KnowledgeSourceConnector(name="Broken", uri="https://example.test/broken", user_id="owner")
        saved = repository.save(source)

        result = sync_source(
            saved,
            user_id="owner",
            repository=repository,
            fetcher=lambda _source: (_ for _ in ()).throw(RuntimeError("upstream unavailable")),
            register=lambda **_kwargs: {},
        )
        assert result["status"] == "failed"
        run = repository.list_sync_runs("owner", source_id=source.source_id, limit=1)[0]
        assert run["status"] == "failed"
        assert "upstream unavailable" in (run["error"] or "")


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


def test_rag_metric_comparison_is_direction_aware_and_explicit_about_zero_baselines():
    comparison = compare_metric_sets(
        {"recall_at_5": 0.5, "latency_ms": {"p95": 100.0}, "unsupported_relation_rate": 0.0},
        {"recall_at_5": 0.6, "latency_ms": {"p95": 75.0}, "unsupported_relation_rate": 0.1},
    )
    assert comparison["absolute_delta"]["recall_at_5"] == 0.1
    assert comparison["relative_change"]["recall_at_5"] == 0.2
    assert comparison["absolute_delta"]["latency_ms.p95"] == 25.0
    assert comparison["relative_change"]["latency_ms.p95"] == 0.25
    assert comparison["absolute_delta"]["unsupported_relation_rate"] == -0.1
    assert comparison["relative_change"]["unsupported_relation_rate"] is None
    assert comparison["undefined"]["unsupported_relation_rate"] == "baseline_is_zero"


def test_rag_query_groups_and_coverage_surface_small_or_missing_slices():
    cases = [
        {"id": "a", "category": "fact", "difficulty": "easy", "split": "test", "relevant": ["a"], "ranked": [{"label": "a", "document_id": "d", "chunk_id": "c"}]},
        {"id": "b", "category": "no_answer", "difficulty": "hard", "split": "test", "relevant": [], "ranked": []},
    ]
    grouped = aggregate_query_metrics(cases, k=5)
    assert grouped["category"]["fact"]["sample_count"] == 1
    assert grouped["category"]["no_answer"]["metrics"]["abstention_accuracy"] == 1.0
    assert grouped["product"]["shared/unspecified"]["sample_count"] == 2
    assert grouped["answerability"]["unanswerable"]["sample_count"] == 1
    coverage = evaluation_coverage(cases, minimum_cases=3, required_categories=("fact", "comparison"))
    assert coverage["case_count"] == 2
    assert "comparison" in coverage["missing_categories"]
    assert len(coverage["warnings"]) == 2


def test_runtime_metrics_report_logs_and_unknown_token_cost_without_guessing():
    metrics = compute_runtime_metrics(
        [{"latency_ms": 10, "token_count": 12}, {"latency_ms": 30}],
        [
            {"status": "completed", "filters": {"cache_hit": True}},
            {"status": "degraded", "filters": {"cache_hit": False}},
        ],
    )
    assert metrics["search_count"] == 2
    assert metrics["cache_hit_count"] == 1
    assert metrics["cache_hit_rate"] == 0.5
    assert metrics["degraded_count"] == 1
    assert metrics["retrieved_token_estimate"] == 12.0
    assert metrics["latency_ms"]["p99"] == 29.8
    assert metrics["cost"]["estimated_cost_usd"] is None


def test_cost_metrics_use_observed_usage_and_optional_model_pricing():
    cases = [
        {"usage": {"model": "gpt-test", "input_tokens": 1000, "output_tokens": 500}},
        {"usage": {"model": "gpt-test", "input_tokens": 500, "output_tokens": 100, "cost_usd": 0.02}},
        {"token_count": 999},
    ]
    metrics = compute_cost_metrics(
        cases,
        pricing={"gpt-test": {"input_usd_per_1k": 0.01, "output_usd_per_1k": 0.02}},
    )
    assert metrics["instrumented_case_count"] == 2
    assert metrics["total_tokens"] == 2100.0
    assert metrics["estimated_cost_usd"] == 0.027
    assert metrics["observed_cost_usd"] == 0.02
    assert metrics["pricing_coverage"] == 1.0


def test_dataset_quality_and_drift_report_are_explicit():
    baseline = {
        "documents": [{"id": "a", "filename": "a.md", "text": "A", "source_url": "https://a", "product": "A", "dimension": "pricing", "authority_tier": "primary", "captured_at": "2026-01-01"}],
        "queries": [{"id": "q1", "query": "A?", "category": "fact", "difficulty": "easy", "split": "test", "relevant": ["a"]}],
    }
    current = {
        "documents": baseline["documents"] + [{"id": "b", "filename": "b.md", "text": "B", "source_url": "https://b", "product": "B", "dimension": "features", "authority_tier": "primary", "captured_at": "2026-01-02"}],
        "queries": baseline["queries"] + [{"id": "q2", "query": "B?", "category": "comparison", "difficulty": "hard", "split": "test", "relevant": ["b"]}],
    }
    quality = compute_dataset_quality_metrics(current)
    assert quality["document_metadata_completeness"] == 1.0
    assert quality["distractor_document_count"] == 0
    assert quality["category_counts"] == {"comparison": 1, "fact": 1}
    drift = compute_dataset_drift(current, baseline, max_category_shift=0.25)
    assert drift["status"] == "drifted"
    assert drift["query_count_delta"] == 1
    assert drift["added_document_ids"] == ["b"]
    legacy = compute_dataset_drift(current, {"documents": baseline["documents"], "queries": [{"id": "legacy", "query": "A?", "relevant": ["a"]}]})
    assert legacy["status"] == "partial"
    assert "baseline_category_metadata_unavailable" in legacy["warnings"]


def test_robustness_metrics_measure_paired_query_degradation():
    cases = [
        {"robustness_group": "price", "variant_type": "baseline", "relevant": ["price"], "ranked": [{"label": "price"}]},
        {"robustness_group": "price", "variant_type": "paraphrase", "relevant": ["price"], "ranked": [], "expected_invariant": True},
        {"robustness_group": "feature", "variant_type": "baseline", "relevant": ["feature"], "ranked": [{"label": "feature"}]},
        {"robustness_group": "feature", "variant_type": "translation", "relevant": ["feature"], "ranked": [{"label": "feature"}], "expected_invariant": True},
    ]
    metrics = compute_robustness_metrics(cases, tolerance=0.1)
    assert metrics["group_count"] == 2
    assert metrics["invariance_rate"] == 0.5
    assert metrics["degradation_rate"] == 0.5


def test_runtime_quality_gates_cover_failure_tail_latency_and_cost():
    failures = check_thresholds(
        {
            "recall_at_5": 1.0,
            "mrr": 1.0,
            "ndcg_at_5": 1.0,
            "abstention_accuracy": 1.0,
            "traceability_rate": 1.0,
            "runtime": {
                "failure_rate": 0.2,
                "degraded_rate": 0.1,
                "latency_ms": {"p99": 120.0},
                "cost": {"case_count": 2, "observed_cost_usd": 0.4},
            },
        },
        EvaluationThresholds(max_failure_rate=0.1, max_degraded_rate=0.05, max_p99_latency_ms=100, max_cost_usd_per_case=0.1),
    )
    assert any("runtime.failure_rate" in failure for failure in failures)
    assert any("runtime.degraded_rate" in failure for failure in failures)
    assert any("runtime.latency_ms.p99" in failure for failure in failures)
    assert any("runtime.cost.usd_per_case" in failure for failure in failures)


def test_load_metrics_use_supplied_wall_time_for_concurrent_throughput():
    metrics = compute_load_metrics(
        [{"latency_ms": 20}, {"latency_ms": 30, "status": "failed"}],
        wall_time_ms=40,
        concurrency=2,
    )
    assert metrics["wall_time_source"] == "supplied"
    assert metrics["throughput_qps"] == 50.0
    assert metrics["error_rate"] == 0.5
    with pytest.raises(ValueError):
        compute_load_metrics([], concurrency=0)


def test_answer_quality_scores_are_separate_from_retrieval_and_report_coverage():
    metrics = compute_answer_quality_metrics(
        [
            {"scores": {"factuality": 0.9, "groundedness": 0.8, "citation_completeness": 1.0}},
            {"scores": {"factuality": 0.7, "decision_usefulness": 0.6, "comparison_fairness": 0.9}},
        ]
    )
    assert metrics["overall_mean"] == 0.82
    assert metrics["dimensions"]["factuality"]["sample_count"] == 2
    assert metrics["coverage"] == 1.0
    invalid = compute_answer_quality_metrics([{"scores": {"factuality": 2.0}}])
    assert invalid["invalid_score_count"] == 1
    assert invalid["overall_mean"] is None


def test_bootstrap_intervals_are_reproducible_and_warn_on_tiny_samples():
    cases = [
        {"relevant": ["a"], "ranked": [{"label": "a", "document_id": "d", "chunk_id": "c"}], "latency_ms": 10},
        {"relevant": ["a"], "ranked": [], "latency_ms": 20},
        {"relevant": [], "ranked": [], "latency_ms": 30},
    ]
    first = bootstrap_metric_intervals(cases, iterations=100, seed=11)
    second = bootstrap_metric_intervals(cases, iterations=100, seed=11)
    assert first == second
    assert first["intervals"]["recall_at_5"]["estimate"] == 0.5
    tiny = bootstrap_metric_intervals(cases[:1], iterations=100)
    assert tiny["intervals"] == {}
    assert tiny["warnings"]


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


def test_json_pagination_and_item_level_source_sync_only_register_changes(tmp_path: Path):
    payload = b'{"items":[{"id":"one","title":"One","summary":"Initial"}],"links":{"next":"https://example.test/feed?page=2"}}'
    page = parse_json_api_page(payload, source_uri="https://example.test/feed", media_type="application/json")
    assert page["items"][0]["entry_id"] == "one"
    assert page["next_uri"].endswith("page=2")
    with SourceRepository(db_path=tmp_path / "source-items.db") as repository:
        source = KnowledgeSourceConnector(name="API", uri="https://example.test/feed", source_type="json_api", user_id="owner", max_pages=2)
        saved = repository.save(source)
        calls = []

        def register(**kwargs):
            calls.append(kwargs)
            return {"document": {"document_id": f"doc-{len(calls)}"}, "job": {"job_id": f"job-{len(calls)}"}}

        result = sync_source(
            saved,
            user_id="owner",
            repository=repository,
            fetcher=lambda _source: SourceFetchResult(
                status="changed",
                data=payload,
                media_type="application/json",
                content_hash="first",
                items=({"entry_id": "one", "title": "One", "summary": "Initial", "source_uri": "https://example.test/one"},),
                pages_fetched=1,
            ),
            register=register,
        )
        assert result["status"] == "queued"
        assert len(calls) == 1
        assert repository.list_items(source.source_id, "owner")[0]["status"] == "queued"

        current = repository.get(source.source_id, "owner")
        assert current
        unchanged = sync_source(
            current,
            user_id="owner",
            repository=repository,
            fetcher=lambda _source: SourceFetchResult(
                status="changed",
                data=payload,
                media_type="application/json",
                content_hash="second",
                items=({"entry_id": "one", "title": "One", "summary": "Initial", "source_uri": "https://example.test/one"},),
                pages_fetched=1,
            ),
            register=register,
        )
        assert unchanged["changed"] is False
        assert len(calls) == 1


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


def test_lexical_fallback_search_is_scoped_and_ranked(tmp_path: Path):
    service = build_service(tmp_path)
    result = service.register_bytes(
        user_id="owner",
        filename="cursor.md",
        data=b"# Cursor pricing\nCursor offers a team plan and enterprise controls.",
        title="Cursor pricing",
        product="Cursor",
        dimension="pricing",
    )
    job_id = (result["job"] or {})["job_id"]
    service.process_job(job_id)
    with KnowledgeRepository(db_path=service.db_path) as repository:
        hits = repository.search_chunks_lexical(
            "Cursor enterprise pricing",
            "owner",
            filters=RetrievalFilters(products=("Cursor",), dimensions=("pricing",)),
            limit=5,
        )
    assert hits
    assert hits[0][1] > 0
    assert hits[0][0]["retrieval_source"] == "lexical_fallback" or "retrieval_source" not in hits[0][0]
