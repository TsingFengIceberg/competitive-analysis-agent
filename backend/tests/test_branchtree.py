"""Tests for BranchNode and BranchTree."""

from __future__ import annotations

from unittest.mock import MagicMock

from deerflow.branchtree.node import BranchNode
from deerflow.branchtree.tree import BranchTree, MetadataStore

# ── Minimal concrete BranchTree for testing ─────────────────────


class _TestTree(BranchTree):
    """Minimal concrete BranchTree for unit tests."""

    def _serialize_state(self, channel_values: dict) -> dict:
        return channel_values


# ── Helpers ────────────────────────────────────────────────────


def _mock_store(rows: list[dict] | None = None) -> MagicMock:
    """Create a mock MetadataStore."""
    store = MagicMock(spec=MetadataStore)
    store.list_by_thread.return_value = rows or []
    return store


def _mock_checkpoint_ops() -> MagicMock:
    """Create a mock CheckpointOps."""
    from unittest.mock import patch

    with patch(
        "deerflow.branchtree.tree.CheckpointOps", autospec=True
    ) as mock_cls:
        yield mock_cls


# ── BranchNode tests ───────────────────────────────────────────


class TestBranchNode:
    def test_create_root_node(self):
        n = BranchNode(node_id="v1", parent_id=None, checkpoint_id="ck1", action="initial")
        assert n.node_id == "v1"
        assert n.parent_id is None
        assert n.is_root is True
        assert n.is_leaf is True  # no children yet
        assert n.is_fork_point is False

    def test_create_child_node(self):
        n = BranchNode(node_id="v2", parent_id="v1", checkpoint_id="ck2", action="rewrite")
        assert n.is_root is False
        assert n.is_leaf is True

    def test_to_dict(self):
        n = BranchNode(
            node_id="v3",
            parent_id="v1",
            checkpoint_id="ck3",
            action="reanalyze",
            metadata={"comment": "补充用户数据"},
        )
        n.children = ["v4", "v5"]
        d = n.to_dict()
        assert d["node_id"] == "v3"
        assert d["parent_id"] == "v1"
        assert d["action"] == "reanalyze"
        assert d["metadata"]["comment"] == "补充用户数据"
        assert d["children"] == ["v4", "v5"]
        assert "created_at" in d

    def test_is_fork_point(self):
        n = BranchNode(node_id="v1", parent_id=None, checkpoint_id="ck1", action="initial")
        assert n.is_fork_point is False
        n.children = ["v2", "v3"]
        assert n.is_fork_point is True


# ── BranchTree tests ───────────────────────────────────────────


class TestBranchTreeLoad:
    def test_load_empty_thread(self):
        store = _mock_store([])
        tree = _TestTree(MagicMock(), store)
        tree.load("t1")
        assert tree.to_dict() == {"nodes": [], "root": None}

    def test_load_linear_history(self):
        store = _mock_store([
            {"version": 1, "parent_version": None, "checkpoint_id": "ck1", "action": "initial", "created_at": "2026-01-01T00:00:00", "metadata_json": {}},
            {"version": 2, "parent_version": 1, "checkpoint_id": "ck2", "action": "rewrite", "created_at": "2026-01-01T00:01:00", "metadata_json": {}},
        ])
        tree = _TestTree(MagicMock(), store)
        tree.load("t1")
        d = tree.to_dict()
        assert len(d["nodes"]) == 2
        assert d["root"] == "v1"

        v1 = tree.get_node(1)
        assert v1 is not None
        assert v1.children == ["v2"]

    def test_load_forked_history(self):
        store = _mock_store([
            {"version": 1, "parent_version": None, "checkpoint_id": "ck1", "action": "initial", "created_at": "2026-01-01T00:00:00", "metadata_json": {}},
            {"version": 2, "parent_version": 1, "checkpoint_id": "ck2", "action": "rewrite", "created_at": "2026-01-01T00:01:00", "metadata_json": {}},
            {"version": 3, "parent_version": 1, "checkpoint_id": "ck3", "action": "recollect", "created_at": "2026-01-01T00:02:00", "metadata_json": {}},
        ])
        tree = _TestTree(MagicMock(), store)
        tree.load("t1")

        v1 = tree.get_node(1)
        assert sorted(v1.children) == ["v2", "v3"]  # fork point
        assert v1.is_fork_point is True


class TestBranchTreeLineage:
    def test_lineage_linear(self):
        store = _mock_store([
            {"version": 1, "parent_version": None, "checkpoint_id": "ck1", "action": "initial", "created_at": "2026-01-01T00:00:00", "metadata_json": {}},
            {"version": 2, "parent_version": 1, "checkpoint_id": "ck2", "action": "rewrite", "created_at": "2026-01-01T00:01:00", "metadata_json": {}},
            {"version": 3, "parent_version": 2, "checkpoint_id": "ck3", "action": "reanalyze", "created_at": "2026-01-01T00:02:00", "metadata_json": {}},
        ])
        tree = _TestTree(MagicMock(), store)
        tree.load("t1")

        chain = tree.lineage(3)
        assert [n.node_id for n in chain] == ["v1", "v2", "v3"]

    def test_lineage_root(self):
        store = _mock_store([
            {"version": 1, "parent_version": None, "checkpoint_id": "ck1", "action": "initial", "created_at": "2026-01-01T00:00:00", "metadata_json": {}},
        ])
        tree = _TestTree(MagicMock(), store)
        tree.load("t1")

        chain = tree.lineage(1)
        assert [n.node_id for n in chain] == ["v1"]

    def test_lineage_nonexistent(self):
        store = _mock_store([])
        tree = _TestTree(MagicMock(), store)
        tree.load("t1")

        chain = tree.lineage(999)
        assert chain == []


class TestBranchTreeToDict:
    def test_to_dict_structure(self):
        store = _mock_store([
            {"version": 1, "parent_version": None, "checkpoint_id": "ck1", "action": "initial", "created_at": "2026-01-01T00:00:00", "metadata_json": {"persona": "PM"}},
        ])
        tree = _TestTree(MagicMock(), store)
        tree.load("t1")

        d = tree.to_dict()
        assert "nodes" in d
        assert "root" in d
        assert d["root"] == "v1"
        node = d["nodes"][0]
        assert node["id"] == "v1"
        assert node["action"] == "initial"
        assert node["metadata"]["persona"] == "PM"


class TestBranchTreeCurrentVersion:
    def test_current_version_empty(self):
        store = _mock_store([])
        tree = _TestTree(MagicMock(), store)
        tree.load("t1")
        assert tree.current_version() is None

    def test_current_version_multiple(self):
        store = _mock_store([
            {"version": 1, "parent_version": None, "checkpoint_id": "ck1", "action": "initial", "created_at": "2026-01-01T00:00:00", "metadata_json": {}},
            {"version": 5, "parent_version": 1, "checkpoint_id": "ck5", "action": "rewrite", "created_at": "2026-01-01T00:01:00", "metadata_json": {}},
        ])
        tree = _TestTree(MagicMock(), store)
        tree.load("t1")
        assert tree.current_version() == 5


class TestBranchTreeGetNode:
    def test_get_node_exists(self):
        store = _mock_store([
            {"version": 3, "parent_version": None, "checkpoint_id": "ck3", "action": "initial", "created_at": "2026-01-01T00:00:00", "metadata_json": {}},
        ])
        tree = _TestTree(MagicMock(), store)
        tree.load("t1")
        n = tree.get_node(3)
        assert n is not None
        assert n.node_id == "v3"

    def test_get_node_missing(self):
        store = _mock_store([])
        tree = _TestTree(MagicMock(), store)
        tree.load("t1")
        assert tree.get_node(999) is None
