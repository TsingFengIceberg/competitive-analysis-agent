"""Deterministic evidence-level diffs for immutable report versions."""

from __future__ import annotations

from typing import Any

from competition.intelligence import canonicalize_url, normalize_label


def _points(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    points = snapshot.get("collected_data")
    if isinstance(points, list):
        return [item for item in points if isinstance(item, dict)]
    report = snapshot.get("report_data")
    traceability = report.get("traceability_map") if isinstance(report, dict) else None
    if not isinstance(traceability, dict):
        return []
    return [
        {
            "id": citation_id,
            "product": source.get("product", ""),
            "category": source.get("category", ""),
            "label": source.get("label", ""),
            "value": source.get("snippet", ""),
            "source_url": source.get("url", ""),
            "confidence": source.get("confidence", 0),
        }
        for citation_id, source in traceability.items()
        if isinstance(source, dict)
    ]


def _key(point: dict[str, Any]) -> str:
    return "|".join((
        str(point.get("product") or "").casefold(),
        str(point.get("category") or point.get("dimension") or "").casefold(),
        normalize_label(str(point.get("label") or "")),
        canonicalize_url(str(point.get("source_url") or point.get("url") or "")),
    ))


def _public(point: dict[str, Any] | None) -> dict[str, Any] | None:
    if not point:
        return None
    return {
        "id": point.get("id"),
        "product": point.get("product"),
        "dimension": point.get("category") or point.get("dimension"),
        "label": point.get("label"),
        "value": point.get("value"),
        "source_url": point.get("source_url") or point.get("url"),
        "source_type": point.get("source_type"),
        "confidence": point.get("confidence"),
        "published_at": point.get("published_at"),
        "collected_at": point.get("collected_at") or point.get("fetched_at"),
    }


def build_evidence_diff(
    old_snapshot: dict[str, Any] | None,
    new_snapshot: dict[str, Any] | None,
    *,
    old_version: int | None = None,
    new_version: int | None = None,
) -> dict[str, Any]:
    """Compare facts, values, sources and confidence without model calls."""
    old_map = {_key(point): point for point in _points(old_snapshot)}
    new_map = {_key(point): point for point in _points(new_snapshot)}
    facts: list[dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}
    for key in sorted(set(old_map) | set(new_map)):
        old = old_map.get(key)
        new = new_map.get(key)
        if old is None:
            change_type = "added"
        elif new is None:
            change_type = "removed"
        elif any(old.get(field) != new.get(field) for field in ("value", "confidence", "source_url", "published_at")):
            change_type = "modified"
        else:
            change_type = "unchanged"
        counts[change_type] += 1
        if change_type != "unchanged":
            facts.append({"change_type": change_type, "key": key, "old": _public(old), "new": _public(new)})
    old_report = old_snapshot.get("report_data") if isinstance(old_snapshot, dict) else None
    new_report = new_snapshot.get("report_data") if isinstance(new_snapshot, dict) else None
    old_context = old_report.get("analysis_context") if isinstance(old_report, dict) else None
    new_context = new_report.get("analysis_context") if isinstance(new_report, dict) else None
    return {
        "schema_version": "evidence-diff.v1",
        "from_version": old_version,
        "to_version": new_version,
        "summary": {**counts, "changed": counts["added"] + counts["removed"] + counts["modified"]},
        "facts": facts,
        "context_quality": {"old": (old_context or {}).get("quality", {}), "new": (new_context or {}).get("quality", {})},
    }
