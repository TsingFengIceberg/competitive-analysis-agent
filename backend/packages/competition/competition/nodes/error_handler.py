"""Error handler node — graceful degradation for fatal and logic-fault errors.

Per COMPETITION_PLAN.md §3.15.6: D-class (fatal) → graceful stop,
C-class (logic fault) → auto-replan, partial results preserved.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def error_handler_node(state: dict) -> dict:
    """Graph node: handle errors from any upstream node.

    §3.15.6.3: Reads error field, decides graceful stop vs degraded continue.

    Returns partial state update with either:
    - Degraded continue: cleared error + unresolved_issues (has partial results)
    - Graceful stop: error preserved + minimal ReportData (no results)
    """
    error = str(state.get("error") or "").strip()
    has_results = bool(state.get("collected_data") or state.get("analysis_result"))

    if not error and not has_results:
        error = "未采集到可用于分析的数据"

    if has_results:
        return _degraded_continue(error, state)
    else:
        return _graceful_stop(error, state)


def _degraded_continue(error: str, state: dict) -> dict:
    """C-class: partial results exist → clear error, annotate, continue.

    §3.15.6.2: Logic faults auto-trigger replan; data quality issues degrade.
    """
    logger.warning("Error handler: degraded continue — %s", error[:100])

    issues = state.get("unresolved_issues") or []
    if isinstance(issues, list):
        issues.append({
            "type": "system_error",
            "description": f"系统在运行中遇到错误，以下结论可能不完整: {error[:200]}",
            "severity": "minor",
        })

    return {
        "error": None,  # Clear error → graph continues
        "unresolved_issues": issues,
        "hitl_decision": {
            "action": "approve",
            "comment": f"系统自动降级处理: {error[:100]}",
            "target_focus": None,
            "timestamp": _now_iso(),
        },
    }


def _graceful_stop(error: str, state: dict) -> dict:
    """D-class: no results → graceful stop with error report.

    §3.15.6.3: Save checkpoint, produce minimal ReportData, skip HITL.
    """
    logger.error("Error handler: graceful stop — %s", error[:100])

    report_data = {
        "persona": state.get("persona", "pm"),
        "title": "分析失败",
        "generated_at": _now_iso(),
        "products": state.get("target_products", []),
        "sections": [{
            "id": "sec-error",
            "title": "错误",
            "content": (
                "## 分析失败\n\n"
                "系统在运行过程中遇到致命错误：\n\n"
                f"> {error}\n\n"
                "请检查输入或稍后重试。"
            ),
            "content_type": "text",
            "source_ids": [],
            "chart_path": None,
            "subsections": None,
        }],
        "traceability_map": {},
        "quality_summary": {
            "total_data_points": 0,
            "verified_count": 0,
            "multi_source_count": 0,
            "single_source_count": 0,
            "fact_errors_count": 0,
            "unresolved_gaps": [],
            "overall_quality_score": 0.0,
            "improvement_ratio": None,
        },
        "forecast": None,
        "metrics": {},
    }

    return {
        "error": f"FATAL: {error}",
        "report_data": report_data,
        "hitl_decision": {
            "action": "approve",
            "comment": "致命错误，自动批准",
            "target_focus": None,
            "timestamp": _now_iso(),
        },
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
