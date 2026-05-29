"""Tests for merge module."""

from __future__ import annotations

from unittest.mock import MagicMock

from deerflow.branchtree.merge import (
    _build_merge_prompt,
    find_common_ancestor,
    merge_execute,
    merge_prepare,
)

# ── Helpers ────────────────────────────────────────────────────


def _make_adapter():
    """Create mock adapter for merge tests."""
    a = MagicMock()

    a.restore_state.side_effect = lambda tid, ver: {
        1: {"report_data": {"title": "v1"}},
        2: {"report_data": {"title": "v2"}},
        3: {"report_data": {"title": "v3"}},
    }[ver]

    a._tree = MagicMock()

    def _node(nid, pid):
        n = MagicMock()
        n.node_id = nid
        n.parent_id = pid
        return n

    # Fork tree: v1 → v2 → v3
    #              ↘ v4
    a._tree.lineage.side_effect = lambda ver: {
        1: [_node("v1", None)],
        2: [_node("v1", None), _node("v2", "v1")],
        3: [_node("v1", None), _node("v2", "v1"), _node("v3", "v2")],
        4: [_node("v1", None), _node("v4", "v1")],
    }[ver]
    a._tree.load = MagicMock()
    a.snapshot.return_value = 5

    return a


# ── find_common_ancestor ───────────────────────────────────────


class TestFindCommonAncestor:
    def test_same_branch(self):
        a = _make_adapter()
        assert find_common_ancestor(a, "t1", 2, 3) == 2

    def test_forked_branches(self):
        a = _make_adapter()
        assert find_common_ancestor(a, "t1", 3, 4) == 1

    def test_same_version(self):
        a = _make_adapter()
        assert find_common_ancestor(a, "t1", 2, 2) == 2


# ── merge_prepare ──────────────────────────────────────────────


class TestMergePrepare:
    def test_returns_structure(self):
        a = _make_adapter()
        result = merge_prepare(a, "t1", 1, 2)
        assert result["version_a"] == 1
        assert result["version_b"] == 2
        assert "diff_a_to_b" in result
        assert "merge_prompt" in result

    def test_prompt_contains_versions(self):
        a = _make_adapter()
        result = merge_prepare(a, "t1", 1, 2)
        assert "v1" in result["merge_prompt"]
        assert "v2" in result["merge_prompt"]


# ── merge_execute ──────────────────────────────────────────────


class TestMergeExecute:
    def test_creates_merge_snapshot(self):
        a = _make_adapter()
        merged_state = {"report_data": {"overview": "merged"}}
        new_version = merge_execute(a, "t1", 1, 2, merged_state)
        assert new_version == 5
        a.snapshot.assert_called_once()
        kwargs = a.snapshot.call_args[1]
        assert kwargs["action"] == "merge"
        assert kwargs["metadata"]["merged_from"] == [1, 2]


# ── _build_merge_prompt ────────────────────────────────────────


class TestBuildMergePrompt:
    def test_prompt_structure(self):
        prompt = _build_merge_prompt(
            1, 2, 1,
            {"report_data": {"overview": "A", "swot": {}}},
            {"report_data": {"overview": "B", "pricing": "new"}},
            {"summary": "1 field changed"},
        )
        assert "v1" in prompt
        assert "v2" in prompt
        assert "合并要求" in prompt
