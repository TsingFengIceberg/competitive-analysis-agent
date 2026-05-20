"""Research SubGraph — 对抗式批判验证研究流程。

工作流：
  PI Agent（规划+分发）
    → Send API Fan-out → Data Scouts（并行采集）
    → Critic Agent（对抗式质疑，必须附证据）
    → [有问题] → Scouts 定向补采（rebuttal，最多2轮）
    → [没问题] → Meta-Judge（独立裁决）
    → PI Review（审核裁决书，可推翻但需审计）
    → ValidatedBrief

四权分立：
  - 质疑权（Critic）: 必须附证据，不可自行采集
  - 执行权（Scout）: 可采集+回应质疑，不可质疑/裁决
  - 裁决权（Judge）: 只看证据不站队，不可采集/质疑/合成
  - 监督权（PI）: 可推翻裁决（需审计）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langgraph.constants import END
from langgraph.graph import StateGraph

from deerflow.collaboration.nodes.research_nodes import (
    critic_agent_node,
    data_scout_node,
    error_handler_node,
    meta_judge_node,
    pi_agent_node,
    pi_dispatch_node,
    pi_review_node,
)
from deerflow.collaboration.router import route_after_critic, route_after_pi_review
from deerflow.collaboration.state import ResearchSubGraphState

if TYPE_CHECKING:
    from langgraph.graph import CompiledStateGraph

logger = logging.getLogger(__name__)


# ── SubGraph 构建 ────────────────────────────────────────────────────────────


def build_research_subgraph() -> CompiledStateGraph:
    """构建 Research SubGraph（独立编译）。

    返回编译后的子图，由 Parent Graph 通过 add_node(subgraph, state_in=fn, state_out=fn) 挂载。

    LangGraph 要求子图必须先 .compile() 才能挂载到父图。
    """
    builder = StateGraph(ResearchSubGraphState)

    # 节点注册 — 导入自 deerflow.collaboration.nodes
    builder.add_node("pi_agent", pi_agent_node)
    builder.add_node("pi_dispatch", pi_dispatch_node)
    builder.add_node("data_scout", data_scout_node)
    builder.add_node("critic_agent", critic_agent_node)
    builder.add_node("meta_judge", meta_judge_node)
    builder.add_node("pi_review", pi_review_node)
    builder.add_node("error_handler", error_handler_node)

    # 边
    builder.set_entry_point("pi_agent")
    builder.add_edge("pi_agent", "pi_dispatch")
    builder.add_edge("pi_dispatch", "critic_agent")
    builder.add_conditional_edges("critic_agent", route_after_critic, {
        "data_scout": "data_scout",
        "meta_judge": "meta_judge",
    })
    builder.add_edge("data_scout", "critic_agent")  # 定向补采后回到 Critic
    builder.add_edge("meta_judge", "pi_review")
    builder.add_conditional_edges("pi_review", route_after_pi_review, {
        "__end__": END,
        "error_handler": "error_handler",
    })
    builder.add_edge("error_handler", END)

    return builder.compile()
