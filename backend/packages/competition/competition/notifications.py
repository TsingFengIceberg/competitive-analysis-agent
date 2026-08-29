"""Unified notification contract with isolated channel failures."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass
class NotificationMessage:
    route: str
    title: str
    body: str
    severity: str = "major"
    event_id: str | None = None
    thread_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.route not in {"report", "alert", "system_error"}:
            raise ValueError("route must be report, alert, or system_error")
        self.event_id = self.event_id or uuid.uuid4().hex

    def to_dict(self) -> dict:
        return {"route": self.route, "title": self.title, "body": self.body, "severity": self.severity,
                "event_id": self.event_id, "thread_id": self.thread_id, "payload": self.payload}


class NotificationChannel(Protocol):
    name: str

    def send(self, message: NotificationMessage) -> bool: ...


class FeishuChannel:
    name = "feishu"

    def send(self, message: NotificationMessage) -> bool:
        from competition.feishu_notify import is_notify_enabled, notify_text
        if not is_notify_enabled():
            return False
        return notify_text(message.title, message.body, thread_id=message.thread_id or "")


class WebhookChannel:
    name = "webhook"

    def __init__(self, url: str, *, timeout: float = 10):
        self.url = str(url).strip()
        self.timeout = timeout

    def send(self, message: NotificationMessage) -> bool:
        if not self.url:
            return False
        payload = json.dumps(message.to_dict(), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return 200 <= int(response.status) < 300
        except Exception as exc:
            logger.warning("Webhook notification failed: %s", exc)
            return False


class InAppChannel:
    """Durable in-app delivery represented by the alert_events row itself."""

    name = "in_app"

    def send(self, message: NotificationMessage) -> bool:
        return bool(message.event_id)


class NotificationRouter:
    def __init__(self, channels: list[NotificationChannel] | None = None):
        self.channels = {channel.name: channel for channel in (channels or [])}

    def register(self, channel: NotificationChannel) -> None:
        self.channels[channel.name] = channel

    def dispatch(self, message: NotificationMessage, *, channel_names: list[str] | None = None) -> dict:
        names = channel_names or list(self.channels)
        results: dict[str, dict] = {}
        for name in names:
            channel = self.channels.get(name)
            if channel is None:
                results[name] = {"status": "skipped", "error": "channel_not_configured"}
                continue
            try:
                ok = bool(channel.send(message))
                results[name] = {"status": "sent" if ok else "failed", "error": None if ok else "channel_rejected"}
            except Exception as exc:
                logger.warning("Notification channel %s failed: %s", name, exc)
                results[name] = {"status": "failed", "error": str(exc)[:240]}
        return {"event_id": message.event_id, "route": message.route, "results": results,
                "created_at": datetime.now(UTC).isoformat()}


def default_notification_router(*, webhook_url: str | None = None) -> NotificationRouter:
    router = NotificationRouter([InAppChannel(), FeishuChannel()])
    url = webhook_url or os.environ.get("CI_AGENT_NOTIFICATION_WEBHOOK", "")
    if url:
        router.register(WebhookChannel(url))
    return router


def dispatch_notification(message: NotificationMessage, *, channels: list[str] | None = None, webhook_url: str | None = None) -> dict:
    """Best-effort convenience API; every channel is isolated from the caller."""
    return default_notification_router(webhook_url=webhook_url).dispatch(message, channel_names=channels)
