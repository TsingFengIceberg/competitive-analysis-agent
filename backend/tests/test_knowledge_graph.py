from __future__ import annotations

import pytest
from test_competition_knowledge import build_service

from competition.knowledge_graph import (
    build_relation_candidates,
    plan_graph_retrieval,
)


def _ingest(
    service,
    *,
    user_id: str = "owner",
    filename: str,
    text: str,
    product: str,
    dimension: str,
    source_uri: str,
    observed_at: str,
    space_id: str | None = None,
):
    registration = service.register_bytes(
        user_id=user_id,
        filename=filename,
        data=text.encode(),
        product=product,
        dimension=dimension,
        source_uri=source_uri,
        authority_tier="primary",
        observed_at=observed_at,
        space_id=space_id,
    )
    result = service.process_job(registration["job"]["job_id"])
    assert result["status"] == "completed"
    return registration["document"]["document_id"]


def test_graph_planner_routes_relational_queries_without_expanding_focused_lookups():
    direct = plan_graph_retrieval(
        {
            "user_request": "What is the current Cursor price?",
            "target_products": ["Cursor"],
        }
    )
    assert direct.use_graph is False
    assert direct.route == "vector_only"

    relational = plan_graph_retrieval(
        {
            "user_request": "How do Cursor and Codex integrations relate to their ecosystems?",
            "target_products": ["Cursor", "OpenAI Codex"],
        }
    )
    assert relational.use_graph is True
    assert relational.route == "hybrid_graph"
    assert relational.max_hops == 2
    assert {"multiple_products", "relationship_intent"} <= set(relational.reasons)


def test_relation_builder_creates_typed_semantic_and_source_edges():
    document = {
        "document_id": "doc-1",
        "space_id": "space-1",
        "product": "Cursor",
        "dimension": "technology",
        "title": "GitHub integration",
        "source_type": "upload",
        "source_uri": "https://docs.cursor.com/integrations/github",
        "authority_tier": "primary",
        "metadata": {},
    }
    graph = build_relation_candidates(
        document,
        event={
            "event_id": "event-1",
            "title": "GitHub integration",
            "statement": "Cursor integrates with GitHub for repository workflows.",
            "occurred_at": "2026-08-01T00:00:00+00:00",
            "confidence": 0.95,
        },
        chunk={"chunk_id": "chunk-1"},
    )
    assert {entity["entity_type"] for entity in graph["entities"]} == {
        "product",
        "integration",
        "source",
    }
    assert {relation["relation_type"] for relation in graph["relations"]} == {
        "integrates_with",
        "documented_by",
    }
    assert all(relation["citation_eligible"] for relation in graph["relations"])


def test_price_relations_are_versioned_and_cross_source_conflicts_are_visible(tmp_path):
    service = build_service(tmp_path)
    document_id = _ingest(
        service,
        filename="cursor-pricing.md",
        text="# Pricing\n\nCursor Teams costs $40 per month.",
        product="Cursor",
        dimension="pricing",
        source_uri="https://cursor.com/pricing",
        observed_at="2026-07-01T00:00:00+00:00",
    )
    _ingest(
        service,
        filename="cursor-pricing.md",
        text="# Pricing\n\nCursor Teams now costs $45 per month.",
        product="Cursor",
        dimension="pricing",
        source_uri="https://cursor.com/pricing",
        observed_at="2026-08-01T00:00:00+00:00",
    )

    current = service.graph("owner", relation_type="priced_at")
    historical = service.graph("owner", relation_type="priced_at", temporal_mode="historical")
    assert [relation["target_name"] for relation in current["relations"]] == ["$45 per month"]
    assert historical["relations"][0]["target_name"] == "$40 per month"
    assert historical["relations"][0]["valid_to"] == "2026-08-01T00:00:00+00:00"
    assert current["relations"][0]["evidence"][0]["document_id"] == document_id

    conflicting_id = _ingest(
        service,
        filename="cursor-pricing-independent.md",
        text="# Pricing\n\nAn independent current listing says Cursor Teams costs $50 per month.",
        product="Cursor",
        dimension="pricing",
        source_uri="https://pricing.example/cursor",
        observed_at="2026-08-02T00:00:00+00:00",
    )
    conflict = service.graph("owner", relation_type="priced_at")
    assert {relation["target_name"] for relation in conflict["relations"]} == {
        "$45 per month",
        "$50 per month",
    }
    assert conflict["stats"]["conflict_count"] == 2

    service.review_document(
        "owner",
        conflicting_id,
        "rejected",
        feedback_type="conflict",
        reason="Contradicts the current official page",
    )
    governed = service.graph("owner", relation_type="priced_at")
    assert [relation["target_name"] for relation in governed["relations"]] == ["$45 per month"]
    assert governed["stats"]["conflict_count"] == 0


def test_graphrag_context_requires_linked_raw_evidence_for_factual_use(tmp_path):
    service = build_service(tmp_path)
    _ingest(
        service,
        filename="cursor-github.md",
        text="# GitHub integration\n\nCursor integrates with GitHub for repository workflows.",
        product="Cursor",
        dimension="technology",
        source_uri="https://docs.cursor.com/integrations/github",
        observed_at="2026-08-01T00:00:00+00:00",
    )
    state = {
        "user_id": "owner",
        "thread_id": "current-analysis",
        "user_request": "Compare how Cursor and Codex integrate with GitHub",
        "target_products": ["Cursor", "OpenAI Codex"],
        "analysis_brief": {
            "target_products": ["Cursor", "OpenAI Codex"],
            "effective_dimensions": [{"id": "technology"}],
        },
    }
    points = service.retrieve_for_analysis(state)
    context, plan = service.retrieve_relationship_context(state, points)
    assert plan["route"] == "hybrid_graph"
    linked = next(item for item in context if item["relation_type"] == "integrates_with")
    assert linked["citation_eligible"] is True
    assert linked["evidence_status"] == "linked"
    assert linked["source_data_point_ids"]

    navigation, _ = service.retrieve_relationship_context(state, [])
    navigation_relation = next(item for item in navigation if item["relation_type"] == "integrates_with")
    assert navigation_relation["citation_eligible"] is False
    assert navigation_relation["usage_policy"] == ("planning_only_until_source_evidence_is_retrieved")


def test_report_nodes_are_planning_only_and_current_thread_is_excluded(tmp_path):
    service = build_service(tmp_path)
    report = {
        "title": "Cursor and Codex ecosystem comparison",
        "products": ["Cursor", "OpenAI Codex"],
        "sections": [
            {
                "id": "ecosystem",
                "content": "The prior report compared GitHub integration ecosystems.",
            }
        ],
        "quality_gate": {"status": "pass", "blocking_count": 0},
        "quality_summary": {"overall_quality_score": 0.9},
        "claim_verification": {"groundedness": 0.9, "citation_precision": 0.9},
    }
    registration = service.register_report_snapshot(
        user_id="owner",
        thread_id="historical-report",
        version=1,
        report_data=report,
    )
    service.process_job(registration["job"]["job_id"])
    graph = service.graph("owner", temporal_mode="all")
    report_relation = next(relation for relation in graph["relations"] if relation["relation_type"] == "summarized_in")
    assert report_relation["target_type"] == "report"
    assert report_relation["citation_eligible"] is False

    base_state = {
        "user_id": "owner",
        "user_request": "Compare Cursor and Codex ecosystem relationships",
        "target_products": ["Cursor", "OpenAI Codex"],
    }
    historical_context, _ = service.retrieve_relationship_context({**base_state, "thread_id": "new-report"}, [])
    prior = next(item for item in historical_context if item["relation_type"] == "summarized_in")
    assert prior["citation_eligible"] is False
    assert prior["usage_policy"] == "planning_only_until_source_evidence_is_retrieved"
    current_context, _ = service.retrieve_relationship_context({**base_state, "thread_id": "historical-report"}, [])
    assert all(item["relation_type"] != "summarized_in" for item in current_context)


def test_graph_permissions_rebuild_and_api_contracts(tmp_path):
    service = build_service(tmp_path)
    space = service.create_space("owner", name="Graph project", require_approval=False)
    service.set_space_member("owner", space["space_id"], "editor", "editor")
    service.set_space_member("owner", space["space_id"], "viewer", "viewer")
    _ingest(
        service,
        filename="feature.md",
        text="# Agent review\n\nCursor provides repository-wide agent review.",
        product="Cursor",
        dimension="features",
        source_uri="https://cursor.com/features",
        observed_at="2026-08-01T00:00:00+00:00",
        space_id=space["space_id"],
    )
    assert service.graph("viewer", space_id=space["space_id"])["relations"]
    with pytest.raises(PermissionError):
        service.rebuild_graph("viewer", space["space_id"])
    rebuilt = service.rebuild_graph("editor", space["space_id"])
    assert rebuilt["evidence_rebuilt"] >= 1
    assert rebuilt["graph"]["relations"]
    with pytest.raises(PermissionError):
        service.graph("outsider", space_id=space["space_id"])

    from app.competition_router import router

    contracts = {(route.path, method) for route in router.routes for method in route.methods or []}
    assert ("/api/competition/knowledge/graph", "GET") in contracts
    assert ("/api/competition/knowledge/graph/rebuild", "POST") in contracts


def test_analyst_prompt_keeps_graph_navigation_separate_from_evidence():
    from competition.nodes.analyst import _build_analyst_task

    task = _build_analyst_task(
        {
            "user_request": "Compare Cursor and Codex integrations",
            "target_products": ["Cursor", "OpenAI Codex"],
            "collected_data": [{"id": "dp-1", "category": "technology"}],
            "relationship_context": [
                {
                    "id": "graph-rel-1",
                    "relation_type": "integrates_with",
                    "citation_eligible": True,
                    "source_data_point_ids": ["dp-1"],
                },
                {
                    "id": "graph-rel-2",
                    "relation_type": "associated_with",
                    "citation_eligible": False,
                    "evidence_status": "navigation_only",
                },
            ],
        }
    )
    assert "RELATIONSHIP GRAPH RULES" in task
    assert "graph-rel-1" in task
    assert "source_data_point_ids" in task
    assert "navigation_only relationships are leads" in task


def test_relation_governance_survives_rebuild_and_records_audit(tmp_path):
    service = build_service(tmp_path)
    _ingest(
        service,
        filename="cursor-feature.md",
        text="# Agent review\n\nCursor provides repository-wide agent review.",
        product="Cursor",
        dimension="features",
        source_uri="https://cursor.com/features",
        observed_at="2026-08-01T00:00:00+00:00",
    )
    graph = service.graph("owner")
    relation = graph["relations"][0]
    edited = service.review_relation(
        "owner",
        relation["relation_id"],
        action="override",
        statement="Human-reviewed repository-wide review capability.",
        reason="Confirmed against product documentation",
    )
    rebuilt = service.rebuild_graph("owner", relation["space_id"])
    persisted = next(item for item in rebuilt["graph"]["relations"] if item["relation_id"] == relation["relation_id"])
    assert persisted["statement"] == edited["statement"]
    assert persisted["metadata"]["governance"]["manual_override"] is True
    audits = service.relation_audits("owner", relation_id=relation["relation_id"])
    assert audits[0]["action"] == "override"


def test_rejected_relation_is_excluded_and_hypothesis_has_lifecycle(tmp_path):
    service = build_service(tmp_path)
    _ingest(
        service,
        filename="cursor-feature.md",
        text="# Agent review\n\nCursor provides repository-wide agent review.",
        product="Cursor",
        dimension="features",
        source_uri="https://cursor.com/features",
        observed_at="2026-08-01T00:00:00+00:00",
    )
    relation = next(item for item in service.graph("owner")["relations"] if item["relation_type"] == "provides")
    service.review_relation("owner", relation["relation_id"], action="reject", reason="Unsupported wording")
    assert all(item["relation_id"] != relation["relation_id"] for item in service.graph("owner")["relations"])
    hypothesis = service.create_hypothesis(
        "owner",
        title="Potential enterprise adoption signal",
        statement="The feature may reduce enterprise review cost.",
        relation_id=relation["relation_id"],
    )
    assert hypothesis["status"] == "proposed"
    validated = service.transition_hypothesis("owner", hypothesis["hypothesis_id"], "validated", notes="Confirmed in workshop")
    assert validated["status"] == "validated"


def test_collector_carries_relationship_context_and_evidence_policy(monkeypatch):
    from competition.nodes import collector

    relationship = {
        "id": "graph-rel-1",
        "relation_type": "integrates_with",
        "citation_eligible": False,
        "evidence_status": "navigation_only",
        "source_data_point_ids": [],
    }
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        collector,
        "_retrieve_local_knowledge",
        lambda state: (
            [],
            {"status": "empty", "graph_retrieval": {"route": "hybrid_graph"}},
            [],
            [],
            [relationship],
        ),
    )
    monkeypatch.setattr(collector, "_run_searches", lambda state: "")
    monkeypatch.setattr(
        collector,
        "_execute_collector",
        lambda task, state: (captured.setdefault("task", task) and "[]", 0),
    )
    monkeypatch.setattr(collector, "_get_search_info", lambda: {})
    monkeypatch.setattr(
        collector,
        "_persist_intelligence_items",
        lambda state, points: {"inserted": 0},
    )

    result = collector.collector_node(
        {
            "user_request": "Compare Cursor and Codex integrations",
            "target_products": ["Cursor", "OpenAI Codex"],
        }
    )
    assert result["relationship_context"] == [relationship]
    assert result["collection_summary"]["rag_retrieval"]["graph_retrieval"]["route"] == "hybrid_graph"
    assert "navigation-only relationships must trigger fresh collection" in captured["task"]
