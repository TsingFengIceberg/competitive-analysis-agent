"""Sprint 3 — Analysis SubGraph node + Report Composer unit tests.

Mock SubagentExecutor to verify node input/output contracts.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deerflow.collaboration.state import AnalysisSubGraphState, CollaborationState


@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mock SubagentExecutor 和 get_available_tools。"""
    mock_executor = MagicMock()
    mock_executor.return_value.execute.return_value = '{"result": "mocked"}'

    mock_tools = MagicMock()
    mock_tools.return_value = [MagicMock()]

    with (
        patch("deerflow.subagents.executor.SubagentExecutor", mock_executor),
        patch("deerflow.tools.get_available_tools", mock_tools),
    ):
        yield {"executor": mock_executor, "tools": mock_tools}


def _make_analysis_state(**overrides) -> AnalysisSubGraphState:
    base: dict = {"messages": []}
    base.update(overrides)
    return base  # type: ignore[return-value]


def _make_parent_state(**overrides) -> CollaborationState:
    base: dict = {"messages": []}
    base.update(overrides)
    return base  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════════════════════════════
# Analyst Lead Node
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalystLeadNode:
    def test_returns_analysis_plan(self, mock_dependencies):
        """Analyst Lead 返回 analysis_plan。"""
        from deerflow.collaboration.nodes.analysis_nodes import analyst_lead_node

        state = _make_analysis_state(validated_brief={"topic": "test"})
        result = analyst_lead_node(state)
        assert "analysis_plan" in result

    def test_handles_executor_error(self, mock_dependencies):
        """处理 SubagentExecutor 异常。"""
        from deerflow.collaboration.nodes.analysis_nodes import analyst_lead_node

        mock_dependencies["executor"].return_value.execute.side_effect = RuntimeError("crash")
        state = _make_analysis_state()
        result = analyst_lead_node(state)
        assert "error" in result
        assert "Analyst Lead" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════════
# Synthesizer Node
# ═══════════════════════════════════════════════════════════════════════════════


class TestSynthesizerNode:
    def test_returns_analysis_results_and_report(self, mock_dependencies):
        """Synthesizer 返回 analysis_results 和 synthesis_report。"""
        from deerflow.collaboration.nodes.analysis_nodes import synthesizer_node

        state = _make_analysis_state(
            validated_brief={"data_points": []},
            analysis_plan={"dimensions": ["price_analysis"]},
        )
        result = synthesizer_node(state)
        assert "analysis_results" in result
        assert "synthesis_report" in result

    def test_handles_executor_error(self, mock_dependencies):
        """处理异常。"""
        from deerflow.collaboration.nodes.analysis_nodes import synthesizer_node

        mock_dependencies["executor"].return_value.execute.side_effect = RuntimeError("computation failed")
        state = _make_analysis_state()
        result = synthesizer_node(state)
        assert "error" in result
        assert "Synthesizer" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════════
# Internal Reviewer Node
# ═══════════════════════════════════════════════════════════════════════════════


class TestInternalReviewerNode:
    def test_returns_review_passed(self, mock_dependencies):
        """Internal Reviewer 返回 internal_review_passed。"""
        from deerflow.collaboration.nodes.analysis_nodes import internal_reviewer_node

        state = _make_analysis_state(synthesis_report={"comparison_matrix": {}})
        result = internal_reviewer_node(state)
        assert "internal_review_passed" in result
        assert "review_feedback" in result

    def test_handles_executor_error(self, mock_dependencies):
        """处理异常。"""
        from deerflow.collaboration.nodes.analysis_nodes import internal_reviewer_node

        mock_dependencies["executor"].return_value.execute.side_effect = RuntimeError("review failed")
        state = _make_analysis_state()
        result = internal_reviewer_node(state)
        assert "error" in result
        assert "Internal Reviewer" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════════
# Report Composer Node (Parent Graph)
# ═══════════════════════════════════════════════════════════════════════════════


class TestReportComposerNode:
    def test_returns_empty_dict_on_success(self, mock_dependencies):
        """Report Composer 成功后返回空 dict（报告已写入文件）。"""
        from deerflow.collaboration.nodes.analysis_nodes import report_composer_node

        state = _make_parent_state(
            validated_brief={"topic": "test"},
            synthesis_report={"comparison_matrix": {}},
        )
        result = report_composer_node(state)
        assert result == {}  # 报告写入文件，无状态更新

    def test_handles_executor_error(self, mock_dependencies):
        """处理异常，写入 collaboration_error。"""
        from deerflow.collaboration.nodes.analysis_nodes import report_composer_node

        mock_dependencies["executor"].return_value.execute.side_effect = RuntimeError("file write failed")
        state = _make_parent_state()
        result = report_composer_node(state)
        assert "collaboration_error" in result
        assert "Report Composer" in result["collaboration_error"]


# ═══════════════════════════════════════════════════════════════════════════════
# Analysis SubGraph 编译 + 路由
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalysisSubGraphIntegration:
    def test_subgraph_compiles_with_real_nodes(self):
        """Analysis SubGraph 用真实节点编译通过。"""
        from deerflow.collaboration.subgraphs.analysis_subgraph import build_analysis_subgraph

        graph = build_analysis_subgraph()
        nodes = graph.get_graph().nodes
        assert "analyst_lead" in nodes
        assert "synthesizer" in nodes
        assert "internal_reviewer" in nodes
        assert "error_handler" in nodes

    def test_route_after_reviewer_passed(self):
        """审查通过 → END。"""
        from deerflow.collaboration.router import route_after_reviewer

        state = _make_analysis_state(internal_review_passed=True)
        assert route_after_reviewer(state) == "__end__"

    def test_route_after_reviewer_failed(self):
        """审查未通过 → error_handler。"""
        from deerflow.collaboration.router import route_after_reviewer

        state = _make_analysis_state(internal_review_passed=False)
        assert route_after_reviewer(state) == "error_handler"

    def test_route_after_reviewer_error(self):
        """节点异常 → error_handler。"""
        from deerflow.collaboration.router import route_after_reviewer

        state = _make_analysis_state(error="something wrong")
        assert route_after_reviewer(state) == "error_handler"


# ═══════════════════════════════════════════════════════════════════════════════
# Prompt 完整性
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalysisPrompts:
    def test_analyst_lead_prompt(self):
        from deerflow.collaboration.prompts import ANALYST_LEAD_PROMPT
        assert "Analyst Lead" in ANALYST_LEAD_PROMPT
        assert "Forbidden" in ANALYST_LEAD_PROMPT
        assert "validated_brief" in ANALYST_LEAD_PROMPT

    def test_synthesizer_prompt(self):
        from deerflow.collaboration.prompts import SYNTHESIZER_PROMPT
        assert "Synthesizer" in SYNTHESIZER_PROMPT
        assert "Python" in SYNTHESIZER_PROMPT
        assert "synthesis_report" in SYNTHESIZER_PROMPT

    def test_internal_reviewer_prompt(self):
        from deerflow.collaboration.prompts import INTERNAL_REVIEWER_PROMPT
        assert "Internal Reviewer" in INTERNAL_REVIEWER_PROMPT
        assert "passed" in INTERNAL_REVIEWER_PROMPT

    def test_report_composer_prompt(self):
        from deerflow.collaboration.prompts import REPORT_COMPOSER_PROMPT
        assert "Report Composer" in REPORT_COMPOSER_PROMPT
        assert "Markdown" in REPORT_COMPOSER_PROMPT
