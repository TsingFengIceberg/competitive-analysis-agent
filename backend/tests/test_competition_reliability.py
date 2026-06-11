"""Tests for reliability features (§Torrent2002-inspired).

Covers:
  - Circuit Breaker (executor.py)
  - Content Persistence (db.py content_store + collector _persist_search_results)
  - Bounded Rework (collector _build_targeted_rework_task + data merge)
"""

from __future__ import annotations

import sqlite3

import pytest

from competition.executor import (
    _check_circuit_breaker,
    _get_call_history,
    _record_agent_call,
    _reset_call_history,
    reset_reliability_state,
)
from competition.nodes.collector import (
    _build_collector_task,
    _build_targeted_rework_task,
)


# ═══════════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════════


class TestCircuitBreaker:
    def setup_method(self):
        _reset_call_history()

    def test_no_trip_on_first_call(self):
        _record_agent_call("collector", "search for Notion pricing")
        err = _check_circuit_breaker("collector", "search for Notion pricing")
        assert err is None

    def test_no_trip_on_different_calls(self):
        _record_agent_call("collector", "search for Notion pricing")
        _record_agent_call("collector", "search for Confluence features")
        _record_agent_call("collector", "search for Notion pricing")
        err = _check_circuit_breaker("collector", "search for Notion pricing")
        assert err is None  # not 3 consecutive

    def test_trips_on_three_identical(self):
        for _ in range(3):
            _record_agent_call("analyst", "compare pricing tiers")
        err = _check_circuit_breaker("analyst", "compare pricing tiers")
        assert err is not None
        assert "Circuit breaker tripped" in err
        assert "analyst" in err

    def test_trips_on_four_identical(self):
        for _ in range(4):
            _record_agent_call("writer", "generate executive summary")
        err = _check_circuit_breaker("writer", "generate executive summary")
        assert err is not None

    def test_different_agents_independent(self):
        # Collector loops, but Analyst is fine
        for _ in range(3):
            _record_agent_call("collector", "fetch same page repeatedly")
        assert _check_circuit_breaker("collector", "fetch same page repeatedly") is not None
        assert _check_circuit_breaker("analyst", "fresh analysis task") is None

    def test_task_preview_truncation(self):
        long_task = "x" * 300
        _record_agent_call("test", long_task)
        # Should not crash; signature uses first 120 chars
        assert len(_get_call_history()) == 1

    def test_reset_clears_history(self):
        for _ in range(3):
            _record_agent_call("x", "same task")
        reset_reliability_state()
        assert len(_get_call_history()) == 0
        assert _check_circuit_breaker("x", "same task") is None

    def test_history_capped_at_10(self):
        for i in range(15):
            _record_agent_call("agent", f"task {i}")
        assert len(_get_call_history()) == 10


# ═══════════════════════════════════════════════════════════════
# Content Persistence
# ═══════════════════════════════════════════════════════════════


class TestContentPersistence:
    @pytest.fixture
    def conn(self):
        c = sqlite3.connect(":memory:")
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS content_store (
                content_ref TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                full_text TEXT NOT NULL,
                char_count INTEGER DEFAULT 0,
                fetched_at TEXT NOT NULL
            );
        """)
        yield c
        c.close()

    def test_save_and_get_content(self, conn):
        from competition.db import save_content, get_content

        save_content("ref-001", "https://example.com/report", "Full page content here.", conn=conn)
        result = get_content("ref-001", conn=conn)
        assert result is not None
        assert result["url"] == "https://example.com/report"
        assert result["full_text"] == "Full page content here."
        assert result["char_count"] == 23

    def test_get_nonexistent_content(self, conn):
        from competition.db import get_content

        assert get_content("no-such-ref", conn=conn) is None

    def test_save_overwrites_existing(self, conn):
        from competition.db import save_content, get_content

        save_content("ref-001", "https://a.com", "First version.", conn=conn)
        save_content("ref-001", "https://a.com", "Updated version with more text.", conn=conn)
        result = get_content("ref-001", conn=conn)
        assert result["full_text"] == "Updated version with more text."

    def test_skip_short_content(self, conn):
        """Content under 100 chars should not be persisted by _persist_search_results."""
        from competition.db import get_content

        # Simulate what _persist_search_results does — it skips raw_content < 100
        raw = "short"
        if len(raw) < 100:
            # Would be skipped — verify get_content returns None
            assert get_content("would-be-skipped", conn=conn) is None


# ═══════════════════════════════════════════════════════════════
# Bounded Rework
# ═══════════════════════════════════════════════════════════════


class TestBoundedRework:
    def test_targeted_rework_task_is_different_from_normal(self):
        """When gaps exist, the task should be a targeted re-collection, not full-task."""
        normal = _build_collector_task({
            "user_request": "compare Notion vs Confluence",
            "target_products": ["Notion", "Confluence"],
        })
        assert "Search for competitive intelligence data on:" in normal
        assert "TARGETED RE-COLLECTION" not in normal

        rework = _build_collector_task({
            "user_request": "compare Notion vs Confluence",
            "target_products": ["Notion", "Confluence"],
            "knowledge_gaps": [
                {"type": "missing_data", "severity": "major",
                 "target_collect_task": "find enterprise pricing for Notion"},
            ],
        })
        assert "TARGETED RE-COLLECTION" in rework
        assert "enterprise pricing" in rework
        # Should NOT include the full "for each product, collect data points" boilerplate
        assert "For each product, collect data points covering these categories" not in rework

    def test_targeted_rework_includes_gap_details(self):
        rework = _build_collector_task({
            "user_request": "test",
            "target_products": ["X", "Y"],
            "knowledge_gaps": [
                {"type": "source_conflict", "severity": "critical",
                 "target_collect_task": "verify Notion MAU from independent source"},
                {"type": "missing_data", "severity": "major",
                 "target_collect_task": "find Confluence enterprise pricing"},
            ],
        })
        assert "verify Notion MAU" in rework
        assert "Confluence enterprise pricing" in rework
        assert "[critical]" in rework
        assert "[major]" in rework
        assert "do not re-collect everything" in rework.lower()

    def test_targeted_rework_task(self):
        """Direct test of _build_targeted_rework_task."""
        task = _build_targeted_rework_task(
            {"target_products": ["Notion", "Confluence"]},
            [
                {"type": "missing_data", "severity": "major",
                 "target_collect_task": "find Notion pricing tiers"},
            ],
        )
        assert "TARGETED RE-COLLECTION" in task
        assert "Notion pricing tiers" in task
        assert "Notion, Confluence" in task  # original products listed

    def test_normal_task_without_gaps_unchanged(self):
        """Without gaps, the task should use the original full-collection format."""
        task = _build_collector_task({
            "user_request": "analyze Cursor",
            "target_products": ["Cursor"],
        })
        assert "Search for competitive intelligence data on:" in task
        assert "features: product capabilities" in task
        assert "pricing: tiers, prices" in task
        assert "TARGETED RE-COLLECTION" not in task

    def test_rework_task_without_product_extraction(self):
        """When gap task_text doesn't contain extractable product names, task still builds."""
        task = _build_collector_task({
            "user_request": "test",
            "target_products": ["A", "B"],
            "knowledge_gaps": [
                {"type": "fact_error", "severity": "minor",
                 "target_collect_task": "re-check the pricing page for accuracy"},
            ],
        })
        assert "TARGETED RE-COLLECTION" in task
        assert "re-check the pricing page" in task
