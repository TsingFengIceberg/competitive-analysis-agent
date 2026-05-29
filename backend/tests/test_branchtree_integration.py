"""Integration tests: BranchTree + CheckpointOps + Store with real InMemorySaver.

Simulates a full competition analysis flow with multiple HITL fork versions.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.branchtree.adapter import BranchTreeAdapter
from deerflow.branchtree.checkpoint_ops import CheckpointOps
from deerflow.branchtree.deliverable_tree import DeliverableTree
from deerflow.branchtree.store import BranchSnapshotStore

# ── Helpers ────────────────────────────────────────────────────


def _put_checkpoint(saver, thread_id, ck_id, parent_ck_id, channel_values):
    """Put a checkpoint into InMemorySaver with proper parent relationship.

    Uses unique version per checkpoint to prevent blob overwrites in InMemorySaver.
    """
    versions = {k: f"{ck_id}_{k}" for k in channel_values}
    saver.put(
        {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": parent_ck_id,
            },
        },
        {
            "v": 1,
            "id": ck_id,
            "ts": f"2026-01-01T00:00:0{ck_id[-1]}",
            "channel_values": channel_values,
            "channel_versions": versions,
            "versions_seen": {},
        },
        {"source": "loop", "step": 1},
        versions,
    )


# ── Integration: CheckpointOps with real InMemorySaver ─────────


class TestCheckpointOpsWithInMemorySaver:
    """Verify CheckpointOps correctly reads InMemorySaver's data."""

    @pytest.fixture
    def ck(self):
        saver = InMemorySaver()
        _put_checkpoint(saver, "t1", "ck1", None, {"round": 1})
        _put_checkpoint(saver, "t1", "ck2", "ck1", {"round": 2})
        _put_checkpoint(saver, "t1", "ck3", "ck2", {"round": 3})
        # Fork: ck4 also from ck2
        _put_checkpoint(saver, "t1", "ck4", "ck2", {"round": 3, "branch": "fork"})
        return CheckpointOps(saver)

    def test_build_tree_structure(self, ck):
        tree = ck.build_tree("t1")
        assert tree[None] == ["ck1"]
        assert sorted(tree["ck2"]) == ["ck3", "ck4"]  # fork point
        assert tree.get("ck3", []) == []
        assert tree.get("ck4", []) == []

    def test_children_fork_point(self, ck):
        assert sorted(ck.children("t1", "ck2")) == ["ck3", "ck4"]

    def test_is_fork_point(self, ck):
        assert ck.is_fork_point("t1", "ck2") is True
        assert ck.is_fork_point("t1", "ck1") is False

    def test_lineage(self, ck):
        chain = ck.lineage("t1", "ck4")
        assert chain == ["ck1", "ck2", "ck4"]

    def test_get_state_latest(self, ck):
        state = ck.get_state("t1")
        assert state.values["round"] == 3

    def test_get_state_specific(self, ck):
        state = ck.get_state("t1", "ck2")
        assert state.values["round"] == 2

    def test_cache_then_rebuild(self, ck):
        ck.build_tree("t1")
        tree1 = ck.build_tree("t1")  # cache hit
        ck.invalidate_cache("t1")
        tree2 = ck.build_tree("t1")  # rebuild
        assert tree1 == tree2


# ── Integration: BranchTree + Store full round-trip ────────────


class TestBranchTreeRoundTrip:
    """Full DeliverableTree + Store cycle: simulate a real competition flow."""

    @pytest.fixture
    def setup(self):
        saver = InMemorySaver()
        store = BranchSnapshotStore(":memory:")
        tree = DeliverableTree(saver, store)

        # Simulate initial analysis: put checkpoints for collector → analyst → writer
        _put_checkpoint(saver, "t1", "c1", None, {
            "collected_data": [{"url": "a.com"}],
            "report_data": None,
        })
        _put_checkpoint(saver, "t1", "c2", "c1", {
            "collected_data": [{"url": "a.com"}],
            "analysis_result": {"swot": {"strengths": ["speed"]}},
            "report_data": None,
        })
        _put_checkpoint(saver, "t1", "c3", "c2", {
            "collected_data": [{"url": "a.com"}],
            "analysis_result": {"swot": {"strengths": ["speed"]}},
            "report_data": {"title": "初始分析", "overview": "v1内容"},
            "hitl_decision": None,
        })

        return saver, store, tree

    def test_full_snapshot_fork_flow(self, setup):
        saver, store, tree = setup
        adapter = BranchTreeAdapter(tree, store)

        # --- Step 1: Initial snapshot ---
        tree.load("t1")
        # The initial checkpoint exists in saver but not in store yet
        assert store.list_by_thread("t1") == []

        # Manually record initial version (mimics what competition flow does)
        v1 = store.insert("t1", None, "c3", "initial", {"persona": "PM"})
        assert v1 == 1

        # --- Step 2: User clicks "rewrite" → fork from v1 ---
        # In real flow, this would call CheckpointOps.fork(), but we need a graph for that.
        # Here we simulate the fork by putting a new checkpoint manually.
        _put_checkpoint(saver, "t1", "c4", "c3", {
            "collected_data": [{"url": "a.com"}],
            "analysis_result": {"swot": {"strengths": ["speed"]}},
            "report_data": {"title": "PM视角重写", "overview": "v2内容"},
        })
        v2 = store.insert("t1", v1, "c4", "rewrite", {"persona": "PM"})
        assert v2 == 2

        # --- Step 3: User goes back to v1, clicks "recollect" → fork ---
        _put_checkpoint(saver, "t1", "c5", "c3", {
            "collected_data": [{"url": "a.com"}, {"url": "b.com"}],
            "analysis_result": {"swot": {"strengths": ["speed", "price"]}},
            "report_data": {"title": "重新采集版本", "overview": "v3内容"},
        })
        v3 = store.insert("t1", v1, "c5", "recollect")
        assert v3 == 3

        # --- Step 4: Load into BranchTree and verify ---
        tree.load("t1")
        assert tree.current_version() == 3

        # Verify tree structure: v1 → v2, v1 → v3
        v1_node = tree.get_node(1)
        assert v1_node is not None
        assert sorted(v1_node.children) == ["v2", "v3"]
        assert v1_node.is_fork_point is True

        # Verify lineage
        chain = tree.lineage(3)
        assert [n.node_id for n in chain] == ["v1", "v3"]

        # --- Step 5: Approve v3 ---
        store.approve("t1", 3)
        assert store.is_approved("t1", 3) is True
        assert store.is_approved("t1", 1) is False

        # --- Step 6: Adapter get_history ---
        history = adapter.get_history("t1")
        assert len(history) == 3
        assert history[0]["version"] == 1
        assert history[0]["report_data"]["title"] == "初始分析"
        assert history[1]["report_data"]["title"] == "PM视角重写"
        assert history[2]["report_data"]["title"] == "重新采集版本"

    def test_restore_returns_state(self, setup):
        saver, store, tree = setup

        store.insert("t1", None, "c3", "initial")
        tree.load("t1")
        state = tree.restore("t1", 1)
        assert state["report_data"]["title"] == "初始分析"
        assert state["analysis_result"]["swot"]["strengths"] == ["speed"]

    def test_to_dict_for_frontend(self, setup):
        saver, store, tree = setup

        store.insert("t1", None, "c3", "initial")
        store.insert("t1", 1, "c4", "rewrite")
        store.insert("t1", 1, "c5", "recollect")

        tree.load("t1")
        d = tree.to_dict()
        assert d["root"] == "v1"
        assert len(d["nodes"]) == 3

    def test_diff_between_versions(self, setup):
        saver, store, tree = setup

        store.insert("t1", None, "c3", "initial")

        from deerflow.branchtree.diff import snapshot_diff

        # Put two versions with different data, diff them
        _put_checkpoint(saver, "t1", "c3_alt", "c3", {
            "collected_data": [{"url": "a.com"}],
            "analysis_result": {"swot": {"strengths": ["speed"]}},
            "report_data": {"title": "版本A", "overview": "内容A"},
        })
        store.insert("t1", 1, "c3_alt", "rewrite")

        tree.load("t1")
        state_v1 = tree.restore("t1", 1)
        state_v2 = tree.restore("t1", 2)
        diff = snapshot_diff(state_v1, state_v2)
        assert "report_data" in str(diff["fields"]) or diff["report_sections"]
