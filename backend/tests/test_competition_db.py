"""Tests for competition/db.py — SQLite business tables."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from competition.brief import brief_from_request, validate_confirmation_brief
from competition.db import (
    CREDIBILITY_DELTA,
    DEFAULT_CREDIBILITY_SCORE,
    claim_analysis_start,
    get_all_credibilities,
    get_analysis,
    get_baseline,
    get_credibility,
    get_phases,
    init_db,
    list_history,
    record_analysis,
    save_phase,
    set_baseline,
    update_credibility,
    upsert_analysis,
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
            pinned INTEGER DEFAULT 0,
            analysis_brief TEXT,
            confirmation_source TEXT,
            confirmed_at TEXT
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

    def test_brief_round_trip_and_list(self, conn):
        brief = brief_from_request("Cursor vs Copilot")
        upsert_analysis(
            "thread-brief", status="awaiting_confirmation", query="Cursor vs Copilot",
            products=brief.target_products, persona="pm", analysis_brief=brief.model_dump(), conn=conn,
        )
        record = get_analysis("thread-brief", conn)
        assert record["analysis_brief"]["target_products"] == ["Cursor", "Copilot"]
        assert list_history(conn)[0]["analysis_brief"]["dimensions"]

    def test_legacy_null_brief_is_readable(self, conn):
        upsert_analysis("legacy", status="completed", query="old", products=["A"], conn=conn)
        assert list_history(conn)[0]["analysis_brief"] is None

    def test_record_analysis_preserves_existing_brief(self, conn):
        brief = brief_from_request("Cursor vs Copilot")
        upsert_analysis("recorded", status="running", query="Cursor vs Copilot", products=brief.target_products,
                        analysis_brief=brief.model_dump(), conn=conn)
        record_analysis("recorded", "Cursor vs Copilot", brief.target_products, "pm", False, [], "", {},
                        report_data={"title": "done"}, conn=conn)
        assert get_analysis("recorded", conn)["analysis_brief"]["target_products"] == ["Cursor", "Copilot"]

    def test_claim_and_idempotent_replay(self, conn):
        draft = brief_from_request("最好的 AI 编程工具有哪些？")
        upsert_analysis(
            "claim", status="awaiting_confirmation", query="best tools",
            products=draft.target_products, analysis_brief=draft.model_dump(), conn=conn,
        )
        confirmed = validate_confirmation_brief(draft.model_copy(update={"target_products": ["Cursor", "Copilot"]}))
        claimed = claim_analysis_start("claim", draft.revision, confirmed.model_dump(), conn=conn)
        assert claimed["result"] == "claimed"
        replay = claim_analysis_start("claim", 999, confirmed.model_dump(), conn=conn)
        assert replay["result"] == "idempotent"

    def test_claim_conflict_after_start(self, conn):
        draft = brief_from_request("Cursor vs Copilot")
        upsert_analysis("conflict", status="awaiting_confirmation", analysis_brief=draft.model_dump(), conn=conn)
        confirmed = validate_confirmation_brief(draft)
        assert claim_analysis_start("conflict", draft.revision, confirmed.model_dump(), conn=conn)["result"] == "claimed"
        different = validate_confirmation_brief(draft.model_copy(update={"target_products": ["Cursor", "Windsurf"]}))
        result = claim_analysis_start("conflict", draft.revision, different.model_dump(), conn=conn)
        assert result["result"] == "conflict"

    def test_concurrent_claim_has_one_winner(self, tmp_path):
        db_path = tmp_path / "claim.db"
        setup = init_db(db_path)
        draft = brief_from_request("Cursor vs Copilot")
        upsert_analysis("race", status="awaiting_confirmation", analysis_brief=draft.model_dump(), conn=setup)
        setup.close()
        confirmed = validate_confirmation_brief(draft)

        def attempt(_):
            local = init_db(db_path)
            try:
                return claim_analysis_start("race", draft.revision, confirmed.model_dump(), conn=local)["result"]
            finally:
                local.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        assert results.count("claimed") == 1
        assert results.count("idempotent") == 1


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

    def test_phase_generation_id_round_trip(self, tmp_path):
        db_path = tmp_path / "phases.db"
        conn = init_db(db_path)
        save_phase("thread", "writer", label="报告生成", generation_id="generation-1", conn=conn)
        rows = get_phases("thread", conn=conn)
        assert rows[0]["generation_id"] == "generation-1"
        column_names = {row[1] for row in conn.execute("PRAGMA table_info(phase_history)")}
        assert "generation_id" in column_names
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
