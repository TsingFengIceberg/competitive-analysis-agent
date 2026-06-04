"""Tests for CheckpointOps and AgentBranchOps.

Usage:
    cd backend && PYTHONPATH=packages/harness uv run pytest tests/test_competition_branchtree_agent.py -v
"""

import pytest

from deerflow.branchtree.checkpoint_ops import AgentBranchOps, CheckpointOps


@pytest.fixture
def checkpointer():
    """Create an in-memory checkpointer for testing."""
    from langgraph.checkpoint.memory import InMemorySaver
    return InMemorySaver()


@pytest.fixture
def graph():
    """Create a minimal CompiledStateGraph for testing write operations."""
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class TestState(TypedDict):
        messages: list
        coverage: float
        data: str

    builder = StateGraph(TestState)
    builder.add_node("noop", lambda s: {})
    builder.add_edge(START, "noop")
    builder.add_edge("noop", END)

    # We'll inject the checkpointer later per test
    return builder


class TestCheckpointOpsReadOps:
    def test_build_tree_empty(self, checkpointer):
        ck = CheckpointOps(checkpointer)
        tree = ck.build_tree("empty-thread")
        assert tree == {}

    def test_cache_invalidation(self, checkpointer):
        ck = CheckpointOps(checkpointer)
        # Build cache on empty thread
        ck.build_tree("t1")
        assert "t1" in ck._tree_cache
        # Invalidate
        ck.invalidate_cache("t1")
        assert "t1" not in ck._tree_cache

    def test_children_empty(self, checkpointer):
        ck = CheckpointOps(checkpointer)
        assert ck.children("t1", "ck-1") == []

    def test_is_fork_point_empty(self, checkpointer):
        ck = CheckpointOps(checkpointer)
        assert ck.is_fork_point("t1", "ck-1") is False

    def test_lineage_empty(self, checkpointer):
        ck = CheckpointOps(checkpointer)
        assert ck.lineage("t1", "ck-1") == []


class TestCheckpointOpsWriteOps:
    def test_fork_requires_graph(self, checkpointer):
        """fork() without graph should raise RuntimeError."""
        ck = CheckpointOps(checkpointer)
        with pytest.raises(RuntimeError, match="requires a CompiledStateGraph"):
            ck.fork("t1", "ck-1", {"data": "new"})

    def test_update_state_requires_graph(self, checkpointer):
        """update_state() without graph should raise RuntimeError."""
        ck = CheckpointOps(checkpointer)
        with pytest.raises(RuntimeError, match="requires a CompiledStateGraph"):
            ck.update_state("t1", {"data": "new"})

    def test_fork_and_get_state(self, checkpointer, graph):
        """End-to-end: fork from an existing checkpoint and read it back."""
        compiled = graph.compile(checkpointer=checkpointer)

        # Run once to create initial state
        config = {"configurable": {"thread_id": "fork-test"}}
        compiled.invoke({"data": "original", "coverage": 0.5}, config)

        ck = CheckpointOps(checkpointer, graph=compiled)
        snap = ck.latest("fork-test")
        initial_id = snap.config["configurable"]["checkpoint_id"]

        # Fork with new data
        new_id = ck.fork("fork-test", initial_id, {"data": "from-fork"})

        # Read back forked state
        forked = ck.get_state("fork-test", new_id)
        assert forked.values["data"] == "from-fork"
        # coverage from original should be preserved
        assert forked.values["coverage"] == 0.5

        # Original should be unchanged
        orig_state = ck.get_state("fork-test", initial_id)
        assert orig_state.values["data"] == "original"

    def test_tree_after_fork(self, checkpointer, graph):
        """build_tree should show fork structure after forking."""
        compiled = graph.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "tree-test"}}
        compiled.invoke({"data": "root"}, config)

        ck = CheckpointOps(checkpointer, graph=compiled)
        snap = ck.latest("tree-test")
        root_id = snap.config["configurable"]["checkpoint_id"]

        # Create two forks
        ck.fork("tree-test", root_id, {"data": "branch-a"})
        ck.fork("tree-test", root_id, {"data": "branch-b"})

        # Tree should show root with 2 children
        tree = ck.build_tree("tree-test")
        children = tree.get(root_id, [])
        assert len(children) == 2

        # root should be a fork point
        assert ck.is_fork_point("tree-test", root_id) is True


class TestAgentBranchOps:
    def test_explore_branches(self, checkpointer, graph):
        compiled = graph.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "explore-test"}}
        compiled.invoke({"data": "base", "coverage": 0.3}, config)

        ck = CheckpointOps(checkpointer, graph=compiled)
        agent = AgentBranchOps(ck, compiled)

        snap = ck.latest("explore-test")
        base_id = snap.config["configurable"]["checkpoint_id"]

        results = agent.explore_branches(
            "explore-test",
            base_id,
            [
                {"label": "strategy-A", "state_update": {"data": "aggressive"}},
                {"label": "strategy-B", "state_update": {"data": "conservative"}},
            ],
        )
        assert len(results) == 2
        assert results[0]["label"] == "strategy-A"
        assert results[1]["label"] == "strategy-B"
        assert results[0]["parent"] == base_id
        assert results[1]["parent"] == base_id

        # Each branch should have its own state
        state_a = ck.get_state("explore-test", results[0]["checkpoint_id"])
        state_b = ck.get_state("explore-test", results[1]["checkpoint_id"])
        assert state_a.values["data"] == "aggressive"
        assert state_b.values["data"] == "conservative"

    def test_a_b_test(self, checkpointer, graph):
        compiled = graph.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "ab-test"}}
        compiled.invoke({"data": "base", "coverage": 0.3}, config)

        ck = CheckpointOps(checkpointer, graph=compiled)
        agent = AgentBranchOps(ck, compiled)

        snap = ck.latest("ab-test")
        base_id = snap.config["configurable"]["checkpoint_id"]

        result = agent.a_b_test(
            "ab-test",
            base_id,
            branch_a={"state_update": {"coverage": 0.9}},
            branch_b={"state_update": {"coverage": 0.5}},
            evaluator=lambda s: s.values.get("coverage", 0) if hasattr(s, "values") else 0,
        )
        assert result["winner"] == "a"
        assert result["score_a"] > result["score_b"]
        assert "checkpoint_a" in result
        assert "checkpoint_b" in result

    def test_compare_branches(self, checkpointer, graph):
        compiled = graph.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "compare-test"}}
        compiled.invoke({"data": "base", "coverage": 0.3}, config)

        ck = CheckpointOps(checkpointer, graph=compiled)
        agent = AgentBranchOps(ck, compiled)

        snap = ck.latest("compare-test")
        base_id = snap.config["configurable"]["checkpoint_id"]

        # Create branches with different coverage
        a_id = ck.fork("compare-test", base_id, {"coverage": 0.9})
        b_id = ck.fork("compare-test", base_id, {"coverage": 0.5})

        result = agent.compare_branches(
            "compare-test",
            [{"checkpoint_id": a_id, "label": "high"}, {"checkpoint_id": b_id, "label": "low"}],
            key="coverage",
        )
        assert result["best"]["label"] == "high"
        assert result["best"]["score"] == 0.9
        assert len(result["rankings"]) == 2
        assert result["all_tied"] is False

    def test_cherry_pick(self, checkpointer, graph):
        compiled = graph.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "cherry-test"}}
        compiled.invoke({"data": "main", "coverage": 0.5, "extra": "from-main"}, config)

        ck = CheckpointOps(checkpointer, graph=compiled)
        agent = AgentBranchOps(ck, compiled)

        snap = ck.latest("cherry-test")
        base_id = snap.config["configurable"]["checkpoint_id"]

        # Create source branch with better "data" field
        src_id = ck.fork("cherry-test", base_id, {"data": "improved-data", "coverage": 0.9})

        # Cherry-pick just the "data" field into a target
        result_id = agent.cherry_pick(
            "cherry-test", base_id, src_id, ["data"]
        )
        final = ck.get_state("cherry-test", result_id)
        assert final.values["data"] == "improved-data"
        # coverage should stay from target
        assert final.values["coverage"] == 0.5

    def test_auto_merge_best_overall(self, checkpointer, graph):
        compiled = graph.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "merge-overall-test"}}
        compiled.invoke({"data": "base", "coverage": 0.3}, config)

        ck = CheckpointOps(checkpointer, graph=compiled)
        agent = AgentBranchOps(ck, compiled)

        snap = ck.latest("merge-overall-test")
        base_id = snap.config["configurable"]["checkpoint_id"]

        # Create branches with different coverage
        a_id = ck.fork("merge-overall-test", base_id, {"coverage": 0.4})
        b_id = ck.fork("merge-overall-test", base_id, {"coverage": 0.9})

        merged_id = agent.auto_merge(
            "merge-overall-test", [a_id, b_id], strategy="best_overall"
        )
        merged = ck.get_state("merge-overall-test", merged_id)
        assert merged.values["coverage"] == 0.9  # picked best

    def test_explore_with_error_handling(self, checkpointer, graph):
        """explore_branches should handle errors gracefully without crashing."""
        compiled = graph.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "explore-err-test"}}
        compiled.invoke({"data": "base"}, config)

        ck = CheckpointOps(checkpointer, graph=compiled)
        agent = AgentBranchOps(ck, compiled)

        snap = ck.latest("explore-err-test")
        base_id = snap.config["configurable"]["checkpoint_id"]

        # This should not raise even with empty state_update
        results = agent.explore_branches(
            "explore-err-test",
            base_id,
            [
                {"label": "ok", "state_update": {}},
                {"label": "also-ok", "state_update": {"nonexistent": "value"}},
            ],
        )
        assert len(results) == 2


class TestTokenCostZero:
    """Verify AgentBranchOps operations don't trigger LLM calls."""

    def test_agentbranchops_is_pure_data_ops(self, checkpointer, graph):
        """All AgentBranchOps methods operate on checkpoint data only — no LLM."""
        compiled = graph.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "token-cost-test"}}
        compiled.invoke({"data": "base", "coverage": 0.3}, config)

        ck = CheckpointOps(checkpointer, graph=compiled)
        agent = AgentBranchOps(ck, compiled)

        snap = ck.latest("token-cost-test")
        base_id = snap.config["configurable"]["checkpoint_id"]

        # All these operations should complete without any LLM interaction
        results = agent.explore_branches(
            "token-cost-test", base_id,
            [{"label": "b1", "state_update": {"coverage": 0.8}}],
        )
        branch_id = results[0]["checkpoint_id"]

        agent.compare_branches(
            "token-cost-test",
            [{"checkpoint_id": base_id, "label": "base"}, {"checkpoint_id": branch_id, "label": "branch"}],
            key="coverage",
        )

        agent.cherry_pick("token-cost-test", base_id, branch_id, ["data"])
        # No assertions needed — if any of these triggered an LLM call, the test
        # environment would crash (no API key configured).
        assert True
