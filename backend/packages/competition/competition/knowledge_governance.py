"""Knowledge-space identities, role checks, and retention helpers."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

SPACE_ROLES = ("owner", "editor", "viewer")
WRITE_ROLES = frozenset({"owner", "editor"})
REVIEW_ROLES = frozenset({"owner"})

AUTO_APPROVAL_SCORE = 0.72
MINIMUM_CONTENT_CONFIDENCE = 0.45


def personal_space_id(user_id: str) -> str:
    digest = hashlib.sha256(f"ci-agent-personal-space:{user_id}".encode()).hexdigest()[:20]
    return f"kspace-{digest}"


def retention_deadline(retention_days: int, *, now: datetime | None = None) -> str | None:
    if retention_days <= 0:
        return None
    current = now or datetime.now(UTC)
    return (current + timedelta(days=retention_days)).isoformat()


def can_read(role: str | None) -> bool:
    return role in SPACE_ROLES


def can_write(role: str | None) -> bool:
    return role in WRITE_ROLES


def can_review(role: str | None) -> bool:
    return role in REVIEW_ROLES


def assess_intelligence_item(item: dict[str, Any], *, source_credibility: float = 0.5) -> dict[str, Any]:
    """Apply a deterministic admission policy to one observed fact."""
    confidence = max(0.0, min(1.0, float(item.get("confidence") or 0.0)))
    credibility = max(0.0, min(1.0, float(source_credibility)))
    official = str(item.get("credibility_tier") or "") == "official"
    score = min(1.0, confidence * 0.6 + credibility * 0.4 + (0.05 if official else 0.0))
    reasons: list[str] = []
    for field in ("product", "dimension", "label", "value", "source_url"):
        if not str(item.get(field) or "").strip():
            reasons.append(f"missing_{field}")
    if confidence < MINIMUM_CONTENT_CONFIDENCE:
        reasons.append("low_confidence")
    if credibility < 0.4:
        reasons.append("low_source_credibility")
    approval_status = "approved" if not reasons and score >= AUTO_APPROVAL_SCORE else "pending"
    if approval_status == "pending" and not reasons:
        reasons.append("quality_score_below_auto_approval")
    return {
        "policy_version": 1,
        "source_kind": "observation",
        "quality_score": round(score, 4),
        "content_confidence": round(confidence, 4),
        "source_credibility": round(credibility, 4),
        "approval_status": approval_status,
        "quarantined": approval_status == "pending",
        "reasons": reasons,
    }


def assess_report(report_data: dict[str, Any]) -> dict[str, Any]:
    """Gate generated reports before they can become retrieval evidence."""
    gate = report_data.get("quality_gate") or {}
    quality = report_data.get("quality_summary") or {}
    claims = report_data.get("claim_verification") or {}
    gate_status = str(gate.get("status") or "unknown")
    overall_quality = max(0.0, min(1.0, float(quality.get("overall_quality_score") or 0.0)))
    groundedness = max(0.0, min(1.0, float(claims.get("groundedness") or 0.0)))
    citation_precision = max(0.0, min(1.0, float(claims.get("citation_precision") or 0.0)))
    score = overall_quality * 0.45 + groundedness * 0.35 + citation_precision * 0.2
    reasons: list[str] = []
    if gate_status != "pass":
        reasons.append("quality_gate_not_passed")
    if int(gate.get("blocking_count") or 0) > 0:
        reasons.append("blocking_quality_issues")
    if overall_quality < 0.7:
        reasons.append("overall_quality_below_threshold")
    if groundedness < 0.6:
        reasons.append("groundedness_below_threshold")
    approval_status = "approved" if not reasons and score >= AUTO_APPROVAL_SCORE else "pending"
    if approval_status == "pending" and not reasons:
        reasons.append("quality_score_below_auto_approval")
    return {
        "policy_version": 1,
        "source_kind": "analysis_report",
        "quality_score": round(score, 4),
        "overall_quality": round(overall_quality, 4),
        "groundedness": round(groundedness, 4),
        "citation_precision": round(citation_precision, 4),
        "quality_gate_status": gate_status,
        "approval_status": approval_status,
        "quarantined": approval_status == "pending",
        "reasons": reasons,
    }
