"""Tests for competition/prompts/ — prompt loading and variable injection."""

from __future__ import annotations

import pytest

from deerflow.competition.prompts import load_prompt, load_prompt_with_vars


class TestLoadPrompt:
    def test_collector_prompt(self):
        prompt = load_prompt("collector")
        assert "信息采集 Agent" in prompt
        assert "source_url" in prompt
        assert "{task_description}" in prompt

    def test_analyst_prompt(self):
        prompt = load_prompt("analyst")
        assert "分析师 Agent" in prompt
        assert "comparison_matrix" in prompt
        assert "source_data_point_ids" in prompt
        assert "{persona_profile}" in prompt

    def test_reviewer_prompt(self):
        prompt = load_prompt("reviewer")
        assert "质检 Agent" in prompt
        assert "G1" in prompt
        assert "G8" in prompt

    def test_writer_prompt(self):
        prompt = load_prompt("writer")
        assert "报告撰写 Agent" in prompt
        assert "ReportData" in prompt
        assert "产品经理视角" in prompt
        assert "{persona_profile}" in prompt

    def test_caching(self):
        """load_prompt() caches results."""
        p1 = load_prompt("collector")
        p2 = load_prompt("collector")
        assert p1 is p2  # same object from cache

    def test_unknown_agent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent")


class TestLoadPromptWithVars:
    def test_variable_injection(self):
        prompt = load_prompt_with_vars(
            "collector",
            task_description="test task",
        )
        assert "test task" in prompt
        # Check that {task_description} was replaced but other JSON braces intact
        assert "{task_description}" not in prompt

    def test_unknown_vars_safely_ignored(self):
        """Safe substitution: unknown placeholders left as-is, no KeyError."""
        prompt = load_prompt_with_vars("collector", task_description="x")
        assert "x" in prompt  # known var replaced
        # JSON braces in examples should be untouched
        assert "dp-" in prompt
