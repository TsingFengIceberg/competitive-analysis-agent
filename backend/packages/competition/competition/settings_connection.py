"""Explicit, bounded connection checks for saved per-user providers."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

TIMEOUT_SECONDS = 8


class ConnectionCheckError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _request(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, token: str = "") -> None:
    if not url.startswith(("http://", "https://")):
        raise ConnectionCheckError("invalid_base", "Provider 地址必须使用 HTTP(S)。")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if not 200 <= response.status < 300:
                raise ConnectionCheckError("provider_error", f"Provider 返回 HTTP {response.status}。")
            response.read(4096)
    except urllib.error.HTTPError as exc:
        raise ConnectionCheckError("provider_error", f"Provider 返回 HTTP {exc.code}。") from None
    except urllib.error.URLError:
        raise ConnectionCheckError("network_error", "无法连接到 Provider。") from None
    except TimeoutError:
        raise ConnectionCheckError("timeout", "连接测试超过 8 秒。") from None


def check_saved_provider(kind: str, name: str, settings: dict) -> None:
    keys = settings.get("provider_keys", {}) or {}
    bases = settings.get("provider_bases", {}) or {}
    if kind == "llm":
        key = str(keys.get(name, ""))
        base = str(bases.get(name, "")).rstrip("/")
        if not base or not key:
            raise ConnectionCheckError("missing_config", "该 LLM Provider 尚未配置地址或密钥。")
        _request(f"{base}/models", token=key)
        return
    if kind == "tavily":
        key = str(keys.get(f"search:tavily:{name}", ""))
        if not key:
            raise ConnectionCheckError("missing_config", "该 Tavily Provider 尚未配置密钥。")
        _request("https://api.tavily.com/search", method="POST", payload={"api_key": key, "query": "connection check", "max_results": 1})
        return
    if kind == "jina":
        key = str(keys.get(f"search:jina:{name}", ""))
        if not key:
            raise ConnectionCheckError("missing_config", "该 Jina Provider 尚未配置密钥。")
        _request("https://r.jina.ai/http://example.com", token=key)
        return
    if kind == "feishu":
        config = (settings.get("feishu_config", {}) or {}).get(name, {})
        app_id = str(config.get("app_id", ""))
        app_secret = str(config.get("app_secret", ""))
        if not app_id or not app_secret:
            raise ConnectionCheckError("missing_config", "该飞书 Provider 尚未配置 App ID 或 Secret。")
        _request("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", method="POST", payload={"app_id": app_id, "app_secret": app_secret})
        return
    raise ConnectionCheckError("unsupported_kind", "不支持的 Provider 类型。")


def run_connection_check(kind: str, name: str, settings: dict) -> dict[str, Any]:
    started = time.monotonic()
    check_saved_provider(kind, name, settings)
    return {"ok": True, "kind": kind, "name": name, "latency_ms": round((time.monotonic() - started) * 1000), "message": "连接成功。"}
