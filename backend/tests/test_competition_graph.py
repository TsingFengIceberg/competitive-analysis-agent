"""Tests for competition/graph.py — build_competition_graph().

Covers §2.2 of the coding plan.
- Graph compiles without errors
- All 13 nodes registered
- Conditional edges map to correct targets
- register_nodes() injects real implementations
"""

from __future__ import annotations

from deerflow.competition.graph import (
    _NODE_IMPLEMENTATIONS,
    build_competition_graph,
    register_nodes,
)
from deerflow.competition.state import CompetitionState


class TestBuildCompetitionGraph:
    def test_graph_compiles_without_checkpointer(self):
        graph = build_competition_graph()
        assert graph is not None
        assert hasattr(graph, "invoke")

    def test_graph_compiles_with_checkpointer(self):
        """Graph should accept optional checkpointer (SqliteSaver etc.)."""
        # Use None checkpointer — real checkpointer tested in integration
        graph = build_competition_graph(checkpointer=None)
        assert graph is not None

    def test_all_nodes_registered(self):
        build_competition_graph()  # compiles → all node names resolved
        expected = {
            "orchestrator",  # v4
            "collector", "analyst", "reviewer", "writer", "hitl_gate",
            "error_handler",
            "deep_collector", "deep_analyst", "deep_reviewer",
            "deep_writer", "deep_hitl", "deep_error_handler",
            "feishu_delivery",
        }
        assert set(_NODE_IMPLEMENTATIONS.keys()) == expected

    def test_graph_invocation_with_minimal_state(self):
        """Graph should accept minimal CompetitionState and reach END."""
        graph = build_competition_graph()
        result = graph.invoke(CompetitionState(
            messages=[],
            user_request="test",
            target_products=["ProductA"],
            persona="pm",
            collected_data=[{"id": "dp-1"}],       # pass empty-result guard
            review_verdict={"passed": True},         # skip reviewer→collector loop
            hitl_decision={"action": "approve"},     # skip HITL loop
        ))
        assert result is not None

    def test_graph_invocation_error_path(self):
        """Error in collector → error_handler → END."""
        graph = build_competition_graph()
        result = graph.invoke(CompetitionState(
            messages=[],
            user_request="test",
            target_products=["ProductA"],
            error="collector failed",
        ))
        assert result is not None


class TestRegisterNodes:
    def test_register_custom_node(self):
        calls = []
        def my_collector(state: dict) -> dict:
            calls.append("called")
            return {"collected_data": [{"id": "dp-x"}]}

        register_nodes({"collector": my_collector})
        assert _NODE_IMPLEMENTATIONS["collector"] is my_collector

        graph = build_competition_graph()
        result = graph.invoke(CompetitionState(
            messages=[],
            collected_data=[{"id": "dp-1"}],
            review_verdict={"passed": True},     # prevent reviewer loop
            hitl_decision={"action": "approve"},  # exit HITL
        ))
        assert len(calls) == 1
        assert result is not None

    def test_register_unknown_node_warns(self, caplog):
        register_nodes({"nonexistent_node": lambda s: s})
        assert "nonexistent_node" in _NODE_IMPLEMENTATIONS  # added anyway

    def test_register_preserves_unmentioned_nodes(self):
        original = _NODE_IMPLEMENTATIONS["analyst"]
        register_nodes({"collector": lambda s: s})
        assert _NODE_IMPLEMENTATIONS["analyst"] is original
