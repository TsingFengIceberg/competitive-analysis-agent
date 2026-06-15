"""Tests for competition/db.py — SQLite business tables."""

from __future__ import annotations

import sqlite3

import pytest

from competition.db import (
    CREDIBILITY_DELTA,
    upsert_analysis,
    DEFAULT_CREDIBILITY_SCORE,
    get_all_credibilities,
    get_baseline,
    get_credibility,
    init_db,
    list_history,
    record_analysis,
    set_baseline,
    update_credibility,
)


@pytest.fixture
def conn():
    """In-memory SQLite for test isolation."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
        CREATE TABLE IF NOT EXISTS source_credibility (
            source_domain TEXT PRIMARY KEY,
            score REAL NOT NULL DEFAULT 0.50,
            verification_count INTEGER DEFAULT 0,
            last_verified_at TEXT,
            last_verdict TEXT
        );
        CREATE TABLE IF NOT EXISTS product_baseline (
            product_name TEXT NOT NULL,
            attribute TEXT NOT NULL,
            value TEXT,
            source_url TEXT,
            confidence REAL,
            recorded_at TEXT,
            updated_at TEXT,
            PRIMARY KEY (product_name, attribute)
        );
        CREATE TABLE IF NOT EXISTS analysis_history (
            thread_id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'default',
            query TEXT,
            products TEXT,
            industry TEXT DEFAULT 'general',
            persona TEXT,
            deep_mode INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running',
            current_node TEXT,
            progress TEXT,
            created_at TEXT,
            updated_at TEXT,
            key_findings TEXT,
            report_path TEXT,
            metrics TEXT,
            report_data TEXT,
            token_usage TEXT,
            title TEXT,
            pinned INTEGER DEFAULT 0
        );
    """)
    c.commit()
    yield c
    c.close()


class TestSourceCredibility:
    def test_default_for_unknown(self, conn):
        assert get_credibility("unknown.com", conn) == 0.50

    def test_update_verified(self, conn):
        new = update_credibility("g2.com", "verified", conn)
        assert new == 0.55

    def test_update_error(self, conn):
        new = update_credibility("bad.com", "error", conn)
        assert new == 0.35

    def test_clamped_to_zero(self, conn):
        score = DEFAULT_CREDIBILITY_SCORE
        domain = "terrible.com"
        for _ in range(10):
            score = update_credibility(domain, "error", conn)
        assert score >= 0.0

    def test_clamped_to_one(self, conn):
        score = DEFAULT_CREDIBILITY_SCORE
        domain = "excellent.com"
        for _ in range(20):
            score = update_credibility(domain, "verified", conn)
        assert score <= 1.0

    def test_get_all(self, conn):
        update_credibility("a.com", "verified", conn)
        update_credibility("b.com", "conflict", conn)
        all_scores = get_all_credibilities(conn)
        assert "a.com" in all_scores
        assert "b.com" in all_scores

    def test_empty_domain_unchanged(self, conn):
        assert update_credibility("", "verified", conn) == 0.50


class TestProductBaseline:
    def test_set_and_get(self, conn):
        set_baseline("Cursor", "pricing_pro", "$20", source_url="cursor.com/pricing", conn=conn)
        baseline = get_baseline("Cursor", conn)
        assert "pricing_pro" in baseline
        assert baseline["pricing_pro"]["value"] == "$20"

    def test_update_same_value(self, conn):
        set_baseline("Cursor", "version", "0.48", conn=conn)
        set_baseline("Cursor", "version", "0.48", conn=conn)  # no change
        baseline = get_baseline("Cursor", conn)
        assert baseline["version"]["value"] == "0.48"

    def test_update_changed_value(self, conn):
        set_baseline("Cursor", "pricing_pro", "$20", conn=conn)
        set_baseline("Cursor", "pricing_pro", "$30", conn=conn)
        baseline = get_baseline("Cursor", conn)
        assert baseline["pricing_pro"]["value"] == "$30"

    def test_unknown_product(self, conn):
        assert get_baseline("Unknown", conn) == {}


class TestAnalysisHistory:
    def test_record_and_list(self, conn):
        upsert_analysis(
            "thread-1", status="completed", query="analyze Cursor",
            products=["Cursor"], persona="pm",
            key_findings=["finding 1"], metrics={"coverage": 0.9}, conn=conn,
        )
        history = list_history(conn)
        assert len(history) == 1
        assert history[0]["thread_id"] == "thread-1"

    def test_multiple_entries(self, conn):
        for i in range(3):
            upsert_analysis(
                f"thread-{i}", status="completed", query=f"query {i}",
                products=["A"], persona="pm",
                key_findings=[f"f{i}"], metrics={"c": i}, conn=conn,
            )
        assert len(list_history(conn, limit=2)) == 2  # respects limit
        assert len(list_history(conn, limit=10)) == 3

    def test_deep_mode_recorded(self, conn):
        upsert_analysis("t-deep", status="completed", query="q",
                        products=["A"], persona="pm", conn=conn)
        history = list_history(conn)
        # deep_mode was True (1)
        assert history[0]["thread_id"] == "t-deep"


class TestInitDb:
    def test_creates_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = init_db(str(db_path))
        conn.close()
        assert db_path.exists()

    def test_tables_exist(self, tmp_path):
        db_path = tmp_path / "test2.db"
        conn = init_db(str(db_path))
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {t[0] for t in tables}
        assert "source_credibility" in table_names
        assert "product_baseline" in table_names
        assert "analysis_history" in table_names
        conn.close()


class TestCredibilityDelta:
    def test_deltas_defined(self):
        assert "verified" in CREDIBILITY_DELTA
        assert "conflict" in CREDIBILITY_DELTA
        assert "error" in CREDIBILITY_DELTA
        assert "outdated" in CREDIBILITY_DELTA

    def test_error_is_strongest(self):
        assert CREDIBILITY_DELTA["error"] < CREDIBILITY_DELTA["conflict"]
        assert abs(CREDIBILITY_DELTA["error"]) > abs(CREDIBILITY_DELTA["outdated"])
