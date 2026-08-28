"""Business-layer SQLite persistence — source credibility, product baseline, analysis history.

Per COMPETITION_PLAN.md §3.14: Three tables extending the same SQLite file
used by the framework checkpointer. Not required for the core flow to run.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Default DB path — competition-specific database
DEFAULT_DB_PATH = Path(os.getenv("CI_AGENT_DB_PATH", ".ci-agent/competition.db"))

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
    conn.execute("PRAGMA foreign_keys=ON")
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
            token_usage TEXT,
            analysis_brief TEXT,
            confirmation_source TEXT,
            confirmed_at TEXT
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
            generation_id TEXT,
            PRIMARY KEY (thread_id, phase_key)
        );

        CREATE TABLE IF NOT EXISTS intelligence_sources (
            source_key TEXT PRIMARY KEY,
            canonical_url TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_domain TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT 'unknown',
            product TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'Global / unspecified',
            status TEXT NOT NULL DEFAULT 'healthy',
            last_success_at TEXT,
            last_fetched_at TEXT,
            failure_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            avg_latency_ms INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS intelligence_items (
            item_key TEXT PRIMARY KEY,
            product TEXT NOT NULL,
            dimension TEXT NOT NULL,
            label TEXT NOT NULL,
            value TEXT NOT NULL,
            source_url TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_domain TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'Global / unspecified',
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5,
            credibility_tier TEXT NOT NULL DEFAULT 'secondary',
            status TEXT NOT NULL DEFAULT 'available',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS intelligence_item_versions (
            item_key TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (item_key, version_no),
            FOREIGN KEY (item_key) REFERENCES intelligence_items(item_key) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_intelligence_items_scope ON intelligence_items(product, dimension, scope, last_seen_at);
        CREATE INDEX IF NOT EXISTS idx_intelligence_items_source ON intelligence_items(source_type, source_domain);
        CREATE INDEX IF NOT EXISTS idx_intelligence_items_status ON intelligence_items(status, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_intelligence_sources_status ON intelligence_sources(status, updated_at);

        CREATE TABLE IF NOT EXISTS intelligence_changes (
            change_id TEXT PRIMARY KEY,
            item_key TEXT NOT NULL,
            product TEXT NOT NULL DEFAULT '',
            dimension TEXT NOT NULL DEFAULT '',
            source_domain TEXT NOT NULL DEFAULT '',
            change_type TEXT NOT NULL,
            material INTEGER NOT NULL DEFAULT 1,
            old_hash TEXT,
            new_hash TEXT,
            old_value TEXT,
            new_value TEXT,
            detected_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_intelligence_changes_item ON intelligence_changes(item_key, detected_at DESC);
        CREATE INDEX IF NOT EXISTS idx_intelligence_changes_material ON intelligence_changes(material, detected_at DESC);

        CREATE TABLE IF NOT EXISTS observation_schedules (
            schedule_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            name TEXT NOT NULL,
            products_json TEXT NOT NULL DEFAULT '[]',
            dimensions_json TEXT NOT NULL DEFAULT '[]',
            market_scope TEXT NOT NULL DEFAULT 'Global / unspecified',
            daily_times_json TEXT NOT NULL DEFAULT '[]',
            interval_minutes INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            next_run_at TEXT,
            last_run_at TEXT,
            last_success_at TEXT,
            last_failure_at TEXT,
            last_status TEXT NOT NULL DEFAULT 'idle',
            last_error TEXT,
            last_skip_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_observation_schedules_due ON observation_schedules(enabled, next_run_at);

        CREATE TABLE IF NOT EXISTS observation_runs (
            run_id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            summary_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            skip_reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_observation_runs_schedule ON observation_runs(schedule_id, started_at DESC);

        CREATE TABLE IF NOT EXISTS alert_rules (
            rule_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            name TEXT NOT NULL,
            event_types_json TEXT NOT NULL DEFAULT '[]',
            products_json TEXT NOT NULL DEFAULT '[]',
            dimensions_json TEXT NOT NULL DEFAULT '[]',
            min_severity TEXT NOT NULL DEFAULT 'major',
            cooldown_minutes INTEGER NOT NULL DEFAULT 60,
            quiet_start TEXT,
            quiet_end TEXT,
            timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
            delivery_mode TEXT NOT NULL DEFAULT 'immediate',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_alert_rules_user ON alert_rules(user_id, enabled);

        CREATE TABLE IF NOT EXISTS alert_events (
            event_id TEXT PRIMARY KEY,
            rule_id TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT 'default',
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'major',
            dedupe_key TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            sent_at TEXT,
            suppressed_reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_alert_events_dedupe ON alert_events(rule_id, dedupe_key, last_seen_at DESC);
        CREATE INDEX IF NOT EXISTS idx_alert_events_pending ON alert_events(status, last_seen_at DESC);

        CREATE TABLE IF NOT EXISTS notification_deliveries (
            delivery_id TEXT PRIMARY KEY,
            event_id TEXT,
            route TEXT NOT NULL,
            channel TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_notification_deliveries_event ON notification_deliveries(event_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS knowledge_documents (
            document_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            space_id TEXT NOT NULL DEFAULT '',
            source_key TEXT NOT NULL,
            title TEXT NOT NULL,
            filename TEXT NOT NULL DEFAULT '',
            media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            source_type TEXT NOT NULL DEFAULT 'upload',
            source_uri TEXT NOT NULL DEFAULT '',
            product TEXT NOT NULL DEFAULT '',
            dimension TEXT NOT NULL DEFAULT '',
            market_scope TEXT NOT NULL DEFAULT 'Global / unspecified',
            authority_tier TEXT NOT NULL DEFAULT 'third_party',
            status TEXT NOT NULL DEFAULT 'queued',
            current_version INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT '',
            file_path TEXT NOT NULL DEFAULT '',
            normalized_path TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            published_at TEXT,
            observed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error TEXT,
            approval_status TEXT NOT NULL DEFAULT 'approved',
            approved_by TEXT,
            approved_at TEXT,
            retention_until TEXT,
            deleted_at TEXT,
            deleted_by TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(user_id, source_key)
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_documents_user ON knowledge_documents(user_id, status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_knowledge_documents_scope ON knowledge_documents(user_id, product, dimension, published_at);

        CREATE TABLE IF NOT EXISTS knowledge_document_versions (
            document_id TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            file_path TEXT NOT NULL,
            normalized_path TEXT NOT NULL DEFAULT '',
            char_count INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'queued',
            created_at TEXT NOT NULL,
            superseded_at TEXT,
            error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (document_id, version_no),
            FOREIGN KEY (document_id) REFERENCES knowledge_documents(document_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_versions_hash ON knowledge_document_versions(content_hash);

        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            user_id TEXT NOT NULL DEFAULT 'default',
            ordinal INTEGER NOT NULL,
            text TEXT NOT NULL,
            contextual_text TEXT NOT NULL,
            section_path TEXT NOT NULL DEFAULT '',
            page_no INTEGER,
            token_count INTEGER NOT NULL DEFAULT 0,
            qdrant_point_id TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (document_id, version_no) REFERENCES knowledge_document_versions(document_id, version_no) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document ON knowledge_chunks(document_id, version_no, active, ordinal);
        CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_user ON knowledge_chunks(user_id, active);

        CREATE TABLE IF NOT EXISTS knowledge_ingestion_jobs (
            job_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            document_id TEXT,
            operation TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            progress INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (document_id) REFERENCES knowledge_documents(document_id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_jobs_user ON knowledge_ingestion_jobs(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS knowledge_retrieval_logs (
            retrieval_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default',
            query TEXT NOT NULL,
            filters_json TEXT NOT NULL DEFAULT '{}',
            result_count INTEGER NOT NULL DEFAULT 0,
            selected_chunk_ids_json TEXT NOT NULL DEFAULT '[]',
            duration_ms INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'completed',
            error TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_retrieval_user ON knowledge_retrieval_logs(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS knowledge_spaces (
            space_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            require_approval INTEGER NOT NULL DEFAULT 0,
            retention_days INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_spaces_owner ON knowledge_spaces(owner_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS knowledge_space_members (
            space_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (space_id, user_id),
            FOREIGN KEY (space_id) REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_members_user ON knowledge_space_members(user_id, role);

        CREATE TABLE IF NOT EXISTS knowledge_deletion_audit (
            audit_id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            deleted_at TEXT NOT NULL,
            snapshot_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS knowledge_review_feedback (
            review_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            space_id TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            feedback_type TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            correction TEXT NOT NULL DEFAULT '',
            source_domain TEXT NOT NULL DEFAULT '',
            credibility_before REAL,
            credibility_after REAL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (document_id) REFERENCES knowledge_documents(document_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_review_document ON knowledge_review_feedback(document_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_knowledge_review_space ON knowledge_review_feedback(space_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_knowledge_deletion_space ON knowledge_deletion_audit(space_id, deleted_at DESC);

        CREATE TABLE IF NOT EXISTS knowledge_entities (
            entity_id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            entity_type TEXT NOT NULL DEFAULT 'product',
            normalized_key TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(space_id, normalized_key)
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_entities_space ON knowledge_entities(space_id, canonical_name);

        CREATE TABLE IF NOT EXISTS knowledge_entity_aliases (
            space_id TEXT NOT NULL,
            alias_key TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (space_id, alias_key),
            FOREIGN KEY (entity_id) REFERENCES knowledge_entities(entity_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS knowledge_events (
            event_id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            dimension TEXT NOT NULL DEFAULT 'general',
            title TEXT NOT NULL,
            statement TEXT NOT NULL,
            occurred_at TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'observed',
            confidence REAL NOT NULL DEFAULT 0.5,
            evidence_count INTEGER NOT NULL DEFAULT 0,
            cluster_key TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(space_id, cluster_key),
            FOREIGN KEY (entity_id) REFERENCES knowledge_entities(entity_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_events_scope ON knowledge_events(space_id, entity_id, occurred_at DESC);

        CREATE TABLE IF NOT EXISTS knowledge_event_evidence (
            event_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            chunk_id TEXT,
            source_uri TEXT NOT NULL DEFAULT '',
            authority_tier TEXT NOT NULL DEFAULT 'third_party',
            observed_at TEXT NOT NULL,
            PRIMARY KEY (event_id, document_id, version_no),
            FOREIGN KEY (event_id) REFERENCES knowledge_events(event_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS knowledge_insights (
            insight_id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            insight_type TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5,
            status TEXT NOT NULL DEFAULT 'active',
            period_start TEXT,
            period_end TEXT,
            evidence_event_ids_json TEXT NOT NULL DEFAULT '[]',
            generated_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_insights_space ON knowledge_insights(space_id, insight_type, generated_at DESC);

        CREATE TABLE IF NOT EXISTS knowledge_relations (
            relation_id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            source_entity_id TEXT NOT NULL,
            target_entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            dimension TEXT NOT NULL DEFAULT 'general',
            statement TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.5,
            status TEXT NOT NULL DEFAULT 'observed',
            valid_from TEXT,
            valid_to TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            evidence_count INTEGER NOT NULL DEFAULT 0,
            citation_eligible INTEGER NOT NULL DEFAULT 1,
            cluster_key TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(space_id, cluster_key),
            FOREIGN KEY (source_entity_id) REFERENCES knowledge_entities(entity_id) ON DELETE CASCADE,
            FOREIGN KEY (target_entity_id) REFERENCES knowledge_entities(entity_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_relations_source ON knowledge_relations(space_id, source_entity_id, relation_type, valid_from DESC);
        CREATE INDEX IF NOT EXISTS idx_knowledge_relations_target ON knowledge_relations(space_id, target_entity_id, relation_type, valid_from DESC);

        CREATE TABLE IF NOT EXISTS knowledge_relation_evidence (
            evidence_id TEXT PRIMARY KEY,
            relation_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            chunk_id TEXT,
            event_id TEXT,
            source_uri TEXT NOT NULL DEFAULT '',
            authority_tier TEXT NOT NULL DEFAULT 'third_party',
            stance TEXT NOT NULL DEFAULT 'supporting',
            observed_at TEXT NOT NULL,
            FOREIGN KEY (relation_id) REFERENCES knowledge_relations(relation_id) ON DELETE CASCADE,
            FOREIGN KEY (document_id) REFERENCES knowledge_documents(document_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_relation_evidence_relation ON knowledge_relation_evidence(relation_id, observed_at DESC);
        CREATE INDEX IF NOT EXISTS idx_knowledge_relation_evidence_document ON knowledge_relation_evidence(document_id, version_no);
    """)
    # Migration: add columns that may not exist in older DBs
    _migrate_analysis_history(conn)
    _migrate_phase_history(conn)
    _migrate_knowledge_governance(conn)

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

    # User settings: per-user config overrides (API keys, model, search toggles, etc.)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id TEXT PRIMARY KEY,
            active_group TEXT DEFAULT 'groupA',
            default_model TEXT DEFAULT '',
            provider_keys TEXT DEFAULT '{}',
            provider_bases TEXT DEFAULT '{}',
            agent_configs TEXT DEFAULT '{}',
            search_toggles TEXT DEFAULT '{}',
            feishu_config TEXT DEFAULT '{}',
            config_groups TEXT DEFAULT '[]',
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS analysis_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            template_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, name)
        );
        CREATE INDEX IF NOT EXISTS idx_analysis_templates_user ON analysis_templates(user_id, updated_at DESC);
    """)
    # Migrations
    for col, default in [("provider_bases", "'{}'"), ("config_groups", "'[]'")]:
        try:
            conn.execute(f"ALTER TABLE user_settings ADD COLUMN {col} TEXT DEFAULT {default}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def _migrate_phase_history(conn: sqlite3.Connection) -> None:
    """Add optional phase output and exact generation association columns."""
    for sql in (
        "ALTER TABLE phase_history ADD COLUMN json_output TEXT DEFAULT '{}'",
        "ALTER TABLE phase_history ADD COLUMN generation_id TEXT",
    ):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.execute("CREATE INDEX IF NOT EXISTS idx_phase_history_generation ON phase_history(thread_id, generation_id)")


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
        "ALTER TABLE analysis_history ADD COLUMN analysis_brief TEXT",
        "ALTER TABLE analysis_history ADD COLUMN confirmation_source TEXT",
        "ALTER TABLE analysis_history ADD COLUMN confirmed_at TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists


def _migrate_knowledge_governance(conn: sqlite3.Connection) -> None:
    """Extend pre-space knowledge databases without discarding local content."""
    migrations = (
        "ALTER TABLE knowledge_documents ADD COLUMN space_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE knowledge_documents ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'approved'",
        "ALTER TABLE knowledge_documents ADD COLUMN approved_by TEXT",
        "ALTER TABLE knowledge_documents ADD COLUMN approved_at TEXT",
        "ALTER TABLE knowledge_documents ADD COLUMN retention_until TEXT",
        "ALTER TABLE knowledge_documents ADD COLUMN deleted_at TEXT",
        "ALTER TABLE knowledge_documents ADD COLUMN deleted_by TEXT",
    )
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_documents_space ON knowledge_documents(space_id, approval_status, deleted_at, updated_at DESC)"
    )


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
    analysis_brief: dict | None = None,
    confirmation_source: str | None = None,
    confirmed_at: str | None = None,
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
                current_node, progress, created_at, updated_at, token_usage, title,
                analysis_brief, confirmation_source, confirmed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                json.dumps(analysis_brief, ensure_ascii=False, default=str) if analysis_brief is not None else None,
                confirmation_source,
                confirmed_at,
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
        if analysis_brief is not None:
            updates.append("analysis_brief = ?")
            params.append(json.dumps(analysis_brief, ensure_ascii=False, default=str))
        if confirmation_source is not None:
            updates.append("confirmation_source = ?")
            params.append(confirmation_source)
        if confirmed_at is not None:
            updates.append("confirmed_at = ?")
            params.append(confirmed_at)

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
    existing = conn.execute("SELECT thread_id FROM analysis_history WHERE thread_id = ?", (thread_id,)).fetchone()
    if existing:
        conn.execute(
            """UPDATE analysis_history SET query = ?, products = ?, persona = ?, deep_mode = ?,
               status = 'completed', key_findings = ?, report_path = ?, metrics = ?,
               report_data = ?, updated_at = ? WHERE thread_id = ?""",
            (
                query, json.dumps(products), persona, int(deep_mode),
                json.dumps(key_findings), report_path, json.dumps(metrics),
                json.dumps(report_data, ensure_ascii=False, default=str) if report_data else None,
                now, thread_id,
            ),
        )
    else:
        conn.execute(
            """INSERT INTO analysis_history
               (thread_id, user_id, query, products, persona, deep_mode, status,
                created_at, key_findings, report_path, metrics, report_data, updated_at)
               VALUES (?, 'default', ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?)""",
            (
                thread_id, query, json.dumps(products), persona, int(deep_mode),
                now, json.dumps(key_findings), report_path, json.dumps(metrics),
                json.dumps(report_data, ensure_ascii=False, default=str) if report_data else None, now,
            ),
        )
    conn.commit()


def get_analysis(thread_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
    """Retrieve a single analysis record by thread_id, including full report_data."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    row = conn.execute(
        "SELECT thread_id, user_id, query, products, industry, persona, created_at, key_findings, metrics, report_data, status, token_usage, title, analysis_brief, confirmation_source, confirmed_at "
        "FROM analysis_history WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    if close_conn:
        conn.close()
    if row is None:
        return None
    return {
        "thread_id": row[0], "user_id": row[1], "query": row[2],
        "products": json.loads(row[3]) if row[3] else [],
        "industry": row[4] or "general", "persona": row[5], "created_at": row[6],
        "key_findings": json.loads(row[7]) if row[7] else [],
        "metrics": json.loads(row[8]) if row[8] else {},
        "report_data": json.loads(row[9]) if row[9] else None,
        "status": row[10] or "unknown",
        "token_usage": json.loads(row[11]) if row[11] else [],
        "title": row[12] or "",
        "analysis_brief": _decode_json_object(row[13]),
        "confirmation_source": row[14],
        "confirmed_at": row[15],
    }


def _decode_json_object(raw: str | None) -> dict | None:
    """Decode persisted JSON without making legacy reads fail."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Ignoring malformed persisted JSON object")
        return None


def claim_analysis_start(
    thread_id: str,
    expected_revision: int,
    normalized_brief: dict,
    *,
    confirmation_source: str = "user",
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Atomically claim an awaiting thread for exactly one worker submission."""
    from competition.brief import canonical_editable_payload
    from competition.schema import AnalysisBrief

    close_conn = conn is None
    if conn is None:
        conn = init_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status, analysis_brief, query, products, user_id, industry, persona FROM analysis_history WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            conn.rollback()
            return {"result": "not_found"}

        current_status, raw_brief = row[0], _decode_json_object(row[1])
        submitted = AnalysisBrief.model_validate(normalized_brief)
        current = AnalysisBrief.model_validate(raw_brief) if raw_brief else None
        if current_status != "awaiting_confirmation":
            if current is not None and canonical_editable_payload(current) == canonical_editable_payload(submitted):
                conn.commit()
                return {"result": "idempotent", "status": current_status, "brief": current.model_dump()}
            conn.commit()
            return {"result": "conflict", "status": current_status, "brief": current.model_dump() if current else None}

        current_revision = current.revision if current is not None else 1
        if expected_revision != current_revision:
            conn.rollback()
            return {"result": "conflict", "status": current_status, "reason": "stale_revision", "brief": current.model_dump() if current else None}

        encoded = json.dumps(submitted.model_dump(), ensure_ascii=False, default=str)
        cursor = conn.execute(
            """UPDATE analysis_history
               SET status = 'running', analysis_brief = ?, products = ?,
                   confirmation_source = ?, confirmed_at = ?, updated_at = ?
               WHERE thread_id = ? AND status = 'awaiting_confirmation'""",
            (
                encoded,
                json.dumps(submitted.target_products, ensure_ascii=False),
                confirmation_source,
                submitted.confirmed_at,
                datetime.now(UTC).isoformat(),
                thread_id,
            ),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return {"result": "conflict", "status": current_status, "reason": "lost_claim"}
        conn.commit()
        return {
            "result": "claimed",
            "status": "running",
            "brief": submitted.model_dump(),
            "query": row[2] or "",
            "user_id": row[4] or "default",
            "industry": row[5] or "general",
            "persona": row[6] or "pm",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        if close_conn:
            conn.close()


def restore_analysis_to_waiting(thread_id: str, *, error: str = "") -> bool:
    """Rollback only a just-claimed start when executor submission fails."""
    conn = init_db()
    try:
        updates = "status = 'awaiting_confirmation', confirmation_source = NULL, confirmed_at = NULL, updated_at = ?"
        params: list = [datetime.now(UTC).isoformat()]
        if error:
            updates += ", progress = ?"
            params.append(error[:200])
        params.append(thread_id)
        cursor = conn.execute(
            f"UPDATE analysis_history SET {updates} WHERE thread_id = ? AND status = 'running' AND current_node IS NULL",
            params,
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


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
    generation_id: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """INSERT or REPLACE a phase record for persistent phase bubble content."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    conn.execute(
        """INSERT OR REPLACE INTO phase_history
           (thread_id, phase_key, label, icon, status, start_time, end_time, tokens, content, details, json_output, version, generation_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            thread_id, phase_key, label, icon, status,
            start_time, end_time, tokens,
            json.dumps(content or {}, ensure_ascii=False),
            json.dumps(details or [], ensure_ascii=False, default=str),
            json.dumps(json_output or {}, ensure_ascii=False, default=str),
            version,
            generation_id,
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
        "SELECT phase_key, label, icon, status, start_time, end_time, tokens, content, details, json_output, version, generation_id "
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
            "version": r[10], "generation_id": r[11],
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


def list_history(conn: sqlite3.Connection, limit: int = 10, user_id: str | None = None) -> list[dict]:
    """List recent analysis history entries.

    When user_id is provided and not 'default', filters to that user only.
    The 'default' user sees all entries (backward compatible).
    """
    if user_id and user_id != "default":
        rows = conn.execute(
            "SELECT thread_id, user_id, query, products, industry, persona, status, "
            "current_node, progress, created_at, key_findings, metrics, pinned, title, analysis_brief "
            "FROM analysis_history WHERE user_id IN (?, 'default') "
            "ORDER BY pinned DESC, created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT thread_id, user_id, query, products, industry, persona, status, "
            "current_node, progress, created_at, key_findings, metrics, pinned, title, analysis_brief "
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
            "analysis_brief": _decode_json_object(row[14]) if len(row) > 14 else None,
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


# ── Analysis Brief templates ──


def list_analysis_templates(user_id: str, conn: sqlite3.Connection | None = None) -> list[dict]:
    """Return the current user's reusable Analysis Brief templates."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    rows = conn.execute(
        "SELECT id, name, template_json, created_at, updated_at FROM analysis_templates WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    ).fetchall()
    if close_conn:
        conn.close()
    result = []
    for row in rows:
        try:
            brief = json.loads(row[2])
        except (TypeError, json.JSONDecodeError):
            continue
        result.append({"id": row[0], "name": row[1], "brief": brief, "created_at": row[3], "updated_at": row[4]})
    return result


def save_analysis_template(user_id: str, name: str, brief: dict, conn: sqlite3.Connection | None = None) -> dict:
    """Create or update one user-owned Analysis Brief template."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO analysis_templates (user_id, name, template_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id, name) DO UPDATE SET template_json = excluded.template_json, updated_at = excluded.updated_at""",
        (user_id, name, json.dumps(brief, ensure_ascii=False), now, now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, created_at, updated_at FROM analysis_templates WHERE user_id = ? AND name = ?",
        (user_id, name),
    ).fetchone()
    if close_conn:
        conn.close()
    return {"id": row[0], "name": name, "brief": brief, "created_at": row[1], "updated_at": row[2]}


def delete_analysis_template(user_id: str, template_id: int, conn: sqlite3.Connection | None = None) -> bool:
    """Delete one template only when it belongs to the requesting user."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    cursor = conn.execute("DELETE FROM analysis_templates WHERE id = ? AND user_id = ?", (template_id, user_id))
    conn.commit()
    if close_conn:
        conn.close()
    return cursor.rowcount > 0


# ── User Settings (per-user config overrides) ──


def get_user_settings(user_id: str, conn: sqlite3.Connection | None = None) -> dict:
    """Get per-user settings. Returns defaults if no settings saved yet."""
    import json as _json
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    row = conn.execute(
        "SELECT active_group, default_model, provider_keys, provider_bases, agent_configs, search_toggles, feishu_config, config_groups, updated_at "
        "FROM user_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if close_conn:
        conn.close()
    if row is None:
        return {
            "active_group": "groupA", "default_model": "",
            "provider_keys": {}, "provider_bases": {},
            "agent_configs": {},
            "search_toggles": {}, "feishu_config": {},
            "config_groups": [],
        }
    return {
        "active_group": row[0] or "groupA",
        "default_model": row[1] or "",
        "provider_keys": _json.loads(row[2]) if row[2] else {},
        "provider_bases": _json.loads(row[3]) if row[3] else {},
        "agent_configs": _json.loads(row[4]) if row[4] else {},
        "search_toggles": _json.loads(row[5]) if row[5] else {},
        "feishu_config": _json.loads(row[6]) if row[6] else {},
        "config_groups": _json.loads(row[7]) if row[7] else [],
        "updated_at": row[8] or "",
    }


def save_user_settings(user_id: str, settings: dict, conn: sqlite3.Connection | None = None) -> bool:
    """Save per-user settings (upsert)."""
    import json as _json
    from datetime import UTC, datetime
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO user_settings (user_id, active_group, default_model, provider_keys, provider_bases, agent_configs, search_toggles, feishu_config, config_groups, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             active_group=excluded.active_group, default_model=excluded.default_model,
             provider_keys=excluded.provider_keys, provider_bases=excluded.provider_bases,
             agent_configs=excluded.agent_configs,
             search_toggles=excluded.search_toggles, feishu_config=excluded.feishu_config,
             config_groups=excluded.config_groups,
             updated_at=excluded.updated_at""",
        (
            user_id,
            settings.get("active_group", "groupA"),
            settings.get("default_model", ""),
            _json.dumps(settings.get("provider_keys", {}), ensure_ascii=False),
            _json.dumps(settings.get("provider_bases", {}), ensure_ascii=False),
            _json.dumps(settings.get("agent_configs", {}), ensure_ascii=False),
            _json.dumps(settings.get("search_toggles", {}), ensure_ascii=False),
            _json.dumps(settings.get("feishu_config", {}), ensure_ascii=False),
            _json.dumps(settings.get("config_groups", []), ensure_ascii=False),
            now,
        ),
    )
    conn.commit()
    if close_conn:
        conn.close()
    return True


def save_user_settings_if_current(
    user_id: str,
    settings: dict,
    expected_updated_at: str = "",
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Atomically save settings only when the caller still has the latest token."""
    import json as _json
    from datetime import UTC, datetime

    close_conn = conn is None
    if conn is None:
        conn = init_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT updated_at FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        current_token = (row[0] if row and row[0] else "")
        if current_token != (expected_updated_at or ""):
            conn.rollback()
            return {"result": "conflict", "settings": get_user_settings(user_id, conn=conn)}

        now = datetime.now(UTC).isoformat()
        conn.execute(
            """INSERT INTO user_settings (user_id, active_group, default_model, provider_keys, provider_bases, agent_configs, search_toggles, feishu_config, config_groups, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 active_group=excluded.active_group, default_model=excluded.default_model,
                 provider_keys=excluded.provider_keys, provider_bases=excluded.provider_bases,
                 agent_configs=excluded.agent_configs, search_toggles=excluded.search_toggles,
                 feishu_config=excluded.feishu_config, config_groups=excluded.config_groups,
                 updated_at=excluded.updated_at""",
            (
                user_id,
                settings.get("active_group", "groupA"),
                settings.get("default_model", ""),
                _json.dumps(settings.get("provider_keys", {}), ensure_ascii=False),
                _json.dumps(settings.get("provider_bases", {}), ensure_ascii=False),
                _json.dumps(settings.get("agent_configs", {}), ensure_ascii=False),
                _json.dumps(settings.get("search_toggles", {}), ensure_ascii=False),
                _json.dumps(settings.get("feishu_config", {}), ensure_ascii=False),
                _json.dumps(settings.get("config_groups", []), ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
        return {"result": "saved", "settings": get_user_settings(user_id, conn=conn)}
    finally:
        if close_conn:
            conn.close()


def migrate_default_data(target_user_id: str, conn: sqlite3.Connection | None = None) -> int:
    """Assign all 'default' user data to target_user_id. Returns number of rows updated."""
    close_conn = conn is None
    if conn is None:
        conn = init_db()
    cursor = conn.execute(
        "UPDATE analysis_history SET user_id = ? WHERE user_id = 'default'",
        (target_user_id,),
    )
    count = cursor.rowcount
    conn.commit()
    if close_conn:
        conn.close()
    return count
