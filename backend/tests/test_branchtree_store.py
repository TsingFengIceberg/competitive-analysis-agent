"""Tests for BranchSnapshotStore."""

from __future__ import annotations

from competition.branchtree.store import BranchSnapshotStore

# ── Fixture ─────────────────────────────────────────────────────


def new_store() -> BranchSnapshotStore:
    """Create a fresh in-memory store for each test."""
    return BranchSnapshotStore(":memory:")


def test_store_creates_missing_database_parent(tmp_path):
    store = BranchSnapshotStore(tmp_path / "nested" / "versions.db")

    version = store.insert("thread-1", None, "checkpoint-1", "initial")

    assert version == 1
    assert (tmp_path / "nested" / "versions.db").is_file()


# ── Tests ────────────────────────────────────────────────────────


class TestInsert:
    def test_insert_root(self):
        store = new_store()
        v = store.insert("t1", None, "ck1", "initial")
        assert v == 1

        row = store.get("t1", 1)
        assert row is not None
        assert row["version"] == 1
        assert row["parent_version"] is None
        assert row["checkpoint_id"] == "ck1"
        assert row["action"] == "initial"

    def test_insert_child(self):
        store = new_store()
        v1 = store.insert("t1", None, "ck1", "initial")
        v2 = store.insert("t1", v1, "ck2", "rewrite")
        assert v2 == 2

        row = store.get("t1", 2)
        assert row["parent_version"] == 1

    def test_insert_with_metadata(self):
        store = new_store()
        v = store.insert("t1", None, "ck1", "initial", {"persona": "PM", "comment": "初始分析"})
        row = store.get("t1", v)
        assert row["metadata_json"] == {"persona": "PM", "comment": "初始分析"}

    def test_insert_auto_increment_across_threads(self):
        store = new_store()
        v1 = store.insert("t1", None, "ck1", "initial")  # t1 version 1
        v2 = store.insert("t2", None, "ckA", "initial")  # t2 version 1
        v3 = store.insert("t1", v1, "ck2", "rewrite")    # t1 version 2
        assert v1 == 1
        assert v2 == 1
        assert v3 == 2


class TestGet:
    def test_get_existing(self):
        store = new_store()
        store.insert("t1", None, "ck1", "initial")
        row = store.get("t1", 1)
        assert row is not None
        assert row["version"] == 1

    def test_get_nonexistent(self):
        store = new_store()
        assert store.get("t1", 999) is None

    def test_get_wrong_thread(self):
        store = new_store()
        store.insert("t1", None, "ck1", "initial")
        # Version exists but in different thread
        assert store.get("t2", 1) is None


class TestListByThread:
    def test_list_empty(self):
        store = new_store()
        assert store.list_by_thread("t1") == []

    def test_list_multiple(self):
        store = new_store()
        store.insert("t1", None, "ck1", "initial")
        store.insert("t1", 1, "ck2", "rewrite")
        store.insert("t1", 1, "ck3", "recollect")

        rows = store.list_by_thread("t1")
        assert len(rows) == 3
        # Should be sorted by version ASC
        assert rows[0]["version"] == 1
        assert rows[2]["version"] == 3

    def test_list_thread_isolation(self):
        store = new_store()
        store.insert("t1", None, "ck1", "initial")
        store.insert("t2", None, "ckA", "initial")

        assert len(store.list_by_thread("t1")) == 1
        assert len(store.list_by_thread("t2")) == 1


class TestApprove:
    def test_approve_and_check(self):
        store = new_store()
        store.insert("t1", None, "ck1", "initial")
        assert store.is_approved("t1", 1) is False

        store.approve("t1", 1)
        assert store.is_approved("t1", 1) is True

    def test_get_approved(self):
        store = new_store()
        store.insert("t1", None, "ck1", "initial")
        store.insert("t1", 1, "ck2", "rewrite")
        store.approve("t1", 1)

        approved = store.get_approved("t1")
        assert len(approved) == 1
        assert approved[0]["version"] == 1


class TestDeleteThread:
    def test_delete_removes_all(self):
        store = new_store()
        store.insert("t1", None, "ck1", "initial")
        store.insert("t1", 1, "ck2", "rewrite")
        store.insert("t2", None, "ckA", "initial")

        store.delete_thread("t1")
        assert store.list_by_thread("t1") == []
        # t2 unaffected
        assert len(store.list_by_thread("t2")) == 1


class TestForkTreeRoundTrip:
    """Simulate a full fork tree: load data → build tree → verify structure."""

    def test_full_tree_round_trip(self):
        store = new_store()

        # Build a fork tree:
        # v1 → v2 → v3
        #    ↘ v4 → v5
        v1 = store.insert("t1", None, "ck1", "initial")
        v2 = store.insert("t1", v1, "ck2", "rewrite")
        store.insert("t1", v2, "ck3", "reanalyze")
        v4 = store.insert("t1", v1, "ck4", "recollect")
        store.insert("t1", v4, "ck5", "rewrite")

        # Load and verify
        rows = store.list_by_thread("t1")
        assert len(rows) == 5

        # Check parent relationships
        by_version = {r["version"]: r for r in rows}
        assert by_version[1]["parent_version"] is None
        assert by_version[2]["parent_version"] == 1
        assert by_version[3]["parent_version"] == 2
        assert by_version[4]["parent_version"] == 1  # fork from v1
        assert by_version[5]["parent_version"] == 4

        # Verify checkpoint_ids
        assert by_version[1]["checkpoint_id"] == "ck1"
        assert by_version[5]["checkpoint_id"] == "ck5"
