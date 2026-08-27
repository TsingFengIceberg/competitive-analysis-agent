"""Build auditable knowledge-version timelines and deterministic source conflicts."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from competition.knowledge_types import AUTHORITY_PRIORS

_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b")
_NUMBER_RE = re.compile(
    r"(?<![\w])[-+]?\d+(?:[.,]\d+)?[ \t]*(?:%|％|美元|万元|元|万|亿|[kmb](?![a-z]))?",
    re.I,
)


def _numbers(text: str) -> tuple[str, ...]:
    comparable = _ISO_DATE_RE.sub(" ", text or "")
    return tuple(
        dict.fromkeys(
            match.casefold().replace(" ", "").replace("％", "%")
            for match in _NUMBER_RE.findall(comparable)
        )
    )


def _resolution(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_authority = AUTHORITY_PRIORS.get(str(left.get("authority_tier")), 0.5)
    right_authority = AUTHORITY_PRIORS.get(str(right.get("authority_tier")), 0.5)
    if left_authority != right_authority:
        preferred = left if left_authority > right_authority else right
        return {
            "status": "resolved",
            "strategy": "higher_authority",
            "preferred_document_id": preferred.get("document_id"),
        }
    left_time = str(left.get("published_at") or left.get("observed_at") or left.get("valid_from") or "")
    right_time = str(right.get("published_at") or right.get("observed_at") or right.get("valid_from") or "")
    if left_time != right_time:
        preferred = left if left_time > right_time else right
        return {
            "status": "resolved",
            "strategy": "newer_evidence",
            "preferred_document_id": preferred.get("document_id"),
        }
    return {"status": "unresolved", "strategy": "manual_review", "preferred_document_id": None}


def build_knowledge_timeline(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Add change semantics and flag conflicting current numeric claims."""
    ordered = sorted(events, key=lambda item: (str(item.get("valid_from") or ""), int(item.get("version_no") or 0)))
    previous_by_document: dict[str, dict[str, Any]] = {}
    timeline: list[dict[str, Any]] = []
    for event in ordered:
        item = dict(event)
        comparison_text = str(item.pop("comparison_text", "") or item.get("excerpt") or "")
        previous = previous_by_document.get(str(item.get("document_id")))
        item["change_type"] = "version_added" if previous is None else "version_changed"
        item["previous_version_no"] = previous.get("version_no") if previous else None
        item["previous_content_hash"] = previous.get("content_hash") if previous else None
        item["changed"] = previous is None or previous.get("content_hash") != item.get("content_hash")
        item["numeric_values"] = list(_numbers(comparison_text))
        previous_by_document[str(item.get("document_id"))] = item
        timeline.append(item)

    current_by_scope: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in timeline:
        if event.get("is_current"):
            current_by_scope[(str(event.get("product") or "").casefold(), str(event.get("dimension") or "").casefold())].append(event)

    conflicts: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for (product, dimension), group in current_by_scope.items():
        for left_index, left in enumerate(group):
            left_numbers = set(left.get("numeric_values") or [])
            if not left_numbers:
                continue
            for right in group[left_index + 1 :]:
                pair = tuple(sorted((str(left.get("document_id")), str(right.get("document_id")))))
                if pair in seen_pairs:
                    continue
                right_numbers = set(right.get("numeric_values") or [])
                if not right_numbers or left_numbers == right_numbers:
                    continue
                seen_pairs.add(pair)
                conflicts.append(
                    {
                        "conflict_id": f"conflict-{pair[0]}-{pair[1]}",
                        "type": "numeric_source_conflict",
                        "product": left.get("product") or right.get("product") or product,
                        "dimension": left.get("dimension") or right.get("dimension") or dimension,
                        "left": {
                            "document_id": left.get("document_id"),
                            "version_no": left.get("version_no"),
                            "source_uri": left.get("source_uri"),
                            "values": sorted(left_numbers),
                            "excerpt": left.get("excerpt"),
                        },
                        "right": {
                            "document_id": right.get("document_id"),
                            "version_no": right.get("version_no"),
                            "source_uri": right.get("source_uri"),
                            "values": sorted(right_numbers),
                            "excerpt": right.get("excerpt"),
                        },
                        "resolution": _resolution(left, right),
                    }
                )

    timeline.sort(key=lambda item: str(item.get("valid_from") or ""), reverse=True)
    return {
        "events": timeline,
        "conflicts": conflicts,
        "summary": {
            "event_count": len(timeline),
            "document_count": len({item.get("document_id") for item in timeline}),
            "current_count": sum(bool(item.get("is_current")) for item in timeline),
            "historical_count": sum(not bool(item.get("is_current")) for item in timeline),
            "conflict_count": len(conflicts),
            "unresolved_conflict_count": sum(
                item["resolution"]["status"] == "unresolved" for item in conflicts
            ),
        },
    }
