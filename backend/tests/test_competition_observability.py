"""Tests for competition/observability.py — observability data extractors."""

from __future__ import annotations

from competition.observability import (
    get_agent_detail,
    get_all_agent_details,
    get_all_traceability_chains,
    get_message_flow,
    get_traceability_chain,
)


class TestAgentDetail:
    def test_collector_detail(self):
        detail = get_agent_detail({
            "user_request": "analyze Cursor",
            "target_products": ["Cursor"],
            "collected_data": [{"id": "1"}],
            "collection_summary": {"total_data_points": 1},
        }, "collector")
        assert detail["node_id"] == "collector"
        assert detail["status"] == "done"
        assert "user_request" in detail["input"]
        assert "collected_data" in detail["output"]

    def test_waiting_node(self):
        detail = get_agent_detail({}, "analyst")
        assert detail["status"] == "waiting"

    def test_all_details(self):
        details = get_all_agent_details({"collected_data": [{"id": "1"}]})
        assert len(details) == 6  # v4: +orchestrator
        ids = {d["node_id"] for d in details}
        assert "orchestrator" in ids
        assert "collector" in ids
        assert "writer" in ids

    def test_tools_inferred(self):
        detail = get_agent_detail({}, "collector")
        assert "web_search" in detail["tools_used"]

    def test_hitl_no_tools(self):
        detail = get_agent_detail({}, "hitl_gate")
        assert "(no tools" in detail["tools_used"][0]


class TestMessageFlow:
    def test_empty_state(self):
        flow = get_message_flow({})
        assert flow["total_messages"] == 0

    def test_collector_to_analyst(self):
        flow = get_message_flow({
            "collected_data": [{"id": "1", "product": "Cursor", "category": "pricing", "label": "Pro", "confidence": 0.9}],
        })
        assert flow["total_messages"] == 1
        assert flow["events"][0]["edge"] == "①"

    def test_feedback_loop_detected(self):
        flow = get_message_flow({
            "collected_data": [{"id": "1"}],
            "analysis_result": {"comparison_matrix": {}, "swot": {}},
            "review_verdict": {
                "passed": False,
                "gaps": [{"type": "missing_data", "severity": "major", "description": "missing X"}],
                "quality_summary": {},
            },
            "review_round": 1,
        })
        assert flow["feedback_loops"] == 1
        assert any(e.get("is_feedback_loop") for e in flow["events"])

    def test_full_flow(self):
        flow = get_message_flow({
            "collected_data": [{"id": "1"}],
            "analysis_result": {"comparison_matrix": {"cells": [], "dimensions": []}, "swot": {}},
            "review_verdict": {"passed": True, "quality_summary": {"total_data_points": 1}},
            "review_package": {"key_findings": ["finding 1"]},
            "hitl_decision": {"action": "approve"},
        })
        # 5 edges: ① Collector→Analyst, ② Analyst→Reviewer, ③ Reviewer→Writer, ④ Writer→HITL, ⑥ HITL→END
        # (No ⑤ because passed=True → no gap feedback loop)
        assert flow["total_messages"] == 5
        assert flow["feedback_loops"] == 0


class TestTraceabilityChain:
    def test_chain_found(self):
        chain = get_traceability_chain("1", {
            "traceability_map": {"1": {"url": "cursor.com", "timestamp": "2026-05-23", "confidence": 0.9}},
            "collected_data": [{"id": "dp-1", "source_url": "cursor.com", "collected_at": "2026-05-23", "confidence": 0.9}],
            "review_verdict": {"gaps": [], "quality_summary": {}},
        })
        assert chain is not None
        assert chain["source_url"] == "cursor.com"
        assert chain["data_point_id"] == "dp-1"

    def test_chain_not_found(self):
        assert get_traceability_chain("999", {"traceability_map": {}}) is None

    def test_chain_with_gaps(self):
        chain = get_traceability_chain("1", {
            "traceability_map": {"1": {"url": "a.com", "timestamp": "", "confidence": 0.5}},
            "collected_data": [{"id": "dp-1", "source_url": "a.com"}],
            "review_verdict": {"gaps": [
                {"type": "source_conflict", "description": "conflict", "related_data_point_ids": ["1"]},
            ]},
        })
        assert chain is not None
        assert "⚠" in chain["verification_status"]

    def test_all_chains(self):
        state = {
            "traceability_map": {
                "1": {"url": "a.com", "timestamp": "", "confidence": 0.9},
                "2": {"url": "b.com", "timestamp": "", "confidence": 0.8},
            },
            "collected_data": [
                {"id": "dp-1", "source_url": "a.com"},
                {"id": "dp-2", "source_url": "b.com"},
            ],
            "review_verdict": {"gaps": []},
        }
        chains = get_all_traceability_chains(state)
        assert len(chains) == 2
