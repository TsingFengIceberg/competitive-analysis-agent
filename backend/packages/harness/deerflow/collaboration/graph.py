"""Parent Graph — Nested SubGraph 组装。

Parent Graph 职责：
- 挂载 Research SubGraph 和 Analysis SubGraph（Nested SubGraph 模式）
- HITL Gate（人类审批门）
- Report Composer（最终报告生成）
- 子图异常降级处理
- 条件路由

架构：
┌──────────────────────────────────────────────────────┐
│                    Parent Graph                       │
│                                                       │
│  Research SubGraph ──→ Analysis SubGraph               │
│       (state_out)         (state_in)                  │
│                                  │                    │
│                           HITL Gate                    │
│                                  │                    │
│                          Report Composer               │
└──────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.runnables import RunnableConfig
from langgraph.constants import END
from langgraph.graph import StateGraph

from deerflow.collaboration.nodes.analysis_nodes import report_composer_node
from deerflow.collaboration.nodes.hitl_gate import hitl_gate_node
from deerflow.collaboration.router import (
    route_after_analysis,
    route_after_hitl,
    route_after_research,
)
from deerflow.collaboration.state import CollaborationState
from deerflow.collaboration.subgraphs.analysis_subgraph import build_analysis_subgraph
from deerflow.collaboration.subgraphs.research_subgraph import build_research_subgraph
from deerflow.collaboration.subgraphs.state_mapping import (
    map_analysis_to_parent,
    map_parent_to_analysis,
    map_parent_to_research,
    map_research_to_parent,
)

if TYPE_CHECKING:
    from langgraph.checkpoint.base import Checkpointer
    from langgraph.graph import CompiledStateGraph

logger = logging.getLogger(__name__)


# ── Parent 层节点 ──


def error_handler_node(state: CollaborationState) -> dict:
    """Parent 层错误处理 — 子图异常降级。

    读取 collaboration_error 字段，记录错误并终止图运行。
    此节点后连接 END，节点异常不冒泡到父图。
    """
    error_msg = state.get("collaboration_error", "Unknown error")
    logger.error("Collaboration error handler triggered: %s", error_msg)
    return {}  # 错误已记录，终止图运行


# ── Parent Graph 构建 ────────────────────────────────────────────────────────


def build_collaboration_graph(checkpointer: "Checkpointer | None" = None) -> CompiledStateGraph:
    """构建 Parent Graph (Nested SubGraph 架构)。

    LangGraph Nested SubGraph 关键 API：
    - add_node("name", compiled_subgraph, state_in=fn, state_out=fn)
      - state_in: ParentState → dict（传入子图前投影）
      - state_out: (ChildState, ParentState) → dict（子图输出后写回父图）
    - 子图必须先 .compile() 才能挂载
    - 父子图共享 checkpointer 实例
    - 每 SubGraph 使用独立 checkpoint_ns 防止并行碰撞

    Args:
        checkpointer: LangGraph Checkpointer (SqliteSaver / PostgresSaver / InMemorySaver)。
                      由 DeerFlow Worker 在运行时注入或通过 make_collaboration_agent(config) 传入。
                      传入后 HITL interrupt() 具备持久化能力。

    返回编译后的协作图。
    """
    builder = StateGraph(CollaborationState)

    # ── SubGraph 挂载 ──
    # 关键：build_*_subgraph() 返回的是 CompiledStateGraph，
    # 可以直接传给 add_node() 作为嵌套子图。
    research_subgraph = build_research_subgraph(checkpointer=checkpointer)
    analysis_subgraph = build_analysis_subgraph(checkpointer=checkpointer)

    builder.add_node(
        "research_subgraph",
        research_subgraph,  # type: ignore[arg-type]
        state_in=map_parent_to_research,
        state_out=map_research_to_parent,
    )

    builder.add_node(
        "analysis_subgraph",
        analysis_subgraph,  # type: ignore[arg-type]
        state_in=map_parent_to_analysis,
        state_out=map_analysis_to_parent,
    )

    # ── Parent 层节点 ──
    builder.add_node("hitl_gate", hitl_gate_node)
    builder.add_node("report_composer", report_composer_node)
    builder.add_node("error_handler", error_handler_node)

    # ── 边与路由 ──
    builder.set_entry_point("research_subgraph")

    builder.add_conditional_edges(
        "research_subgraph",
        route_after_research,
        {
            "analysis_subgraph": "analysis_subgraph",
            "error_handler": "error_handler",
        },
    )

    builder.add_conditional_edges(
        "analysis_subgraph",
        route_after_analysis,
        {
            "hitl_gate": "hitl_gate",
            "error_handler": "error_handler",
        },
    )

    # HITL → approve/compose | modify/analysis | replan/research
    builder.add_conditional_edges(
        "hitl_gate",
        route_after_hitl,
        {
            "report_composer": "report_composer",
            "analysis_subgraph": "analysis_subgraph",
            "research_subgraph": "research_subgraph",
            "__end__": END,
        },
    )

    builder.add_edge("report_composer", END)
    builder.add_edge("error_handler", END)

    return builder.compile(checkpointer=checkpointer)


def make_collaboration_agent(config: "RunnableConfig") -> "CompiledStateGraph":
    """LangGraph 工厂函数，供 langgraph.json 的 graphs 注册。

    签名与 make_lead_agent(config) 兼容，由 LangGraph Runtime 传入
    RunnableConfig（含 configurable.thread_id, assistant_id 等）。

    checkpointer 由 DeerFlow Worker 在运行时注入 (agent.checkpointer = ...)，
    或通过 config.configurable 传入（用于测试和独立运行）。
    """
    # Runtime 传入的 checkpointer（可选）
    checkpointer = config.get("configurable", {}).get("checkpointer") if config else None
    return build_collaboration_graph(checkpointer=checkpointer)
