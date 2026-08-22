"""Build a bounded, quality-aware analysis context from durable evidence.

The context pack is a read model for Analyst and Reviewer.  It deliberately
does not replace ``collected_data``: the latter remains the run-level contract
and the pack adds reusable evidence, filtering and explicit quality semantics.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from competition.intelligence import build_intelligence_item, canonicalize_url, normalize_label

logger = logging.getLogger(__name__)

QUALITY_STATES = ("available", "partial", "stale", "fallback", "missing", "fetch_failed", "conflict")
_DIMENSION_LABELS = {
    "features": "功能与体验",
    "pricing": "定价与商业模式",
    "users": "用户与使用场景",
    "market": "市场与竞争格局",
    "technology": "技术与集成能力",
}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _time_bounds(brief: dict) -> tuple[datetime | None, datetime | None]:
    value = brief.get("time_range")
    if not isinstance(value, dict) or value.get("mode") in (None, "latest", "all_available"):
        return None, None
    return _parse_time(value.get("start")), _parse_time(value.get("end"))


def _effective_dimensions(brief: dict) -> list[dict]:
    dimensions = brief.get("effective_dimensions") or brief.get("dimensions") or []
    result: list[dict] = []
    for item in dimensions:
        if isinstance(item, str):
            result.append({"id": item, "label": _DIMENSION_LABELS.get(item, item)})
        elif isinstance(item, dict) and item.get("id"):
            result.append({
                "id": str(item["id"]),
                "label": str(item.get("label") or _DIMENSION_LABELS.get(str(item["id"]), item["id"])),
            })
    return result


def _item_time(item: dict) -> datetime | None:
    return _parse_time(item.get("published_at")) or _parse_time(item.get("fetched_at")) or _parse_time(item.get("collected_at"))


def _matches_scope(item: dict, products: set[str], scope: str, start: datetime | None, end: datetime | None) -> bool:
    if products and str(item.get("product", "")).casefold() not in products:
        return False
    item_scope = str(item.get("scope") or "Global / unspecified")
    if scope and item_scope.casefold() not in {scope.casefold(), "global / unspecified"}:
        return False
    if start or end:
        observed = _item_time(item)
        if observed is None:
            return False
        if start and observed < start:
            return False
        if end and observed > end + timedelta(days=1):
            return False
    return True


def _transient_item(point: dict, scope: str) -> dict:
    item = build_intelligence_item(point, scope=scope, now=str(point.get("collected_at") or ""))
    data = item.to_dict()
    data["id"] = str(point.get("id") or item.item_key)
    data["source_data_point_id"] = data["id"]
    data["collected_at"] = point.get("collected_at")
    return data


def _quality_for_dimension(items: list[dict], *, stale_after: timedelta, now: datetime, policy: str) -> dict:
    domains = {str(item.get("source_domain") or "") for item in items if item.get("source_domain")}
    official = [item for item in items if item.get("credibility_tier") == "official" or item.get("source_type") in {"official", "docs", "pricing"}]
    latest = max((_item_time(item) for item in items if _item_time(item)), default=None)
    stale_count = sum(1 for item in items if (observed := _item_time(item)) and now - observed > stale_after)
    conflicts: list[dict] = []
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in items:
        grouped[(str(item.get("product", "")).casefold(), normalize_label(str(item.get("label", ""))))].append(item)
    for key, group in grouped.items():
        values = {str(item.get("value", "")).strip() for item in group}
        if len(values) > 1 and len({item.get("source_domain") for item in group}) > 1:
            conflicts.append({"product": key[0], "label": key[1], "values": sorted(values), "item_ids": [item.get("id") or item.get("item_key") for item in group]})
    if not items:
        quality = "missing"
    elif conflicts:
        quality = "conflict"
    elif stale_count == len(items):
        quality = "stale"
    elif policy == "strict_multi_source" and len(domains) < 2:
        quality = "partial"
    elif policy == "official_preferred" and not official:
        quality = "fallback"
    elif stale_count:
        quality = "partial"
    else:
        quality = "available"
    fallback_reason = ""
    if quality == "fallback":
        fallback_reason = "没有官方来源，使用了备用来源"
    elif quality == "partial" and policy == "strict_multi_source":
        fallback_reason = "严格多来源策略下独立来源域名不足"
    elif quality == "stale":
        fallback_reason = "证据均超过新鲜度阈值"
    return {
        "quality_state": quality,
        "evidence_count": len(items),
        "source_domain_count": len(domains),
        "official_source_count": len(official),
        "latest_evidence_at": latest.isoformat() if latest else None,
        "stale_evidence_count": stale_count,
        "conflicts": conflicts,
        "fallback_reason": fallback_reason,
    }


def build_analysis_context_pack(state: dict, repository=None, *, now: datetime | None = None, stale_after_days: int = 180) -> dict:
    """Build the Analyst/Reviewer context pack without making LLM or network calls."""
    now = now or datetime.now(UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    brief = state.get("analysis_brief") or {}
    products = {str(product).casefold() for product in (brief.get("target_products") or state.get("target_products") or []) if product}
    scope = str(brief.get("market_scope") or "Global / unspecified")
    dimensions = _effective_dimensions(brief)
    if not dimensions:
        dimensions = [{"id": item, "label": _DIMENSION_LABELS[item]} for item in ("features", "pricing", "users", "market")]
    dimension_ids = {item["id"] for item in dimensions}
    start, end = _time_bounds(brief)
    policy = str(brief.get("evidence_policy") or "balanced")
    durable: list[dict] = []
    fetch_error = ""
    owned = False
    try:
        if repository is None:
            from competition.intelligence_repo import IntelligenceRepository
            repository = IntelligenceRepository()
            owned = True
        durable = repository.list_items(limit=500)
    except Exception as exc:
        fetch_error = str(exc)[:240]
        logger.warning("Analysis context durable fetch degraded: %s", exc)
    finally:
        if owned and repository is not None:
            repository.close()

    candidates = [item for item in durable if _matches_scope(item, products, scope, start, end)]
    transient = [_transient_item(point, scope) for point in (state.get("collected_data") or []) if isinstance(point, dict)]
    transient = [item for item in transient if _matches_scope(item, products, scope, start, end)]

    def context_identity(item: dict) -> str:
        return "|".join((
            str(item.get("product", "")).casefold(),
            str(item.get("dimension", "")).casefold(),
            normalize_label(str(item.get("label", ""))),
            str(item.get("canonical_url") or canonicalize_url(str(item.get("source_url") or ""))),
        ))

    by_identity: dict[str, dict] = {context_identity(item): item for item in candidates}
    for item in transient:
        key = context_identity(item)
        by_identity[key] = item  # current run is authoritative for this context
    selected = [item for item in by_identity.values() if str(item.get("dimension", "")) in dimension_ids]
    def evidence_sort_key(item: dict) -> tuple[int, datetime, str]:
        is_official = item.get("credibility_tier") == "official" or item.get("source_type") in {"official", "docs", "pricing"}
        return (int(is_official) if policy == "official_preferred" else 0, _item_time(item) or datetime.min.replace(tzinfo=UTC), str(item.get("id") or item.get("item_key")))

    selected.sort(key=evidence_sort_key, reverse=True)

    by_dimension: dict[str, dict] = {}
    for dimension in dimensions:
        dim_items = [item for item in selected if str(item.get("dimension")) == dimension["id"]]
        quality = _quality_for_dimension(dim_items, stale_after=timedelta(days=stale_after_days), now=now, policy=policy)
        by_dimension[dimension["id"]] = {"id": dimension["id"], "label": dimension["label"], **quality, "items": dim_items}

    missing_dimensions = [dimension["id"] for dimension in dimensions if not by_dimension[dimension["id"]]["items"]]
    stale_count = sum(entry["stale_evidence_count"] for entry in by_dimension.values())
    conflicts = [conflict for entry in by_dimension.values() for conflict in entry["conflicts"]]
    quality_states = {entry["quality_state"] for entry in by_dimension.values()}
    if fetch_error and not selected:
        overall = "fetch_failed"
    elif fetch_error:
        overall = "fallback"
    elif not selected:
        overall = "missing"
    elif conflicts:
        overall = "conflict"
    elif all(state == "stale" for state in quality_states):
        overall = "stale"
    elif missing_dimensions or "partial" in quality_states or "fallback" in quality_states:
        overall = "partial"
    else:
        overall = "available"
    return {
        "schema_version": "analysis-context-pack.v1",
        "generated_at": now.isoformat(),
        "scope": {
            "products": sorted(products),
            "market_scope": scope,
            "time_range": brief.get("time_range") or {"mode": "all_available", "label": "全部可用证据"},
            "dimensions": dimensions,
            "evidence_policy": policy,
        },
        "quality": {
            "quality_state": overall,
            "evidence_count": len(selected),
            "source_domain_count": len({item.get("source_domain") for item in selected if item.get("source_domain")}),
            "official_source_count": sum(1 for item in selected if item.get("credibility_tier") == "official" or item.get("source_type") in {"official", "docs", "pricing"}),
            "latest_evidence_at": max((_item_time(item) for item in selected if _item_time(item)), default=None).isoformat() if selected and any(_item_time(item) for item in selected) else None,
            "stale_evidence_count": stale_count,
            "conflicts": conflicts,
            "missing_dimensions": missing_dimensions,
            "fallback_reason": fetch_error or ("当前运行使用了未持久化的采集结果" if not durable and transient else ""),
            "fetch_error": fetch_error,
        },
        "dimensions": by_dimension,
        "evidence": selected,
    }


def context_pack_prompt_excerpt(pack: dict, *, max_items: int = 80) -> str:
    """Return a compact JSON excerpt suitable for an LLM task prompt."""
    evidence = (pack.get("evidence") or [])[:max_items]
    return json.dumps({
        "scope": pack.get("scope", {}),
        "quality": pack.get("quality", {}),
        "evidence": evidence,
    }, ensure_ascii=False, indent=2, default=str)
