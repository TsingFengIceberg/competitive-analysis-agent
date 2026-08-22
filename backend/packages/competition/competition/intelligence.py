"""Durable competitive-intelligence contracts and normalization helpers.

P0-A keeps long-lived evidence separate from one graph run's ``collected_data``.
The functions in this module are deterministic and do not perform I/O, which
makes URL canonicalization, deduplication and content versioning testable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_QUERY_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref")


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonicalize_url(url: str) -> str:
    """Normalize a URL while retaining meaningful query parameters."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    scheme = parsed.scheme.lower() or "https"
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    port = parsed.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        host = f"{host}:{port}"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not any(key.lower().startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES)
    ]
    return urlunsplit((scheme, host, parsed.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def source_domain(url: str) -> str:
    canonical = canonicalize_url(url)
    try:
        return urlsplit(canonical).hostname or ""
    except ValueError:
        return ""


def normalize_label(label: str) -> str:
    return " ".join(str(label or "").lower().strip().split())


def _json_hash(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IntelligenceItem:
    """A versioned, reusable competitive fact derived from a source."""

    item_key: str
    product: str
    dimension: str
    label: str
    value: str | float
    source_url: str
    canonical_url: str
    source_type: str
    source_domain: str
    scope: str
    published_at: str | None
    fetched_at: str
    first_seen_at: str
    last_seen_at: str
    content_hash: str
    confidence: float
    credibility_tier: str
    status: str
    payload: dict

    def to_dict(self) -> dict:
        return asdict(self)


def build_intelligence_item(point: dict, *, scope: str = "Global / unspecified", now: str | None = None) -> IntelligenceItem:
    """Convert a CollectedDataPoint-like mapping into a stable intelligence item."""
    fetched_at = now or utc_now_iso()
    product = str(point.get("product") or "").strip()
    dimension = str(point.get("category") or "").strip()
    label = str(point.get("label") or "").strip()
    value = point.get("value", "")
    source_url = str(point.get("source_url") or "").strip()
    canonical_url = canonicalize_url(source_url)
    source_type = str(point.get("source_type") or "unknown").strip().lower()
    normalized_scope = str(scope or "Global / unspecified").strip()
    identity = "|".join((product.lower(), dimension.lower(), normalize_label(label), canonical_url, source_type, normalized_scope.lower()))
    item_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    payload = {
        "product": product,
        "dimension": dimension,
        "label": label,
        "value": value,
        "source_url": source_url,
        "canonical_url": canonical_url,
        "source_type": source_type,
        "published_at": point.get("published_at"),
        "scope": normalized_scope,
    }
    content_hash = _json_hash(payload)
    confidence = max(0.0, min(1.0, float(point.get("confidence", 0.5) or 0.5)))
    credibility_tier = "official" if source_type in {"official", "docs", "pricing"} else "secondary"
    return IntelligenceItem(
        item_key=item_key,
        product=product,
        dimension=dimension,
        label=label,
        value=value,
        source_url=source_url,
        canonical_url=canonical_url,
        source_type=source_type,
        source_domain=source_domain(source_url),
        scope=normalized_scope,
        published_at=point.get("published_at"),
        fetched_at=fetched_at,
        first_seen_at=fetched_at,
        last_seen_at=fetched_at,
        content_hash=content_hash,
        confidence=confidence,
        credibility_tier=credibility_tier,
        status="available",
        payload=payload,
    )
