"""Analysis SubGraph + Report Composer node implementations.

每个节点使用 SubagentExecutor 执行角色特定的 Agent。
与 Research 节点的区别：Analysis 是顺序流水线，不需要对抗式辩论状态机。
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from deerflow.collaboration.context import current_role
from deerflow.collaboration.prompts import (
    ANALYST_LEAD_PROMPT,
    INTERNAL_REVIEWER_PROMPT,
    REPORT_COMPOSER_PROMPT,
    SYNTHESIZER_PROMPT,
)
from deerflow.collaboration.state import AnalysisSubGraphState, CollaborationState

if TYPE_CHECKING:
    from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict | list | None:
    """从 LLM 输出中提取 JSON 块。"""
    # 1. 直接解析纯 JSON
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # 2. 尝试 ```json ... ``` 代码块
    match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # 3. 尝试裸 JSON 数组（必须在对象之前，因为数组含对象）
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    # 4. 尝试裸 JSON 对象
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _build_analysis_task(state: AnalysisSubGraphState, role: str, specific_instruction: str) -> str:
    """从 AnalysisSubGraphState 构建子代理任务描述。"""
    parts = [f"## Role: {role}", "", specific_instruction]

    brief = state.get("validated_brief")
    if brief:
        parts.append("\n## Validated Research Brief")
        parts.append(json.dumps(brief, ensure_ascii=False, indent=2))

    quality_score = state.get("research_quality_score")
    if quality_score is not None:
        parts.append(f"\nResearch Quality Score: {quality_score}")

    unresolved = state.get("unresolved_issues", [])
    if unresolved:
        parts.append(f"\n## Unresolved Issues ({len(unresolved)} items)")
        parts.append(json.dumps(unresolved, ensure_ascii=False, indent=2))

    plan = state.get("analysis_plan")
    if plan:
        parts.append("\n## Analysis Plan")
        parts.append(json.dumps(plan, ensure_ascii=False, indent=2))

    results = state.get("analysis_results", [])
    if results:
        parts.append(f"\n## Current Analysis Results ({len(results)} items)")
        parts.append(json.dumps(results[-3:], ensure_ascii=False, indent=2))

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# Analyst Lead — 分析调度
# ═══════════════════════════════════════════════════════════════════════════════


def analyst_lead_node(state: AnalysisSubGraphState) -> dict:
    """Analyst Lead — 基于 validated_brief 规划分析维度和 Skill 调度。"""
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import SubagentExecutor
    from deerflow.tools import get_available_tools

    config = SubagentConfig(
        name="analyst_lead",
        description="Analyst Lead — plans analysis dimensions and dispatches Synthesizer",
        system_prompt=ANALYST_LEAD_PROMPT,
        tools=["read_file"],
        model="claude-opus-4-7",
        max_turns=15,
    )

    try:
        tools = get_available_tools()
        instruction = (
            "Plan the analysis work. Based on the validated_brief, determine which dimensions "
            "to analyze, which Skills to use, and what visualizations to generate. "
            "Output as JSON with keys: dimensions (list), skills_to_use (list), "
            "comparison_framework (object with categories/metrics/weights), "
            "visualizations (list), priority_order (list)."
        )
        task = _build_analysis_task(state, "Analyst Lead", instruction)
        executor = SubagentExecutor(config, tools)
        with current_role("analyst_lead"):
            result = executor.execute(task)
        plan = _extract_json(result) or {"raw_output": result}
    except Exception as e:
        logger.exception("analyst_lead_node failed")
        return {"error": f"Analyst Lead: {e}"}

    return {"analysis_plan": plan}


# ═══════════════════════════════════════════════════════════════════════════════
# Synthesizer — 多维分析合成
# ═══════════════════════════════════════════════════════════════════════════════


def synthesizer_node(state: AnalysisSubGraphState) -> dict:
    """Synthesizer — 执行多维度分析，生成对比矩阵、SWOT、趋势和建议。"""
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import SubagentExecutor
    from deerflow.tools import get_available_tools

    config = SubagentConfig(
        name="synthesizer",
        description="Synthesizer — multi-dimensional analysis with Skills, Python, and visualizations",
        system_prompt=SYNTHESIZER_PROMPT,
        tools=["read_file", "python", "write_file"],
        skills=["spec-comparator", "price-elasticity", "market-share-calc", "trend-detector"],
        model="claude-opus-4-7",
        max_turns=50,
    )

    try:
        tools = get_available_tools()
        instruction = (
            "Execute multi-dimensional analysis on the validated research data.\n"
            "1. For each dimension in the analysis plan, run Python computations\n"
            "2. Generate visualizations (matplotlib/plotly) and save to /mnt/user-data/outputs/\n"
            "3. Output a structured result for each dimension as JSON with: dimension, data, insight, "
            "visualization_path, confidence\n"
            "4. Combine all dimensions into a synthesis_report with: comparison_matrix, "
            "swot_analysis, trend_analysis, recommendations\n\n"
            "IMPORTANT: Every number must trace back to validated_brief data points.\n"
            "Generate at least one visualization per major dimension."
        )
        task = _build_analysis_task(state, "Synthesizer", instruction)
        executor = SubagentExecutor(config, tools)
        with current_role("synthesizer"):
            result = executor.execute(task)

        synthesis_data = _extract_json(result) or {}
        dimension_result = {
            "dimension": "combined",
            "data": synthesis_data,
            "insight": synthesis_data.get("executive_summary", ""),
            "confidence": 0.8,
        }
    except Exception as e:
        logger.exception("synthesizer_node failed")
        return {"error": f"Synthesizer: {e}"}

    return {
        "analysis_results": [dimension_result],
        "synthesis_report": synthesis_data.get("synthesis_report", synthesis_data),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Internal Reviewer — 分析质量内审
# ═══════════════════════════════════════════════════════════════════════════════


def internal_reviewer_node(state: AnalysisSubGraphState) -> dict:
    """Internal Reviewer — 检查 synthesis_report 的数据准确性、逻辑一致性和可视化完整性。"""
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import SubagentExecutor
    from deerflow.tools import get_available_tools

    config = SubagentConfig(
        name="internal_reviewer",
        description="Internal Reviewer — quality assurance on analysis output",
        system_prompt=INTERNAL_REVIEWER_PROMPT,
        tools=["read_file", "python"],
        model="inherit",
        max_turns=15,
    )

    try:
        tools = get_available_tools()
        instruction = (
            "Review the synthesis_report for quality.\n"
            "Check: data accuracy (claims trace to sources?), logical consistency "
            "(conclusions follow from data?), visualization completeness (all expected charts present?), "
            "recommendation quality (specific, measurable, actionable?).\n"
            "Output as JSON with keys: passed (bool), issues (list), data_trace_check "
            "({total_claims, claims_with_source_trace, trace_rate}), "
            "visualization_check ({expected_count, generated_count, all_present}), "
            "recommendation_quality (strong|adequate|weak), suggestions (list).\n\n"
            "Only block (passed=false) for factual errors or missing mandatory sections."
        )
        task = _build_analysis_task(state, "Internal Reviewer", instruction)
        executor = SubagentExecutor(config, tools)
        with current_role("internal_reviewer"):
            result = executor.execute(task)

        review_data = _extract_json(result) or {}
        passed = review_data.get("passed", True)
    except Exception as e:
        logger.exception("internal_reviewer_node failed")
        return {"error": f"Internal Reviewer: {e}"}

    return {
        "internal_review_passed": passed,
        "review_feedback": json.dumps(review_data, ensure_ascii=False),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Report Composer — 最终报告生成（Parent Graph 节点）
# ═══════════════════════════════════════════════════════════════════════════════


def report_composer_node(state: CollaborationState) -> dict:
    """Report Composer — 将 synthesis_report 转换为 Markdown 报告。"""
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import SubagentExecutor
    from deerflow.tools import get_available_tools

    config = SubagentConfig(
        name="report_composer",
        description="Report Composer — generates final Markdown analysis report",
        system_prompt=REPORT_COMPOSER_PROMPT,
        tools=["write_file", "python", "bash", "read_file"],
        model="inherit",
        max_turns=40,
    )

    try:
        tools = get_available_tools()
        instruction = (
            "Generate the final analysis report in Markdown format.\n"
            "Write it to /mnt/user-data/outputs/analysis_report.md\n"
            "Structure: Executive Summary → Product Comparison → Market Position → "
            "SWOT Analysis → Trends & Outlook → Recommendations → Appendix.\n"
            "Use tables for comparisons, embed generated visualizations, "
            "keep executive summary under 200 words.\n"
            "After writing, use present_files to make it visible to the user."
        )
        task = (
            f"## Role: Report Composer\n\n{instruction}\n\n"
            f"## Validated Brief\n{json.dumps(state.get('validated_brief', {}), ensure_ascii=False, indent=2)}\n\n"
            f"## Synthesis Report\n{json.dumps(state.get('synthesis_report', {}), ensure_ascii=False, indent=2)}"
        )
        executor = SubagentExecutor(config, tools)
        with current_role("report_composer"):
            result = executor.execute(task)
    except Exception as e:
        logger.exception("report_composer_node failed")
        return {"collaboration_error": f"Report Composer: {e}"}

    return {}  # 报告已写入文件，状态无需更新
