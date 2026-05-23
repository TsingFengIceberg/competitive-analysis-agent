"""Feishu Delivery node (P1) — deliver report to Feishu Doc + Bot notification.

Per COMPETITION_PLAN.md §3.1: Create Feishu document via lark-cli, send Bot notification.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def feishu_delivery_node(state: dict) -> dict:
    """Graph node: create Feishu document and send Bot notification.

    In production: calls lark-cli docs +create → doc_token → Bot push message.
    For now: placeholder that records the intent.
    """
    report_data = state.get("report_data") or {}
    deep_report = state.get("deep_report", "")
    target_products = state.get("target_products", [])

    title = report_data.get("title", f"{' vs '.join(target_products)} 竞品分析")

    # Placeholder: real implementation calls lark-cli
    feishu_url = _create_feishu_doc(title, report_data, deep_report)
    _send_bot_notification(title, feishu_url, state)

    return {"deep_feishu_url": feishu_url}


def _create_feishu_doc(title: str, report_data: dict, html_content: str) -> str:
    """Create Feishu document via lark-cli docs +create --api-version v2.

    Placeholder — returns a mock URL. Real impl calls:
        lark-cli docs +create --api-version v2 --title "{title}"
    """
    logger.info("Creating Feishu doc: %s", title)
    # Placeholder URL
    return f"https://bytedance.larkoffice.com/docs/placeholder-{_short_hash(title)}"


def _send_bot_notification(title: str, doc_url: str, state: dict) -> None:
    """Send Feishu Bot notification with document link.

    Placeholder — real impl calls:
        lark-cli im +messages-send --chat-id {chat_id} --content "{notification}"
    """
    chat_id = state.get("_feishu_chat_id", "unknown")
    logger.info("Sending Feishu Bot notification to %s: %s → %s", chat_id, title, doc_url)


def _short_hash(s: str) -> str:
    import hashlib
    return hashlib.md5(s.encode()).hexdigest()[:8]
