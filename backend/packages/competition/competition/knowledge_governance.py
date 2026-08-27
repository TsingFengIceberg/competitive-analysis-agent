"""Knowledge-space identities, role checks, and retention helpers."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

SPACE_ROLES = ("owner", "editor", "viewer")
WRITE_ROLES = frozenset({"owner", "editor"})
REVIEW_ROLES = frozenset({"owner"})


def personal_space_id(user_id: str) -> str:
    digest = hashlib.sha256(f"ci-agent-personal-space:{user_id}".encode()).hexdigest()[:20]
    return f"kspace-{digest}"


def retention_deadline(retention_days: int, *, now: datetime | None = None) -> str | None:
    if retention_days <= 0:
        return None
    current = now or datetime.now(UTC)
    return (current + timedelta(days=retention_days)).isoformat()


def can_read(role: str | None) -> bool:
    return role in SPACE_ROLES


def can_write(role: str | None) -> bool:
    return role in WRITE_ROLES


def can_review(role: str | None) -> bool:
    return role in REVIEW_ROLES
