"""Tests for competition/dag.py — DAG state extraction."""

from __future__ import annotations

from deerflow.competition.dag import (
    DAG_TOPOLOGY,
    _compute_edge_annotation,
    _compute_node_annotation,
    _compute_node_status,
    _infer_current_node,
    _is_edge_active,
    _node_style,
    get_dag_state,
)


class TestTopology:
    def test_all_nodes_have_ids(self):
        ids = {n["id"] for n in DAG_TOPOLOGY["nodes"]}
        assert len(ids) == 14  # v4: +orchestrator

    def test_edges_have_valid_refs(self):
        node_ids = {n["id"] for n in DAG_TOPOLOGY["nodes"]} | {"__end__"}
        for edge in DAG_TOPOLOGY["edges"]:
            assert edge["from"] in node_ids
            assert edge["to"] in node_ids

    def test_feedback_edges_exist(self):
        """Reviewer→Collector and HITL→Collector/Analyst/Writer feedback loops."""
        feedback_edges = [e for e in DAG_TOPOLOGY["edges"] if e.get("type") in ("feedback", "deep_feedback")]
        assert len(feedback_edges) >= 2  # r2c + dr2dc


class TestInferCurrentNode:
    def test_empty_state(self):
        assert _infer_current_node({}) == "orchestrator"  # v4: Orchestrator first

    def test_orchestrator_done(self):
        assert _infer_current_node({"orchestration_result": {"complexity": "standard"}}) == "collector"

    def test_collector_done(self):
        assert _infer_current_node({
            "orchestration_result": {"complexity": "standard"},
            "collected_data": [{"id": "1"}],
        }) == "analyst"

    def test_analyst_done(self):
        assert _infer_current_node({
            "orchestration_result": {"complexity": "standard"},
            "collected_data": [{"id": "1"}],
            "analysis_result": {"comparison_matrix": {}},
        }) == "reviewer"

    def test_error_state(self):
        assert _infer_current_node({"error": "crashed"}) == "error_handler"

    def test_all_done(self):
        state = {
            "orchestration_result": {"complexity": "standard"},
            "collected_data": [{"id": "1"}],
            "analysis_result": {"comparison_matrix": {"products": ["A"]}},
            "review_verdict": {"passed": True},
            "report_data": {"title": "Test"},
            "hitl_decision": {"action": "approve"},
        }
        assert _infer_current_node(state) is None


class TestComputeNodeStatus:
    def test_collector_active(self):
        assert _compute_node_status("collector", {}, "collector", None) == "active"

    def test_collector_done(self):
        assert _compute_node_status("collector", {"collected_data": [{}]}, "analyst", None) == "done"

    def test_hitl_pending(self):
        assert _compute_node_status("hitl_gate", {"hitl_decision": {"action": "replan"}}, "hitl_gate", None) == "hitl_pending"

    def test_error_active(self):
        assert _compute_node_status("error_handler", {"error": "x"}, "error_handler", "x") == "active"

    def test_deep_hidden_in_normal(self):
        """Deep nodes are 'waiting' (hidden) in normal mode."""
        assert _compute_node_status("deep_collector", {}, "collector", None) == "waiting"


class TestNodeAnnotation:
    def test_collector_annotation(self):
        ann = _compute_node_annotation("collector", {
            "collected_data": [{}, {}],
            "collection_summary": {"stopped_by": "soft_stop"},
        })
        assert "2 data points" in ann
        assert "soft_stop" in ann

    def test_reviewer_gaps(self):
        ann = _compute_node_annotation("reviewer", {
            "review_verdict": {"gaps": [{}, {}]},
        })
        assert "2 gap" in ann


class TestEdgeAnnotation:
    def test_r2c_round(self):
        ann = _compute_edge_annotation({"id": "r2c"}, {"review_round": 1})
        assert "1/2" in ann

    def test_r2w_forced(self):
        ann = _compute_edge_annotation({"id": "r2w"}, {
            "review_verdict": {"passed": False},
            "review_round": 2,
        })
        assert "forced" in ann


class TestIsEdgeActive:
    def test_normal_flow(self):
        nodes = {
            "collector": {"status": "done"},
            "analyst": {"status": "active"},
        }
        assert _is_edge_active({"from": "collector", "to": "analyst", "type": "normal"}, nodes, {}) is True

    def test_deep_inactive_in_normal(self):
        nodes = {
            "hitl_gate": {"status": "done"},
            "deep_collector": {"status": "waiting"},
        }
        assert _is_edge_active({"from": "hitl_gate", "to": "deep_collector", "type": "deep"}, nodes, {}) is False

    def test_deep_active_in_deep(self):
        nodes = {
            "hitl_gate": {"status": "done"},
            "deep_collector": {"status": "active"},
        }
        assert _is_edge_active(
            {"from": "hitl_gate", "to": "deep_collector", "type": "deep"},
            nodes, {"deep_mode": True},
        ) is True


class TestNodeStyle:
    def test_all_styles_defined(self):
        for status in ("waiting", "active", "done", "error", "hitl_pending"):
            style = _node_style(status)
            assert "color" in style
            assert "icon" in style

    def test_active_has_animation(self):
        assert _node_style("active")["animation"] == "pulse"


class TestGetDagState:
    def test_returns_structure(self):
        state = get_dag_state({
            "orchestration_result": {"complexity": "standard"},
            "collected_data": [{"id": "1"}],
        })
        assert "nodes" in state
        assert "edges" in state
        assert "current_node" in state
        assert state["current_node"] == "analyst"

    def test_all_nodes_present(self):
        state = get_dag_state({})
        assert len(state["nodes"]) == 14  # v4: +orchestrator

    def test_summary(self):
        state = get_dag_state({
            "collected_data": [{}, {}, {}],
            "review_round": 1,
            "gap_coverage_improvement": 0.5,
        })
        assert state["summary"]["total_data_points"] == 3
        assert state["summary"]["improvement_ratio"] == 0.5
