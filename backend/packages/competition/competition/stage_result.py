"""Stage execution contracts for the competition LangGraph.

The graph state carries business outputs (collected data, analysis and report)
while this module carries compact, serialisable execution facts for each node.
Detailed prompts, tool payloads and stack traces remain in logs rather than in
checkpoint state.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

STAGE_STATUSES = frozenset({
    "running",
    "completed",
    "partial",
    "failed",
    "timeout",
    "skipped",
    "cancelled",
})
TERMINAL_FAILURE_STATUSES = frozenset({"failed", "timeout", "cancelled"})


def utc_now_iso() -> str:
    """Return a stable UTC timestamp suitable for checkpoint JSON."""
    return datetime.now(UTC).isoformat()


def normalize_status(value: Any, default: str = "completed") -> str:
    candidate = str(value or default).strip().lower()
    return candidate if candidate in STAGE_STATUSES else default


def latest_stage_result(state: dict[str, Any], stage: str) -> dict[str, Any] | None:
    """Return the most recent result for ``stage`` from an accumulated state."""
    results = state.get("stage_results") or []
    for result in reversed(results):
        if isinstance(result, dict) and result.get("stage") == stage:
            return result
    return None


def next_attempt(state: dict[str, Any], stage: str) -> int:
    results = state.get("stage_results") or []
    return 1 + sum(
        1
        for result in results
        if isinstance(result, dict) and result.get("stage") == stage
    )


def build_stage_result(
    *,
    stage: str,
    started_at: str,
    finished_at: str | None = None,
    status: str = "completed",
    run_id: str | None = None,
    attempt: int = 1,
    duration_ms: int | None = None,
    token_usage: dict[str, int] | None = None,
    llm_calls: int = 0,
    tool_calls: int = 0,
    source_count: int = 0,
    metrics: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    degraded_reason: str | None = None,
    output_ref: str | None = None,
) -> dict[str, Any]:
    """Build the compact serialisable stage record stored in graph state."""
    finished = finished_at or utc_now_iso()
    usage = token_usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    total_tokens = max(0, int(usage.get("total_tokens", 0) or 0))
    normalized_usage = {
        "input_tokens": max(0, int(usage.get("input_tokens", 0) or 0)),
        "output_tokens": max(0, int(usage.get("output_tokens", 0) or 0)),
        "total_tokens": total_tokens,
    }
    return {
        "stage": str(stage),
        "run_id": str(run_id) if run_id else None,
        "attempt": max(1, int(attempt or 1)),
        "status": normalize_status(status),
        "started_at": started_at,
        "finished_at": finished,
        "duration_ms": max(0, int(duration_ms or 0)),
        "token_usage": normalized_usage,
        "llm_calls": max(0, int(llm_calls or 0)),
        "tool_calls": max(0, int(tool_calls or 0)),
        "source_count": max(0, int(source_count or 0)),
        "metrics": dict(metrics or {}),
        "error_code": error_code,
        "error_message": error_message,
        "degraded_reason": degraded_reason,
        "output_ref": output_ref,
    }


def summarize_stage_results(results: Iterable[dict[str, Any]] | None) -> dict[str, Any]:
    """Aggregate terminal stage facts without duplicating business outputs."""
    items = [item for item in (results or []) if isinstance(item, dict)]
    total_tokens = 0
    total_duration = 0
    total_llm_calls = 0
    total_tool_calls = 0
    statuses: dict[str, str] = {}
    for item in items:
        stage = str(item.get("stage") or "")
        if stage:
            statuses[stage] = str(item.get("status") or "completed")
        usage = item.get("token_usage") or {}
        total_tokens += max(0, int(usage.get("total_tokens", 0) or 0))
        total_duration += max(0, int(item.get("duration_ms", 0) or 0))
        total_llm_calls += max(0, int(item.get("llm_calls", 0) or 0))
        total_tool_calls += max(0, int(item.get("tool_calls", 0) or 0))
    failed = [stage for stage, status in statuses.items() if status in TERMINAL_FAILURE_STATUSES]
    return {
        "stage_count": len(items),
        "statuses": statuses,
        "failed_stages": failed,
        "total_tokens": total_tokens,
        "total_duration_ms": total_duration,
        "total_llm_calls": total_llm_calls,
        "total_tool_calls": total_tool_calls,
    }
