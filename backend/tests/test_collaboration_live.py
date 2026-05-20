"""P2: 真实 LLM 集成测试 — 需要 API Key，手动运行。

使用真实 LLM（默认 gemini-3-flash）验证：
- create_chat_model + prompt 可正常工作
- LLM 输出 JSON 可被 _extract_json 正确解析
- SubagentExecutor 正确传递配置给真实 LLM

运行方式：
    PYTHONPATH=packages/harness:. uv run pytest tests/test_collaboration_live.py -v -m live

注意：conftest.py 全局 mock 了 deerflow.subagents.executor（解决循环导入），
live 测试需要在运行时移除 mock 以使用真实模块。

Author: Wu Gang + Claude
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock

import pytest

from deerflow.collaboration.nodes.research_nodes import _extract_json
from deerflow.collaboration.state import ResearchSubGraphState


def _has_api_key() -> bool:
    """检查是否有可用的 API Key。"""
    return bool(os.environ.get("GEMINI_API_KEY"))


def _remove_executor_mock():
    """移除 conftest.py 注入的 SubagentExecutor mock，允许使用真实模块。"""
    mock = sys.modules.get("deerflow.subagents.executor")
    if mock is not None:
        del sys.modules["deerflow.subagents.executor"]
    # 清除依赖 mock 模块的缓存
    for key in list(sys.modules):
        if key.startswith("deerflow.subagents") and key != "deerflow.subagents":
            if key != "deerflow.subagents.executor":
                del sys.modules[key]
    return mock


def _restore_executor_mock(mock):
    """恢复 SubagentExecutor mock。"""
    if mock is not None:
        sys.modules["deerflow.subagents.executor"] = mock


def _make_state(**overrides) -> ResearchSubGraphState:
    """构建测试 State。"""
    base: dict = {
        "messages": [{"role": "user", "content": "对比分析 iPhone 17 和 三星 S25 Ultra"}],
        "scout_results": [],
        "challenges": [],
        "rebuttals": [],
        "debate_round": 0,
        "ruling": None,
        "research_plan": None,
        "validated_brief": None,
        "research_quality_score": None,
        "error": None,
        "workflow_type": "competitive_analysis",
        "max_scouts": 3,
        "scout_task": None,
        "source_credibility_memory": None,
        "product_knowledge_memory": None,
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════════════════════════════
# 底层 LLM 连通性验证（不依赖 SubagentExecutor）
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.live
class TestLLMConnectivity:
    """验证真实 LLM 连通性和基本能力（绕过 SubagentExecutor）。"""

    def test_model_can_be_created(self):
        """模型可成功创建。"""
        if not _has_api_key():
            pytest.skip("GEMINI_API_KEY not set")

        from deerflow.models import create_chat_model

        model = create_chat_model(name="gemini-3-flash", thinking_enabled=False)
        assert model is not None

    def test_model_can_invoke_simple_prompt(self):
        """模型可成功调用并返回内容。"""
        if not _has_api_key():
            pytest.skip("GEMINI_API_KEY not set")

        from deerflow.models import create_chat_model

        model = create_chat_model(name="gemini-3-flash", thinking_enabled=False)
        response = model.invoke("Say 'hello world' and nothing else.")

        assert response is not None
        assert hasattr(response, "content")
        assert len(response.content) > 0
        assert "hello" in response.content.lower()

    def test_model_outputs_valid_json(self):
        """模型可输出有效 JSON 格式。"""
        if not _has_api_key():
            pytest.skip("GEMINI_API_KEY not set")

        from deerflow.models import create_chat_model

        model = create_chat_model(name="gemini-3-flash", thinking_enabled=False)
        prompt = (
            "You are a research planner. Output ONLY a JSON object, no other text.\n"
            'Format: {"topic": "...", "sub_tasks": [{"id": "t1", "query": "..."}]}\n\n'
            "Plan a research investigation for: Compare iPhone 17 and Samsung S25 Ultra."
        )
        response = model.invoke(prompt)

        parsed = _extract_json(response.content)
        assert parsed is not None, f"Failed to parse JSON from: {response.content[:500]}"
        assert "topic" in parsed
        assert "sub_tasks" in parsed
        assert len(parsed["sub_tasks"]) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 单节点真实 LLM 测试（移除 mock，使用真实 SubagentExecutor）
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.live
class TestPIAgentLive:
    """PI Agent 使用真实 LLM 生成研究计划。"""

    def test_pi_agent_generates_valid_plan(self):
        """真实 LLM 生成的研究计划应包含 topic 和 sub_tasks。"""
        if not _has_api_key():
            pytest.skip("GEMINI_API_KEY not set")

        mock = _remove_executor_mock()
        try:
            from deerflow.collaboration.nodes.research_nodes import pi_agent_node

            state = _make_state()
            result = pi_agent_node(state)

            assert result is not None
            assert isinstance(result, dict)
            assert "error" not in result

            plan = result.get("research_plan")
            assert plan is not None, f"PI Agent should return research_plan, got: {result}"
            assert isinstance(plan, dict)
            assert "topic" in plan
            assert "sub_tasks" in plan
            assert len(plan["sub_tasks"]) >= 1
        finally:
            _restore_executor_mock(mock)

    def test_pi_agent_generates_chinese_plan(self):
        """中文输入 → 研究计划 topic 应包含中文关键词。"""
        if not _has_api_key():
            pytest.skip("GEMINI_API_KEY not set")

        mock = _remove_executor_mock()
        try:
            from deerflow.collaboration.nodes.research_nodes import pi_agent_node

            state = _make_state(
                messages=[{"role": "user", "content": "帮我分析华为 Mate 70 Pro 的竞品情况"}],
            )
            result = pi_agent_node(state)

            assert result is not None
            plan = result.get("research_plan")
            assert plan is not None
            topic = plan.get("topic", "")
            assert any(keyword in topic for keyword in ["华为", "Mate", "竞品", "分析"]), f"topic not related: {topic}"
        finally:
            _restore_executor_mock(mock)


@pytest.mark.live
class TestSubagentExecutorLive:
    """验证真实 LLM 通过 SubagentExecutor 执行的完整性。"""

    def test_executor_produces_parsable_json(self):
        """SubagentExecutor + 真实 LLM → 输出可被 _extract_json 解析。"""
        if not _has_api_key():
            pytest.skip("GEMINI_API_KEY not set")

        mock = _remove_executor_mock()
        try:
            from deerflow.subagents.config import SubagentConfig
            from deerflow.subagents.executor import SubagentExecutor
            from deerflow.tools import get_available_tools

            config = SubagentConfig(
                name="pi_live_test",
                description="Test PI agent with real LLM",
                system_prompt="You are a research planner. Output ONLY a JSON object with 'topic' and 'sub_tasks' (list of {id, query}). No markdown.",
                tools=["read_file"],
                model="gemini-3-flash",
                max_turns=5,
            )

            tools = get_available_tools()
            executor = SubagentExecutor(config, tools)
            result = executor.execute(
                "Plan research for: Compare iPhone 17 and Samsung S25 Ultra battery life. "
                "Output ONLY valid JSON."
            )

            assert result is not None
            assert len(result) > 0

            parsed = _extract_json(result)
            assert parsed is not None, f"Failed to parse JSON from: {result[:500]}"

            if isinstance(parsed, dict):
                assert "topic" in parsed
        finally:
            _restore_executor_mock(mock)

    def test_executor_with_python_computation(self):
        """SubagentExecutor + 真实 LLM + Python tool → 执行计算并输出 JSON。"""
        if not _has_api_key():
            pytest.skip("GEMINI_API_KEY not set")

        mock = _remove_executor_mock()
        try:
            from deerflow.subagents.config import SubagentConfig
            from deerflow.subagents.executor import SubagentExecutor
            from deerflow.tools import get_available_tools

            config = SubagentConfig(
                name="judge_live_test",
                description="Test Meta-Judge with real LLM",
                system_prompt="You adjudicate data conflicts. Use Python for calculations, then output JSON. No markdown.",
                tools=["read_file", "python"],
                model="gemini-3-flash",
                max_turns=5,
            )

            tools = get_available_tools()
            executor = SubagentExecutor(config, tools)
            result = executor.execute(
                "Run Python: calculate mean of [0.85, 0.92, 0.78, 0.91]. "
                "Output JSON: {'quality_score': <mean>, 'computation_summary': '<brief>'}"
            )

            assert result is not None
            parsed = _extract_json(result)
            assert parsed is not None, f"Failed to parse JSON from: {result[:500]}"

            if isinstance(parsed, dict):
                quality = parsed.get("quality_score")
                assert quality is not None
                assert 0.0 <= float(quality) <= 1.0
        finally:
            _restore_executor_mock(mock)


# ═══════════════════════════════════════════════════════════════════════════════
# Prompt 模板验证（无需真实 LLM）
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptTemplates:
    """验证 Prompt 模板基本结构。"""

    def test_pi_prompt_is_non_empty(self):
        from deerflow.collaboration.prompts import PI_AGENT_PROMPT

        assert PI_AGENT_PROMPT
        assert len(PI_AGENT_PROMPT) > 100

    def test_critic_prompt_is_non_empty(self):
        from deerflow.collaboration.prompts import CRITIC_AGENT_PROMPT

        assert CRITIC_AGENT_PROMPT
        assert len(CRITIC_AGENT_PROMPT) > 100

    def test_judge_prompt_is_non_empty(self):
        from deerflow.collaboration.prompts import META_JUDGE_PROMPT

        assert META_JUDGE_PROMPT
        assert len(META_JUDGE_PROMPT) > 100

    def test_pi_prompt_mentions_role(self):
        from deerflow.collaboration.prompts import PI_AGENT_PROMPT

        assert "PI" in PI_AGENT_PROMPT or "Principal Investigator" in PI_AGENT_PROMPT

    def test_critic_prompt_mentions_evidence(self):
        from deerflow.collaboration.prompts import CRITIC_AGENT_PROMPT

        assert "evidence" in CRITIC_AGENT_PROMPT.lower()

    def test_judge_prompt_mentions_computation(self):
        from deerflow.collaboration.prompts import META_JUDGE_PROMPT

        prompt_lower = META_JUDGE_PROMPT.lower()
        assert "computation" in prompt_lower or "python" in prompt_lower or "statistical" in prompt_lower
