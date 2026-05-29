"""节点对比 — 两个 BranchNode 快照的差异计算。

P2 功能：用于前端展示版本间变化、分支合并前的差异预览。
"""

from __future__ import annotations

from typing import Any


def diff_dicts(
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Compute field-level diff between two flat-ish dicts.

    Returns:
        {"field_name": {"old": val, "new": val, "changed": bool}, ...}
        Only includes fields where old != new.
    """
    result: dict[str, dict[str, Any]] = {}
    all_keys = set(old or {}) | set(new or {})

    for key in all_keys:
        old_val = (old or {}).get(key)
        new_val = (new or {}).get(key)
        if old_val != new_val:
            result[key] = {"old": old_val, "new": new_val, "changed": True}

    return result


def diff_lists(
    old: list[Any] | None,
    new: list[Any] | None,
    key_fn: callable | None = None,
) -> dict[str, list[Any]]:
    """Compute add/remove diff between two lists.

    Args:
        key_fn: Optional function to extract identity key from items.
                If provided, uses it for matching; otherwise uses item equality.

    Returns:
        {"added": [...], "removed": [...]}
    """
    old_list = old or []
    new_list = new or []

    if key_fn is not None:
        old_keys = {key_fn(x): x for x in old_list}
        new_keys = {key_fn(x): x for x in new_list}

        removed = [old_keys[k] for k in set(old_keys) - set(new_keys)]
        added = [new_keys[k] for k in set(new_keys) - set(old_keys)]
    else:
        removed = [x for x in old_list if x not in new_list]
        added = [x for x in new_list if x not in old_list]

    return {"added": added, "removed": removed}


def diff_report_sections(
    old_report: dict[str, Any] | None,
    new_report: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute section-level diff between two ReportData dicts.

    Identifies which report sections (e.g. 'overview', 'swot', 'pricing', 'features')
    were added, removed, or modified.
    """
    sections: dict[str, Any] = {}
    all_sections = set(old_report or {}) | set(new_report or {})

    for section in all_sections:
        old_val = (old_report or {}).get(section)
        new_val = (new_report or {}).get(section)

        if old_val is None and new_val is not None:
            sections[section] = {"status": "added"}
        elif old_val is not None and new_val is None:
            sections[section] = {"status": "removed"}
        elif old_val != new_val:
            sections[section] = {"status": "modified"}
        # else: unchanged — skip

    return sections


def snapshot_diff(
    old_snapshot: dict[str, Any],
    new_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Compute a comprehensive diff between two version snapshots.

    Args:
        old_snapshot: restore() output from the older version.
        new_snapshot: restore() output from the newer version.

    Returns:
        {
            "fields": {...},           # Top-level field changes
            "report_sections": {...},   # Report section changes
            "collected_data_diff": {...},  # Collected data add/remove
            "summary": str,             # Human-readable summary
        }
    """
    # Top-level field changes
    field_changes = diff_dicts(old_snapshot, new_snapshot)

    # Report section changes
    report_changes = diff_report_sections(
        old_snapshot.get("report_data"),
        new_snapshot.get("report_data"),
    )

    # Collected data changes — match by source URL
    collected_diff = diff_lists(
        old_snapshot.get("collected_data"),
        new_snapshot.get("collected_data"),
        key_fn=lambda x: x.get("url", str(x)),
    )

    # Summary
    parts = []
    if field_changes:
        parts.append(f"{len(field_changes)} fields changed")
    if report_changes:
        changed_sections = [
            f"{s}({d['status']})" for s, d in report_changes.items()
        ]
        parts.append(f"report sections: {', '.join(changed_sections)}")
    if collected_diff["added"]:
        parts.append(f"+{len(collected_diff['added'])} data points")
    if collected_diff["removed"]:
        parts.append(f"-{len(collected_diff['removed'])} data points")

    return {
        "fields": field_changes,
        "report_sections": report_changes,
        "collected_data_diff": collected_diff,
        "summary": "; ".join(parts) if parts else "no changes",
    }
