"""User-scoped source connectors with conditional HTTP synchronization."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from competition.db import DEFAULT_DB_PATH, init_db

MAX_SOURCE_BYTES = 50 * 1024 * 1024
SUPPORTED_SCHEMES = {"http", "https"}
SOURCE_STATUSES = {"idle", "checking", "unchanged", "queued", "healthy", "failed", "disabled"}
SOURCE_TYPES = {"web", "rss", "atom", "sitemap", "json_api"}
_PRIVATE_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal", "metadata"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _decode(value: Any) -> str:
    return str(value or "").strip()


def _is_private_host(hostname: str) -> bool:
    value = hostname.casefold().strip("[]")
    if value in _PRIVATE_HOSTNAMES or value.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_unspecified)


def validate_source_uri(uri: str, *, allow_private: bool | None = None) -> str:
    value = _decode(uri)
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in SUPPORTED_SCHEMES or not parsed.netloc:
        raise ValueError("Only http(s) source URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("Source URL must not contain embedded credentials")
    if allow_private is None:
        allow_private = os.getenv("CI_AGENT_KNOWLEDGE_ALLOW_PRIVATE_SOURCES", "false").lower() in {"1", "true", "yes", "on"}
    if not allow_private and _is_private_host(parsed.hostname or ""):
        raise ValueError("Private or local source hosts are not allowed")
    return value


def _xml_local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].casefold()


def _xml_text(element: ElementTree.Element | None, names: tuple[str, ...]) -> str:
    if element is None:
        return ""
    for child in list(element):
        if _xml_local_name(child.tag) in names:
            return " ".join("".join(child.itertext()).split())
    return ""


def parse_feed_items(data: bytes, *, source_uri: str, media_type: str = "") -> list[dict[str, Any]]:
    """Extract bounded RSS/Atom entries into a provider-neutral shape."""
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return []
    root_name = _xml_local_name(root.tag)
    if root_name not in {"rss", "feed", "rdf"}:
        return []
    entries = [element for element in root.iter() if _xml_local_name(element.tag) in {"item", "entry"}]
    result: list[dict[str, Any]] = []
    for index, entry in enumerate(entries[:200]):
        title = _xml_text(entry, ("title",))
        summary = _xml_text(entry, ("description", "summary", "content"))
        published = _xml_text(entry, ("pubdate", "published", "updated", "date"))
        link = _xml_text(entry, ("link", "guid"))
        if not link:
            for child in list(entry):
                if _xml_local_name(child.tag) == "link" and child.attrib.get("href"):
                    link = str(child.attrib["href"])
                    break
        result.append({
            "entry_id": link or f"{source_uri}#entry-{index + 1}",
            "title": title[:500],
            "summary": summary[:4000],
            "published_at": published[:120] or None,
            "source_uri": link or source_uri,
            "media_type": media_type or "application/rss+xml",
        })
    return [item for item in result if item["title"] or item["summary"]]


def parse_sitemap_urls(data: bytes, *, source_uri: str) -> list[dict[str, Any]]:
    """Extract URLs and last-modified timestamps from XML sitemaps."""
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return []
    result: list[dict[str, Any]] = []
    for index, element in enumerate(root.iter()):
        if _xml_local_name(element.tag) != "url":
            continue
        loc = _xml_text(element, ("loc",))
        if not loc:
            continue
        result.append({
            "entry_id": loc,
            "title": loc,
            "summary": "",
            "published_at": _xml_text(element, ("lastmod",)) or None,
            "source_uri": loc,
            "media_type": "text/html",
            "ordinal": index,
        })
        if len(result) >= 500:
            break
    return result


def parse_json_api_items(data: bytes, *, source_uri: str, media_type: str = "") -> list[dict[str, Any]]:
    """Normalize common JSON API list envelopes without exposing arbitrary fields."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        for key in ("items", "results", "data", "entries"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(payload[:200]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or item.get("id") or f"Entry {index + 1}")
        summary = str(item.get("summary") or item.get("description") or item.get("content") or "")
        uri = str(item.get("url") or item.get("link") or source_uri)
        result.append({
            "entry_id": str(item.get("id") or uri or index),
            "title": title[:500],
            "summary": summary[:4000],
            "published_at": str(item.get("published_at") or item.get("published") or item.get("updated_at") or "")[:120] or None,
            "source_uri": uri,
            "media_type": media_type or "application/json",
        })
    return result


def parse_source_items(data: bytes, *, source_uri: str, source_type: str, media_type: str = "") -> list[dict[str, Any]]:
    kind = str(source_type or "web").casefold()
    if kind in {"rss", "atom"} or "rss" in media_type.casefold() or "atom" in media_type.casefold():
        return parse_feed_items(data, source_uri=source_uri, media_type=media_type)
    if kind == "sitemap" or "sitemap" in media_type.casefold() or source_uri.casefold().split("?", 1)[0].endswith(".xml"):
        return parse_sitemap_urls(data, source_uri=source_uri)
    if kind == "json_api" or "json" in media_type.casefold():
        return parse_json_api_items(data, source_uri=source_uri, media_type=media_type)
    return []


@dataclass
class KnowledgeSourceConnector:
    name: str
    uri: str
    product: str = ""
    dimension: str = ""
    market_scope: str = "Global / unspecified"
    authority_tier: str = "primary"
    media_type: str = "application/octet-stream"
    space_id: str = ""
    source_type: str = "web"
    enabled: bool = True
    sync_interval_minutes: int = 360
    timeout_seconds: int = 20
    source_id: str = ""
    user_id: str = "default"
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    last_checked_at: str | None = None
    last_success_at: str | None = None
    last_status: str = "idle"
    last_error: str | None = None
    failure_count: int = 0
    cooldown_until: str | None = None
    last_job_id: str | None = None

    def __post_init__(self) -> None:
        self.name = _decode(self.name)[:160]
        if not self.name:
            raise ValueError("source name is required")
        self.uri = validate_source_uri(self.uri)
        self.source_type = _decode(self.source_type).casefold() or "web"
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"Unsupported source type: {self.source_type}")
        if self.authority_tier not in {"primary", "structured_fact", "change_event", "third_party", "report"}:
            raise ValueError("Unsupported authority tier")
        self.sync_interval_minutes = max(5, min(int(self.sync_interval_minutes), 7 * 24 * 60))
        self.timeout_seconds = max(3, min(int(self.timeout_seconds), 120))
        self.source_id = self.source_id or f"ksource-{uuid.uuid4().hex}"
        self.last_status = self.last_status if self.last_status in SOURCE_STATUSES else "idle"

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, user_id: str) -> KnowledgeSourceConnector:
        fields = {
            "name",
            "uri",
            "product",
            "dimension",
            "market_scope",
            "authority_tier",
            "media_type",
            "space_id",
            "source_type",
            "enabled",
            "sync_interval_minutes",
            "timeout_seconds",
            "source_id",
            "etag",
            "last_modified",
            "content_hash",
            "last_checked_at",
            "last_success_at",
            "last_status",
            "last_error",
            "failure_count",
            "cooldown_until",
            "last_job_id",
        }
        values = {key: value for key, value in payload.items() if key in fields}
        values["user_id"] = user_id
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "user_id": self.user_id,
            "space_id": self.space_id,
            "name": self.name,
            "uri": self.uri,
            "source_type": self.source_type,
            "product": self.product,
            "dimension": self.dimension,
            "market_scope": self.market_scope,
            "authority_tier": self.authority_tier,
            "media_type": self.media_type,
            "enabled": bool(self.enabled),
            "sync_interval_minutes": self.sync_interval_minutes,
            "timeout_seconds": self.timeout_seconds,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "content_hash": self.content_hash,
            "last_checked_at": self.last_checked_at,
            "last_success_at": self.last_success_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "failure_count": self.failure_count,
            "cooldown_until": self.cooldown_until,
            "last_job_id": self.last_job_id,
        }


class SourceRepository:
    """Persist connector configuration and conditional request metadata."""

    def __init__(self, conn: sqlite3.Connection | None = None, db_path=DEFAULT_DB_PATH):
        self._owned = conn is None
        self.conn = conn or init_db(db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._owned:
            self.conn.close()

    def __enter__(self) -> SourceRepository:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        return item

    def save(self, source: KnowledgeSourceConnector) -> dict[str, Any]:
        now = _now()
        self.conn.execute(
            """INSERT INTO knowledge_source_connectors (
                source_id, user_id, space_id, name, uri, source_type, product,
                dimension, market_scope, authority_tier, media_type, enabled,
                sync_interval_minutes, timeout_seconds, etag, last_modified,
                content_hash, last_checked_at, last_success_at, last_status,
                last_error, failure_count, cooldown_until, last_job_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                name=excluded.name, uri=excluded.uri, source_type=excluded.source_type,
                product=excluded.product, dimension=excluded.dimension,
                market_scope=excluded.market_scope, authority_tier=excluded.authority_tier,
                media_type=excluded.media_type, enabled=excluded.enabled,
                sync_interval_minutes=excluded.sync_interval_minutes,
                timeout_seconds=excluded.timeout_seconds, updated_at=excluded.updated_at""",
            (
                source.source_id,
                source.user_id,
                source.space_id,
                source.name,
                source.uri,
                source.source_type,
                source.product,
                source.dimension,
                source.market_scope,
                source.authority_tier,
                source.media_type,
                int(source.enabled),
                source.sync_interval_minutes,
                source.timeout_seconds,
                source.etag,
                source.last_modified,
                source.content_hash,
                source.last_checked_at,
                source.last_success_at,
                source.last_status,
                source.last_error,
                source.failure_count,
                source.cooldown_until,
                source.last_job_id,
                now,
                now,
            ),
        )
        self.conn.commit()
        return self.get(source.source_id, source.user_id) or source.to_dict()

    def get(self, source_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM knowledge_source_connectors WHERE source_id = ? AND user_id = ?",
            (source_id, user_id),
        ).fetchone()
        return self._row(row)

    def list(self, user_id: str, *, enabled_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        where = "user_id = ?" + (" AND enabled = 1" if enabled_only else "")
        rows = self.conn.execute(
            f"SELECT * FROM knowledge_source_connectors WHERE {where} ORDER BY updated_at DESC LIMIT ?",
            (user_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [self._row(row) for row in rows if row is not None]

    def list_due(self, *, user_id: str | None = None, limit: int = 20, now: datetime | None = None) -> list[dict[str, Any]]:
        """Return enabled sources whose interval has elapsed and cooldown expired."""
        where = ["enabled = 1"]
        params: list[Any] = []
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        rows = self.conn.execute(
            f"SELECT * FROM knowledge_source_connectors WHERE {' AND '.join(where)} ORDER BY updated_at ASC LIMIT ?",
            [*params, max(1, min(int(limit), 100))],
        ).fetchall()
        current = now or datetime.now(UTC)
        result: list[dict[str, Any]] = []
        for row in rows:
            item = self._row(row)
            if item is None:
                continue
            cooldown = item.get("cooldown_until")
            if cooldown:
                try:
                    if datetime.fromisoformat(str(cooldown).replace("Z", "+00:00")) > current:
                        continue
                except ValueError:
                    pass
            checked = item.get("last_checked_at")
            if checked:
                try:
                    checked_at = datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
                    interval = timedelta(minutes=max(5, int(item.get("sync_interval_minutes") or 360)))
                    if checked_at + interval > current:
                        continue
                except ValueError:
                    pass
            result.append(item)
        return result

    def health(self, user_id: str, *, limit: int = 100) -> dict[str, Any]:
        """Return connector health aggregates without exposing credentials."""
        rows = self.list(user_id, limit=limit)
        counts: dict[str, int] = {}
        for item in rows:
            status = str(item.get("last_status") or "idle")
            counts[status] = counts.get(status, 0) + 1
        failures = sum(int(item.get("failure_count") or 0) for item in rows)
        return {
            "source_count": len(rows),
            "enabled_count": sum(bool(item.get("enabled")) for item in rows),
            "status_counts": counts,
            "failure_count": failures,
            "due_count": len(self.list_due(user_id=user_id, limit=limit)),
            "degraded": bool(counts.get("failed") or counts.get("cooldown")),
        }

    def delete(self, source_id: str, user_id: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM knowledge_source_connectors WHERE source_id = ? AND user_id = ?",
            (source_id, user_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def update_result(self, source_id: str, user_id: str, **values: Any) -> dict[str, Any] | None:
        allowed = {
            "etag",
            "last_modified",
            "content_hash",
            "last_checked_at",
            "last_success_at",
            "last_status",
            "last_error",
            "failure_count",
            "cooldown_until",
            "last_job_id",
            "enabled",
        }
        filtered = {key: value for key, value in values.items() if key in allowed}
        if "enabled" in filtered:
            filtered["enabled"] = int(bool(filtered["enabled"]))
        if "last_error" in filtered and filtered["last_error"] is not None:
            filtered["last_error"] = str(filtered["last_error"])[:1000]
        if not filtered:
            return self.get(source_id, user_id)
        filtered["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in filtered)
        self.conn.execute(
            f"UPDATE knowledge_source_connectors SET {assignments} WHERE source_id = ? AND user_id = ?",
            [*filtered.values(), source_id, user_id],
        )
        self.conn.commit()
        return self.get(source_id, user_id)


@dataclass(frozen=True)
class SourceFetchResult:
    status: str
    data: bytes = b""
    media_type: str = "application/octet-stream"
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    error: str | None = None
    items: tuple[dict[str, Any], ...] = ()

    @property
    def changed(self) -> bool:
        return self.status == "changed"


def fetch_http_source(
    source: KnowledgeSourceConnector | dict[str, Any],
    *,
    opener: Callable[..., Any] = urlopen,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> SourceFetchResult:
    """Fetch one source with validators and bounded response size."""
    item = source if isinstance(source, KnowledgeSourceConnector) else KnowledgeSourceConnector.from_dict(source, user_id=str(source.get("user_id") or "default"))
    headers = {"User-Agent": "CA-Agent-KnowledgeSync/1.0", "Accept": "text/markdown,text/html,application/json,*/*"}
    if item.etag:
        headers["If-None-Match"] = item.etag
    if item.last_modified:
        headers["If-Modified-Since"] = item.last_modified
    request = Request(item.uri, headers=headers, method="GET")
    try:
        with opener(request, timeout=item.timeout_seconds) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                return SourceFetchResult(status="failed", error=f"Source exceeds {max_bytes // (1024 * 1024)} MB limit")
            headers_obj = response.headers
            media_type = str(headers_obj.get_content_type() if hasattr(headers_obj, "get_content_type") else headers_obj.get("Content-Type", "application/octet-stream")).split(";", 1)[0]
            items = parse_source_items(
                data,
                source_uri=item.uri,
                source_type=item.source_type,
                media_type=media_type,
            )
            return SourceFetchResult(
                status="changed",
                data=data,
                media_type=media_type or item.media_type,
                etag=headers_obj.get("ETag"),
                last_modified=headers_obj.get("Last-Modified"),
                content_hash=hashlib.sha256(data).hexdigest(),
                items=tuple(items),
            )
    except HTTPError as exc:
        if exc.code == 304:
            return SourceFetchResult(status="unchanged", etag=item.etag, last_modified=item.last_modified)
        return SourceFetchResult(status="failed", error=f"HTTP {exc.code}")
    except (URLError, TimeoutError, OSError) as exc:
        return SourceFetchResult(status="failed", error=str(exc)[:500])


def sync_source(
    source: dict[str, Any],
    *,
    user_id: str,
    register: Callable[..., dict[str, Any]],
    repository: SourceRepository,
    fetcher: Callable[..., SourceFetchResult] = fetch_http_source,
) -> dict[str, Any]:
    """Fetch and register a source; unchanged content never creates a job."""
    source_id = str(source.get("source_id") or "")
    if not source_id or str(source.get("user_id")) != user_id:
        raise PermissionError("Knowledge source not found")
    if not source.get("enabled"):
        repository.update_result(source_id, user_id, last_status="disabled", last_checked_at=_now())
        return {"source_id": source_id, "status": "disabled", "changed": False}
    cooldown_until = source.get("cooldown_until")
    if cooldown_until:
        try:
            if datetime.fromisoformat(str(cooldown_until).replace("Z", "+00:00")) > datetime.now(UTC):
                return {"source": source, "status": "cooldown", "changed": False, "error": "Source is in retry cooldown"}
        except ValueError:
            pass
    repository.update_result(source_id, user_id, last_status="checking", last_checked_at=_now(), last_error=None)
    result = fetcher(source)
    now = _now()
    if result.status == "unchanged":
        updated = repository.update_result(
            source_id,
            user_id,
            etag=result.etag or source.get("etag"),
            last_modified=result.last_modified or source.get("last_modified"),
            last_checked_at=now,
            last_status="unchanged",
            last_error=None,
        )
        return {"source": updated, "status": "unchanged", "changed": False}
    if not result.changed:
        failures = int(source.get("failure_count") or 0) + 1
        backoff_minutes = min(360, 2 ** min(failures, 8))
        updated = repository.update_result(
            source_id,
            user_id,
            last_checked_at=now,
            last_status="failed",
            last_error=result.error or "Source fetch failed",
            failure_count=failures,
            cooldown_until=(datetime.now(UTC) + timedelta(minutes=backoff_minutes)).isoformat(),
        )
        return {"source": updated, "status": "failed", "changed": False, "error": result.error or "Source fetch failed"}
    if result.content_hash and result.content_hash == source.get("content_hash"):
        updated = repository.update_result(source_id, user_id, last_checked_at=now, last_success_at=now, last_status="unchanged", last_error=None, failure_count=0, cooldown_until=None, etag=result.etag, last_modified=result.last_modified)
        return {"source": updated, "status": "unchanged", "changed": False}
    filename = Path(urlsplit(str(source["uri"])).path).name or "source-document"
    if "." not in filename.rsplit("/", 1)[-1]:
        suffix = {
            "text/markdown": ".md",
            "text/plain": ".txt",
            "application/json": ".json",
            "text/html": ".html",
        }.get((result.media_type or "").casefold(), ".html")
        filename += suffix
    registration = register(
        filename=filename,
        data=result.data,
        title=source.get("name") or "Web source",
        media_type=result.media_type or source.get("media_type") or "application/octet-stream",
        source_type=source.get("source_type") or "web",
        source_uri=source["uri"],
        product=source.get("product") or "",
        dimension=source.get("dimension") or "",
        market_scope=source.get("market_scope") or "Global / unspecified",
        authority_tier=source.get("authority_tier") or "primary",
        published_at=None,
        metadata={
            "connector_kind": source.get("source_type") or "web",
            "discovered_items": list(result.items)[:200],
            "sync_fetched_at": now,
        },
        space_id=source.get("space_id") or None,
    )
    job = registration.get("job") or {}
    updated = repository.update_result(
        source_id,
        user_id,
        etag=result.etag,
        last_modified=result.last_modified,
        content_hash=result.content_hash,
        last_checked_at=now,
        last_success_at=now,
        last_status="queued",
        last_error=None,
        failure_count=0,
        cooldown_until=None,
        last_job_id=job.get("job_id"),
    )
    return {"source": updated, "status": "queued", "changed": True, "registration": registration}
