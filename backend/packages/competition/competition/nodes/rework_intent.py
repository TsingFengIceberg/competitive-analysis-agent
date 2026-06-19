"""Rework Intent Parser — route free-form HITL feedback to a rework action."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Literal, TypedDict

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "rework_intent.md"

ReworkAction = Literal["replan", "reanalyze", "rewrite"]


class ReworkIntent(TypedDict):
    action: ReworkAction
    target_focus: list[str]
    comment: str
    reason: str
    confidence: float


def _load_prompt() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return "You route user report rework feedback to replan, reanalyze, or rewrite. Output strict JSON only."


def _extract_json(raw: str) -> dict | None:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _keywords(text: str) -> list[str]:
    candidates = re.split(r"[，,。；;、\s]+", text)
    seen: set[str] = set()
    result: list[str] = []
    for item in candidates:
        word = item.strip("：:（）()[]【】\"'")
        if len(word) < 2 or word in seen:
            continue
        if any(token in word for token in ("数据", "来源", "指标", "准确率", "市场", "定价", "SWOT", "分析", "风格", "结构", "视角", "证据", "引用")):
            seen.add(word)
            result.append(word[:24])
        if len(result) >= 5:
            break
    return result or [text[:24]] if text else []



def _rule_based_intent(comment: str) -> ReworkIntent:
    text = comment.strip()
    replan_tokens = (
        "重新收集", "再次收集", "重收集", "再收集", "收集信息", "采集信息", "重新采集", "再次采集", "重采集", "再采集",
        "重新搜索", "再次搜索", "重搜索", "再搜索", "搜索信息", "搜集信息", "检索", "查找", "找更多", "补充数据", "补数据",
        "来源", "指标", "具体数字", "定量", "查一下", "找", "证据不足", "引用", "准确率", "市场份额", "DAU", "NPS", "价格",
    )
    reanalyze_tokens = ("重新分析", "再次分析", "重分析", "再分析", "结论偏", "权重", "归类", "机会点", "判断", "分析角度", "推理", "SWOT")
    rewrite_tokens = ("改写", "重写", "更简洁", "风格", "措辞", "标题", "层级", "结构", "投资人", "咨询报告", "不改结论")

    if any(token in text for token in replan_tokens):
        action: ReworkAction = "replan"
        reason = "用户要求新增或补充事实数据/来源，需重新采集。"
        confidence = 0.72
    elif any(token in text for token in reanalyze_tokens):
        action = "reanalyze"
        reason = "用户要求调整分析角度、权重或结论，需重新分析。"
        confidence = 0.68
    elif any(token in text for token in rewrite_tokens):
        action = "rewrite"
        reason = "用户主要要求表达、结构或风格调整。"
        confidence = 0.66
    else:
        action = "reanalyze"
        reason = "用户反馈未明确要求新增数据，默认进入重新分析以更新结论。"
        confidence = 0.5

    return {
        "action": action,
        "target_focus": _keywords(text),
        "comment": text,
        "reason": reason,
        "confidence": confidence,
    }


def _normalize_intent(data: dict, fallback_comment: str) -> ReworkIntent:
    action = str(data.get("action") or "").strip().lower()
    if action not in {"replan", "reanalyze", "rewrite"}:
        return _rule_based_intent(fallback_comment)
    focus_raw = data.get("target_focus") or []
    if isinstance(focus_raw, str):
        focus = [focus_raw]
    elif isinstance(focus_raw, list):
        focus = [str(x).strip() for x in focus_raw if str(x).strip()]
    else:
        focus = []
    comment = str(data.get("comment") or fallback_comment).strip()
    reason = str(data.get("reason") or "基于用户反馈自动判断返工动作").strip()
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.6))))
    except (TypeError, ValueError):
        confidence = 0.6
    return {
        "action": action,  # type: ignore[typeddict-item]
        "target_focus": focus[:5] or _keywords(comment),
        "comment": comment,
        "reason": reason,
        "confidence": confidence,
    }


def parse_rework_intent(state: dict, user_comment: str) -> ReworkIntent:
    """Parse free-form user rework feedback into a concrete HITL action."""
    fallback = _rule_based_intent(user_comment)
    if not user_comment.strip():
        return fallback

    try:
        from competition.executor import execute_agent

        report = state.get("report_data") or {}
        task = json.dumps({
            "original_query": state.get("user_request", ""),
            "target_products": state.get("target_products", []),
            "report_title": report.get("title", "") if isinstance(report, dict) else getattr(report, "title", ""),
            "user_rework_query": user_comment,
        }, ensure_ascii=False)
        raw, _tokens = execute_agent(
            _load_prompt(),
            task,
            temperature=0.0,
            max_tokens=512,
            agent_name="rework_intent",
        )
        if not raw:
            return fallback
        parsed = _extract_json(raw)
        if not parsed:
            logger.warning("Rework intent parser returned non-JSON: %s", raw[:200])
            return fallback
        return _normalize_intent(parsed, user_comment)
    except Exception:
        logger.exception("Rework intent parser failed, using rule fallback")
        return fallback
