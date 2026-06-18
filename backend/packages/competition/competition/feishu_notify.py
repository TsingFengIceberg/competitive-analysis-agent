"""Feishu notification: send a DM when analysis completes.

Uses Feishu IM API (app robot + tenant_access_token).
Requires app permission: im:message:send_as_bot.

Env vars:
  FEISHU_NOTIFY_ENABLED   — set to "true" to enable
  FEISHU_APP_ID          — Feishu app ID (cli_xxx)
  FEISHU_APP_SECRET      — Feishu app secret
  FEISHU_NOTIFY_OPEN_ID  — target user's open_id (ou_xxx)
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"


def _get_token(app_id: str, app_secret: str) -> str | None:
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(_TOKEN_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("code") == 0:
                return data.get("tenant_access_token")
    except Exception as e:
        logger.warning("Feishu notify token error: %s", e)
    return None


def _get_feishu_config() -> dict:
    """Read feishu toggles from DB config_group only."""
    from competition.config_mode import is_file_mode

    if is_file_mode():
        return _get_feishu_config_from_file()

    try:
        from competition.executor import _get_active_config_group
        cg = _get_active_config_group()
        toggles = cg.get("feishu_toggles", {}) or {}
        if isinstance(toggles, dict):
            return toggles
    except Exception:
        pass
    return {}


def _get_feishu_credentials() -> dict:
    """Get feishu credentials from DB. Supports multi-provider format."""
    try:
        from competition.executor import _get_user_settings, _get_active_config_group
        us = _get_user_settings() or {}
    except Exception:
        us = {}
    fc = us.get("feishu_config", {}) or {}
    if not isinstance(fc, dict):
        return {"app_id": "", "app_secret": "", "notify_open_id": "", "tenant": ""}

    # Check if new multi-provider format (nested dicts) vs old flat format
    first_val = next(iter(fc.values()), None) if fc else None
    if isinstance(first_val, dict):
        # Multi-provider: {"name": {app_id, ...}}
        try:
            cg = _get_active_config_group()
            provider_name = cg.get("feishu_provider") or ""
            if provider_name and provider_name in fc:
                p = fc[provider_name]
                return {"app_id": p.get("app_id", "") or "", "app_secret": p.get("app_secret", "") or "",
                        "notify_open_id": p.get("notify_open_id", "") or "", "tenant": p.get("tenant", "") or ""}
        except Exception:
            pass
        # Fallback: return first provider
        p = first_val
        return {"app_id": p.get("app_id", "") or "", "app_secret": p.get("app_secret", "") or "",
                "notify_open_id": p.get("notify_open_id", "") or "", "tenant": p.get("tenant", "") or ""}

    # Old flat format
    return {"app_id": fc.get("app_id", "") or "", "app_secret": fc.get("app_secret", "") or "",
            "notify_open_id": fc.get("notify_open_id", "") or "", "tenant": fc.get("tenant", "") or ""}


def is_notify_enabled() -> bool:
    return _get_feishu_config().get("notify_enabled", False) is True


def notify_analysis_complete(thread_id: str, title: str, products: str, doc_url: str = "") -> bool:
    """Send a Feishu DM notifying that an analysis has finished."""
    if not is_notify_enabled():
        return False

    creds = _get_feishu_credentials()
    app_id = creds["app_id"].strip()
    app_secret = creds["app_secret"].strip()
    open_id = creds["notify_open_id"].strip()

    if not (app_id and app_secret and open_id):
        return False

    token = _get_token(app_id, app_secret)
    if not token:
        return False

    text = f"✅ 竞品分析完成\n\n{title}\n产品：{products}"
    if doc_url:
        text += f"\n\n飞书文档：{doc_url}"

    content = json.dumps({"text": text})
    body = json.dumps({
        "receive_id": open_id, "msg_type": "text", "content": content,
    }).encode()
    req = urllib.request.Request(_SEND_URL, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("code") == 0:
                logger.info("Feishu notification sent for thread %s", thread_id)
                return True
            logger.warning("Feishu send error: code=%s msg=%s", data.get("code"), data.get("msg", ""))
    except Exception as e:
        logger.warning("Feishu send failed: %s", e)
    return False
