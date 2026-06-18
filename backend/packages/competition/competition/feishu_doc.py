"""Feishu document export: create a Feishu Docx from a Markdown report.

Uses the Feishu Docx API (block-based).
Requires app permission: docx:document.

Env vars:
  FEISHU_APP_ID               — Feishu app ID
  FEISHU_APP_SECRET           — Feishu app secret
  FEISHU_DOC_AUTO_EXPORT      — if "true", auto-export on completion
  FEISHU_DOC_MANUAL_EXPORT    — if "true", manual export button is enabled
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_CREATE_DOC_URL = "https://open.feishu.cn/open-apis/docx/v1/documents"
_BLOCKS_URL = "https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children"

BT_TEXT = 2
BT_HEADING1 = 3
BT_HEADING2 = 4
# Bullet lists are rendered as text blocks with • prefix
BT_DIVIDER = 22


def _get_token(app_id: str, app_secret: str) -> str | None:
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(_TOKEN_URL, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("code") == 0:
                return data.get("tenant_access_token")
    except Exception as e:
        logger.warning("Feishu doc token error: %s", e)
    return None


def _post_json(url: str, body: dict, token: str) -> dict | None:
    data = json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result
    except Exception as e:
        logger.warning("Feishu doc request failed: %s", e)
    return None


def _write_block(url: str, block_type: int, content: str, token: str) -> bool:
    """Write a single text-like block to the document."""
    key = {BT_TEXT: "text", BT_HEADING1: "heading1", BT_HEADING2: "heading2",
           BT_DIVIDER: "divider"}.get(block_type, "text")
    if block_type == BT_DIVIDER:
        child = {"block_type": BT_DIVIDER, "divider": {}}
    else:
        child = {"block_type": block_type, key: {"elements": [{"text_run": {"content": content}}]}}
    result = _post_json(url, {"children": [child], "index": -1}, token)
    return result is not None and result.get("code") == 0


def _markdown_to_blocks(md: str) -> list[tuple[int, str]]:
    """Convert Markdown to a list of (block_type, content) tuples."""
    blocks: list[tuple[int, str]] = []
    lines = md.split("\n")
    i = 0
    in_table = False

    while i < len(lines):
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        # Heading
        m = re.match(r"^(#{1,2})\s+(.+)", line)
        if m:
            level = len(m.group(1))
            bt = BT_HEADING1 if level == 1 else BT_HEADING2
            blocks.append((bt, m.group(2).strip()))
            i += 1
            continue

        # Divider
        if re.match(r"^[-*_]{3,}$", line.strip()):
            blocks.append((BT_DIVIDER, ""))
            i += 1
            continue

        # Bullet
        if re.match(r"^[-*+]\s+", line):
            blocks.append((BT_TEXT, "• " + re.sub(r"^[-*+]\s+", "", line).strip()))
            i += 1
            continue

        # Table: skip separator row, format data rows as text
        if "|" in line and re.match(r"^\|.+\|$", line.strip()):
            # Skip table header and separator, output rows as bullet-like text
            i += 1  # skip header
            if i < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i].strip()):
                i += 1  # skip separator
            while i < len(lines) and "|" in lines[i]:
                cells = [c.strip() for c in lines[i].split("|")[1:-1]]
                blocks.append((BT_TEXT, " · ".join(cells)))
                i += 1
            continue

        # Regular text
        blocks.append((BT_TEXT, line.strip()))
        i += 1

    return blocks


def export_report_to_doc(title: str, markdown: str) -> str | None:
    """Create a Feishu Doc and populate it from a Markdown report."""
    creds = _get_feishu_credentials()
    app_id = creds["app_id"].strip()
    app_secret = creds["app_secret"].strip()

    if not (app_id and app_secret):
        return None

    token = _get_token(app_id, app_secret)
    if not token:
        return None

    # 1. Create document
    create_resp = _post_json(_CREATE_DOC_URL, {"title": title}, token)
    if not create_resp or create_resp.get("code") != 0:
        return None
    doc_id = create_resp.get("data", {}).get("document", {}).get("document_id")
    if not doc_id:
        return None

    # 2. Transfer ownership to user + share
    open_id = creds["notify_open_id"].strip()
    if open_id:
        # Share with full access first
        _post_json(
            f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_id}/members?type=docx",
            {"member_type": "openid", "member_id": open_id, "perm": "full_access"}, token)
        # Transfer ownership from app to user
        _post_json(
            f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_id}/members/transfer_owner?type=docx",
            {"member_type": "openid", "member_id": open_id}, token)

    # 3. Write blocks
    blocks = _markdown_to_blocks(markdown)
    url = _BLOCKS_URL.format(doc_id=doc_id)
    count = 0
    for bt, content in blocks:
        if _write_block(url, bt, content, token):
            count += 1
        else:
            logger.warning("Feishu doc: block write failed type=%s", bt)

    logger.info("Feishu doc: created %s (%d/%d blocks)", doc_id, count, len(blocks))
    tenant = creds["tenant"].strip()
    return f"https://{tenant}.feishu.cn/docx/{doc_id}"


def _get_feishu_config() -> dict:
    """Read feishu toggles from DB or config.yaml."""
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
    """Get feishu credentials from DB or env."""
    from competition.config_mode import is_file_mode
    if is_file_mode():
        return {"app_id": os.environ.get("FEISHU_APP_ID", ""),
                "app_secret": os.environ.get("FEISHU_APP_SECRET", ""),
                "notify_open_id": os.environ.get("FEISHU_NOTIFY_OPEN_ID", ""),
                "tenant": os.environ.get("FEISHU_TENANT", "")}
    try:
        from competition.executor import _get_user_settings, _get_active_config_group
        us = _get_user_settings() or {}
    except Exception:
        us = {}
    fc = us.get("feishu_config", {}) or {}
    if not isinstance(fc, dict):
        return {"app_id": "", "app_secret": "", "notify_open_id": "", "tenant": ""}
    first_val = next(iter(fc.values()), None) if fc else None
    if isinstance(first_val, dict):
        try:
            cg = _get_active_config_group()
            provider_name = cg.get("feishu_provider") or ""
            if provider_name and provider_name in fc:
                p = fc[provider_name]
                return {"app_id": p.get("app_id", "") or "", "app_secret": p.get("app_secret", "") or "",
                        "notify_open_id": p.get("notify_open_id", "") or "", "tenant": p.get("tenant", "") or ""}
        except Exception:
            pass
        p = first_val
        return {"app_id": p.get("app_id", "") or "", "app_secret": p.get("app_secret", "") or "",
                "notify_open_id": p.get("notify_open_id", "") or "", "tenant": p.get("tenant", "") or ""}
    return {"app_id": fc.get("app_id", "") or "", "app_secret": fc.get("app_secret", "") or "",
            "notify_open_id": fc.get("notify_open_id", "") or "", "tenant": fc.get("tenant", "") or ""}


def _get_feishu_config_from_file() -> dict:
    """Read feishu from config.yaml (file mode)."""
    try:
        import yaml
        from pathlib import Path
        for p in (Path("config.yaml"), Path("backend/config.yaml"),
                  Path(__file__).parent.parent.parent.parent.parent / "config.yaml",
                  Path(__file__).parent.parent.parent.parent.parent.parent / "config.yaml"):
            if p.exists():
                cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                comp = cfg.get("competition") or {}
                active = comp.get("active_group") or ""
                groups = comp.get("groups") or {}
                group_cfg = groups.get(active, {}) if active and groups else comp
                return group_cfg.get("feishu") or comp.get("feishu") or {}
    except Exception:
        pass
    return {}


def is_doc_export_enabled() -> bool:
    return _get_feishu_config().get("doc_auto_export", False) is True


def is_manual_export_enabled() -> bool:
    return _get_feishu_config().get("doc_manual_export", False) is True
