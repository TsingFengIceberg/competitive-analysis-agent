"""BranchTree SQLite MetadataStore — branch_snapshots 表持久化。

只存 checkpoint_id 引用 + 业务 metadata。完整 state 由 LangGraph 管理。
实现 tree.MetadataStore 协议。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(".deer-flow/competition.db")

# ── Schema ──────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS branch_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    parent_version INTEGER,
    checkpoint_id TEXT NOT NULL,
    action TEXT NOT NULL,
    is_approved INTEGER DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bs_thread ON branch_snapshots(thread_id);
CREATE INDEX IF NOT EXISTS idx_bs_thread_version ON branch_snapshots(thread_id, version);
CREATE INDEX IF NOT EXISTS idx_bs_parent ON branch_snapshots(parent_version);
CREATE INDEX IF NOT EXISTS idx_bs_approved ON branch_snapshots(thread_id, is_approved);
"""


# ── Store ───────────────────────────────────────────────────────


class BranchSnapshotStore:
    """SQLite 实现的 MetadataStore 协议。

    Usage::

        store = BranchSnapshotStore()
        v1 = store.insert("t1", None, "ck001", "initial", {"persona": "PM"})
        v2 = store.insert("t1", v1, "ck002", "rewrite")
        rows = store.list_by_thread("t1")
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None  # 惰性初始化，复用同一连接
        # :memory: 数据库必须共享同一连接（每个 :memory: 连接是独立数据库）
        # 文件数据库也复用连接以避免 WAL 锁竞争

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            try:
                self._conn.execute("SELECT 1")
                return self._conn
            except sqlite3.ProgrammingError:
                # Connection from another thread — recreate
                self._conn = None
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(CREATE_TABLE_SQL)
        self._conn = conn
        return conn

    # ── MetadataStore protocol ───────────────────────────────────

    def insert(
        self,
        thread_id: str,
        parent_version: int | None,
        checkpoint_id: str,
        action: str,
        metadata: dict | None = None,
    ) -> int:
        """插入新版本记录，返回 per-thread version 号。"""
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        # Compute next version number for this thread (per-thread, starts at 1)
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM branch_snapshots WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        next_version = row[0]
        conn.execute(
            """INSERT INTO branch_snapshots
               (thread_id, version, parent_version, checkpoint_id, action, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (thread_id, next_version, parent_version, checkpoint_id, action,
             json.dumps(metadata or {}, ensure_ascii=False), now),
        )
        conn.commit()
        return next_version

    def get(self, thread_id: str, version: int) -> dict | None:
        """获取指定版本的 metadata。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM branch_snapshots WHERE thread_id = ? AND version = ?",
            (thread_id, version),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_by_thread(self, thread_id: str) -> list[dict]:
        """列出 thread 下所有版本，按 version 升序。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM branch_snapshots WHERE thread_id = ? ORDER BY version ASC",
            (thread_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ── 扩展操作（MetadataStore 协议之外）─────────────────────────

    def approve(self, thread_id: str, version: int) -> None:
        """标记版本为已批准。"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE branch_snapshots SET is_approved = 1 WHERE thread_id = ? AND version = ?",
            (thread_id, version),
        )
        conn.commit()

    def is_approved(self, thread_id: str, version: int) -> bool:
        """检查版本是否已批准。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT is_approved FROM branch_snapshots WHERE thread_id = ? AND version = ?",
            (thread_id, version),
        ).fetchone()
        return bool(row and row[0])

    def get_approved(self, thread_id: str) -> list[dict]:
        """获取 thread 下所有已批准的版本。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM branch_snapshots WHERE thread_id = ? AND is_approved = 1 ORDER BY version ASC",
            (thread_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete_thread(self, thread_id: str) -> None:
        """删除 thread 下所有版本记录。"""
        conn = self._get_conn()
        conn.execute("DELETE FROM branch_snapshots WHERE thread_id = ?", (thread_id,))
        conn.commit()

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── 内部 ─────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return {
            "version": row["version"],
            "thread_id": row["thread_id"],
            "parent_version": row["parent_version"],
            "checkpoint_id": row["checkpoint_id"],
            "action": row["action"],
            "is_approved": bool(row["is_approved"]),
            "metadata_json": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
        }
