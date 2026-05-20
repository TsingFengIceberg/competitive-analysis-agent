"""Analysis SubGraph — 多维度分析与报告合成。

工作流：
  Analyst Lead（分析调度）
    → Synthesizer（多维对比 + SWOT + 趋势 + 建议）
    → Internal Reviewer（分析质量内审）
    → SynthesisReport

接收 Research SubGraph 的精炼输出（validated_brief），
产出完整分析报告（synthesis_report）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langgraph.constants import END
from langgraph.graph import StateGraph

from deerflow.collaboration.nodes.analysis_nodes import (
    analyst_lead_node,
    internal_reviewer_node,
    synthesizer_node,
)
from deerflow.collaboration.router import route_after_reviewer
from deerflow.collaboration.state import AnalysisSubGraphState

if TYPE_CHECKING:
    from langgraph.checkpoint.base import Checkpointer
    from langgraph.graph import CompiledStateGraph

logger = logging.getLogger(__name__)


# ── SubGraph 构建 ────────────────────────────────────────────────────────────


def build_analysis_subgraph(checkpointer: "Checkpointer | None" = None) -> CompiledStateGraph:
    """构建 Analysis SubGraph（独立编译）。

    返回编译后的子图，由 Parent Graph 挂载。
    Nested SubGraph 不会继承父图的 Checkpointer，必须显式传入以持久化子图内部状态。
    """
    builder = StateGraph(AnalysisSubGraphState)

    builder.add_node("analyst_lead", analyst_lead_node)
    builder.add_node("synthesizer", synthesizer_node)
    builder.add_node("internal_reviewer", internal_reviewer_node)
    builder.add_node("error_handler", error_handler_node)

    builder.set_entry_point("analyst_lead")
    builder.add_edge("analyst_lead", "synthesizer")
    builder.add_edge("synthesizer", "internal_reviewer")
    builder.add_conditional_edges("internal_reviewer", route_after_reviewer, {
        "__end__": END,
        "error_handler": "error_handler",
    })
    builder.add_edge("error_handler", END)

    return builder.compile(checkpointer=checkpointer)


def error_handler_node(state: AnalysisSubGraphState) -> dict:
    """错误处理 — 子图异常上浮。"""
    error_msg = state.get("error", "Unknown error in Analysis SubGraph")
    logger.error("Analysis SubGraph error: %s", error_msg)
    return {}
