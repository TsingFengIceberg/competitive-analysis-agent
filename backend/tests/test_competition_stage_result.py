"""Tests for compact per-node execution records."""

from __future__ import annotations

from competition.graph import _instrument_node
from competition.stage_result import (
    TERMINAL_FAILURE_STATUSES,
    build_stage_result,
    latest_stage_result,
    summarize_stage_results,
)


def test_build_stage_result_is_serializable_and_normalized():
    result = build_stage_result(
        stage="collector",
        started_at="2026-08-21T00:00:00+00:00",
        status="unknown",
        token_usage={"total_tokens": 12},
        metrics={"source_count": 3},
    )
    assert result["status"] == "completed"
    assert result["token_usage"] == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 12}
    assert result["metrics"]["source_count"] == 3


def test_instrumented_node_records_business_output_and_runtime_facts():
    def node(state):
        return {"analysis_result": {"ok": True}}

    result = _instrument_node("analyst", node)({"thread_id": "run-1", "stage_results": []})
    assert result["analysis_result"] == {"ok": True}
    assert result["stage_results"][0]["stage"] == "analyst"
    assert result["stage_results"][0]["status"] == "completed"
    assert result["stage_results"][0]["output_ref"] == "state.analysis_result"
    assert result["current_stage"] == "analyst"
    assert result["run_status"] == "running"


def test_instrumented_node_converts_exception_to_routable_failure():
    def node(_state):
        raise RuntimeError("provider timeout")

    result = _instrument_node("collector", node)({"thread_id": "run-2", "stage_results": []})
    stage = result["stage_results"][0]
    assert result["error"].startswith("collector failed:")
    assert stage["status"] == "failed"
    assert stage["error_code"] == "node_exception"
    assert stage["degraded_reason"] == stage["error_message"]
    assert stage["status"] in TERMINAL_FAILURE_STATUSES


def test_stage_summary_uses_latest_status_and_aggregates_cost():
    first = build_stage_result(stage="collector", started_at="a", token_usage={"total_tokens": 10}, duration_ms=20)
    retry = build_stage_result(stage="collector", started_at="b", status="completed", token_usage={"total_tokens": 5}, duration_ms=30, attempt=2)
    analyst = build_stage_result(stage="analyst", started_at="c", token_usage={"total_tokens": 7}, duration_ms=40)
    state = {"stage_results": [first, retry, analyst]}
    assert latest_stage_result(state, "collector")["attempt"] == 2
    summary = summarize_stage_results(state["stage_results"])
    assert summary["total_tokens"] == 22
    assert summary["total_duration_ms"] == 90
    assert summary["statuses"] == {"collector": "completed", "analyst": "completed"}
