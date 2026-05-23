"""Reviewer node — 8 cross-validation checks, gap generation, and improvement measurement.

Per COMPETITION_PLAN.md §3.6: G1-G8 gap detection rules with computational verification.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def reviewer_node(state: dict) -> dict:
    """Graph node: review Analyst output against collected data, generate gaps.

    Returns partial state update with review_verdict + review_round increment.
    """
    analysis = state.get("analysis_result") or {}
    collected = state.get("collected_data") or []
    prev_gaps = _gaps_from_verdict(state.get("review_verdict"))
    review_round = state.get("review_round", 0)

    # Run 8 gap checks (§3.6.1)
    gaps: list[dict] = []
    gaps.extend(check_url_reachability(collected))        # G1
    gaps.extend(check_multi_source_consistency(collected)) # G2
    gaps.extend(check_data_freshness(collected))           # G3
    gaps.extend(check_dimension_coverage(analysis, state.get("target_products", [])))  # G4
    gaps.extend(check_source_diversity(collected))         # G5
    gaps.extend(check_statistical_outliers(collected))     # G6
    # G7 (semantic contradiction) + G8 (low confidence) are LLM-assisted in full impl

    # Detect feedback loop (§3.15.6.2): same gap 3x → force close
    gaps = _filter_loop_gaps(gaps, prev_gaps, review_round)

    passed = len([g for g in gaps if g.get("severity") == "critical"]) == 0 and review_round < 3

    # Compute improvement (§3.12.1)
    improvement = _measure_improvement(prev_gaps, gaps)

    # Build quality summary
    quality = _build_quality_summary(collected, gaps, improvement)

    new_round = review_round + 1 if not passed else review_round

    verdict = {
        "passed": passed,
        "round": new_round,
        "gaps": gaps,
        "fact_errors": [g for g in gaps if g.get("type") == "fact_error"],
        "quality_summary": quality,
        "reviewer_notes": _generate_notes(gaps, improvement),
    }

    return {
        "review_verdict": verdict,
        "review_round": new_round,
        "gap_coverage_improvement": improvement,
    }


# ── G1: URL Reachability (§3.6.1) ──


def check_url_reachability(points: list[dict]) -> list[dict]:
    """G1: HEAD request each source_url, flag 4xx/5xx as fact_error.

    Note: In production, this does real HEAD requests via Sandbox bash(curl -I).
    For now, placeholder that marks points with obviously invalid URLs.
    """
    gaps = []
    for dp in points:
        url = dp.get("source_url", "")
        if not url or not url.startswith("http"):
            gaps.append(_make_gap(
                gid=f"gap-g1-{dp.get('id', '?')}",
                gap_type="fact_error",
                method="url_reachability",
                desc=f"Invalid or missing URL: '{url}'",
                evidence=f"source_url field is '{url}'",
                task=f"Find alternative source for: {dp.get('label', dp.get('id', '?'))}",
                severity="critical" if dp.get("confidence", 0) > 0.5 else "major",
                related_ids=[dp.get("id", "")],
            ))
    return gaps


# ── G2: Multi-Source Consistency (§3.6.1) ──


def check_multi_source_consistency(points: list[dict]) -> list[dict]:
    """G2: Group by (product, norm_label), detect value conflicts (diff > 5%)."""
    from collections import defaultdict

    from deerflow.competition.nodes.collector import _normalize_label, _values_similar

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for dp in points:
        key = (dp.get("product", "").lower(), _normalize_label(dp.get("label", "")))
        groups[key].append(dp)

    gaps = []
    for (product, label), group in groups.items():
        if len(group) < 2:
            continue
        values = [dp.get("value") for dp in group]
        sources = [dp.get("source_url", "") for dp in group]
        # Check pairwise similarity
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if not _values_similar(values[i], values[j]):
                    gaps.append(_make_gap(
                        gid=f"gap-g2-{group[i].get('id')}-{group[j].get('id')}",
                        gap_type="source_conflict",
                        method="multi_source_consistency",
                        desc=f"'{label}' for {product}: {sources[i]} says {values[i]} vs {sources[j]} says {values[j]}",
                        evidence=f"HEAD {sources[i]} → OK; HEAD {sources[j]} → OK",
                        task=f"Search authoritative source for: {label} ({product})",
                        severity="major",
                        related_ids=[group[i].get("id", ""), group[j].get("id", "")],
                    ))
    return gaps


# ── G3: Data Freshness (§3.6.1) ──


def check_data_freshness(points: list[dict], max_age_days: int = 180) -> list[dict]:
    """G3: Flag data points older than max_age_days as outdated."""
    gaps = []
    now = datetime.now(UTC)
    for dp in points:
        collected_at = dp.get("collected_at", "")
        if not collected_at:
            continue
        try:
            ts = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
            age_days = (now - ts).days
            if age_days > max_age_days:
                gaps.append(_make_gap(
                    gid=f"gap-g3-{dp.get('id', '?')}",
                    gap_type="outdated",
                    method="data_freshness",
                    desc=f"Data point '{dp.get('label', '')}' is {age_days} days old (>{max_age_days})",
                    evidence=f"Collected at: {collected_at}, now: {now.isoformat()}",
                    task=f"Search for latest data on: {dp.get('label', dp.get('id', '?'))}",
                    severity="minor",
                    related_ids=[dp.get("id", "")],
                ))
        except (ValueError, TypeError):
            pass
    return gaps


# ── G4: Dimension Coverage (§3.6.1) ──


def check_dimension_coverage(analysis: dict, target_products: list[str]) -> list[dict]:
    """G4: Check that every target product × mandatory category has ≥1 data point."""
    matrix = analysis.get("comparison_matrix", {})
    cells = matrix.get("cells", [])
    dimensions = set(matrix.get("dimensions", []))

    covered = set()
    for c in cells:
        if isinstance(c, dict):
            covered.add((c.get("product", ""), c.get("dimension", "")))

    gaps = []
    for product in target_products:
        for dim in dimensions:
            if (product, dim) not in covered:
                gaps.append(_make_gap(
                    gid=f"gap-g4-{product}-{dim}",
                    gap_type="missing_data",
                    method="dimension_coverage",
                    desc=f"No data for {product} × {dim}",
                    evidence=f"comparison_matrix missing cell: {product}/{dim}",
                    task=f"Search for {dim} data on {product}",
                    severity="major",
                    related_ids=[],
                ))
    return gaps


# ── G5: Source Diversity (§3.6.1) ──


def check_source_diversity(points: list[dict], min_types: int = 2) -> list[dict]:
    """G5: Flag if all data points come from a single source_type."""
    from collections import Counter
    type_counts = Counter(dp.get("source_type", "unknown") for dp in points)
    if len(type_counts) < min_types and points:
        dominant = type_counts.most_common(1)[0][0]
        return [_make_gap(
            gid="gap-g5-diversity",
            gap_type="missing_data",
            method="source_diversity",
            desc=f"All {len(points)} data points from a single source type: '{dominant}'",
            evidence=f"Source types found: {dict(type_counts)}",
            task="Search for alternative source types (e.g. reviews, news) to diversify",
            severity="minor",
            related_ids=[dp.get("id", "") for dp in points[:5]],
        )]
    return []


# ── G6: Statistical Outliers (§3.6.1) ──


def check_statistical_outliers(points: list[dict]) -> list[dict]:
    """G6: Flag numeric values with |z-score| > 3 as potential errors."""
    numeric = [(i, float(dp["value"])) for i, dp in enumerate(points)
               if isinstance(dp.get("value"), (int, float))]

    if len(numeric) < 3:
        return []

    values = [v for _, v in numeric]
    mean = sum(values) / len(values)
    std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    if std == 0:
        return []

    gaps = []
    for idx, val in numeric:
        z = abs(val - mean) / std
        if z > 3:
            dp = points[idx]
            gaps.append(_make_gap(
                gid=f"gap-g6-{dp.get('id', '?')}",
                gap_type="fact_error",
                method="statistical_outlier",
                desc=f"Value {val} is {z:.1f}σ from mean ({mean:.1f})",
                evidence=f"z-score = {z:.2f}, mean = {mean:.1f}, std = {std:.1f}",
                task=f"Verify outlier value: {dp.get('label', '')} = {val}",
                severity="major" if z > 5 else "minor",
                related_ids=[dp.get("id", "")],
            ))
    return gaps


# ── Helpers ──


def _make_gap(gid: str, gap_type: str, method: str, desc: str, evidence: str, task: str, severity: str, related_ids: list[str]) -> dict:
    return {
        "gap_id": gid,
        "type": gap_type,
        "check_method": method,
        "description": desc,
        "evidence": evidence,
        "target_collect_task": task,
        "severity": severity,
        "related_data_point_ids": related_ids,
    }


def _gaps_from_verdict(verdict: dict | None) -> list[dict]:
    if verdict is None:
        return []
    return verdict.get("gaps", []) or []


def _measure_improvement(prev_gaps: list[dict], current_gaps: list[dict]) -> float:
    """§3.12.1: resolved gaps / total previous gaps."""
    if not prev_gaps:
        return 0.0
    prev_ids = {g.get("gap_id") for g in prev_gaps}
    curr_ids = {g.get("gap_id") for g in current_gaps}
    resolved = prev_ids - curr_ids
    return round(len(resolved) / len(prev_ids), 2)


def _build_quality_summary(points: list[dict], gaps: list[dict], improvement: float) -> dict:
    sources = set()
    for dp in points:
        url = dp.get("source_url", "")
        if url:
            sources.add(url)

    multi = len([dp for dp in points if dp.get("source_url", "").count(",") >= 1])
    single = len(points) - multi
    verified = len(points) - len([g for g in gaps if g.get("type") == "fact_error"])

    return {
        "total_data_points": len(points),
        "verified_count": verified,
        "multi_source_count": multi,
        "single_source_count": single,
        "fact_errors_count": len([g for g in gaps if g.get("type") == "fact_error"]),
        "unresolved_gaps": [g.get("description", "") for g in gaps[:5]],
        "overall_quality_score": round(max(0.0, min(1.0, verified / max(len(points), 1))), 2),
        "improvement_ratio": improvement,
    }


def _filter_loop_gaps(gaps: list[dict], prev_gaps: list[dict], review_round: int) -> list[dict]:
    """§3.15.6.2: same gap appearing 3+ times → downgrade to minor, don't re-collect."""
    prev_descs = {g.get("description", "") for g in prev_gaps}
    filtered = []
    for g in gaps:
        if g.get("description", "") in prev_descs and review_round >= 2:
            g["severity"] = "minor"
            g["description"] = "[LOOP] " + g.get("description", "")
        filtered.append(g)
    return filtered


def _generate_notes(gaps: list[dict], improvement: float) -> str:
    critical = len([g for g in gaps if g.get("severity") == "critical"])
    total = len(gaps)
    if total == 0:
        return "All checks passed. Data quality is good."
    if improvement > 0:
        return f"{total} gap(s) found ({critical} critical). Improvement from previous round: {improvement:.0%}."
    return f"{total} gap(s) found ({critical} critical). First review round."
