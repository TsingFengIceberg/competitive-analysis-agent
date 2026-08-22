"""LangGraph StateGraph builder for the CI-Agent competition system.

Single graph with an Orchestrator entry and the competition analysis pipeline.
Nodes are placeholder lambdas; real
node implementations are injected via ``register_nodes()`` or set directly
on the module-level ``_NODE_IMPLEMENTATIONS`` dict.

Usage::

    from competition.graph import build_competition_graph
    from competition.state import CompetitionState

    graph = build_competition_graph(checkpointer=my_checkpointer)
    result = graph.invoke(CompetitionState(
        messages=[],
        user_request="分析 Cursor vs Copilot",
        target_products=["Cursor", "Copilot"],
    ))
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from competition.router import (
    route_after_analyst,
    route_after_collector,
    route_after_hitl,
    route_after_orchestrator,
    route_after_reviewer,
    route_after_writer,
)
from competition.stage_result import build_stage_result, next_attempt, summarize_stage_results, utc_now_iso
from competition.state import CompetitionState

logger = logging.getLogger(__name__)

# ── Placeholder node implementations ──
# Real nodes (from competition/nodes/*.py) are injected via register_nodes()
# before graph compilation. This avoids circular imports and makes testing easy.


def _placeholder(name: str) -> Callable[[dict], dict]:
    def _node(state: dict) -> dict:
        logger.debug("Node '%s' called (placeholder)", name)
        return {}
    _node.__name__ = name
    return _node


_AGENT_NAMES = {
    "orchestrator": "Orchestrator",
    "collector": "Collector",
    "analyst": "Analyst",
    "reviewer": "Reviewer",
    "writer": "Writer",
    "hitl_gate": "HITL",
    "error_handler": "ErrorHandler",
}

_DEFAULT_STAGE_TIMEOUTS = {
    "orchestrator": 60,
    "collector": 600,
    "analyst": 300,
    "reviewer": 300,
    "writer": 180,
    "hitl_gate": 60,
    "error_handler": 60,
}


def _instrument_node(stage: str, fn: Callable) -> Callable:
    """Wrap one business node with a compact, checkpoint-safe StageResult."""
    agent_name = _AGENT_NAMES.get(stage, stage)

    def _wrapped(state: dict) -> dict:
        started_at = utc_now_iso()
        started_monotonic = time.monotonic()
        stage_timeout = _stage_timeout_seconds(stage, state)
        stage_deadline = started_monotonic + stage_timeout if stage_timeout else None
        try:
            from competition.executor import get_agent_call_counts, get_agent_usage, set_stage_deadline

            set_stage_deadline(stage_deadline)
            before_usage = get_agent_usage()
            before_calls = get_agent_call_counts()
        except Exception:  # pragma: no cover - executor is optional in graph unit tests
            before_usage = {}
            before_calls = {}

        try:
            update = fn(state) or {}
            if not isinstance(update, dict):
                raise TypeError(f"Node '{stage}' must return a dict, got {type(update).__name__}")
            status = _status_for_update(update)
            try:
                from competition.executor import stage_timed_out

                if stage_timed_out():
                    update = {**update, "error": f"{stage} stage timeout after {stage_timeout}s"}
                    status = "timeout"
                    error_code = "timeout"
                else:
                    error_code = "node_error" if update.get("error") else None
            except Exception:
                error_code = "node_error" if update.get("error") else None
            error_message = str(update.get("error") or "")[:500] or None
        except Exception as exc:  # noqa: BLE001 - graph failures become routable state
            logger.exception("Competition stage '%s' failed", stage)
            update = {"error": f"{stage} failed: {str(exc)[:500]}"}
            status = _exception_status(exc)
            error_code = status if status in {"timeout", "cancelled"} else "node_exception"
            error_message = str(exc)[:500] or exc.__class__.__name__

        try:
            from competition.executor import get_agent_call_counts, get_agent_usage

            after_usage = get_agent_usage()
            after_calls = get_agent_call_counts()
        except Exception:  # pragma: no cover - executor is optional in graph unit tests
            after_usage = {}
            after_calls = {}
        finally:
            try:
                from competition.executor import clear_stage_deadline

                clear_stage_deadline()
            except Exception:
                pass

        usage_before = before_usage.get(agent_name, {})
        usage_after = after_usage.get(agent_name, {})
        usage_delta = {
            key: max(0, int(usage_after.get(key, 0) or 0) - int(usage_before.get(key, 0) or 0))
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
        tool_delta = max(0, int(usage_after.get("tool_calls", 0) or 0) - int(usage_before.get("tool_calls", 0) or 0))
        call_delta = max(0, int(after_calls.get(agent_name, 0) or 0) - int(before_calls.get(agent_name, 0) or 0))
        summary = update.get("collection_summary") if isinstance(update.get("collection_summary"), dict) else {}
        collected = update.get("collected_data") if isinstance(update.get("collected_data"), list) else []
        source_urls = {
            str(item.get("source_url"))
            for item in collected
            if isinstance(item, dict) and item.get("source_url")
        }
        source_count = len(source_urls)
        metrics: dict = {}
        if collected:
            metrics["data_point_count"] = len(collected)
        for key in ("coverage_warning", "review_round", "gap_coverage_improvement"):
            if key in update and update.get(key) is not None:
                metrics[key] = update[key]
        if summary:
            metrics.update({
                "source_types": summary.get("source_types", {}),
                "stopped_by": summary.get("stopped_by"),
            })

        result = build_stage_result(
            stage=stage,
            run_id=state.get("thread_id") or state.get("run_id"),
            attempt=next_attempt(state, stage),
            started_at=started_at,
            status=status,
            duration_ms=round((time.monotonic() - started_monotonic) * 1000),
            token_usage=usage_delta,
            llm_calls=call_delta,
            tool_calls=tool_delta,
            source_count=source_count,
            metrics=metrics,
            error_code=error_code,
            error_message=error_message,
            degraded_reason=(error_message if status in {"failed", "timeout", "cancelled"} else update.get("degraded_reason")),
            output_ref=_output_ref(stage, update),
        )
        existing_results = state.get("stage_results") or []
        merged_results = list(existing_results) + [result]
        update["stage_results"] = [result]
        update["current_stage"] = stage
        update["run_status"] = status if status in {"failed", "timeout", "cancelled", "partial"} else "running"
        update["usage_summary"] = summarize_stage_results(merged_results)
        return update

    _wrapped.__name__ = getattr(fn, "__name__", stage)
    _wrapped.__doc__ = getattr(fn, "__doc__", None)
    return _wrapped


def _status_for_update(update: dict) -> str:
    """Infer a degraded status from a node's explicit partial output."""
    if update.get("error"):
        return "failed"
    if update.get("partial") or update.get("degraded_reason") or update.get("coverage_warning"):
        return "partial"
    if update.get("unresolved_issues"):
        return "partial"
    return "completed"


def _exception_status(exc: Exception) -> str:
    """Classify cancellation and timeout exceptions for the runtime contract."""
    try:
        from competition.executor import is_cancelled, stage_timed_out

        if is_cancelled():
            return "cancelled"
        if stage_timed_out():
            return "timeout"
    except Exception:
        pass
    if isinstance(exc, TimeoutError) or "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
        return "timeout"
    return "failed"


def _stage_timeout_seconds(stage: str, state: dict) -> int:
    """Resolve a stage deadline from state overrides, environment, or defaults."""
    overrides = state.get("stage_timeouts") or {}
    if isinstance(overrides, dict) and stage in overrides:
        try:
            return max(1, int(overrides[stage]))
        except (TypeError, ValueError):
            pass
    import os

    env_name = f"CI_AGENT_STAGE_TIMEOUT_{stage.upper()}"
    try:
        return max(1, int(os.environ.get(env_name, _DEFAULT_STAGE_TIMEOUTS.get(stage, 300))))
    except (TypeError, ValueError):
        return _DEFAULT_STAGE_TIMEOUTS.get(stage, 300)


def _output_ref(stage: str, update: dict) -> str | None:
    """Return a stable pointer to a stage's business output, never the payload."""
    candidates = {
        "orchestrator": "orchestration_result",
        "collector": "collected_data",
        "analyst": "analysis_result",
        "reviewer": "review_verdict",
        "writer": "report_data",
        "hitl_gate": "hitl_decision",
    }
    key = candidates.get(stage)
    return f"state.{key}" if key and key in update else None


_NODE_IMPLEMENTATIONS: dict[str, Callable] = {
    # Orchestrator `[v4 新增]`
    "orchestrator": _placeholder("orchestrator"),
    # Normal mode
    "collector": _placeholder("collector"),
    "analyst": _placeholder("analyst"),
    "reviewer": _placeholder("reviewer"),
    "writer": _placeholder("writer"),
    "hitl_gate": _placeholder("hitl_gate"),
    "error_handler": _placeholder("error_handler"),
}


def register_nodes(nodes: dict[str, Callable]) -> None:
    """Inject real node implementations before graph compilation.

    Args:
        nodes: Mapping of node_name → callable(state) → dict.
               Keys must match the names in _NODE_IMPLEMENTATIONS.
    """
    for name, fn in nodes.items():
        if name not in _NODE_IMPLEMENTATIONS:
            logger.warning("Unknown node name: %s — adding anyway", name)
        _NODE_IMPLEMENTATIONS[name] = fn
        logger.info("Registered node: %s → %s", name, fn.__name__)


def build_competition_graph(
    checkpointer=None,
) -> CompiledStateGraph:
    """Build and compile the CI-Agent competition StateGraph.

    Args:
        checkpointer: Optional LangGraph checkpointer (SqliteSaver, etc.).
                      Provided by the framework persistence layer.

    Returns:
        Compiled LangGraph StateGraph ready for .invoke() / .stream().
    """
    builder = StateGraph(CompetitionState)

    # ── Orchestrator entry `[v4 新增]` ──
    builder.add_node("orchestrator", _instrument_node("orchestrator", _NODE_IMPLEMENTATIONS["orchestrator"]))

    # ── Normal mode nodes ──
    builder.add_node("collector", _instrument_node("collector", _NODE_IMPLEMENTATIONS["collector"]))
    builder.add_node("analyst", _instrument_node("analyst", _NODE_IMPLEMENTATIONS["analyst"]))
    builder.add_node("reviewer", _instrument_node("reviewer", _NODE_IMPLEMENTATIONS["reviewer"]))
    builder.add_node("writer", _instrument_node("writer", _NODE_IMPLEMENTATIONS["writer"]))
    builder.add_node("hitl_gate", _instrument_node("hitl_gate", _NODE_IMPLEMENTATIONS["hitl_gate"]))
    builder.add_node("error_handler", _instrument_node("error_handler", _NODE_IMPLEMENTATIONS["error_handler"]))

    # ── Normal mode edges ──
    builder.set_entry_point("orchestrator")  # v4: Orchestrator as entry
    builder.add_conditional_edges("orchestrator", route_after_orchestrator, {
        "collector": "collector",
        "error_handler": "error_handler",
    })
    builder.add_conditional_edges("collector", route_after_collector, {
        "analyst": "analyst",
        "error_handler": "error_handler",
    })
    builder.add_conditional_edges("analyst", route_after_analyst, {
        "reviewer": "reviewer",
        "error_handler": "error_handler",
    })
    builder.add_conditional_edges("reviewer", route_after_reviewer, {
        "writer": "writer",
        "collector": "collector",
        "error_handler": "error_handler",
    })
    builder.add_conditional_edges("writer", route_after_writer, {
        "hitl_gate": "hitl_gate",
        "error_handler": "error_handler",
    })
    builder.add_conditional_edges("hitl_gate", route_after_hitl, {
        "__end__": END,
        "collector": "collector",
        "analyst": "analyst",
        "writer": "writer",
        "error_handler": "error_handler",
    })
    builder.add_edge("error_handler", END)

    logger.info("Compiling competition graph%s", " with checkpointer" if checkpointer else "")
    return builder.compile(checkpointer=checkpointer)
