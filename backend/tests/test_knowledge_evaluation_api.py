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

