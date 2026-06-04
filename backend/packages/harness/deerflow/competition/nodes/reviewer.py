"""Reviewer node — 8 cross-validation checks, gap generation, and improvement measurement.

Per COMPETITION_PLAN.md §3.6: G1-G8 gap detection rules with computational verification.
"""

from __future__ import annotations

import json
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
    gaps.extend(check_all_na_competitor(analysis, state.get("target_products", [])))  # G4.5
    gaps.extend(check_source_diversity(collected))         # G5
    gaps.extend(check_statistical_outliers(collected))     # G6

    # G7 (semantic contradiction) + G8 (low confidence) — LLM-assisted
    if _should_call_g7_g8(state):
        g7_gaps, g8_verdicts = _run_g7_g8(analysis, collected, state.get("target_products", []))
        gaps.extend(g7_gaps)
        gaps.extend(_g8_verdicts_to_gaps(g8_verdicts, collected))
        state["_g8_verdicts"] = g8_verdicts  # stored for confidence adjustment pass

    # G9: Extra fields validation (§3.17.3) — domain-specific dimensions must have sources
    gaps.extend(_check_extra_fields_sources(analysis))

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


# ── G4.5: All-NA Competitor (§3.6.1) ──


def check_all_na_competitor(analysis: dict, target_products: list[str]) -> list[dict]:
    """G4.5: Flag any competitor with N/A ratings across ALL dimensions.

    An all-N/A row means the competitor was listed but no data was collected or
    analyzed for it. This is a critical gap — forces a targeted re-collect for
    that specific competitor.
    """
    matrix = analysis.get("comparison_matrix", {})
    cells = matrix.get("cells", [])
    if not cells or not target_products:
        return []

    # Build per-product rating set: {product: {True if has non-null rating}}
    product_has_rating: dict[str, bool] = {p: False for p in target_products}
    for c in cells:
        if not isinstance(c, dict):
            continue
        product = c.get("product", "")
        rating = c.get("rating")
        # Treat null/None/0/"N/A" strings as absent
        is_na = rating is None or rating == 0 or str(rating).strip().upper() == "N/A"
        if not is_na:
            product_has_rating[product] = True

    gaps = []
    for product, has_rating in product_has_rating.items():
        if not has_rating:
            # Check if the product appears at all in cells (vs completely absent)
            in_matrix = any(
                isinstance(c, dict) and c.get("product") == product
                for c in cells
            )
            if in_matrix:
                gaps.append(_make_gap(
                    gid=f"gap-g4_5-{product}",
                    gap_type="missing_data",
                    method="all_na_competitor",
                    desc=f"Competitor '{product}' has N/A ratings across ALL dimensions — no usable comparison data",
                    evidence=f"comparison_matrix cells for {product}: all ratings are null",
                    task=f"Re-search for any data on: {product}. Focus on basic facts: features, pricing, users.",
                    severity="critical",
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


# ── G9: Extra fields source validation (§3.17.3) ──


def _check_extra_fields_sources(analysis: dict) -> list[dict]:
    """G9: Every extra_fields entry must have source_data_point_ids.

    Domain-specific dimensions without citations are flagged as minor gaps.
    This ensures dynamic schema fields maintain the same traceability standard
    as the core comparison matrix.
    """
    extra = analysis.get("extra_fields") or {}
    if not extra:
        return []

    gaps = []
    for field_name, field_data in extra.items():
        if not isinstance(field_data, dict):
            continue
        src_ids = field_data.get("source_data_point_ids", [])
        if not src_ids:
            gaps.append(_make_gap(
                gid=f"gap-g9-{field_name}",
                gap_type="missing_data",
                method="extra_fields_source_check",
                desc=f"行业特有维度 '{field_name}' 缺少数据来源引用",
                evidence=f"extra_fields['{field_name}'] has no source_data_point_ids",
                task=f"Verify or provide source citations for extra field: {field_name}",
                severity="minor",
                related_ids=[],
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


# ── G7: Semantic Contradiction Detection (LLM-assisted) ──


def check_semantic_contradictions(analysis: dict, collected: list[dict], target_products: list[str]) -> list[dict]:
    """G7: Use LLM to detect contradictions between Analyst conclusions and raw data.

    Returns list of gap dicts (same format as G1-G6).
    """
    from deerflow.competition.executor import execute_structured_agent
    from deerflow.competition.prompts import load_prompt

    # Build a compact comparison context — only send what the LLM needs
    matrix = analysis.get("comparison_matrix", {})
    cells = matrix.get("cells", [])

    # Extract SWOT items (with their source data IDs)
    swot = analysis.get("swot", {})
    swot_items: list[dict] = []
    for _prod_name, swot_data in swot.items():
        if isinstance(swot_data, dict):
            for item in swot_data.get("items", []):
                if isinstance(item, dict):
                    swot_items.append({
                        "product": _prod_name,
                        "category": item.get("category", "?"),
                        "statement": item.get("statement", ""),
                        "evidence": item.get("evidence", ""),
                        "source_data_point_ids": item.get("source_data_point_ids", []),
                    })

    # Extract trends
    trends = analysis.get("trends", [])

    # Build a compact data point index (id → {label, value, product, category})
    data_index = {}
    for dp in collected:
        if isinstance(dp, dict):
            data_index[dp.get("id", "")] = {
                "product": dp.get("product", ""),
                "category": dp.get("category", ""),
                "label": dp.get("label", ""),
                "value": str(dp.get("value", ""))[:120],
                "confidence": dp.get("confidence", 0),
                "source_type": dp.get("source_type", ""),
            }

    # Skip G7 if not enough structured data
    if not cells and not swot_items:
        return []

    task = json.dumps({
        "comparison_cells": cells[:50],        # cap to prevent token overflow
        "swot_items": swot_items[:30],
        "trends": trends[:10] if isinstance(trends, list) else [],
        "data_index": {k: v for k, v in list(data_index.items())[:80]},
        "target_products": target_products,
    }, ensure_ascii=False, indent=2)

    prompt = load_prompt("reviewer-g7")
    result, _tokens = execute_structured_agent(
        prompt, task, output_schema_desc="JSON with contradictions array",
        agent_name="Reviewer", temperature=0.0, max_tokens=2048,
    )

    if not isinstance(result, dict):
        logger.warning("G7 returned non-dict result: %s", type(result).__name__)
        return []

    contradictions = result.get("contradictions", [])
    if not isinstance(contradictions, list):
        return []

    # Convert contradictions to gap format
    gaps = []
    for c in contradictions:
        if not isinstance(c, dict):
            continue
        ctype = c.get("type", "source_conflict")
        claim = c.get("analysis_claim", {}) if isinstance(c.get("analysis_claim"), dict) else {}
        counter = c.get("counter_evidence", {}) if isinstance(c.get("counter_evidence"), dict) else {}

        severity = c.get("severity", "major")
        # Upgrade: self-contradictory citations → critical
        cited = set(claim.get("cited_data_point_ids", []))
        counter_ids = set(counter.get("data_point_ids", []))
        if cited & counter_ids:
            severity = "critical"

        gaps.append(_make_gap(
            gid=c.get("contradiction_id", "g7-???"),
            gap_type=ctype,
            method="semantic_contradiction",
            desc=f"[G7] {claim.get('content', '?')} vs {counter.get('description', '?')}",
            evidence=f"Claim cites: {list(cited)[:5]}; Counter evidence: {counter.get('excerpts', [])[:3]}",
            task=c.get("resolution_hint", "Re-analyze with counter-evidence considered"),
            severity=severity,
            related_ids=list(cited | counter_ids),
        ))

    return gaps


# ── G8: Low Confidence Review (LLM-assisted) ──


def review_low_confidence(collected: list[dict]) -> list[dict]:
    """G8: Use LLM to cross-validate low-confidence data points against peers.

    Returns list of verdict dicts: {data_point_id, verdict, reason, cross_referenced_with, new_confidence}.
    """
    from deerflow.competition.executor import execute_structured_agent
    from deerflow.competition.prompts import load_prompt

    # Identify low-confidence data points
    low_conf = [dp for dp in collected if isinstance(dp, dict) and dp.get("confidence", 1.0) < 0.5]
    if not low_conf:
        return []

    # Group all data by (product, category) for peer lookup
    from collections import defaultdict
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for dp in collected:
        if isinstance(dp, dict):
            key = (dp.get("product", ""), dp.get("category", ""))
            groups[key].append(dp)

    # Build review items: each low-confidence point + its peers
    review_items = []
    for dp in low_conf:
        key = (dp.get("product", ""), dp.get("category", ""))
        peers = [p for p in groups.get(key, []) if p.get("id") != dp.get("id")]
        review_items.append({
            "target": {
                "id": dp.get("id"),
                "product": dp.get("product"),
                "category": dp.get("category"),
                "label": dp.get("label"),
                "value": str(dp.get("value", ""))[:120],
                "confidence": dp.get("confidence"),
                "source_type": dp.get("source_type"),
            },
            "peers": [{
                "id": p.get("id"),
                "label": p.get("label"),
                "value": str(p.get("value", ""))[:120],
                "confidence": p.get("confidence"),
                "source_type": p.get("source_type"),
            } for p in peers[:5]],  # cap at 5 peers
        })

    task = json.dumps({"items": review_items}, ensure_ascii=False, indent=2)
    prompt = load_prompt("reviewer-g8")
    result, _tokens = execute_structured_agent(
        prompt, task, output_schema_desc="JSON with verdicts array",
        agent_name="Reviewer", temperature=0.0, max_tokens=1024,
    )

    if not isinstance(result, dict):
        logger.warning("G8 returned non-dict result: %s", type(result).__name__)
        return []

    verdicts = result.get("verdicts", [])
    if not isinstance(verdicts, list):
        return []

    # Validate verdict structure
    valid = []
    for v in verdicts:
        if isinstance(v, dict) and v.get("data_point_id") and v.get("verdict") in ("KEEP", "DISCARD", "DOWNGRADE"):
            valid.append(v)
    return valid


def _g8_verdicts_to_gaps(verdicts: list[dict], collected: list[dict]) -> list[dict]:
    """Convert G8 DISCARD verdicts to gap format for Collector re-targeting."""
    gaps = []
    for v in verdicts:
        if v.get("verdict") != "DISCARD":
            continue
        dp_id = v.get("data_point_id", "")
        # Find the original data point for context
        original = next((dp for dp in collected if isinstance(dp, dict) and dp.get("id") == dp_id), {})
        gaps.append(_make_gap(
            gid=f"gap-g8-{dp_id}",
            gap_type="fact_error",
            method="low_confidence_review",
            desc=f"[G8] Low-confidence data point DISCARDED: {v.get('reason', '')}",
            evidence=f"Cross-referenced with: {v.get('cross_referenced_with', [])}",
            task=f"Re-search for reliable data on: {original.get('label', dp_id)}",
            severity="major",
            related_ids=[dp_id] + v.get("cross_referenced_with", []),
        ))
    return gaps


def _should_call_g7_g8(state: dict) -> bool:
    """Guard: only invoke G7/G8 LLM checks when conditions are met.

    Avoids:
    - Calling on empty/minimal data
    - Re-calling after round 2 (data has been through multiple validations)
    """
    analysis = state.get("analysis_result")
    collected = state.get("collected_data") or []
    if not analysis or len(collected) < 5:
        return False

    # G7/G8 are most valuable on the first review pass; skip on late rounds
    # to save tokens when data has already been validated multiple times
    review_round = state.get("review_round", 0)
    if review_round >= 2:
        return False

    return True


def _run_g7_g8(analysis: dict, collected: list[dict], target_products: list[str]) -> tuple[list[dict], list[dict]]:
    """Run G7 + G8 in sequence, returning (gaps, g8_verdicts).

    G8 runs after G7 so that data points flagged by G7 as contradictory
    get extra scrutiny in G8's cross-validation pass.
    """
    logger.info("Reviewer G7+G8 LLM checks starting (%d data points)", len(collected))
    g7_gaps = check_semantic_contradictions(analysis, collected, target_products)
    g8_verdicts = review_low_confidence(collected)
    logger.info("Reviewer G7: %d contradictions, G8: %d verdicts", len(g7_gaps), len(g8_verdicts))
    return g7_gaps, g8_verdicts
