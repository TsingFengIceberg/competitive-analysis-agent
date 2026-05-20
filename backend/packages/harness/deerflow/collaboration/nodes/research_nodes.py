"""Research SubGraph node implementations.

每个节点使用 SubagentExecutor 执行角色特定的 Agent。
DeerFlow-First: 不直接调用 LLM API，全部通过 SubagentExecutor。
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from langgraph.types import Command, Send

from deerflow.collaboration.context import current_role
from deerflow.collaboration.protocols.debate import MAX_DEBATE_ROUNDS, DebateState, create_debate_state
from deerflow.collaboration.protocols.messages import Challenge, Rebuttal, Ruling, Severity
from deerflow.collaboration.prompts import (
    CRITIC_AGENT_PROMPT,
    DATA_SCOUT_PROMPT,
    META_JUDGE_PROMPT,
    PI_AGENT_PROMPT,
)
from deerflow.collaboration.state import ResearchSubGraphState

if TYPE_CHECKING:
    from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


def _extract_json(text: str, key: str | None = None) -> dict | list | None:
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


def _build_task_description(state: ResearchSubGraphState, role: str, specific_instruction: str) -> str:
    """从当前 State 构建子代理任务描述。"""
    parts = [f"## Role: {role}", "", specific_instruction]

    # 包含当前阶段的相关 State 数据
    scout_results = state.get("scout_results", [])
    if scout_results:
        parts.append(f"\n## Scout Results ({len(scout_results)} items)")
        for i, sr in enumerate(scout_results[-5:]):  # 最近 5 条，避免超 token
            parts.append(f"### Result {i + 1}")
            parts.append(json.dumps(sr, ensure_ascii=False, indent=2))

    challenges = state.get("challenges", [])
    if challenges:
        parts.append(f"\n## Existing Challenges ({len(challenges)} items)")
        for ch in challenges[-5:]:
            parts.append(json.dumps(ch, ensure_ascii=False, indent=2))

    rebuttals = state.get("rebuttals", [])
    if rebuttals:
        parts.append(f"\n## Rebuttals ({len(rebuttals)} items)")
        for rb in rebuttals[-5:]:
            parts.append(json.dumps(rb, ensure_ascii=False, indent=2))

    ruling = state.get("ruling")
    if ruling:
        parts.append("\n## Meta-Judge Ruling")
        parts.append(json.dumps(ruling, ensure_ascii=False, indent=2))

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# PI Agent — 规划 + 分发 Scouts
# ═══════════════════════════════════════════════════════════════════════════════


def pi_agent_node(state: ResearchSubGraphState) -> dict:
    """PI Agent — 规划研究任务并分发到 Scouts。

    通过 SubagentExecutor 运行 PI 角色，解析 JSON 输出获取研究计划。
    """
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import SubagentExecutor
    from deerflow.tools import get_available_tools

    # 只读工具：PI 负责规划，不直接执行采集
    config = SubagentConfig(
        name="pi_agent",
        description="Research PI — plans investigation and dispatches Data Scouts",
        system_prompt=PI_AGENT_PROMPT,
        tools=["read_file"],
        model="inherit",
        max_turns=15,
    )

    try:
        tools = get_available_tools()
        executor = SubagentExecutor(config, tools)
        task = _build_task_description(
            state,
            "PI Agent (Principal Investigator)",
            "Plan the research investigation. Based on the user's request and any existing data, "
            "create a structured research plan with sub-tasks, target sources, and assign Scouts. "
            "Output your plan as a JSON object with keys: 'topic', 'sub_tasks' (list of {id, query, "
            "target_sources, method}), 'num_scouts' (int, 2-4).",
        )
        with current_role("pi_agent"):
            result = executor.execute(task)
        plan = _extract_json(result) or {"raw_output": result}
    except Exception as e:
        logger.exception("pi_agent_node failed")
        return {"error": f"PI Agent: {e}"}

    return {"research_plan": plan}


# ═══════════════════════════════════════════════════════════════════════════════
# PI Dispatch — Send API Fan-out 到 Data Scouts
# ═══════════════════════════════════════════════════════════════════════════════


def pi_dispatch_node(state: ResearchSubGraphState) -> Command | dict:
    """PI Dispatch — 读取 research_plan，通过 Send API 并行分发 Scout 任务。

    LangGraph Send API 语义：
    - Command(goto=[Send(...)]) 将多个 Send 目标并行调度
    - 每个 Send payload 合并到目标节点的 state 副本中
    - 所有目标完成后，图沿 pi_dispatch → critic_agent 继续
    """
    plan = state.get("research_plan", {})
    if not isinstance(plan, dict):
        logger.warning("pi_dispatch_node: research_plan is not a dict, skipping fan-out")
        return {}

    sub_tasks = plan.get("sub_tasks", [])
    if not sub_tasks:
        logger.warning("pi_dispatch_node: no sub_tasks in research_plan, skipping fan-out")
        return {}

    sends = [Send("data_scout", {"scout_task": t}) for t in sub_tasks]
    logger.info("pi_dispatch_node: dispatching %d scouts", len(sends))
    return Command(goto=sends)


# ═══════════════════════════════════════════════════════════════════════════════
# Data Scout — 并行采集 + 回应 Critic
# ═══════════════════════════════════════════════════════════════════════════════


def data_scout_node(state: ResearchSubGraphState) -> dict:
    """Data Scout — 采集数据或回应 Critic 质疑。

    判断是首次采集还是定向补采（rebuttal）。
    """
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import SubagentExecutor
    from deerflow.tools import get_available_tools

    config = SubagentConfig(
        name="data_scout",
        description="Data Scout — collects data from web and files, responds to Critic challenges",
        system_prompt=DATA_SCOUT_PROMPT,
        tools=["web_search", "web_fetch", "python", "write_file", "read_file"],
        skills=["data-normalizer", "sentiment-analyzer"],
        model="inherit",
        max_turns=30,
        timeout_seconds=600,
    )

    # 判断模式
    challenges = state.get("challenges", [])
    rebuttals = state.get("rebuttals", [])
    rebutted_ids = {r.get("challenge_id") for r in rebuttals if isinstance(r, dict)}
    pending_challenges = [c for c in challenges if isinstance(c, dict) and c.get("challenge_id") not in rebutted_ids]

    try:
        tools = get_available_tools()

        if pending_challenges:
            # 定向补采模式
            challenge = pending_challenges[0]
            instruction = (
                f"You are responding to a Critic challenge.\n\n"
                f"Challenge ID: {challenge.get('challenge_id')}\n"
                f"Claim: {challenge.get('claim')}\n"
                f"Suggested Remedy: {challenge.get('suggested_remedy')}\n\n"
                f"Collect new data to address this challenge. Output as JSON with keys: "
                f"'challenge_id', 'new_data' (list), 'addresses_concern' (bool), "
                f"'note' (string), 'methods' (list of tool names used)."
            )
            task = _build_task_description(state, "Data Scout (Rebuttal Mode)", instruction)
            executor = SubagentExecutor(config, tools)
            with current_role("data_scout"):
                result = executor.execute(task)
            rebuttal_data = _extract_json(result) or {"raw_output": result}

            return {
                "rebuttals": [rebuttal_data],
                "scout_results": [rebuttal_data.get("new_data")] if rebuttal_data.get("new_data") else [],
            }
        else:
            # 首次采集模式 — 优先使用 Send API 传入的 scout_task
            scout_task = state.get("scout_task")
            if scout_task:
                instruction = (
                    f"Assigned Task: {json.dumps(scout_task, ensure_ascii=False)}\n\n"
                    f"Execute this specific sub-task. Collect data from the specified target sources "
                    f"using the recommended methods. Output as JSON with keys: "
                    f"'source', 'content', 'data_points' (list of {{label, value, confidence}}), "
                    f"'methods' (list of tool names used), 'task_id'."
                )
            else:
                plan = state.get("research_plan", {})
                instruction = (
                    f"Research Plan: {json.dumps(plan, ensure_ascii=False)}\n\n"
                    f"Execute your assigned sub-task. Collect data and output as JSON with keys: "
                    f"'source', 'content', 'data_points' (list of {{label, value, confidence}}), "
                    f"'methods' (list of tool names used)."
                )
            task = _build_task_description(state, "Data Scout (Collection Mode)", instruction)
            executor = SubagentExecutor(config, tools)
            with current_role("data_scout"):
                result = executor.execute(task)
            scout_data = _extract_json(result) or {"raw_output": result}

            return {"scout_results": [scout_data]}
    except Exception as e:
        logger.exception("data_scout_node failed")
        return {"error": f"Data Scout: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# Critic Agent — 对抗式质疑
# ═══════════════════════════════════════════════════════════════════════════════


def critic_agent_node(state: ResearchSubGraphState) -> dict:
    """Critic Agent — 对抗式审查 scout_results，生成 Challenge 列表。"""
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import SubagentExecutor
    from deerflow.tools import get_available_tools

    config = SubagentConfig(
        name="critic_agent",
        description="Critic Agent — adversarial review with evidence-backed challenges",
        system_prompt=CRITIC_AGENT_PROMPT,
        tools=["read_file", "python"],
        model="claude-opus-4-7",
        max_turns=30,
    )

    # 构建 DebateState
    debate_state = DebateState(
        current_round=state.get("debate_round", 0) or 0,
        challenges=[],  # 从 state 重建
        rebuttals=[],   # 从 state 重建
    )

    try:
        tools = get_available_tools()
        scout_results = state.get("scout_results", [])
        debate_round = state.get("debate_round", 0) or 0

        if not scout_results:
            # 首次进入（PI 规划后，尚无数据）：Critic 评审研究计划
            instruction = (
                "No scout data collected yet. Review the research plan for adequacy. "
                "Output a JSON list of challenges about what data to collect or verify. "
                "Keep challenges focused on data gaps, source selection, and methodology. "
                "If the plan is sufficient, output an empty list [].\n\n"
                "Each challenge must have: challenge_id, claim, evidence (list), "
                "severity (critical/major/minor), suggested_remedy, target_scout_index (optional)."
            )
        else:
            instruction = (
                f"You are reviewing {len(scout_results)} scout results (debate round {debate_round + 1}).\n"
                f"Review each data point for: source conflicts, methodological gaps, timeliness, "
                f"statistical outliers.\n\n"
                f"Output a JSON list of challenges. Each challenge must have: "
                f"challenge_id, claim, evidence (list), severity (critical/major/minor), "
                f"suggested_remedy, target_scout_index (optional).\n"
                f"If no issues found, output an empty list []."
            )
        task = _build_task_description(state, "Critic Agent", instruction)
        executor = SubagentExecutor(config, tools)
        with current_role("critic_agent"):
            result = executor.execute(task)

        challenges_data = _extract_json(result)
        if isinstance(challenges_data, list):
            challenges = challenges_data
        elif isinstance(challenges_data, dict) and "challenges" in challenges_data:
            challenges = challenges_data["challenges"]
        else:
            challenges = []

        # 推进辩论状态
        if challenges:
            debate_state.advance_to_critique([])
    except Exception as e:
        logger.exception("critic_agent_node failed")
        return {"error": f"Critic Agent: {e}"}

    # Memory: 记录质疑涉及的来源
    src_mem_update: dict = {}
    if challenges:
        try:
            from deerflow.collaboration.memory import SourceCredibilityMemory

            src_mem = SourceCredibilityMemory.from_state(state.get("source_credibility_memory"))
            src_mem.apply_challenges(challenges)
            src_mem_update = {"source_credibility_memory": src_mem.to_dict()}
        except Exception as e:
            logger.debug("SourceCredibilityMemory update skipped: %s", e)

    return {
        "challenges": challenges,
        "debate_round": debate_state.current_round,
        **src_mem_update,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Meta-Judge — 独立裁决
# ═══════════════════════════════════════════════════════════════════════════════


def meta_judge_node(state: ResearchSubGraphState) -> dict:
    """Meta-Judge — 独立裁决，基于计算而非多数意见。"""
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import SubagentExecutor
    from deerflow.tools import get_available_tools

    config = SubagentConfig(
        name="meta_judge",
        description="Meta-Judge — independent computation-backed adjudication",
        system_prompt=META_JUDGE_PROMPT,
        tools=["read_file", "python"],
        model="claude-opus-4-7",
        max_turns=25,
    )

    try:
        tools = get_available_tools()
        instruction = (
            "You are adjudicating challenges against scout results.\n"
            "1. Run Python statistical tests on the data conflicts (scipy.stats)\n"
            "2. Cross-validate sources\n"
            "3. Compute quality_score based on: data coverage, cross-validation rate, conflict rate\n"
            "4. Issue a Ruling as JSON with keys: ruling_id, resolved (list), "
            "unresolved (list of {challenge_id, issue, reason}), dismissed (list), "
            "quality_score (float 0.0-1.0), computation_summary (string)\n\n"
            "CRITICAL: Run at least one Python computation before issuing your ruling.\n"
            "Your quality_score must be reproducible from the computation_summary."
        )
        task = _build_task_description(state, "Meta-Judge", instruction)
        executor = SubagentExecutor(config, tools)
        with current_role("meta_judge"):
            result = executor.execute(task)

        ruling_data = _extract_json(result) or {}
        ruling = Ruling(
            ruling_id=ruling_data.get("ruling_id", "rul-unknown"),
            resolved=ruling_data.get("resolved", []),
            unresolved=ruling_data.get("unresolved", []),
            dismissed=ruling_data.get("dismissed", []),
            quality_score=float(ruling_data.get("quality_score", 0.0)),
            computation_summary=ruling_data.get("computation_summary", ""),
        )
    except Exception as e:
        logger.exception("meta_judge_node failed")
        return {"error": f"Meta-Judge: {e}"}

    # Memory: 根据裁决更新来源可信度分数
    src_mem_update: dict = {}
    try:
        from deerflow.collaboration.memory import SourceCredibilityMemory

        src_mem = SourceCredibilityMemory.from_state(state.get("source_credibility_memory"))
        src_mem.apply_ruling(ruling_data, state.get("scout_results", []))
        src_mem_update = {"source_credibility_memory": src_mem.to_dict()}
    except Exception as e:
        logger.debug("SourceCredibilityMemory update skipped: %s", e)

    return {
        "ruling": {
            "ruling_id": ruling.ruling_id,
            "resolved": ruling.resolved,
            "unresolved": ruling.unresolved,
            "dismissed": ruling.dismissed,
            "quality_score": ruling.quality_score,
            "computation_summary": ruling.computation_summary,
        },
        "research_quality_score": ruling.quality_score,
        **src_mem_update,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PI Review — 审核裁决书
# ═══════════════════════════════════════════════════════════════════════════════


def pi_review_node(state: ResearchSubGraphState) -> dict:
    """PI Review — 审核 Meta-Judge 裁决书，生成 validated_brief 或推翻裁决。"""
    from deerflow.subagents.config import SubagentConfig
    from deerflow.subagents.executor import SubagentExecutor
    from deerflow.tools import get_available_tools

    config = SubagentConfig(
        name="pi_review",
        description="PI Review — reviews Meta-Judge ruling and produces validated brief",
        system_prompt=PI_AGENT_PROMPT,
        tools=["read_file"],
        model="claude-opus-4-7",
        max_turns=15,
    )

    try:
        tools = get_available_tools()
        instruction = (
            "Review the Meta-Judge's ruling below. You have two options:\n\n"
            "1. APPROVE: Generate a validated_brief JSON with keys: topic, verified_data_points "
            "(list of {data, source, confidence}), rejected_claims (list of {claim, reason}), "
            "quality_score (float), unresolved (list of strings).\n\n"
            "2. OVERRIDE: Only if you identify a clear logical error in the ruling — not a disagreement "
            "of opinion. Set override_log with {overridden_ruling, reason, timestamp} "
            "and generate your own validated_brief.\n\n"
            "Default to APPROVE. The Meta-Judge's computation-backed verdict should be overturned "
            "only in exceptional circumstances."
        )
        task = _build_task_description(state, "PI Review", instruction)
        executor = SubagentExecutor(config, tools)
        with current_role("pi_review"):
            result = executor.execute(task)

        review_data = _extract_json(result) or {}
        validated_brief = review_data.get("validated_brief") or review_data
        override_log = review_data.get("override_log")
    except Exception as e:
        logger.exception("pi_review_node failed")
        return {"error": f"PI Review: {e}"}

    # Memory: 将验证过的数据点存入产品知识库
    prod_mem_update: dict = {}
    if validated_brief:
        try:
            from deerflow.collaboration.memory import ProductKnowledgeMemory

            prod_mem = ProductKnowledgeMemory.from_state(state.get("product_knowledge_memory"))
            prod_mem.ingest_brief(validated_brief, state.get("research_quality_score", 0.5))
            prod_mem_update = {"product_knowledge_memory": prod_mem.to_dict()}
        except Exception as e:
            logger.debug("ProductKnowledgeMemory update skipped: %s", e)

    state_update: dict = {
        "validated_brief": validated_brief,
        **prod_mem_update,
    }
    if override_log:
        state_update["pi_override_log"] = [override_log]
    return state_update


# ═══════════════════════════════════════════════════════════════════════════════
# Error Handler
# ═══════════════════════════════════════════════════════════════════════════════


def error_handler_node(state: ResearchSubGraphState) -> dict:
    """错误处理 — 记录错误信息，不静默吞掉异常。"""
    error_msg = state.get("error", "Unknown error in Research SubGraph")
    logger.error("Research SubGraph error: %s", error_msg)
    # 错误已记录在 state.error 中，由 state_out 映射到父图
    return {}
