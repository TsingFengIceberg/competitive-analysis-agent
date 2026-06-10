"""Tests for BranchTreeAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock

from competition.branchtree.adapter import BranchTreeAdapter
from competition.branchtree.store import BranchSnapshotStore

# ── Fixtures ───────────────────────────────────────────────────


def _mock_tree():
    """Create a mock BranchTree with minimal behavior."""
    tree = MagicMock()
    tree.restore.return_value = {
        "report_data": {"title": "测试报告"},
        "analysis_result": {"swot": {}},
        "collected_data": [{"source": "url1"}],
    }
    tree.to_dict.return_value = {
        "nodes": [{"id": "v1", "action": "initial", "children": ["v2"]}],
        "root": "v1",
    }

    # Simulate snapshot: returns a mock BranchNode
    def _snapshot(thread_id, action, metadata=None):
        node = MagicMock()
        node.node_id = "v1"
        return node

    tree.snapshot.return_value = _snapshot(None, "initial")
    # Hmm, this won't work well. Let me rethink.
    return tree


def _adapter_with_data():
    """Create adapter with pre-populated store data."""
    store = BranchSnapshotStore(":memory:")
    # Insert some test versions
    v1 = store.insert("t1", None, "ck001", "initial")
    v2 = store.insert("t1", v1, "ck002", "rewrite")
    v3 = store.insert("t1", v1, "ck003", "recollect")  # fork from v1
    return store, v1, v2, v3


# ── Tests ──────────────────────────────────────────────────────


class TestHistory:
    def test_get_history_structure(self):
        store, v1, v2, v3 = _adapter_with_data()
        tree = MagicMock()
        # Mock restore to return state per version
        tree.restore.side_effect = lambda tid, ver: {
            1: {"report_data": {"title": "v1报告"}, "analysis_result": None, "collected_data": []},
            2: {"report_data": {"title": "v2报告"}, "analysis_result": None, "collected_data": []},
            3: {"report_data": {"title": "v3报告"}, "analysis_result": None, "collected_data": []},
        }[ver]
        # Mock to_dict
        tree.to_dict.return_value = {"nodes": [], "root": "v1"}

        adapter = BranchTreeAdapter(tree, store)
        history = adapter.get_history("t1")

        assert len(history) == 3
        assert history[0]["version"] == 1
        assert history[0]["action"] == "initial"
        assert history[0]["parent_version"] is None
        assert history[0]["report_data"] == {"title": "v1报告"}
        assert history[1]["version"] == 2
        assert history[1]["parent_version"] == 1
        assert history[2]["parent_version"] == 1  # fork from v1

    def test_get_history_empty(self):
        store = BranchSnapshotStore(":memory:")
        tree = MagicMock()
        tree.to_dict.return_value = {"nodes": [], "root": None}

        adapter = BranchTreeAdapter(tree, store)
        assert adapter.get_history("t1") == []


class TestApprove:
    def test_approve_and_check(self):
        store, v1, _, _ = _adapter_with_data()
        tree = MagicMock()
        tree.to_dict.return_value = {"nodes": [], "root": "v1"}

        adapter = BranchTreeAdapter(tree, store)
        assert adapter.is_approved("t1", v1) is False

        adapter.approve("t1", v1)
        assert adapter.is_approved("t1", v1) is True

    def test_get_approved(self):
        store, v1, v2, _ = _adapter_with_data()
        tree = MagicMock()
        tree.to_dict.return_value = {"nodes": [], "root": "v1"}

        adapter = BranchTreeAdapter(tree, store)
        adapter.approve("t1", v1)

        approved = adapter.get_approved("t1")
        assert len(approved) == 1
        assert approved[0]["version"] == v1
        assert approved[0]["action"] == "initial"


class TestCurrentActiveVersion:
    def test_active_version_multiple(self):
        store, v1, v2, v3 = _adapter_with_data()
        tree = MagicMock()
        tree.to_dict.return_value = {"nodes": [], "root": "v1"}

        adapter = BranchTreeAdapter(tree, store)
        assert adapter.current_active_version("t1") == v3

    def test_active_version_empty(self):
        store = BranchSnapshotStore(":memory:")
        tree = MagicMock()
        tree.to_dict.return_value = {"nodes": [], "root": None}

        adapter = BranchTreeAdapter(tree, store)
        assert adapter.current_active_version("t1") is None


class TestGetVersionCheckpointId:
    def test_get_checkpoint_id(self):
        store = BranchSnapshotStore(":memory:")
        store.insert("t1", None, "ck_abc123", "initial")
        tree = MagicMock()
        tree.to_dict.return_value = {"nodes": [], "root": "v1"}

        adapter = BranchTreeAdapter(tree, store)
        ck_id = adapter.get_version_checkpoint_id("t1", 1)
        assert ck_id == "ck_abc123"

    def test_get_checkpoint_id_nonexistent(self):
        store = BranchSnapshotStore(":memory:")
        tree = MagicMock()
        tree.to_dict.return_value = {"nodes": [], "root": None}

        adapter = BranchTreeAdapter(tree, store)
        assert adapter.get_version_checkpoint_id("t1", 999) is None


class TestToTreeDict:
    def test_to_tree_dict(self):
        store, _, _, _ = _adapter_with_data()
        tree = MagicMock()
        tree.to_dict.return_value = {
            "nodes": [
                {"id": "v1", "parent_id": None, "action": "initial", "children": ["v2", "v3"]},
                {"id": "v2", "parent_id": "v1", "action": "rewrite", "children": []},
                {"id": "v3", "parent_id": "v1", "action": "recollect", "children": []},
            ],
            "root": "v1",
        }

        adapter = BranchTreeAdapter(tree, store)
        d = adapter.to_tree_dict("t1")

        assert d["root"] == "v1"
        assert len(d["nodes"]) == 3
        root_node = d["nodes"][0]
        assert sorted(root_node["children"]) == ["v2", "v3"]


class TestRestoreState:
    def test_restore_state_returns_fields(self):
        store, v1, _, _ = _adapter_with_data()
        tree = MagicMock()
        tree.restore.return_value = {
            "report_data": {"title": "测试"},
            "analysis_result": {"swot": {"strengths": []}},
            "collected_data": [{"url": "http://example.com"}],
        }

        adapter = BranchTreeAdapter(tree, store)
        state = adapter.restore_state("t1", v1)
        assert "report_data" in state
        assert "analysis_result" in state
        assert "collected_data" in state
