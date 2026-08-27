from __future__ import annotations

import json
from pathlib import Path

from test_competition_knowledge import build_service

from competition.knowledge_query import plan_retrieval_query
from competition.knowledge_repo import KnowledgeRepository
from competition.knowledge_types import RetrievalFilters
from competition.schema import ReportData


def _ingest(service, *, user_id: str, filename: str, text: str, product: str, dimension: str, space_id: str | None = None):
    registration = service.register_bytes(
        user_id=user_id,
        filename=filename,
        data=text.encode(),
        product=product,
        dimension=dimension,
        source_uri=f"https://example.test/{filename}",
        authority_tier="primary",
        space_id=space_id,
    )
    result = service.process_job(registration["job"]["job_id"])
    assert result["status"] == "completed"
    return registration["document"]["document_id"]


def test_query_planner_routes_simple_and_decomposes_complex_requests():
    direct = plan_retrieval_query(
        "Cursor enterprise price",
        RetrievalFilters(products=("Cursor",), dimensions=("pricing",)),
    )
    assert direct.route == "direct"
    assert [step.hop for step in direct.steps] == [1]

    complex_plan = plan_retrieval_query(
        "Compare Cursor and Codex pricing changes and explain the impact",
        RetrievalFilters(products=("Cursor", "OpenAI Codex"), dimensions=("pricing", "features")),
    )
    assert complex_plan.route == "multi_hop"
    assert any(step.purpose == "subquestion" for step in complex_plan.steps)
    assert complex_plan.steps[-1].hop == 2
    assert complex_plan.steps[-1].depends_on


def test_space_approval_permissions_and_shared_retrieval(tmp_path):
    service = build_service(tmp_path)
    space = service.create_space(
        "owner",
        name="AI coding tools",
        require_approval=True,
        retention_days=30,
    )
    service.set_space_member("owner", space["space_id"], "editor", "editor")
    service.set_space_member("owner", space["space_id"], "viewer", "viewer")
    document_id = _ingest(
        service,
        user_id="editor",
        filename="cursor.md",
        text="# Pricing\n\nCursor Teams costs 40 dollars per month.",
        product="Cursor",
        dimension="pricing",
        space_id=space["space_id"],
    )
    detail = service.document_detail(document_id, "owner")
    assert detail is not None
    assert detail["approval_status"] == "pending"
    assert detail["retention_until"]
    assert service.document_detail(document_id, "viewer") is None
    assert service.search(
        "Cursor Teams price",
        user_id="viewer",
        filters=RetrievalFilters(space_ids=(space["space_id"],)),
    ) == []

    approved = service.review_document("owner", document_id, "approved")
    assert approved["approval_status"] == "approved"
    hits = service.search(
        "Cursor Teams price",
        user_id="viewer",
        filters=RetrievalFilters(space_ids=(space["space_id"],)),
    )
    assert hits and hits[0].document_id == document_id

    try:
        service.register_bytes(
            user_id="viewer",
            filename="forbidden.md",
            data=b"viewer cannot write",
            space_id=space["space_id"],
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("viewer unexpectedly wrote to a protected knowledge space")


def test_event_clustering_layered_insights_and_retention_audit(tmp_path):
    service = build_service(tmp_path)
    space = service.create_space("owner", name="Signals", require_approval=False)
    first = _ingest(
        service,
        user_id="owner",
        filename="pricing-a.md",
        text="# Price\n\nCursor business plan is 40 dollars monthly.",
        product="Cursor",
        dimension="pricing",
        space_id=space["space_id"],
    )
    _ingest(
        service,
        user_id="owner",
        filename="pricing-b.md",
        text="# Independent price\n\nA second source lists Cursor at 40 dollars monthly.",
        product="Cursor",
        dimension="pricing",
        space_id=space["space_id"],
    )
    _ingest(
        service,
        user_id="owner",
        filename="feature.md",
        text="# Agent capability\n\nCursor added repository-wide review workflows.",
        product="Cursor",
        dimension="features",
        space_id=space["space_id"],
    )
    _ingest(
        service,
        user_id="owner",
        filename="market.md",
        text="# Adoption\n\nCursor expanded its enterprise partner program.",
        product="Cursor",
        dimension="market",
        space_id=space["space_id"],
    )

    events = service.list_events("owner", space_id=space["space_id"])
    assert len(events) == 3
    pricing = next(event for event in events if event["dimension"] == "pricing")
    assert pricing["status"] == "corroborated"
    assert pricing["evidence_count"] == 2

    insights = service.refresh_insights("owner", space["space_id"])
    assert {item["insight_type"] for item in insights} == {"fact", "hypothesis"}
    hypothesis = next(item for item in insights if item["insight_type"] == "hypothesis")
    assert hypothesis["metadata"]["requires_human_review"] is True

    points = service.retrieve_for_analysis(
        {
            "user_id": "owner",
            "user_request": "Compare Cursor pricing, features, and market changes",
            "target_products": ["Cursor"],
            "analysis_brief": {
                "effective_dimensions": [
                    {"id": "pricing"},
                    {"id": "features"},
                    {"id": "market"},
                ]
            },
        }
    )
    context = service.insights_for_analysis(
        {"user_id": "owner", "target_products": ["Cursor"]},
        points,
    )
    assert {item["insight_type"] for item in context} == {"fact", "hypothesis"}
    assert all(item["evidence_status"] in {"linked", "context_only"} for item in context)
    report = ReportData.model_validate({"long_term_insights": context})
    assert report.long_term_insights == context

    with KnowledgeRepository(db_path=service.db_path) as repository:
        repository.update_document(first, retention_until="2000-01-01T00:00:00+00:00")
    result = service.purge_expired()
    assert first in result["purged"]
    assert service.document_detail(first, "owner") is None
    audit = service.deletion_audit("owner", space_id=space["space_id"])
    assert audit[0]["document_id"] == first
    assert audit[0]["reason"] == "retention_expired"
    assert audit[0]["snapshot"]["version_count"] == 1


def test_p1_knowledge_api_contracts_are_registered():
    from app.competition_router import router

    contracts = {(route.path, method) for route in router.routes for method in route.methods or []}
    assert ("/api/competition/knowledge/spaces", "POST") in contracts
    assert ("/api/competition/knowledge/spaces/{space_id}", "PATCH") in contracts
    assert ("/api/competition/knowledge/spaces/{space_id}/members", "PUT") in contracts
    assert ("/api/competition/knowledge/documents/{document_id}/review", "POST") in contracts
    assert ("/api/competition/knowledge/events", "GET") in contracts
    assert ("/api/competition/knowledge/insights", "GET") in contracts
    assert ("/api/competition/knowledge/insights/refresh", "POST") in contracts
    assert ("/api/competition/knowledge/deletions", "GET") in contracts
    assert ("/api/competition/knowledge/retention/run", "POST") in contracts


def test_real_rag_dataset_has_traceable_public_snapshots():
    root = Path(__file__).resolve().parents[2]
    dataset = json.loads((root / "evals/rag/real-v1.json").read_text())
    assert dataset["curation"]["review_status"] == "human_curated"
    assert len(dataset["documents"]) >= 8
    assert all(item["source_url"].startswith("https://") for item in dataset["documents"])
    assert all(item.get("captured_at") for item in dataset["documents"])
    assert {item["expected_route"] for item in dataset["queries"]} == {"direct", "multi_hop"}
