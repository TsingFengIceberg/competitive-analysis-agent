"""Sprint 4 — HITL Gate unit tests.

Validates:
- build_approval_payload() structure and content
- _extract_key_findings() edge cases
- hitl_gate_node idempotency (existing review_decision)
- hitl_gate_node invalid decision handling
- HITL routing in parent graph
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deerflow.collaboration.state import CollaborationState


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_state(**overrides) -> CollaborationState:
    base: dict = {"messages": []}
    base.update(overrides)
    return base  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════════════════════════════
# build_approval_payload()
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildApprovalPayload:
    def test_returns_standard_fields(self):
        """审批包包含所有必要字段。"""
        from deerflow.collaboration.nodes.hitl_gate import build_approval_payload

        state = _make_state()
        payload = build_approval_payload(state)

        assert "message" in payload
        assert "decisions" in payload
        assert "summary" in payload
        assert "timestamp" in payload
        assert "stale_after_seconds" in payload

    def test_decisions_contain_three_options(self):
        """三个选项：approve / modify / replan。"""
        from deerflow.collaboration.nodes.hitl_gate import build_approval_payload

        state = _make_state()
        payload = build_approval_payload(state)

        decision_values = [d["value"] for d in payload["decisions"]]
        assert decision_values == ["approve", "modify", "replan"]

    def test_summary_includes_research_quality_score(self):
        from deerflow.collaboration.nodes.hitl_gate import build_approval_payload

        state = _make_state(research_quality_score=0.85)
        payload = build_approval_payload(state)
        assert payload["summary"]["research_quality_score"] == 0.85

    def test_summary_includes_verified_data_points(self):
        from deerflow.collaboration.nodes.hitl_gate import build_approval_payload

        state = _make_state(validated_brief={
            "verified_data_points": [{"id": 1}, {"id": 2}, {"id": 3}]
        })
        payload = build_approval_payload(state)
        assert payload["summary"]["verified_data_points"] == 3

    def test_summary_with_empty_state(self):
        from deerflow.collaboration.nodes.hitl_gate import build_approval_payload

        state = _make_state()
        payload = build_approval_payload(state)
        assert payload["summary"]["verified_data_points"] == 0
        assert payload["summary"]["research_quality_score"] is None

    def test_unresolved_issues_propagated(self):
        from deerflow.collaboration.nodes.hitl_gate import build_approval_payload

        state = _make_state(validated_brief={
            "unresolved": ["issue1", "issue2"]
        })
        payload = build_approval_payload(state)
        assert payload["summary"]["unresolved_issues"] == ["issue1", "issue2"]

    def test_stale_after_30_minutes(self):
        from deerflow.collaboration.nodes.hitl_gate import build_approval_payload

        state = _make_state()
        payload = build_approval_payload(state)
        assert payload["stale_after_seconds"] == 1800  # 30 minutes


# ═══════════════════════════════════════════════════════════════════════════════
# _extract_key_findings()
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractKeyFindings:
    def test_extracts_from_recommendations_dict(self):
        from deerflow.collaboration.nodes.hitl_gate import _extract_key_findings

        report = {"recommendations": [
            {"action": "降价 5%"},
            {"action": "加大营销投入"},
        ]}
        findings = _extract_key_findings(report)
        assert "降价 5%" in findings
        assert "加大营销投入" in findings

    def test_extracts_from_recommendations_string(self):
        from deerflow.collaboration.nodes.hitl_gate import _extract_key_findings

        report = {"recommendations": ["rec1", "rec2"]}
        findings = _extract_key_findings(report)
        assert "rec1" in findings
        assert "rec2" in findings

    def test_max_three_findings(self):
        from deerflow.collaboration.nodes.hitl_gate import _extract_key_findings

        report = {"recommendations": [
            {"action": "a"}, {"action": "b"}, {"action": "c"}, {"action": "d"}
        ]}
        findings = _extract_key_findings(report)
        assert len(findings) == 3

    def test_falls_back_to_executive_summary(self):
        from deerflow.collaboration.nodes.hitl_gate import _extract_key_findings

        report = {"executive_summary": "Summary text here"}
        findings = _extract_key_findings(report)
        assert len(findings) == 1
        assert "Summary text here" in findings

    def test_empty_report_returns_empty_list(self):
        from deerflow.collaboration.nodes.hitl_gate import _extract_key_findings

        findings = _extract_key_findings({})
        assert findings == []


# ═══════════════════════════════════════════════════════════════════════════════
# hitl_gate_node()
# ═══════════════════════════════════════════════════════════════════════════════


class TestHitlGateNode:
    def test_idempotent_existing_decision_returns_empty(self):
        """已有 review_decision → 跳过 interrupt → 返回 {}。"""
        from deerflow.collaboration.nodes.hitl_gate import hitl_gate_node

        state = _make_state(review_decision="approve")
        result = hitl_gate_node(state)
        assert result == {}

    def test_idempotent_existing_modify_decision(self):
        """已有 modify 决策 → 循环后重入，清除旧决策并重新 interrupt。

        modify/replan 触发子图重跑后会再次进入 HITL，此时应重新审批而非跳过。
        """
        from deerflow.collaboration.nodes.hitl_gate import hitl_gate_node

        state = _make_state(review_decision="modify")
        with patch("deerflow.collaboration.nodes.hitl_gate.interrupt", return_value="approve"):
            result = hitl_gate_node(state)
        assert result == {"review_decision": "approve"}

    def test_idempotent_existing_replan_decision(self):
        """已有 replan 决策 → 循环后重入，清除旧决策并重新 interrupt。"""
        from deerflow.collaboration.nodes.hitl_gate import hitl_gate_node

        state = _make_state(review_decision="replan")
        with patch("deerflow.collaboration.nodes.hitl_gate.interrupt", return_value="approve"):
            result = hitl_gate_node(state)
        assert result == {"review_decision": "approve"}

    def test_interrupt_called_with_approval_payload(self):
        """无 review_decision → 调用 interrupt() → 返回决定。"""
        from deerflow.collaboration.nodes.hitl_gate import hitl_gate_node

        state = _make_state()
        with patch(
            "deerflow.collaboration.nodes.hitl_gate.interrupt",
            return_value="approve",
        ) as mock_interrupt:
            result = hitl_gate_node(state)
            mock_interrupt.assert_called_once()
            # 验证 interrupt 接收的是审批包
            payload = mock_interrupt.call_args[0][0]
            assert "message" in payload
            assert "decisions" in payload
            assert "_stale_check" in payload
            assert result == {"review_decision": "approve"}

    def test_interrupt_returns_modify(self):
        from deerflow.collaboration.nodes.hitl_gate import hitl_gate_node

        state = _make_state()
        with patch(
            "deerflow.collaboration.nodes.hitl_gate.interrupt",
            return_value="modify",
        ):
            result = hitl_gate_node(state)
            assert result == {"review_decision": "modify"}

    def test_interrupt_returns_replan(self):
        from deerflow.collaboration.nodes.hitl_gate import hitl_gate_node

        state = _make_state()
        with patch(
            "deerflow.collaboration.nodes.hitl_gate.interrupt",
            return_value="replan",
        ):
            result = hitl_gate_node(state)
            assert result == {"review_decision": "replan"}

    def test_invalid_decision_returns_empty(self):
        """无效决定 → 返回 {}。"""
        from deerflow.collaboration.nodes.hitl_gate import hitl_gate_node

        state = _make_state()
        with patch(
            "deerflow.collaboration.nodes.hitl_gate.interrupt",
            return_value="invalid_value",
        ):
            result = hitl_gate_node(state)
            assert result == {}

    def test_stale_check_payload_includes_timestamps(self):
        import time
        from deerflow.collaboration.nodes.hitl_gate import hitl_gate_node, STALE_TIMEOUT_SECONDS

        state = _make_state()
        before = time.time()
        with patch(
            "deerflow.collaboration.nodes.hitl_gate.interrupt",
            return_value="approve",
        ) as mock_interrupt:
            hitl_gate_node(state)
            after = time.time()
            payload = mock_interrupt.call_args[0][0]
            stale = payload["_stale_check"]
            assert before <= stale["generated_at"] <= after
            assert stale["stale_after"] == STALE_TIMEOUT_SECONDS


# ═══════════════════════════════════════════════════════════════════════════════
# HITL Routing in Parent Graph
# ═══════════════════════════════════════════════════════════════════════════════


class TestHitlRouting:
    def test_approve_routes_to_report_composer(self):
        from deerflow.collaboration.router import route_after_hitl

        state = _make_state(review_decision="approve")
        assert route_after_hitl(state) == "report_composer"

    def test_modify_routes_to_analysis_subgraph(self):
        from deerflow.collaboration.router import route_after_hitl

        state = _make_state(review_decision="modify")
        assert route_after_hitl(state) == "analysis_subgraph"

    def test_replan_routes_to_research_subgraph(self):
        from deerflow.collaboration.router import route_after_hitl

        state = _make_state(review_decision="replan")
        assert route_after_hitl(state) == "research_subgraph"

    def test_missing_decision_routes_to_end(self):
        from deerflow.collaboration.router import route_after_hitl

        state = _make_state()
        from langgraph.constants import END
        assert route_after_hitl(state) == END


# ═══════════════════════════════════════════════════════════════════════════════
# Parent Graph with real HITL node
# ═══════════════════════════════════════════════════════════════════════════════


class TestParentGraphWithHitl:
    def test_graph_compiles_with_real_hitl_node(self):
        """验证 graph.py 已导入真实 hitl_gate_node（非 stub），可编译。"""
        from deerflow.collaboration.graph import build_collaboration_graph

        graph = build_collaboration_graph()
        nodes = graph.get_graph().nodes
        assert "hitl_gate" in nodes

    def test_hitl_node_not_not_implemented(self):
        """验证 hitl_gate_node 不再是 NotImplementedError stub。"""
        from deerflow.collaboration.nodes.hitl_gate import hitl_gate_node

        state = _make_state(review_decision="approve")
        result = hitl_gate_node(state)
        assert result == {}
