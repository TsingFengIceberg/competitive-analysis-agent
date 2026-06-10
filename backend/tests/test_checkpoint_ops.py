"""Tests for CheckpointOps.

Uses Mock BaseCheckpointSaver to control parent-child relationships precisely,
without depending on LangGraph pregel loop internals.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# Module under test
from competition.branchtree.checkpoint_ops import CheckpointOps  # noqa: E402

# ── Helpers ────────────────────────────────────────────────────


def _make_config(thread_id: str, checkpoint_id: str) -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
            "checkpoint_id": checkpoint_id,
        }
    }


def _make_parent_config(thread_id: str, checkpoint_id: str | None) -> dict | None:
    if checkpoint_id is None:
        return None
    return _make_config(thread_id, checkpoint_id)


def _make_checkpoint_tuple(
    thread_id: str,
    checkpoint_id: str,
    parent_checkpoint_id: str | None,
    channel_values: dict | None = None,
) -> MagicMock:
    """Create a mock CheckpointTuple with proper parent_config."""
    cp = MagicMock()
    cp.config = _make_config(thread_id, checkpoint_id)
    cp.parent_config = _make_parent_config(thread_id, parent_checkpoint_id)
    cp.checkpoint = {
        "v": 1,
        "id": checkpoint_id,
        "ts": "2026-01-01T00:00:00",
        "channel_values": channel_values or {"data": checkpoint_id},
        "channel_versions": {},
        "versions_seen": {},
    }
    cp.metadata = {"source": "loop", "step": 1}
    cp.pending_writes = []
    return cp


def _make_state_snapshot(values: dict) -> MagicMock:
    snap = MagicMock()
    snap.values = values
    snap.next = ()
    snap.config = {}
    snap.metadata = None
    snap.created_at = "2026-01-01T00:00:00"
    snap.parent_config = None
    snap.tasks = ()
    snap.interrupts = ()
    return snap


# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def mock_saver():
    """Mock BaseCheckpointSaver."""
    return MagicMock()


@pytest.fixture
def ops(mock_saver):
    """CheckpointOps with mock saver."""
    return CheckpointOps(mock_saver)


@pytest.fixture
def fork_tree_cps():
    """Build a set of CheckpointTuples forming a fork tree.

    Tree shape:
        None → ck1 → ck2 → ck3 (main line)
                       ↘ ck4 → ck5 (fork from ck2)
    """
    return [
        _make_checkpoint_tuple("t1", "ck1", None),
        _make_checkpoint_tuple("t1", "ck2", "ck1"),
        _make_checkpoint_tuple("t1", "ck3", "ck2"),
        _make_checkpoint_tuple("t1", "ck4", "ck2"),
        _make_checkpoint_tuple("t1", "ck5", "ck4"),
    ]


# ── get_state ──────────────────────────────────────────────────


class TestGetState:
    def test_get_state_latest(self, ops, mock_saver):
        """Without checkpoint_id → returns latest via get_tuple(None)."""
        mock_saver.get.return_value = {
            "channel_values": {"x": 42},
            "ts": "2026-01-01",
        }
        state = ops.get_state("t1")
        assert state.values == {"x": 42}

    def test_get_state_specific(self, ops, mock_saver):
        """With checkpoint_id → includes it in config."""
        mock_saver.get.return_value = {
            "channel_values": {"x": 99},
            "ts": "2026-01-01",
        }
        state = ops.get_state("t1", "ck3")
        assert state.values == {"x": 99}

    def test_get_state_not_found_raises(self, ops, mock_saver):
        mock_saver.get.return_value = None
        with pytest.raises(ValueError, match="not found"):
            ops.get_state("t1", "ck99")


# ── get_history ────────────────────────────────────────────────


class TestGetHistory:
    def test_get_history_no_limit(self, ops, mock_saver, fork_tree_cps):
        mock_saver.list.return_value = fork_tree_cps
        history = ops.get_history("t1")
        assert len(history) == 5

    def test_get_history_with_limit(self, ops, mock_saver, fork_tree_cps):
        mock_saver.list.return_value = fork_tree_cps[:3]
        history = ops.get_history("t1", limit=3)
        assert len(history) == 3


# ── latest ─────────────────────────────────────────────────────


class TestLatest:
    def test_latest_equals_get_state(self, ops, mock_saver):
        mock_saver.get.return_value = {
            "channel_values": {"latest": True},
            "ts": "2026-01-01",
        }
        latest = ops.latest("t1")
        state = ops.get_state("t1")
        assert latest.values == state.values


# ── build_tree ─────────────────────────────────────────────────


class TestBuildTree:
    def test_tree_structure(self, ops, mock_saver, fork_tree_cps):
        mock_saver.list.return_value = fork_tree_cps
        tree = ops.build_tree("t1")

        # None key = root nodes
        assert tree[None] == ["ck1"]
        assert tree["ck1"] == ["ck2"]
        assert sorted(tree["ck2"]) == ["ck3", "ck4"]  # fork point
        assert tree.get("ck3", []) == []  # leaf
        assert tree["ck4"] == ["ck5"]
        assert tree.get("ck5", []) == []  # leaf

    def test_cache_hit_no_re_list(self, ops, mock_saver, fork_tree_cps):
        """Second call should hit cache — zero DB queries."""
        mock_saver.list.return_value = fork_tree_cps

        ops.build_tree("t1")  # first call → triggers list()
        assert mock_saver.list.call_count == 1

        ops.build_tree("t1")  # second call → cache hit
        assert mock_saver.list.call_count == 1  # no additional call

    def test_cache_invalidated_rebuilds(self, ops, mock_saver, fork_tree_cps):
        """After invalidate_cache, next call should rebuild."""
        mock_saver.list.return_value = fork_tree_cps

        ops.build_tree("t1")
        assert mock_saver.list.call_count == 1

        ops.invalidate_cache("t1")
        ops.build_tree("t1")
        assert mock_saver.list.call_count == 2


# ── children ───────────────────────────────────────────────────


class TestChildren:
    def test_children_fork_point(self, ops, mock_saver, fork_tree_cps):
        mock_saver.list.return_value = fork_tree_cps
        # ck2 has two children: ck3 and ck4
        assert sorted(ops.children("t1", "ck2")) == ["ck3", "ck4"]

    def test_children_leaf(self, ops, mock_saver, fork_tree_cps):
        mock_saver.list.return_value = fork_tree_cps
        # ck5 is a leaf
        assert ops.children("t1", "ck5") == []

    def test_children_cached(self, ops, mock_saver, fork_tree_cps):
        """children() caches the tree same as build_tree."""
        mock_saver.list.return_value = fork_tree_cps
        ops.children("t1", "ck1")
        ops.children("t1", "ck2")
        # Only one list() call for both children() calls
        assert mock_saver.list.call_count == 1


# ── is_fork_point ──────────────────────────────────────────────


class TestIsForkPoint:
    def test_is_fork_point_true(self, ops, mock_saver, fork_tree_cps):
        mock_saver.list.return_value = fork_tree_cps
        assert ops.is_fork_point("t1", "ck2") is True

    def test_is_fork_point_false(self, ops, mock_saver, fork_tree_cps):
        mock_saver.list.return_value = fork_tree_cps
        assert ops.is_fork_point("t1", "ck5") is False

    def test_is_fork_point_single_child(self, ops, mock_saver, fork_tree_cps):
        mock_saver.list.return_value = fork_tree_cps
        assert ops.is_fork_point("t1", "ck1") is False  # 1 child


# ── lineage ────────────────────────────────────────────────────


class TestLineage:
    def test_lineage_from_leaf(self, ops, mock_saver, fork_tree_cps):
        mock_saver.list.return_value = fork_tree_cps
        result = ops.lineage("t1", "ck5")
        # ck5's lineage: ck1 → ck2 → ck4 → ck5
        assert result == ["ck1", "ck2", "ck4", "ck5"]

    def test_lineage_from_root(self, ops, mock_saver, fork_tree_cps):
        mock_saver.list.return_value = fork_tree_cps
        result = ops.lineage("t1", "ck1")
        assert result == ["ck1"]

    def test_lineage_from_fork_point(self, ops, mock_saver, fork_tree_cps):
        mock_saver.list.return_value = fork_tree_cps
        result = ops.lineage("t1", "ck3")
        assert result == ["ck1", "ck2", "ck3"]

    def test_lineage_cached_no_db(self, ops, mock_saver, fork_tree_cps):
        """lineage() after build_tree() should use cache, zero DB queries."""
        mock_saver.list.return_value = fork_tree_cps
        ops.build_tree("t1")  # populates cache
        assert mock_saver.list.call_count == 1

        ops.lineage("t1", "ck5")  # should use cache
        assert mock_saver.list.call_count == 1  # no new call


# ── fork ───────────────────────────────────────────────────────


class TestFork:
    def test_fork_requires_graph(self, ops):
        """fork() without graph raises RuntimeError."""
        with pytest.raises(RuntimeError, match="requires a CompiledStateGraph"):
            ops.fork("t1", "ck2", {"x": 1})

    def test_fork_invalidates_cache(self, mock_saver, fork_tree_cps):
        mock_graph = MagicMock()
        mock_graph.update_state.return_value = _make_config("t1", "ck6")
        ck = CheckpointOps(mock_saver, graph=mock_graph)

        mock_saver.list.return_value = fork_tree_cps
        ck.build_tree("t1")
        assert mock_saver.list.call_count == 1

        # fork should invalidate
        ck.fork("t1", "ck3", {"decision": "rewrite"})
        mock_graph.update_state.assert_called_once()

        # Next build_tree should re-fetch
        ck.build_tree("t1")
        assert mock_saver.list.call_count == 2


# ── update_state ───────────────────────────────────────────────


class TestUpdateState:
    def test_update_state_requires_graph(self, ops):
        with pytest.raises(RuntimeError, match="requires a CompiledStateGraph"):
            ops.update_state("t1", {"x": 1})

    def test_update_state_invalidates_cache(self, mock_saver, fork_tree_cps):
        mock_graph = MagicMock()
        mock_graph.update_state.return_value = _make_config("t1", "ck_latest")
        ck = CheckpointOps(mock_saver, graph=mock_graph)

        mock_saver.list.return_value = fork_tree_cps
        ck.build_tree("t1")

        ck.update_state("t1", {"x": 1})
        assert mock_saver.list.call_count == 1  # cache invalidated, not yet rebuilt

        ck.build_tree("t1")
        assert mock_saver.list.call_count == 2  # rebuilt


# ── tag / list_tags / restore_to_tag ───────────────────────────


class TestTags:
    def test_tag_and_list(self, ops, mock_saver):
        mock_saver.get.return_value = {
            "channel_values": {},
            "metadata": {},
            "channel_versions": {},
            "versions_seen": {},
        }
        ops.tag("t1", "ck1", "baseline")

        # Verify put was called with metadata containing the tag
        mock_saver.put.assert_called_once()
        call_args = mock_saver.put.call_args
        metadata = call_args[0][2]
        assert metadata["extra"]["tags"] == ["baseline"]

    def test_list_tags(self, ops, mock_saver, fork_tree_cps):
        cps_with_tags = []
        for cp in fork_tree_cps:
            cp.checkpoint = dict(cp.checkpoint)
            cp.checkpoint["metadata"] = {"extra": {"tags": ["tag_" + cp.config["configurable"]["checkpoint_id"]]}}
            cps_with_tags.append(cp)
        mock_saver.list.return_value = cps_with_tags

        tags = ops.list_tags("t1")
        assert len(tags) == 5
        assert "tag_ck1" in tags["ck1"]

    def test_list_tags_empty(self, ops, mock_saver):
        cp = _make_checkpoint_tuple("t1", "ck1", None)
        cp.checkpoint = dict(cp.checkpoint)
        cp.checkpoint["metadata"] = {}
        mock_saver.list.return_value = [cp]
        assert ops.list_tags("t1") == {}

    def test_restore_to_tag_found(self, ops, mock_saver):
        cp = _make_checkpoint_tuple("t1", "ck2", "ck1", {"data": "v2"})
        cp.checkpoint = dict(cp.checkpoint)
        cp.checkpoint["metadata"] = {"extra": {"tags": ["important"]}}
        mock_saver.list.return_value = [cp]
        mock_saver.get.return_value = {
            "channel_values": {"data": "v2"},
            "ts": "2026-01-01",
        }

        state = ops.restore_to_tag("t1", "important")
        assert state.values == {"data": "v2"}

    def test_restore_to_tag_not_found(self, ops, mock_saver):
        cp = _make_checkpoint_tuple("t1", "ck1", None)
        cp.checkpoint = dict(cp.checkpoint)
        cp.checkpoint["metadata"] = {}
        mock_saver.list.return_value = [cp]

        with pytest.raises(ValueError, match="Tag not found"):
            ops.restore_to_tag("t1", "nonexistent")


# ── Cross-thread isolation ─────────────────────────────────────


class TestCrossThreadIsolation:
    def test_different_threads_independent(self, ops, mock_saver):
        cps_t1 = [
            _make_checkpoint_tuple("t1", "ck1", None),
            _make_checkpoint_tuple("t1", "ck2", "ck1"),
        ]
        cps_t2 = [
            _make_checkpoint_tuple("t2", "ckA", None),
            _make_checkpoint_tuple("t2", "ckB", "ckA"),
        ]

        # Build t1 cache
        mock_saver.list.return_value = cps_t1
        tree_t1 = ops.build_tree("t1")
        assert tree_t1[None] == ["ck1"]

        # Build t2 cache
        mock_saver.list.return_value = cps_t2
        tree_t2 = ops.build_tree("t2")
        assert tree_t2[None] == ["ckA"]

        # t1 cache still intact
        tree_t1_again = ops.build_tree("t1")
        assert tree_t1_again[None] == ["ck1"]  # still cached, not t2's data


# ── Empty / edge cases ─────────────────────────────────────────


class TestEmptyThread:
    def test_empty_thread_tree(self, ops, mock_saver):
        """Thread with zero checkpoints → empty tree."""
        mock_saver.list.return_value = []
        tree = ops.build_tree("t1")
        assert tree == {}

    def test_empty_thread_children(self, ops, mock_saver):
        mock_saver.list.return_value = []
        assert ops.children("t1", "ckX") == []

    def test_empty_thread_lineage(self, ops, mock_saver):
        mock_saver.list.return_value = []
        # unknown checkpoint in empty thread → returns just itself
        assert ops.lineage("t1", "nonexistent") == ["nonexistent"]

    def test_single_node_thread(self, ops, mock_saver):
        """Thread with one checkpoint."""
        cps = [_make_checkpoint_tuple("t1", "ck1", None)]
        mock_saver.list.return_value = cps

        tree = ops.build_tree("t1")
        assert tree[None] == ["ck1"]
        assert tree.get("ck1", []) == []  # leaf node, no children key

        assert ops.children("t1", "ck1") == []
        assert ops.is_fork_point("t1", "ck1") is False
        assert ops.lineage("t1", "ck1") == ["ck1"]
