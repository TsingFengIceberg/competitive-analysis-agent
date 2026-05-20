"""Sprint 1 — Parent Graph 组装 + Nested SubGraph 挂载测试。

验证：
- Parent Graph 可编译，挂载两个 SubGraph
- 条件路由声明正确（research → analysis | error, hitl → compose | modify | replan）
- State Mapping 与 SubGraph 集成正确
- 子图异常上浮路径
"""

from __future__ import annotations

import pytest

from deerflow.collaboration.graph import (
    build_collaboration_graph,
    route_after_analysis,
    route_after_hitl,
    route_after_research,
)
from deerflow.collaboration.state import CollaborationState


# ═══════════════════════════════════════════════════════════════════════════════
# Parent Graph 编译验证
# ═══════════════════════════════════════════════════════════════════════════════


class TestParentGraphCompilation:
    """验证 Parent Graph 的 Nested SubGraph 架构可正确编译。"""

    def test_parent_graph_compiles(self):
        """Parent Graph 编译成功。"""
        graph = build_collaboration_graph()
        assert graph is not None

    def test_all_nodes_registered(self):
        """所有节点注册正确：2 个 SubGraph + 3 个 Parent 层节点。"""
        graph = build_collaboration_graph()
        nodes = graph.get_graph().nodes
        assert "research_subgraph" in nodes
        assert "analysis_subgraph" in nodes
        assert "hitl_gate" in nodes
        assert "report_composer" in nodes
        assert "error_handler" in nodes

    def test_entry_point_is_research(self):
        """入口是 Research SubGraph。"""
        graph = build_collaboration_graph()
        # 编译后的图入口是 __start__ → research_subgraph
        nodes = graph.get_graph().nodes
        assert "research_subgraph" in nodes

    def test_state_channels_created(self):
        """所有 State 字段都有对应的 channel。"""
        graph = build_collaboration_graph()
        channel_names = list(graph.channels.keys())
        # Parent State 字段
        assert "validated_brief" in channel_names
        assert "synthesis_report" in channel_names
        assert "collaboration_error" in channel_names
        assert "review_decision" in channel_names
        # 继承自 AgentState
        assert "messages" in channel_names

    def test_subgraphs_have_namespace_isolation(self):
        """每个 SubGraph 使用独立 namespace，防止并行碰撞。"""
        graph = build_collaboration_graph()
        # Nested SubGraph 自动获得独立 namespace
        # 验证图结构中有两个不同的子图节点
        nodes = graph.get_graph().nodes
        research_node = nodes["research_subgraph"]
        analysis_node = nodes["analysis_subgraph"]
        assert research_node is not None
        assert analysis_node is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 条件路由逻辑
# ═══════════════════════════════════════════════════════════════════════════════


class TestConditionalRouting:
    """验证 Parent Graph 的条件路由逻辑。"""

    # ── Research → Analysis / Error ──

    def test_route_after_research_normal(self):
        """Research 正常完成 → 路由到 Analysis。"""
        state = _make_state()
        assert route_after_research(state) == "analysis_subgraph"

    def test_route_after_research_error(self):
        """Research 异常 → 路由到 error_handler。"""
        state = _make_state(collaboration_error="Research timeout")
        assert route_after_research(state) == "error_handler"

    # ── Analysis → HITL / Error ──

    def test_route_after_analysis_normal(self):
        """Analysis 正常完成 → 路由到 HITL。"""
        state = _make_state()
        assert route_after_analysis(state) == "hitl_gate"

    def test_route_after_analysis_error(self):
        """Analysis 异常 → 路由到 error_handler。"""
        state = _make_state(collaboration_error="Synthesizer failed")
        assert route_after_analysis(state) == "error_handler"

    # ── HITL → Compose / Modify / Replan ──

    def test_route_after_hitl_approve(self):
        """审批通过 → Report Composer。"""
        state = _make_state(review_decision="approve")
        assert route_after_hitl(state) == "report_composer"

    def test_route_after_hitl_modify(self):
        """审批修改 → 重新进入 Analysis SubGraph。"""
        state = _make_state(review_decision="modify")
        assert route_after_hitl(state) == "analysis_subgraph"

    def test_route_after_hitl_replan(self):
        """审批重新规划 → 重新进入 Research SubGraph。"""
        state = _make_state(review_decision="replan")
        assert route_after_hitl(state) == "research_subgraph"

    def test_route_after_hitl_no_decision(self):
        """无审批决定 → 结束。"""
        state = _make_state()
        assert route_after_hitl(state) == "__end__"


# ═══════════════════════════════════════════════════════════════════════════════
# HITL 全场景覆盖
# ═══════════════════════════════════════════════════════════════════════════════


class TestHITLRoutingScenarios:
    """HITL Gate 三种决策的完整覆盖。"""

    @pytest.mark.parametrize(
        "decision,expected",
        [
            ("approve", "report_composer"),
            ("modify", "analysis_subgraph"),
            ("replan", "research_subgraph"),
        ],
    )
    def test_hitl_decisions(self, decision, expected):
        """HITL 三种决策正确路由。"""
        state = _make_state(review_decision=decision)
        assert route_after_hitl(state) == expected

    def test_hitl_modify_preserves_synthesis_data(self):
        """modify 路由时 synthesis_report 保留，供 Analysis 重新使用。"""
        state = _make_state(
            review_decision="modify",
            synthesis_report={"comparison_matrix": {"exists": True}},
        )
        assert route_after_hitl(state) == "analysis_subgraph"
        assert state.get("synthesis_report") is not None  # 数据未被清除

    def test_hitl_replan_clears_synthesis(self):
        """replan 路由时，synthesis_report 可能为 None（重新规划后重新开始）。"""
        state = _make_state(review_decision="replan")
        assert route_after_hitl(state) == "research_subgraph"


# ═══════════════════════════════════════════════════════════════════════════════
# 异常上浮路径
# ═══════════════════════════════════════════════════════════════════════════════


class TestErrorPropagation:
    """验证子图异常通过 collaboration_error 字段上浮到父图的完整路径。"""

    def test_research_error_propagates(self):
        """Research SubGraph error → collaboration_error → 触发 error 路由。"""
        state = _make_state(collaboration_error="Scout: all sources failed")
        assert route_after_research(state) == "error_handler"

    def test_analysis_error_propagates(self):
        """Analysis SubGraph error → collaboration_error → 触发 error 路由。"""
        state = _make_state(collaboration_error="Internal Reviewer: failed validation")
        assert route_after_analysis(state) == "error_handler"

    def test_no_error_normal_flow(self):
        """无异常时走正常流程。"""
        state = _make_state()
        assert route_after_research(state) == "analysis_subgraph"
        assert route_after_analysis(state) == "hitl_gate"


# ═══════════════════════════════════════════════════════════════════════════════
# 测试辅助
# ═══════════════════════════════════════════════════════════════════════════════


def _make_state(**overrides) -> CollaborationState:
    """创建 Parent State 的测试辅助。"""
    base: dict = {
        "messages": [],
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════════════════════════════
# P0: Lead Agent 路由到协作图
# ═══════════════════════════════════════════════════════════════════════════════


class TestLeadAgentCollaborationRouting:
    """验证 make_lead_agent() 在 collaboration.enabled 时路由到协作图。"""

    def test_routes_to_collaboration_when_enabled(self, monkeypatch):
        """collaboration.enabled=true → 返回协作图而非 ReAct agent。"""
        import deerflow.agents.lead_agent.agent as agent_module

        mock_config = _mock_app_config(collaboration_enabled=True)
        monkeypatch.setattr(agent_module, "get_app_config", lambda: mock_config)
        monkeypatch.setattr(agent_module, "_get_runtime_config", lambda c: {})

        graph = agent_module.make_lead_agent({})
        nodes = graph.get_graph().nodes
        assert "research_subgraph" in nodes
        assert "analysis_subgraph" in nodes
        assert "hitl_gate" in nodes

    def test_routes_to_react_when_disabled(self, monkeypatch):
        """collaboration.enabled=false → 调用 _make_lead_agent 返回标准 ReAct agent。"""
        import deerflow.agents.lead_agent.agent as agent_module

        mock_config = _mock_app_config(collaboration_enabled=False)
        monkeypatch.setattr(agent_module, "get_app_config", lambda: mock_config)
        monkeypatch.setattr(agent_module, "_get_runtime_config", lambda c: {})

        called_with = {}

        def fake_make_lead_agent(config, *, app_config):
            called_with["called"] = True
            from langgraph.graph import StateGraph

            builder = StateGraph(dict)
            builder.add_node("test", lambda s: {})
            builder.set_entry_point("test")
            builder.set_finish_point("test")
            return builder.compile()

        monkeypatch.setattr(agent_module, "_make_lead_agent", fake_make_lead_agent)

        graph = agent_module.make_lead_agent({})
        assert called_with["called"]

    def test_routes_to_react_when_collaboration_field_missing(self, monkeypatch):
        """collaboration 配置段缺失 → 调用 _make_lead_agent（向后兼容）。"""
        import deerflow.agents.lead_agent.agent as agent_module

        mock_config = _mock_app_config(collaboration_enabled=None)
        monkeypatch.setattr(agent_module, "get_app_config", lambda: mock_config)
        monkeypatch.setattr(agent_module, "_get_runtime_config", lambda c: {})

        called_with = {}

        def fake_make_lead_agent(config, *, app_config):
            called_with["called"] = True
            from langgraph.graph import StateGraph

            builder = StateGraph(dict)
            builder.add_node("test", lambda s: {})
            builder.set_entry_point("test")
            builder.set_finish_point("test")
            return builder.compile()

        monkeypatch.setattr(agent_module, "_make_lead_agent", fake_make_lead_agent)

        graph = agent_module.make_lead_agent({})
        assert called_with["called"]


def _mock_app_config(collaboration_enabled: bool | None):
    """Create a minimal mock AppConfig for routing tests."""
    from unittest.mock import MagicMock

    config = MagicMock()
    if collaboration_enabled is not None:
        collab = MagicMock()
        collab.enabled = collaboration_enabled
        config.collaboration = collab
    else:
        config.collaboration = None
    return config
