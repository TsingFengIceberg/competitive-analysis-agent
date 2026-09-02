"""HTTP contract tests for offline RAG evaluation and retrieval profiles."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_knowledge_evaluation_endpoint_persists_metrics(monkeypatch, tmp_path):
    import app.competition_router as router
    import competition.knowledge_evaluation_repo as evaluation_repo

    monkeypatch.setattr(evaluation_repo, "DEFAULT_DB_PATH", tmp_path / "evaluations.db")
    app = FastAPI()
    app.include_router(router.router)
    body = {
        "dataset_name": "smoke-v1",
        "cases": [
            {
                "relevant": ["pricing"],
                "ranked": [{"label": "pricing", "document_id": "doc-1", "chunk_id": "chunk-1"}],
                "latency_ms": 12,
            }
        ],
        "k": 5,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/competition/knowledge/evaluate", json=body)
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["metrics"]["schema_version"] == "rag-evaluation.v1"
        history = await client.get("/api/competition/knowledge/evaluations")
    assert history.status_code == 200
    assert history.json()["runs"][0]["dataset_name"] == "smoke-v1"


@pytest.mark.asyncio
async def test_knowledge_evaluation_quality_gate_reports_coverage_failures(monkeypatch, tmp_path):
    import app.competition_router as router
    import competition.knowledge_evaluation_repo as evaluation_repo

    monkeypatch.setattr(evaluation_repo, "DEFAULT_DB_PATH", tmp_path / "evaluations.db")
    app = FastAPI()
    app.include_router(router.router)
    body = {
        "dataset_name": "coverage-v1",
        "cases": [{"category": "fact", "relevant": ["doc"], "ranked": [{"label": "doc", "document_id": "d", "chunk_id": "c"}]}],
        "minimum_case_count": 2,
        "required_categories": ["fact", "comparison"],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/competition/knowledge/evaluate", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["metrics"]["coverage"]["missing_categories"] == ["comparison"]
    assert any(item.startswith("coverage.") for item in payload["failures"])


@pytest.mark.asyncio
async def test_retrieval_experiment_endpoint_returns_relative_and_group_metrics(monkeypatch, tmp_path):
    import app.competition_router as router
    import competition.knowledge_evaluation_repo as evaluation_repo

    monkeypatch.setattr(evaluation_repo, "DEFAULT_DB_PATH", tmp_path / "experiments.db")
    app = FastAPI()
    app.include_router(router.router)
    body = {
        "name": "hybrid-ablation",
        "baseline": {"id": "dense"},
        "candidate": {"id": "hybrid"},
        "baseline_cases": [{"category": "fact", "relevant": ["doc"], "ranked": [{"label": "doc", "document_id": "d", "chunk_id": "c"}], "latency_ms": 100}],
        "candidate_cases": [{"category": "fact", "relevant": ["doc"], "ranked": [{"label": "doc", "document_id": "d", "chunk_id": "c"}], "latency_ms": 50}],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/competition/knowledge/retrieval-experiments", json=body)
    assert response.status_code == 201
    metrics = response.json()["experiment"]["metrics"]
    assert metrics["comparison"]["relative_change"]["latency_ms.p95"] == 0.5
    assert metrics["baseline_by_group"]["category"]["fact"]["sample_count"] == 1


@pytest.mark.asyncio
async def test_knowledge_evaluation_accepts_answer_quality_rubric_scores(monkeypatch, tmp_path):
    import app.competition_router as router
    import competition.knowledge_evaluation_repo as evaluation_repo

    monkeypatch.setattr(evaluation_repo, "DEFAULT_DB_PATH", tmp_path / "answer-quality.db")
    app = FastAPI()
    app.include_router(router.router)
    body = {
        "dataset_name": "answer-quality-v1",
        "answer_quality_cases": [
            {"scores": {"factuality": 0.9, "groundedness": 0.8, "citation_completeness": 1.0}},
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/competition/knowledge/evaluate", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["metrics"]["answer_quality"]["scored_case_count"] == 1
    assert payload["metrics"]["answer_quality"]["coverage"] == 0.6


@pytest.mark.asyncio
async def test_knowledge_evaluation_exposes_runtime_cost_and_robustness_metrics(monkeypatch, tmp_path):
    import app.competition_router as router
    import competition.knowledge_evaluation_repo as evaluation_repo

    monkeypatch.setattr(evaluation_repo, "DEFAULT_DB_PATH", tmp_path / "runtime.db")
    app = FastAPI()
    app.include_router(router.router)
    body = {
        "dataset_name": "runtime-v1",
        "cases": [
            {
                "relevant": ["doc"],
                "ranked": [{"label": "doc", "document_id": "d", "chunk_id": "c"}],
                "latency_ms": 10,
                "usage": {"model": "test-model", "input_tokens": 1000, "output_tokens": 100},
                "robustness_group": "price",
                "variant_type": "baseline",
            },
            {
                "relevant": ["doc"],
                "ranked": [{"label": "doc", "document_id": "d", "chunk_id": "c"}],
                "latency_ms": 30,
                "usage": {"model": "test-model", "input_tokens": 500, "output_tokens": 50},
                "robustness_group": "price",
                "variant_type": "paraphrase",
            },
        ],
        "runtime_logs": [{"status": "completed", "filters": {"cache_hit": True}}],
        "pricing": {"test-model": {"input_usd_per_1k": 0.01, "output_usd_per_1k": 0.02}},
        "runtime_wall_time_ms": 40,
        "runtime_concurrency": 2,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/competition/knowledge/evaluate", json=body)
    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["runtime"]["cost"]["estimated_cost_usd"] == 0.018
    assert metrics["runtime"]["latency_ms"]["p99"] == 29.8
    assert metrics["runtime"]["load"]["throughput_qps"] == 50.0
    assert metrics["robustness"]["invariance_rate"] == 1.0
