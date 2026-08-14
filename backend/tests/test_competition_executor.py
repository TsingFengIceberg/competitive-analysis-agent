"""Focused transport-compatibility tests for the competition executor."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

from competition.executor import (
    _raw_chat_completion,
    _resolve_provider_context,
    _thinking_control_payload,
    execute_agent,
)


def test_thinking_control_allowlist_is_conservative():
    assert _thinking_control_payload("deepseek", "https://api.deepseek.com/v1", True) is None
    assert _thinking_control_payload("openai", "https://api.openai.com/v1", True) is None
    assert _thinking_control_payload("custom-provider", "https://provider.example/v1", True) is None
    assert _thinking_control_payload("doubao", "https://provider.example/v1", True) == {
        "thinking": {"type": "disabled"}
    }
    assert _thinking_control_payload("", "https://ark.cn-beijing.volces.com/api/v3", True) == {
        "thinking": {"type": "disabled"}
    }
    assert _thinking_control_payload("doubao", "https://api.deepseek.com/v1", False) is None
    assert _thinking_control_payload("unknown", "https://volces.com.example.invalid", True) is None


def test_provider_context_retains_name_without_changing_tuple_resolution():
    settings = {
        "provider_keys": {"deepseek": "sentinel-key"},
        "provider_bases": {"deepseek": "https://api.deepseek.com/v1"},
    }
    group = {
        "default_provider": "deepseek",
        "default_model": "deepseek-chat",
        "agent_configs": {},
    }
    with mock.patch("competition.executor._get_user_settings", return_value=settings), \
         mock.patch("competition.executor._get_active_config_group", return_value=group):
        context = _resolve_provider_context("BriefBuilder")

    assert context.provider_name == "deepseek"
    assert context.model == "deepseek-chat"
    assert context.api_base.endswith("/v1")
    assert "sentinel-key" not in repr(context)


def test_langchain_constructor_omits_thinking_for_deepseek(monkeypatch):
    captured: dict = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def invoke(self, _messages):
            return SimpleNamespace(content="{}", usage_metadata={"total_tokens": 1})

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    result, tokens = execute_agent(
        "system", "unique deepseek compatibility task", model="deepseek-chat",
        api_base="https://api.deepseek.com/v1", api_key="sentinel-key",
        agent_name="", disable_thinking=True, max_retries=0,
    )

    assert result == "{}"
    assert tokens == 1
    assert "thinking" not in captured
    assert "model_kwargs" not in captured


def test_langchain_constructor_keeps_ark_thinking_control(monkeypatch):
    captured: dict = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def invoke(self, _messages):
            return SimpleNamespace(content="{}", usage_metadata={"total_tokens": 1})

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    execute_agent(
        "system", "unique ark compatibility task", model="ark-model",
        api_base="https://ark.cn-beijing.volces.com/api/v3", api_key="sentinel-key",
        agent_name="", disable_thinking=True, max_retries=0,
    )

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "model_kwargs" not in captured


def test_raw_transport_uses_the_same_capability_decision(monkeypatch):
    requests: list[dict] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 2}}).encode()

    def fake_urlopen(request, timeout):
        requests.append({"body": json.loads(request.data.decode()), "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _raw_chat_completion(
        "deepseek-chat", "https://api.deepseek.com/v1", "sentinel-key", [],
        20, 0.0, True, 7, provider_name="deepseek",
    )
    _raw_chat_completion(
        "ark-model", "https://ark.cn-beijing.volces.com/api/v3", "sentinel-key", [],
        20, 0.0, True, 8, provider_name="doubao",
    )

    assert "thinking" not in requests[0]["body"]
    assert requests[0]["timeout"] == 7
    assert requests[1]["body"]["thinking"] == {"type": "disabled"}
    assert requests[1]["timeout"] == 8
