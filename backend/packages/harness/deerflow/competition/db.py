"""Business-layer SQLite persistence — source credibility, product baseline, analysis history.

Per COMPETITION_PLAN.md §3.14: Three tables extending the same SQLite file
used by DF's SqliteSaver. Not required for the core flow to run.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Default DB path — same directory as DF's SqliteSaver checkpoint DB
DEFAULT_DB_PATH = Path(".deer-flow/competition.db")

# Credibility score adjustments (§3.14.2)
CREDIBILITY_DELTA: dict[str, float] = {
    "verified": +0.05,
    "conflict": -0.05,
    "error": -0.15,
    "outdated": -0.02,
}
DEFAULT_CREDIBILITY_SCORE = 0.50


# ── Database Initialization ──


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create tables if they don't exist. Returns a connection (caller must close)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
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
            persona TEXT,
            deep_mode INTEGER DEFAULT 0,
            created_at TEXT,
            key_findings TEXT,
            report_path TEXT,
            metrics TEXT,
            report_data TEXT
        );
    """)
    conn.commit()
    return conn


# ── Source Credibility (§3.14.2) ──


def get_credibility(domain: str, conn: sqlite3.Connection) -> float:
    """Get current credibility score for a domain. Returns 0.50 for unknown domains."""
    row = conn.execute(
        "SELECT score FROM source_credibility WHERE source_domain = ?", (domain,)
    ).fetchone()
    return row[0] if row else DEFAULT_CREDIBILITY_SCORE


def update_credibility(domain: str, verdict: str, conn: sqlite3.Connection) -> float:
    """Update credibility score based on Reviewer verdict. Returns new score.

    Verdict values: "verified" / "conflict" / "error" / "outdated"
    """
    if not domain:
        return DEFAULT_CREDIBILITY_SCORE

    delta = CREDIBILITY_DELTA.get(verdict, 0.0)
    current = get_credibility(domain, conn)
    new_score = max(0.0, min(1.0, current + delta))

    conn.execute(
        """INSERT INTO source_credibility (source_domain, score, verification_count, last_verified_at, last_verdict)
           VALUES (?, ?, 1, ?, ?)
           ON CONFLICT(source_domain) DO UPDATE SET
             score = excluded.score,
             verification_count = source_credibility.verification_count + 1,
             last_verified_at = excluded.last_verified_at,
             last_verdict = excluded.last_verdict""",
        (domain, new_score, datetime.now(UTC).isoformat(), verdict),
    )
    conn.commit()
    return new_score


def get_all_credibilities(conn: sqlite3.Connection) -> dict[str, float]:
    """Return all known domain → score mappings."""
    rows = conn.execute("SELECT source_domain, score FROM source_credibility").fetchall()
    return {row[0]: row[1] for row in rows}


# ── Product Baseline (§3.14.3) ──


def get_baseline(product_name: str, conn: sqlite3.Connection) -> dict[str, dict]:
    """Get all baseline attributes for a product. Returns {attribute: {value, updated_at, ...}}."""
    rows = conn.execute(
        "SELECT attribute, value, source_url, confidence, recorded_at, updated_at "
        "FROM product_baseline WHERE product_name = ?",
        (product_name,),
    ).fetchall()
    return {
        row[0]: {
            "value": row[1], "source_url": row[2], "confidence": row[3],
            "recorded_at": row[4], "updated_at": row[5],
        }
        for row in rows
    }


def set_baseline(
    product_name: str, attribute: str, value: str,
    source_url: str = "", confidence: float = 0.5, conn: sqlite3.Connection | None = None,
) -> None:
    """Record/update a product baseline attribute. Detects change from previous value."""
    now = datetime.now(UTC).isoformat()

    if conn is None:
        conn = init_db()

    existing = conn.execute(
        "SELECT value FROM product_baseline WHERE product_name = ? AND attribute = ?",
        (product_name, attribute),
    ).fetchone()

    if existing and existing[0] == value:
        # Value unchanged — just bump updated_at
        conn.execute(
            "UPDATE product_baseline SET updated_at = ? WHERE product_name = ? AND attribute = ?",
            (now, product_name, attribute),
        )
    else:
        conn.execute(
            """INSERT INTO product_baseline (product_name, attribute, value, source_url, confidence, recorded_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(product_name, attribute) DO UPDATE SET
                 value = excluded.value, source_url = excluded.source_url,
                 confidence = excluded.confidence, updated_at = excluded.updated_at""",
            (product_name, attribute, value, source_url, confidence, now, now),
        )
    conn.commit()


# ── Analysis History (§3.14.4) ──


def record_analysis(
    thread_id: str, query: str, products: list[str], persona: str,
    deep_mode: bool, key_findings: list[str], report_path: str,
    metrics: dict, report_data: dict | None = None, conn: sqlite3.Connection | None = None,
) -> None:
    """Record a completed analysis in history. Stores full report_data JSON for later retrieval."""
    if conn is None:
        conn = init_db()
    conn.execute(
        """INSERT OR REPLACE INTO analysis_history
           (thread_id, user_id, query, products, persona, deep_mode, created_at, key_findings, report_path, metrics, report_data)
           VALUES (?, 'default', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            thread_id, query, json.dumps(products), persona, int(deep_mode),
            datetime.now(UTC).isoformat(), json.dumps(key_findings), report_path,
            json.dumps(metrics), json.dumps(report_data, ensure_ascii=False, default=str) if report_data else None,
        ),
    )
    conn.commit()


def get_analysis(thread_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
    """Retrieve a single analysis record by thread_id, including full report_data."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    row = conn.execute(
        "SELECT thread_id, query, products, persona, created_at, key_findings, metrics, report_data "
        "FROM analysis_history WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    if close_conn:
        conn.close()
    if row is None:
        return None
    return {
        "thread_id": row[0], "query": row[1],
        "products": json.loads(row[2]) if row[2] else [],
        "persona": row[3], "created_at": row[4],
        "key_findings": json.loads(row[5]) if row[5] else [],
        "metrics": json.loads(row[6]) if row[6] else {},
        "report_data": json.loads(row[7]) if row[7] else None,
    }


def list_history(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """List recent analysis history entries."""
    rows = conn.execute(
        "SELECT thread_id, query, products, persona, created_at, key_findings, metrics "
        "FROM analysis_history ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "thread_id": row[0], "query": row[1], "products": json.loads(row[2]),
            "persona": row[3], "created_at": row[4], "key_findings": json.loads(row[5]),
            "metrics": json.loads(row[6]),
        }
        for row in rows
    ]
