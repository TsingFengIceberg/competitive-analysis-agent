"""BranchTree 适配器 — 与 competition 现有代码的桥接层。

Connect BranchTree to the competition flow:
- CompetitionState → BranchNode snapshot
- BranchNode version → CompetitionState restoration
- HITL fork logic wrapping CheckpointOps + BranchTree

Usage (drop-in replacement for current _store dict)::

    from deerflow.branchtree.adapter import BranchTreeAdapter
    from deerflow.branchtree.store import BranchSnapshotStore
    from deerflow.branchtree.deliverable_tree import DeliverableTree

    store = BranchSnapshotStore()
    tree = DeliverableTree(checkpointer, store)
    adapter = BranchTreeAdapter(tree, store)

    # After each graph run, snapshot:
    adapter.snapshot(thread_id, "initial", state_values)

    # HITL fork:
    adapter.fork(thread_id, from_version=1, action="rewrite")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.branchtree.store import BranchSnapshotStore
    from deerflow.branchtree.tree import BranchTree

logger = logging.getLogger(__name__)

# CompetitionState fields preserved in BranchTree snapshots
_SNAPSHOT_FIELDS = [
    "report_data",
    "analysis_result",
    "collected_data",
    "hitl_decision",
    "review_verdict",
    "user_request",
    "target_products",
    "persona",
]


class BranchTreeAdapter:
    """Bridge between CompetitionState flow and BranchTree.

    Responsibilities:
    - Extract relevant fields from CompetitionState channel_values for snapshot
    - Load/restore thread history into BranchTree
    - Provide fork logic for HITL decisions
    - Convert BranchTree history to frontend-compatible JSON
    """

    def __init__(
        self, tree: BranchTree, store: BranchSnapshotStore
    ) -> None:
        self._tree = tree
        self._store = store

    # ── Snapshot ──────────────────────────────────────────────────

    def snapshot(
        self,
        thread_id: str,
        action: str,
        state_values: dict,
        metadata: dict | None = None,
    ) -> int:
        """Create a new BranchTree version from CompetitionState values.

        Returns the new version number.
        """
        self._tree.load(thread_id)
        node = self._tree.snapshot(thread_id, action, metadata)
        return int(node.node_id[1:])

    def fork(
        self,
        thread_id: str,
        from_version: int,
        action: str,
        metadata: dict | None = None,
    ) -> int:
        """Fork a new branch from a historical version.

        Uses CheckpointOps.fork to create LangGraph-level fork,
        then records the new version in BranchTree.
        """
        self._tree.load(thread_id)
        node = self._tree.fork(thread_id, from_version, action, metadata)
        return int(node.node_id[1:])

    # ── State restoration ─────────────────────────────────────────

    def restore_state(
        self, thread_id: str, version: int
    ) -> dict:
        """Restore CompetitionState values from a BranchTree version.

        Returns only the fields that were snapshotted (not full channel_values).
        """
        return self._tree.restore(thread_id, version)

    def get_version_checkpoint_id(
        self, thread_id: str, version: int
    ) -> str | None:
        """Get the LangGraph checkpoint_id for a given BranchTree version."""
        meta = self._store.get(thread_id, version)
        if meta is None:
            return None
        return meta.get("checkpoint_id")

    # ── History / Frontend ────────────────────────────────────────

    def get_history(self, thread_id: str) -> list[dict]:
        """Get version history as frontend-compatible list.

        Same shape as current ReportHistoryItem in api-client.ts.
        """
        self._tree.load(thread_id)
        rows = self._store.list_by_thread(thread_id)
        result: list[dict] = []
        for r in rows:
            # Restore state to include actual report data
            state = self._tree.restore(thread_id, r["version"])
            result.append({
                "version": r["version"],
                "parent_version": r["parent_version"],
                "action": r["action"],
                "is_approved": r["is_approved"],
                "created_at": r["created_at"],
                "report_data": state.get("report_data"),
                "analysis_result": state.get("analysis_result"),
                "collected_data": state.get("collected_data"),
            })
        return result

    def approve(self, thread_id: str, version: int) -> None:
        """Mark a version as approved."""
        self._store.approve(thread_id, version)

    def is_approved(self, thread_id: str, version: int) -> bool:
        """Check if a version is approved."""
        return self._store.is_approved(thread_id, version)

    def get_approved(self, thread_id: str) -> list[dict]:
        """Get all approved versions for a thread."""
        return self._store.get_approved(thread_id)

    def current_active_version(self, thread_id: str) -> int | None:
        """Get the latest version number for a thread."""
        rows = self._store.list_by_thread(thread_id)
        if not rows:
            return None
        return max(r["version"] for r in rows)

    def to_tree_dict(self, thread_id: str) -> dict:
        """Get tree structure for frontend rendering."""
        self._tree.load(thread_id)
        return self._tree.to_dict()
