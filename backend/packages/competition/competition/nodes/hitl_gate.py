"""HITL Gate node — human-in-the-loop approval with free-text intent parsing.

Per COMPETITION_PLAN.md §5.2: 4-way decision routing + free-text interaction.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# Approval timeout in minutes (§5.2.5)
DEFAULT_APPROVAL_TIMEOUT_MINUTES = 30

# Intent parsing prompt (§5.2.3)
INTENT_PARSE_PROMPT = """你是一个意图解析器。用户在审阅竞品分析报告后给出了反馈。
请判断用户的意图，输出 JSON。

用户反馈: "{comment}"

可选动作:
- "approve": 用户满意，可以发布
- "replan": 用户认为数据不够，需要重新搜索
- "reanalyze": 用户认为分析不对，需要重新分析
- "rewrite": 用户认为报告表达需要修改

输出格式:
{{
    "action": "replan" | "reanalyze" | "rewrite" | "approve",
    "target_focus": ["维度1", "维度2"],
    "reasoning": "一句话"
}}"""


def hitl_gate_node(state: dict) -> dict:
    """Graph node: present review package to user, wait for decision.

    In production, this calls LangGraph interrupt() to pause execution,
    then resumes when HITL decision arrives (frontend or Feishu).

    For testing, processes pre-existing hitl_decision from state or auto-approves.
    """
    decision = state.get("hitl_decision") or {}
    # review_package available via state.get("review_package") when building approval card

    # If user provided free-text comment but no action, parse intent
    comment = decision.get("comment", "").strip()
    if comment and decision.get("action", "approve") == "approve":
        # Only parse if user wrote text without explicitly choosing an action
        parsed = parse_user_intent(comment)
        if parsed:
            decision = parsed

    # Validate / default the decision
    action = decision.get("action", "approve")
    if action not in ("approve", "replan", "reanalyze", "rewrite"):
        action = "approve"

    target_focus = decision.get("target_focus")
    timestamp = decision.get("timestamp") or datetime.now(UTC).isoformat()

    resolved = {
        "action": action,
        "comment": comment or None,
        "target_focus": target_focus,
        "timestamp": timestamp,
    }

    # Check timeout (§5.2.5)
    if _is_timed_out(timestamp):
        logger.warning("HITL approval timed out — auto-approving")
        resolved["action"] = "approve"
        resolved["comment"] = "⚠ 用户未响应，自动批准"

    return {"hitl_decision": resolved}


def parse_user_intent(comment: str) -> dict | None:
    """Parse free-text user feedback into HitlDecision via LLM intent parsing.

    §5.2.3: Lightweight LLM call to extract action + target_focus from natural language.
    In production, calls the LLM with INTENT_PARSE_PROMPT.
    For now, uses keyword-based heuristics as fallback.
    """
    if not comment.strip():
        return None

    comment_lower = comment.lower()

    # Heuristic keyword detection (production: LLM call)
    action = "approve"
    target_focus = None

    # Data-related keywords → replan
    data_keywords = ["数据不够", "缺数据", "数据太少", "来源太少", "数据过时",
                     "need more data", "missing data", "outdated", "stale",
                     "重新搜索", "再搜", "补采", "search again"]
    if any(kw in comment_lower for kw in data_keywords):
        action = "replan"
        target_focus = _extract_dimensions(comment)

    # Analysis-related keywords → reanalyze
    analysis_keywords = ["分析不对", "结论偏了", "不准", "重新分析", "swot",
                         "wrong analysis", "incorrect", "重新对比", "reanalyze"]
    if any(kw in comment_lower for kw in analysis_keywords):
        action = "reanalyze"
        target_focus = _extract_dimensions(comment)

    # Style/format keywords → rewrite
    style_keywords = ["重写", "改写", "换个风格", "视角", "换个角度",
                      "rewrite", "restyle", "perspective", "format",
                      "太笼统", "展开", "详细", "expand", "elaborate"]
    if any(kw in comment_lower for kw in style_keywords):
        action = "rewrite"
        target_focus = _extract_dimensions(comment)

    # Explicit approval
    approve_keywords = ["通过", "没问题", "发布", "可以", "approve", "ok", "好的", "不错"]
    if any(kw in comment_lower for kw in approve_keywords):
        action = "approve"

    return {
        "action": action,
        "comment": comment,
        "target_focus": target_focus,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _extract_dimensions(comment: str) -> list[str] | None:
    """Extract mentioned analysis dimensions from user comment."""
    dimensions = {
        "功能": "功能", "features": "功能",
        "定价": "定价", "价格": "定价", "pricing": "定价", "price": "定价",
        "用户": "用户", "user": "用户", "users": "用户",
        "市场": "市场", "market": "市场", "份额": "市场",
        "技术": "技术", "tech": "技术", "technical": "技术",
        "团队": "团队", "team": "团队",
        "swot": "SWOT", "swot分析": "SWOT",
    }
    found = []
    comment_lower = comment.lower()
    for keyword, dimension in dimensions.items():
        if keyword.lower() in comment_lower and dimension not in found:
            found.append(dimension)
    return found if found else None


def _is_timed_out(timestamp: str, timeout_minutes: int = DEFAULT_APPROVAL_TIMEOUT_MINUTES) -> bool:
    """Check if HITL approval has timed out (§5.2.5)."""
    if not timestamp:
        return False
    try:
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        elapsed = (datetime.now(UTC) - ts).total_seconds() / 60
        return elapsed > timeout_minutes
    except (ValueError, TypeError):
        return False


def build_approval_card(review_package: dict, decision: dict | None = None) -> dict:
    """Build the frontend approval card data from ReviewPackage (§5.2.1).

    Returns a dict that the frontend renders as the HITL approval UI.
    """
    return {
        "type": "approval_card",
        "executive_summary": review_package.get("executive_summary", "")[:500],
        "key_findings": review_package.get("key_findings", [])[:5],
        "data_stats": review_package.get("data_stats", {}),
        "quality_summary": review_package.get("quality_summary", {}),
        "unresolved_issues": review_package.get("unresolved_issues", []),
        "recommendations": review_package.get("recommendations", []),
        "actions": [
            {"id": "approve", "label": "✅ 批准发布", "description": "结果没问题，可以直接用"},
            {"id": "replan", "label": "🔄 重新搜索", "description": "关键维度缺数据、来源太少"},
            {"id": "reanalyze", "label": "📊 重新分析", "description": "数据没问题但结论偏了"},
            {"id": "rewrite", "label": "✏️ 重写报告", "description": "表达风格/视角不合适"},
        ],
        "allow_free_text": True,
        "free_text_placeholder": "输入修改意见（可选），如：SWOT 太笼统，需要具体的 Tab 补全准确率数据",
        "current_decision": decision,
        "timeout_minutes": DEFAULT_APPROVAL_TIMEOUT_MINUTES,
    }
