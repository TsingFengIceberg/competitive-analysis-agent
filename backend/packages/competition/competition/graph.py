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
from collections.abc import Callable

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from competition.router import (
    route_after_analyst,
    route_after_collector,
    route_after_hitl,
    route_after_reviewer,
    route_after_writer,
)
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
    builder.add_node("orchestrator", _NODE_IMPLEMENTATIONS["orchestrator"])

    # ── Normal mode nodes ──
    builder.add_node("collector", _NODE_IMPLEMENTATIONS["collector"])
    builder.add_node("analyst", _NODE_IMPLEMENTATIONS["analyst"])
    builder.add_node("reviewer", _NODE_IMPLEMENTATIONS["reviewer"])
    builder.add_node("writer", _NODE_IMPLEMENTATIONS["writer"])
    builder.add_node("hitl_gate", _NODE_IMPLEMENTATIONS["hitl_gate"])
    builder.add_node("error_handler", _NODE_IMPLEMENTATIONS["error_handler"])

    # ── Normal mode edges ──
    builder.set_entry_point("orchestrator")  # v4: Orchestrator as entry
    builder.add_edge("orchestrator", "collector")  # fixed: O→C always
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
    })
    builder.add_edge("error_handler", END)

    logger.info("Compiling competition graph%s", " with checkpointer" if checkpointer else "")
    return builder.compile(checkpointer=checkpointer)
