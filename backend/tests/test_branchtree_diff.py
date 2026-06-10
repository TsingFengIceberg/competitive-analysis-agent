"""Tests for diff module."""

from __future__ import annotations

from competition.branchtree.diff import (
    diff_dicts,
    diff_lists,
    diff_report_sections,
    snapshot_diff,
)


class TestDiffDicts:
    def test_no_changes(self):
        result = diff_dicts({"a": 1, "b": 2}, {"a": 1, "b": 2})
        assert result == {}

    def test_field_changed(self):
        result = diff_dicts({"a": 1, "b": 2}, {"a": 1, "b": 3})
        assert "b" in result
        assert result["b"] == {"old": 2, "new": 3, "changed": True}

    def test_field_added(self):
        result = diff_dicts({"a": 1}, {"a": 1, "b": 2})
        assert "b" in result
        assert result["b"]["old"] is None
        assert result["b"]["new"] == 2

    def test_field_removed(self):
        result = diff_dicts({"a": 1, "b": 2}, {"a": 1})
        assert "b" in result
        assert result["b"]["old"] == 2
        assert result["b"]["new"] is None

    def test_handle_none_inputs(self):
        result = diff_dicts(None, {"a": 1})
        assert "a" in result

        result = diff_dicts({"a": 1}, None)
        assert "a" in result


class TestDiffLists:
    def test_no_changes(self):
        result = diff_lists([1, 2, 3], [1, 2, 3])
        assert result == {"added": [], "removed": []}

    def test_added_items(self):
        result = diff_lists([1, 2], [1, 2, 3])
        assert result["added"] == [3]
        assert result["removed"] == []

    def test_removed_items(self):
        result = diff_lists([1, 2, 3], [1, 3])
        assert result["added"] == []
        assert result["removed"] == [2]

    def test_with_key_fn(self):
        old = [{"url": "a.com", "data": "old"}, {"url": "b.com", "data": "same"}]
        new = [{"url": "b.com", "data": "same"}, {"url": "c.com", "data": "new"}]
        result = diff_lists(old, new, key_fn=lambda x: x["url"])
        assert len(result["added"]) == 1
        assert result["added"][0]["url"] == "c.com"
        assert len(result["removed"]) == 1
        assert result["removed"][0]["url"] == "a.com"

    def test_handle_none_inputs(self):
        result = diff_lists(None, [1, 2])
        assert result["added"] == [1, 2]
        assert result["removed"] == []

        result = diff_lists([1, 2], None)
        assert result["added"] == []
        assert result["removed"] == [1, 2]


class TestDiffReportSections:
    def test_section_added(self):
        result = diff_report_sections(
            {"overview": "text"},
            {"overview": "text", "pricing": "new section"},
        )
        assert result["pricing"]["status"] == "added"

    def test_section_removed(self):
        result = diff_report_sections(
            {"overview": "text", "pricing": "old"},
            {"overview": "text"},
        )
        assert result["pricing"]["status"] == "removed"

    def test_section_modified(self):
        result = diff_report_sections(
            {"overview": "v1 text", "swot": {}},
            {"overview": "v2 text", "swot": {}},
        )
        assert result["overview"]["status"] == "modified"
        assert "swot" not in result  # unchanged

    def test_no_changes(self):
        result = diff_report_sections(
            {"a": 1, "b": 2},
            {"a": 1, "b": 2},
        )
        assert result == {}


class TestSnapshotDiff:
    def test_full_diff(self):
        old = {
            "report_data": {"overview": "v1 overview", "swot": {"strengths": ["fast"]}},
            "analysis_result": {"score": 7},
            "collected_data": [
                {"url": "a.com", "title": "A"},
                {"url": "b.com", "title": "B"},
            ],
        }
        new = {
            "report_data": {"overview": "v2 overview", "swot": {"strengths": ["fast", "cheap"]}, "pricing": "new"},
            "analysis_result": {"score": 8},
            "collected_data": [
                {"url": "b.com", "title": "B"},
                {"url": "c.com", "title": "C"},
            ],
        }

        result = snapshot_diff(old, new)

        # Field changes
        assert "analysis_result" in result["fields"]

        # Report sections
        assert "overview" in result["report_sections"]  # modified
        assert "pricing" in result["report_sections"]  # added

        # Collected data
        assert len(result["collected_data_diff"]["added"]) == 1
        assert len(result["collected_data_diff"]["removed"]) == 1

        # Summary
        assert "report sections" in result["summary"] or "fields" in result["summary"]

    def test_no_changes(self):
        snap = {"report_data": {"title": "same"}}
        result = snapshot_diff(snap, snap)
        assert result["summary"] == "no changes"
        assert result["fields"] == {}
        assert result["report_sections"] == {}
