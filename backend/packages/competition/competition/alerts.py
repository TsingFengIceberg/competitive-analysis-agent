"""Rule-based competitive-change alerts with dedupe, cooldown and quiet hours."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from competition.db import DEFAULT_DB_PATH, init_db

logger = logging.getLogger(__name__)
SEVERITY_ORDER = {"minor": 1, "major": 2, "critical": 3}
DEFAULT_EVENT_TYPES = ("fact_changed", "new_fact", "page_changed", "source_failure", "evidence_conflict", "recommendation_changed")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        item = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return item.replace(tzinfo=UTC) if item.tzinfo is None else item.astimezone(UTC)
    except ValueError:
        return None


@dataclass
class AlertRule:
    name: str
    event_types: list[str] = field(default_factory=lambda: list(DEFAULT_EVENT_TYPES))
    products: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    min_severity: str = "major"
    cooldown_minutes: int = 60
    quiet_start: str | None = None
    quiet_end: str | None = None
    timezone: str = "Asia/Shanghai"
    delivery_mode: str = "immediate"
    enabled: bool = True
    rule_id: str = ""
    user_id: str = "default"

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("alert rule name is required")
        if self.min_severity not in SEVERITY_ORDER:
            raise ValueError("min_severity must be minor, major, or critical")
        if self.delivery_mode not in {"immediate", "digest"}:
            raise ValueError("delivery_mode must be immediate or digest")
        if self.cooldown_minutes < 0:
            raise ValueError("cooldown_minutes cannot be negative")
        for value in (self.quiet_start, self.quiet_end):
            if value is not None and (len(value) != 5 or value[2] != ":"):
                raise ValueError("quiet hours must use HH:MM")
        try:
            ZoneInfo(self.timezone)
        except Exception as exc:
            raise ValueError(f"invalid timezone: {self.timezone}") from exc
        self.event_types = list(dict.fromkeys(self.event_types or DEFAULT_EVENT_TYPES))
        self.rule_id = self.rule_id or uuid.uuid4().hex

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AlertRule:
        return cls(
            name=payload.get("name", ""), event_types=payload.get("event_types") or list(DEFAULT_EVENT_TYPES),
            products=payload.get("products") or [], dimensions=payload.get("dimensions") or [],
            min_severity=payload.get("min_severity", "major"), cooldown_minutes=int(payload.get("cooldown_minutes", 60)),
            quiet_start=payload.get("quiet_start"), quiet_end=payload.get("quiet_end"), timezone=payload.get("timezone", "Asia/Shanghai"),
            delivery_mode=payload.get("delivery_mode", "immediate"), enabled=bool(payload.get("enabled", True)),
            rule_id=str(payload.get("rule_id") or ""), user_id=str(payload.get("user_id") or "default"),
        )

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "user_id": self.user_id, "name": self.name, "event_types": self.event_types,
                "products": self.products, "dimensions": self.dimensions, "min_severity": self.min_severity,
                "cooldown_minutes": self.cooldown_minutes, "quiet_start": self.quiet_start, "quiet_end": self.quiet_end,
                "timezone": self.timezone, "delivery_mode": self.delivery_mode, "enabled": self.enabled}


class AlertRepository:
    def __init__(self, conn=None, db_path=DEFAULT_DB_PATH):
        self._owned = conn is None
        self.conn = conn or init_db(db_path)

    def close(self) -> None:
        if self._owned:
            self.conn.close()

    def save_rule(self, rule: AlertRule) -> dict:
        now = _iso(_now())
        self.conn.execute(
            """INSERT INTO alert_rules (rule_id, user_id, name, event_types_json, products_json, dimensions_json,
               min_severity, cooldown_minutes, quiet_start, quiet_end, timezone, delivery_mode, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(rule_id) DO UPDATE SET user_id=excluded.user_id, name=excluded.name, event_types_json=excluded.event_types_json,
               products_json=excluded.products_json, dimensions_json=excluded.dimensions_json, min_severity=excluded.min_severity,
               cooldown_minutes=excluded.cooldown_minutes, quiet_start=excluded.quiet_start, quiet_end=excluded.quiet_end,
               timezone=excluded.timezone, delivery_mode=excluded.delivery_mode, enabled=excluded.enabled, updated_at=excluded.updated_at""",
            (rule.rule_id, rule.user_id, rule.name, json.dumps(rule.event_types), json.dumps(rule.products), json.dumps(rule.dimensions),
             rule.min_severity, rule.cooldown_minutes, rule.quiet_start, rule.quiet_end, rule.timezone, rule.delivery_mode, int(rule.enabled), now, now),
        )
        self.conn.commit()
        return self.get_rule(rule.rule_id) or rule.to_dict()

    def get_rule(self, rule_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM alert_rules WHERE rule_id = ?", (rule_id,)).fetchone()
        return self._decode_rule(row) if row else None

    def list_rules(self, *, user_id: str | None = None, enabled_only: bool = False) -> list[dict]:
        clauses, params = [], []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if enabled_only:
            clauses.append("enabled = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(f"SELECT * FROM alert_rules {where} ORDER BY created_at ASC", params).fetchall()
        return [self._decode_rule(row) for row in rows]

    def delete_rule(self, rule_id: str) -> bool:
        cursor = self.conn.execute("DELETE FROM alert_rules WHERE rule_id = ?", (rule_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def find_recent(self, rule_id: str, dedupe_key: str, since: datetime) -> dict | None:
        row = self.conn.execute(
            "SELECT event_id, last_seen_at, sent_at, status FROM alert_events WHERE rule_id = ? AND dedupe_key = ? AND last_seen_at >= ? ORDER BY last_seen_at DESC LIMIT 1",
            (rule_id, dedupe_key, _iso(since)),
        ).fetchone()
        return {"event_id": row[0], "last_seen_at": row[1], "sent_at": row[2], "status": row[3]} if row else None

    def save_event(self, event: dict) -> dict:
        self.conn.execute(
            """INSERT INTO alert_events (event_id, rule_id, user_id, event_type, severity, dedupe_key, title, message, payload_json, status, first_seen_at, last_seen_at, sent_at, suppressed_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event["event_id"], event["rule_id"], event.get("user_id", "default"), event["event_type"],
                event["severity"], event["dedupe_key"], event["title"], event["message"],
                json.dumps(event.get("payload", {}), ensure_ascii=False, default=str), event.get("status", "pending"),
                event["first_seen_at"], event["last_seen_at"], event.get("sent_at"), event.get("suppressed_reason"),
            ),
        )
        self.conn.commit()
        return event

    def list_events(self, *, user_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
        clauses, params = [], []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        rows = self.conn.execute(
            f"SELECT event_id, rule_id, user_id, event_type, severity, dedupe_key, title, message, "
            f"payload_json, status, first_seen_at, last_seen_at, sent_at, suppressed_reason "
            f"FROM alert_events {where} ORDER BY last_seen_at DESC LIMIT ?", params,
        ).fetchall()
        keys = ("event_id", "rule_id", "user_id", "event_type", "severity", "dedupe_key", "title", "message", "payload", "status", "first_seen_at", "last_seen_at", "sent_at", "suppressed_reason")
        result = []
        for row in rows:
            item = dict(zip(keys, row, strict=True))
            item["payload"] = json.loads(item["payload"]) if item["payload"] else {}
            result.append(item)
        return result

    def get_event(self, event_id: str, *, user_id: str | None = None) -> dict | None:
        """Load one alert event while enforcing its optional user boundary."""
        clauses = ["event_id = ?"]
        params: list[Any] = [event_id]
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        row = self.conn.execute(
            f"SELECT event_id, rule_id, user_id, event_type, severity, dedupe_key, title, message, payload_json, status, first_seen_at, last_seen_at, sent_at, suppressed_reason FROM alert_events WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
        if row is None:
            return None
        keys = ("event_id", "rule_id", "user_id", "event_type", "severity", "dedupe_key", "title", "message", "payload", "status", "first_seen_at", "last_seen_at", "sent_at", "suppressed_reason")
        result = dict(zip(keys, row, strict=True))
        result["payload"] = json.loads(result["payload"]) if result["payload"] else {}
        return result

    def mark_status(self, event_ids: list[str], status: str, *, sent_at: str | None = None, reason: str | None = None) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        self.conn.execute(
            f"UPDATE alert_events SET status = ?, sent_at = COALESCE(?, sent_at), suppressed_reason = COALESCE(?, suppressed_reason) WHERE event_id IN ({placeholders})",
            [status, sent_at, reason, *event_ids],
        )
        self.conn.commit()

    @staticmethod
    def _decode_rule(row) -> dict:
        keys = ("rule_id", "user_id", "name", "event_types", "products", "dimensions", "min_severity", "cooldown_minutes", "quiet_start", "quiet_end", "timezone", "delivery_mode", "enabled", "created_at", "updated_at")
        item = dict(zip(keys, row, strict=True))
        for key in ("event_types", "products", "dimensions"):
            item[key] = json.loads(item[key]) if item[key] else []
        item["enabled"] = bool(item["enabled"])
        return item


class AlertEngine:
    def __init__(self, repository: AlertRepository, clock: Any = _now):
        self.repository = repository
        self.clock = clock

    def evaluate(self, changes: list[dict], *, rules: list[dict] | None = None) -> list[dict]:
        now = self.clock()
        rules = rules if rules is not None else self.repository.list_rules(enabled_only=True)
        emitted = []
        for change in changes:
            event_type = str(change.get("change_type") or "fact_changed")
            severity = self._severity(change)
            for rule in rules:
                if not self._matches(rule, change, event_type, severity):
                    continue
                dedupe_key = self._dedupe_key(change, event_type)
                recent = self.repository.find_recent(rule["rule_id"], dedupe_key, now.replace(microsecond=0) - timedelta(minutes=int(rule.get("cooldown_minutes", 60))))
                if recent:
                    continue
                quiet = self._in_quiet_hours(rule, now)
                status = "suppressed" if quiet else ("pending" if rule.get("delivery_mode") == "digest" else "pending")
                event = {
                    "event_id": uuid.uuid4().hex, "rule_id": rule["rule_id"], "user_id": rule.get("user_id", "default"),
                    "event_type": event_type, "severity": severity, "dedupe_key": dedupe_key,
                    "title": self._title(change, event_type), "message": self._message(change, event_type),
                    "payload": {**change, "_notification_channels": list(rule.get("channels") or [])},
                    "status": status, "first_seen_at": _iso(now), "last_seen_at": _iso(now),
                    "suppressed_reason": "quiet_hours" if quiet else None,
                    "channels": list(rule.get("channels") or []),
                }
                self.repository.save_event(event)
                emitted.append(event)
        return emitted

    def digest_events(self, *, user_id: str | None = None, limit: int = 100) -> list[dict]:
        """Return pending digest events without sending them or changing status."""
        events = self.repository.list_events(user_id=user_id, status="pending", limit=limit)
        rule_ids = {event["rule_id"] for event in events}
        digest_rules = {rule["rule_id"] for rule in self.repository.list_rules(user_id=user_id) if rule.get("delivery_mode") == "digest"}
        return [event for event in events if event["rule_id"] in rule_ids & digest_rules]

    @staticmethod
    def _matches(rule: dict, change: dict, event_type: str, severity: str) -> bool:
        if not rule.get("enabled", True) or event_type not in (rule.get("event_types") or DEFAULT_EVENT_TYPES):
            return False
        if SEVERITY_ORDER[severity] < SEVERITY_ORDER.get(rule.get("min_severity", "major"), 2):
            return False
        product = str(change.get("product", "")).casefold()
        dimension = str(change.get("dimension", "")).casefold()
        products = {str(item).casefold() for item in rule.get("products") or []}
        dimensions = {str(item).casefold() for item in rule.get("dimensions") or []}
        return (not products or product in products) and (not dimensions or dimension in dimensions)

    @staticmethod
    def _severity(change: dict) -> str:
        if change.get("change_type") in {"source_failure", "recommendation_changed", "evidence_conflict"}:
            return "critical"
        if change.get("change_type") in {"fact_changed", "new_fact"} or change.get("material"):
            return "major"
        return "minor"

    @staticmethod
    def _dedupe_key(change: dict, event_type: str) -> str:
        raw = f"{event_type}|{change.get('product','')}|{change.get('dimension','')}|{change.get('item_key','')}|{change.get('new_hash','')}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _title(change: dict, event_type: str) -> str:
        return f"竞品变化：{change.get('product', '未知产品')} · {event_type}"

    @staticmethod
    def _message(change: dict, event_type: str) -> str:
        return f"{change.get('product', '未知产品')} 的 {change.get('dimension', '未知维度')} 出现 {event_type}，新值：{change.get('new_value', '')}。"

    @staticmethod
    def _in_quiet_hours(rule: dict, now: datetime) -> bool:
        start, end = rule.get("quiet_start"), rule.get("quiet_end")
        if not start or not end:
            return False
        try:
            local = now.astimezone(ZoneInfo(rule.get("timezone") or "Asia/Shanghai"))
            current = local.hour * 60 + local.minute
            begin = int(start[:2]) * 60 + int(start[3:])
            finish = int(end[:2]) * 60 + int(end[3:])
            return current >= begin or current < finish if begin > finish else begin <= current < finish
        except Exception:
            return False


def deliver_alert_events(repository: AlertRepository, events: list[dict], *, channels: list[str] | None = None) -> list[dict]:
    """Deliver alert events best-effort and persist per-channel outcomes."""
    from competition.notifications import NotificationMessage, dispatch_notification

    results = []
    for event in events:
        if event.get("status") == "suppressed":
            continue
        result = dispatch_notification(
            NotificationMessage(route="alert", title=event["title"], body=event["message"], severity=event["severity"], event_id=event["event_id"], payload=event.get("payload") or {}),
            channels=channels or event.get("channels") or (event.get("payload") or {}).get("_notification_channels") or None,
        )
        sent = any(item.get("status") == "sent" for item in result.get("results", {}).values())
        status = "sent" if sent else "failed"
        repository.mark_status([event["event_id"]], status, sent_at=_iso(_now()) if sent else None, reason=None if sent else "all_channels_failed")
        results.append({"event_id": event["event_id"], "status": status, "delivery": result})
    return results
