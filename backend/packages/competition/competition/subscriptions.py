"""Durable subscriptions and user feedback for competitive intelligence alerts."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from competition.db import DEFAULT_DB_PATH, init_db

SEVERITY_ORDER = {"minor": 1, "major": 2, "critical": 3}
FEEDBACK_ACTIONS = {"confirmed", "ignored", "corrected"}
SUPPORTED_CHANNELS = {"in_app", "feishu", "webhook"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _decode(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        result = json.loads(str(value))
    except (TypeError, ValueError):
        return fallback
    return result


def subscriptions_as_alert_rules(subscriptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate enabled subscriptions into ephemeral AlertEngine rules.

    The alert engine remains the single matching/deduplication implementation;
    a subscription only supplies a user's scope and delivery preference.
    """
    rules: list[dict[str, Any]] = []
    for item in subscriptions:
        if not item.get("enabled", True):
            continue
        rules.append(
            {
                "rule_id": f"subscription:{item.get('subscription_id')}",
                "user_id": item.get("user_id", "default"),
                "name": item.get("name", "情报订阅"),
                "event_types": ["new_fact", "fact_changed", "source_failure", "evidence_conflict", "recommendation_changed"],
                "products": item.get("products") or [],
                "dimensions": item.get("dimensions") or [],
                "min_severity": item.get("min_severity", "major"),
                "cooldown_minutes": 60,
                "delivery_mode": "immediate",
                "channels": item.get("channels") or ["in_app"],
                "enabled": True,
            }
        )
    return rules


@dataclass
class IntelligenceSubscription:
    name: str
    products: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    space_id: str = ""
    min_severity: str = "major"
    channels: list[str] = field(default_factory=lambda: ["in_app"])
    enabled: bool = True
    subscription_id: str = ""
    user_id: str = "default"

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()
        if not self.name:
            raise ValueError("subscription name is required")
        if self.min_severity not in SEVERITY_ORDER:
            raise ValueError("min_severity must be minor, major, or critical")
        self.products = list(dict.fromkeys(str(value).strip() for value in self.products if str(value).strip()))
        self.dimensions = list(dict.fromkeys(str(value).strip() for value in self.dimensions if str(value).strip()))
        self.channels = list(dict.fromkeys(str(value).strip() for value in self.channels if str(value).strip())) or ["in_app"]
        unsupported = set(self.channels) - SUPPORTED_CHANNELS
        if unsupported:
            raise ValueError(f"unsupported notification channels: {', '.join(sorted(unsupported))}")
        self.subscription_id = self.subscription_id or f"sub-{uuid.uuid4().hex}"

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, user_id: str) -> IntelligenceSubscription:
        return cls(
            name=payload.get("name", ""),
            products=payload.get("products") or [],
            dimensions=payload.get("dimensions") or [],
            space_id=str(payload.get("space_id") or ""),
            min_severity=str(payload.get("min_severity") or "major"),
            channels=payload.get("channels") or ["in_app"],
            enabled=bool(payload.get("enabled", True)),
            subscription_id=str(payload.get("subscription_id") or ""),
            user_id=user_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "user_id": self.user_id,
            "name": self.name,
            "products": self.products,
            "dimensions": self.dimensions,
            "space_id": self.space_id,
            "min_severity": self.min_severity,
            "channels": self.channels,
            "enabled": self.enabled,
        }


class SubscriptionRepository:
    """Own subscriptions and feedback while reusing the competition SQLite DB."""

    def __init__(self, conn=None, db_path=DEFAULT_DB_PATH):
        self._owned = conn is None
        self.conn = conn or init_db(db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._owned:
            self.conn.close()

    def __enter__(self) -> SubscriptionRepository:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def save(self, subscription: IntelligenceSubscription) -> dict[str, Any]:
        now = _now()
        self.conn.execute(
            """INSERT INTO intelligence_subscriptions (
                   subscription_id, user_id, name, products_json, dimensions_json,
                   space_id, min_severity, channels_json, enabled, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(subscription_id) DO UPDATE SET
                   user_id=excluded.user_id, name=excluded.name,
                   products_json=excluded.products_json, dimensions_json=excluded.dimensions_json,
                   space_id=excluded.space_id, min_severity=excluded.min_severity,
                   channels_json=excluded.channels_json, enabled=excluded.enabled,
                   updated_at=excluded.updated_at""",
            (
                subscription.subscription_id,
                subscription.user_id,
                subscription.name,
                json.dumps(subscription.products, ensure_ascii=False),
                json.dumps(subscription.dimensions, ensure_ascii=False),
                subscription.space_id,
                subscription.min_severity,
                json.dumps(subscription.channels, ensure_ascii=False),
                int(subscription.enabled),
                now,
                now,
            ),
        )
        self.conn.commit()
        return self.get(subscription.subscription_id, subscription.user_id) or subscription.to_dict()

    def get(self, subscription_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM intelligence_subscriptions WHERE subscription_id = ? AND user_id = ?",
            (subscription_id, user_id),
        ).fetchone()
        return self._decode_subscription(row) if row else None

    def list(self, user_id: str, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = "user_id = ?" + (" AND enabled = 1" if enabled_only else "")
        rows = self.conn.execute(
            f"SELECT * FROM intelligence_subscriptions WHERE {where} ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [self._decode_subscription(row) for row in rows]

    def delete(self, subscription_id: str, user_id: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM intelligence_subscriptions WHERE subscription_id = ? AND user_id = ?",
            (subscription_id, user_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def save_feedback(
        self,
        *,
        event_id: str,
        user_id: str,
        action: str,
        correction: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        if action not in FEEDBACK_ACTIONS:
            raise ValueError("feedback action must be confirmed, ignored, or corrected")
        if action == "corrected" and not str(correction).strip():
            raise ValueError("correction is required for corrected feedback")
        now = _now()
        feedback_id = f"feedback-{uuid.uuid4().hex}"
        self.conn.execute(
            """INSERT INTO alert_feedback (
                   feedback_id, event_id, user_id, action, correction, note, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(event_id, user_id) DO UPDATE SET
                   action=excluded.action, correction=excluded.correction,
                   note=excluded.note, updated_at=excluded.updated_at""",
            (feedback_id, event_id, user_id, action, str(correction).strip(), str(note).strip(), now, now),
        )
        self.conn.commit()
        return self.get_feedback(event_id, user_id) or {
            "feedback_id": feedback_id,
            "event_id": event_id,
            "user_id": user_id,
            "action": action,
            "correction": correction,
            "note": note,
            "created_at": now,
            "updated_at": now,
        }

    def get_feedback(self, event_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM alert_feedback WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        ).fetchone()
        return dict(row) if row else None

    def list_feedback(self, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM alert_feedback WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [dict(row) for row in rows]

    def feedback_summary(self, user_id: str) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT action, COUNT(*) AS count FROM alert_feedback WHERE user_id = ? GROUP BY action",
            (user_id,),
        ).fetchall()
        counts = {str(row[0]): int(row[1]) for row in rows}
        total = sum(counts.values())
        return {
            "total": total,
            "confirmed": counts.get("confirmed", 0),
            "ignored": counts.get("ignored", 0),
            "corrected": counts.get("corrected", 0),
            "confirmation_rate": round(counts.get("confirmed", 0) / total, 6) if total else 0.0,
        }

    @staticmethod
    def _decode_subscription(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["products"] = _decode(result.pop("products_json", "[]"), [])
        result["dimensions"] = _decode(result.pop("dimensions_json", "[]"), [])
        result["channels"] = _decode(result.pop("channels_json", "[\"in_app\"]"), ["in_app"])
        result["enabled"] = bool(result.get("enabled"))
        return result
