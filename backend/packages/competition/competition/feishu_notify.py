"""Feishu notification: send a DM when analysis completes.

Uses Feishu IM API (app robot + tenant_access_token).
Requires app permission: im:message:send_as_bot.

Env vars:
  FEISHU_APP_ID         — Feishu app ID (cli_xxx)
  FEISHU_APP_SECRET     — Feishu app secret
  FEISHU_NOTIFY_OPEN_ID — target user's open_id (ou_xxx)
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
    """Obtain a tenant_access_token (valid 2h, auto-refreshed each call)."""
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(_TOKEN_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            code = data.get("code", -1)
            if code == 0:
                return data.get("tenant_access_token")
            logger.warning("Feishu token error: code=%s msg=%s", code, data.get("msg", ""))
    except Exception as e:
        logger.warning("Feishu token request failed: %s", e)
    return None


def notify_analysis_complete(thread_id: str, title: str, products: str) -> bool:
    """Send a Feishu DM notifying that an analysis has finished."""
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    open_id = os.environ.get("FEISHU_NOTIFY_OPEN_ID", "").strip()

    if not (app_id and app_secret and open_id):
        return False  # silently skip if not configured

    token = _get_token(app_id, app_secret)
    if not token:
        return False

    text = f"✅ 竞品分析完成\n\n{title}\n产品：{products}"

    content = json.dumps({"text": text})
    body = json.dumps({
        "receive_id": open_id,
        "msg_type": "text",
        "content": content,
    }).encode()

    req = urllib.request.Request(
        _SEND_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            code = data.get("code", -1)
            if code == 0:
                logger.info("Feishu notification sent for thread %s", thread_id)
                return True
            logger.warning("Feishu send error: code=%s msg=%s", code, data.get("msg", ""))
    except Exception as e:
        logger.warning("Feishu send failed: %s", e)
    return False
