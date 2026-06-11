"""Business-layer SQLite persistence — source credibility, product baseline, analysis history.

Per COMPETITION_PLAN.md §3.14: Three tables extending the same SQLite file
used by the framework checkpointer. Not required for the core flow to run.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Default DB path — competition-specific database
DEFAULT_DB_PATH = Path(".ci-agent/competition.db")

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
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    # IOPS optimisation: NORMAL synchronous only fsyncs at WAL checkpoints,
    # not on every commit. Dramatically reduces IOPS on low-quota cloud disks.
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
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
            token_usage TEXT
        );

        CREATE TABLE IF NOT EXISTS phase_history (
            thread_id TEXT NOT NULL,
            phase_key TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            icon TEXT NOT NULL DEFAULT '⚙️',
            status TEXT NOT NULL DEFAULT 'running',
            start_time TEXT,
            end_time TEXT,
            tokens INTEGER DEFAULT 0,
            content TEXT DEFAULT '{}',
            details TEXT DEFAULT '[]',
            version INTEGER DEFAULT 0,
            PRIMARY KEY (thread_id, phase_key)
        );
    """)
    # Migration: add columns that may not exist in older DBs
    _migrate_analysis_history(conn)
    _migrate_phase_history(conn)

    # Content persistence: full fetched page text for evidence verification
    conn.execute("""
        CREATE TABLE IF NOT EXISTS content_store (
            content_ref TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            full_text TEXT NOT NULL,
            char_count INTEGER DEFAULT 0,
            fetched_at TEXT NOT NULL
        );
    """)
    conn.commit()
    return conn


def _migrate_phase_history(conn: sqlite3.Connection) -> None:
    """Add json_output column to phase_history if missing."""
    try:
        conn.execute("ALTER TABLE phase_history ADD COLUMN json_output TEXT DEFAULT '{}'")
    except sqlite3.OperationalError:
        pass  # column already exists


def _migrate_analysis_history(conn: sqlite3.Connection) -> None:
    """Add new columns to analysis_history if missing (safe for existing DBs)."""
    migrations = [
        "ALTER TABLE analysis_history ADD COLUMN user_id TEXT DEFAULT 'default'",
        "ALTER TABLE analysis_history ADD COLUMN industry TEXT DEFAULT 'general'",
        "ALTER TABLE analysis_history ADD COLUMN status TEXT DEFAULT 'completed'",
        "ALTER TABLE analysis_history ADD COLUMN current_node TEXT",
        "ALTER TABLE analysis_history ADD COLUMN progress TEXT",
        "ALTER TABLE analysis_history ADD COLUMN updated_at TEXT",
        "ALTER TABLE analysis_history ADD COLUMN token_usage TEXT",
        "ALTER TABLE analysis_history ADD COLUMN pinned INTEGER DEFAULT 0",
        "ALTER TABLE analysis_history ADD COLUMN title TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists


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


# ── Analysis History (§3.14.4 + §18 persistence upgrade) ──


def upsert_analysis(
    thread_id: str,
    status: str | None = None,
    user_id: str | None = None,
    query: str | None = None,
    products: list[str] | None = None,
    industry: str | None = None,
    persona: str | None = None,
    title: str | None = None,
    current_node: str | None = None,
    progress: str | None = None,
    key_findings: list[str] | None = None,
    metrics: dict | None = None,
    report_data: dict | None = None,
    token_usage: list[dict] | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """INSERT or UPDATE an analysis record at any lifecycle stage (§18).

    Called at: analyze start / node completion / analysis done / HITL approved.
    Only updates the fields that are explicitly provided (partial update).
    """
    close_conn = conn is None
    if conn is None:
        conn = init_db()

    now = datetime.now(UTC).isoformat()

    # Check if record exists
    existing = conn.execute(
        "SELECT thread_id FROM analysis_history WHERE thread_id = ?", (thread_id,)
    ).fetchone()

    if existing is None:
        # INSERT new record
        conn.execute(
            """INSERT INTO analysis_history
               (thread_id, user_id, query, products, industry, persona, status,
                current_node, progress, created_at, updated_at, token_usage, title)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                thread_id,
                user_id or "default",
                query or "",
                json.dumps(products or []),
                industry or "general",
                persona or "pm",
                status or "running",
                current_node or "",
                progress or "",
                now, now,
                json.dumps(token_usage or []),
                title or "",
            ),
        )
    else:
        # UPDATE: only set fields that are provided
        updates = ["updated_at = ?"]
        params: list = [now]

        field_map = {
            "status": status, "user_id": user_id, "query": query,
            "industry": industry, "persona": persona,
            "current_node": current_node, "progress": progress,
        }
        for field, value in field_map.items():
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if products is not None:
            updates.append("products = ?")
            params.append(json.dumps(products))
        if key_findings is not None:
            updates.append("key_findings = ?")
            params.append(json.dumps(key_findings))
        if metrics is not None:
            updates.append("metrics = ?")
            params.append(json.dumps(metrics))
        if report_data is not None:
            updates.append("report_data = ?")
            params.append(json.dumps(report_data, ensure_ascii=False, default=str))
        if token_usage is not None:
            updates.append("token_usage = ?")
            params.append(json.dumps(token_usage))

        params.append(thread_id)
        conn.execute(
            f"UPDATE analysis_history SET {', '.join(updates)} WHERE thread_id = ?",
            params,
        )

    conn.commit()
    if close_conn:
        conn.close()


def record_analysis(
    thread_id: str, query: str, products: list[str], persona: str,
    deep_mode: bool, key_findings: list[str], report_path: str,
    metrics: dict, report_data: dict | None = None, conn: sqlite3.Connection | None = None,
) -> None:
    """Record a completed analysis in history (§18 upgrade)."""
    if conn is None:
        conn = init_db()
    now = datetime.now(UTC).isoformat()
    # 13 cols = 12 ?s + 1 literal
    conn.execute(
        """INSERT OR REPLACE INTO analysis_history
           (thread_id, user_id, query, products, persona, deep_mode, status,
            created_at, key_findings, report_path, metrics, report_data, updated_at)
           VALUES (?, 'default', ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?)""",
        (
            thread_id, query, json.dumps(products), persona, int(deep_mode),
            now, json.dumps(key_findings), report_path,
            json.dumps(metrics),
            json.dumps(report_data, ensure_ascii=False, default=str) if report_data else None,
            now,
        ),
    )
    conn.commit()


def get_analysis(thread_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
    """Retrieve a single analysis record by thread_id, including full report_data."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    row = conn.execute(
        "SELECT thread_id, query, products, persona, created_at, key_findings, metrics, report_data, status, token_usage, title "
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
        "status": row[8] or "unknown",
        "token_usage": json.loads(row[9]) if row[9] else [],
        "title": row[10] or "",
    }


def delete_analysis(thread_id: str, conn: sqlite3.Connection | None = None) -> bool:
    """Delete an analysis record by thread_id. Returns True if deleted."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    cur = conn.execute("DELETE FROM analysis_history WHERE thread_id = ?", (thread_id,))
    conn.commit()
    if close_conn:
        conn.close()
    return cur.rowcount > 0


def pin_analysis(thread_id: str, pinned: bool, conn: sqlite3.Connection | None = None) -> bool:
    """Set the pinned status of an analysis record. Returns True if updated."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    cur = conn.execute(
        "UPDATE analysis_history SET pinned = ? WHERE thread_id = ?",
        (1 if pinned else 0, thread_id),
    )
    conn.commit()
    if close_conn:
        conn.close()
    return cur.rowcount > 0


# ── Phase History (§persistent phase bubbles) ──


def save_phase(
    thread_id: str,
    phase_key: str,
    *,
    label: str = "",
    icon: str = "⚙️",
    status: str = "running",
    start_time: str | None = None,
    end_time: str | None = None,
    tokens: int = 0,
    content: dict[str, str] | None = None,
    details: list[dict] | None = None,
    json_output: dict | None = None,
    version: int = 0,
    conn: sqlite3.Connection | None = None,
) -> None:
    """INSERT or REPLACE a phase record for persistent phase bubble content."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    conn.execute(
        """INSERT OR REPLACE INTO phase_history
           (thread_id, phase_key, label, icon, status, start_time, end_time, tokens, content, details, json_output, version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            thread_id, phase_key, label, icon, status,
            start_time, end_time, tokens,
            json.dumps(content or {}, ensure_ascii=False),
            json.dumps(details or [], ensure_ascii=False, default=str),
            json.dumps(json_output or {}, ensure_ascii=False, default=str),
            version,
        ),
    )
    conn.commit()
    if close_conn:
        conn.close()


def get_phases(thread_id: str, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Get all phase records for a thread, ordered by start_time."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    rows = conn.execute(
        "SELECT phase_key, label, icon, status, start_time, end_time, tokens, content, details, json_output, version "
        "FROM phase_history WHERE thread_id = ? ORDER BY start_time ASC",
        (thread_id,),
    ).fetchall()
    if close_conn:
        conn.close()
    return [
        {
            "phase_key": r[0], "label": r[1], "icon": r[2], "status": r[3],
            "start_time": r[4], "end_time": r[5], "tokens": r[6],
            "content": json.loads(r[7]) if r[7] else {},
            "details": json.loads(r[8]) if r[8] else [],
            "json_output": json.loads(r[9]) if r[9] else {},
            "version": r[10],
        }
        for r in rows
    ]


def delete_phase_history(thread_id: str, conn: sqlite3.Connection | None = None) -> None:
    """Delete all phase records for a thread."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    conn.execute("DELETE FROM phase_history WHERE thread_id = ?", (thread_id,))
    conn.commit()
    if close_conn:
        conn.close()


def list_history(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """List recent analysis history entries (§18: +status +industry +pinned +title)."""
    rows = conn.execute(
        "SELECT thread_id, user_id, query, products, industry, persona, status, "
        "current_node, progress, created_at, key_findings, metrics, pinned, title "
        "FROM analysis_history ORDER BY pinned DESC, created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "thread_id": row[0], "user_id": row[1], "query": row[2],
            "products": json.loads(row[3]) if row[3] else [],
            "industry": row[4], "persona": row[5], "status": row[6],
            "current_node": row[7], "progress": row[8],
            "created_at": row[9],
            "key_findings": json.loads(row[10]) if row[10] else [],
            "metrics": json.loads(row[11]) if row[11] else {},
            "pinned": bool(row[12]) if len(row) > 12 and row[12] else False,
            "title": row[13] if len(row) > 13 else "",
        }
        for row in rows
    ]


# ── Content Persistence (§Torrent2002-inspired) ──


def save_content(content_ref: str, url: str, full_text: str, conn: sqlite3.Connection | None = None) -> None:
    """Persist full fetched page text under a content reference key."""
    from datetime import UTC, datetime

    close_conn = conn is None
    if conn is None:
        conn = init_db()
    conn.execute(
        "INSERT OR REPLACE INTO content_store (content_ref, url, full_text, char_count, fetched_at) VALUES (?, ?, ?, ?, ?)",
        (content_ref, url, full_text, len(full_text), datetime.now(UTC).isoformat()),
    )
    conn.commit()
    if close_conn:
        conn.close()


def get_content(content_ref: str, conn: sqlite3.Connection | None = None) -> dict | None:
    """Retrieve full fetched page text by content reference."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    row = conn.execute(
        "SELECT content_ref, url, full_text, char_count, fetched_at FROM content_store WHERE content_ref = ?",
        (content_ref,),
    ).fetchone()
    if close_conn:
        conn.close()
    if row is None:
        return None
    return {
        "content_ref": row[0], "url": row[1], "full_text": row[2],
        "char_count": row[3], "fetched_at": row[4],
    }
