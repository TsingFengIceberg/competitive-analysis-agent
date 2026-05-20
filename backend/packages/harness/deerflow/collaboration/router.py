"""Centralized routing logic for the collaboration graph.

All conditional routing functions live here so the graph assembly files
(graph.py, research_subgraph.py, analysis_subgraph.py) import them
rather than each defining routing inline.
"""

from __future__ import annotations

import logging
from typing import Literal

from deerflow.collaboration.state import (
    AnalysisSubGraphState,
    CollaborationState,
    ResearchSubGraphState,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Parent Graph 路由
# ═══════════════════════════════════════════════════════════════════════════════


def route_after_research(state: CollaborationState) -> Literal["analysis_subgraph", "error_handler"]:
    """Research 完成后的路径选择。

    Research SubGraph 异常时跳到错误处理而非继续 Analysis。
    """
    if state.get("collaboration_error"):
        logger.warning("Research SubGraph error, routing to error_handler")
        return "error_handler"
    return "analysis_subgraph"


def route_after_analysis(state: CollaborationState) -> Literal["hitl_gate", "error_handler"]:
    """Analysis 完成后的路径选择。"""
    if state.get("collaboration_error"):
        logger.warning("Analysis SubGraph error, routing to error_handler")
        return "error_handler"
    return "hitl_gate"


def route_after_hitl(
    state: CollaborationState,
) -> Literal["report_composer", "research_subgraph", "analysis_subgraph", "__end__"]:
    """HITL 审批后的路径选择。

    - approve → Report Composer
    - modify  → Analysis SubGraph（重新合成）
    - replan  → Research SubGraph（重新规划）
    """
    decision = state.get("review_decision")
    if decision == "approve":
        return "report_composer"
    elif decision == "modify":
        return "analysis_subgraph"
    elif decision == "replan":
        return "research_subgraph"
    return "__end__"


# ═══════════════════════════════════════════════════════════════════════════════
# Research SubGraph 路由
# ═══════════════════════════════════════════════════════════════════════════════


def route_after_critic(state: ResearchSubGraphState) -> Literal["data_scout", "meta_judge"]:
    """Critic 之后的路径选择。

    只检查本轮新产生的 pending challenges（未被 rebuttals 覆盖的），
    避免因 add reducer 累加导致旧 challenges 反复触发循环。
    """
    debate_round = state.get("debate_round", 0) or 0
    challenges = state.get("challenges", [])
    rebuttals = state.get("rebuttals", [])

    if not challenges:
        return "meta_judge"

    rebutted_ids = {r.get("challenge_id") for r in rebuttals if isinstance(r, dict)}
    pending = [c for c in challenges if isinstance(c, dict) and c.get("challenge_id") not in rebutted_ids]

    if pending and debate_round < 2:
        return "data_scout"
    return "meta_judge"


def route_after_pi_review(state: ResearchSubGraphState) -> Literal["__end__", "error_handler"]:
    """PI 审核后的路径选择。"""
    if state.get("error"):
        return "error_handler"
    return "__end__"


# ═══════════════════════════════════════════════════════════════════════════════
# Analysis SubGraph 路由
# ═══════════════════════════════════════════════════════════════════════════════


def route_after_reviewer(state: AnalysisSubGraphState) -> Literal["__end__", "error_handler"]:
    """Internal Reviewer 后的路径选择。

    审查未通过或发生异常时跳到错误处理。
    """
    if state.get("error"):
        return "error_handler"
    if state.get("internal_review_passed") is False:
        return "error_handler"
    return "__end__"
