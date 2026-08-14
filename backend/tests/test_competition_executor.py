"""Focused transport-compatibility tests for the competition executor."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import mock

import competition.executor as executor_module
from competition.executor import (
    _raw_chat_completion,
    _record_token_usage,
    _resolve_provider_context,
    _thinking_control_payload,
    capture_executor_context,
    clear_cancel_checker,
    clear_progress_callback,
    clear_stream_callback,
    execute_agent,
    run_in_executor_context,
    set_cancel_checker,
    set_progress_callback,
    set_stream_callback,
    set_thread_context,
    set_user_context,
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


def test_empty_content_fallback_can_be_disabled(monkeypatch):
    calls = []

    class FakeChatOpenAI:
        def __init__(self, **_kwargs):
            pass

        def invoke(self, _messages):
            return SimpleNamespace(content="", usage_metadata={"total_tokens": 0})

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr("competition.executor._raw_chat_completion", lambda *args, **kwargs: calls.append(1))

    result, tokens = execute_agent(
        "system", "unique empty fallback task", model="model", api_base="https://example.com/v1",
        api_key="sentinel-key", agent_name="", disable_thinking=True, max_retries=0,
        allow_empty_content_fallback=False,
    )

    assert result is None
    assert tokens == 0
    assert calls == []


def test_empty_content_fallback_remains_enabled_by_default(monkeypatch):
    calls = []

    class FakeChatOpenAI:
        def __init__(self, **_kwargs):
            pass

        def invoke(self, _messages):
            return SimpleNamespace(content="", usage_metadata={"total_tokens": 0})

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(
        "competition.executor._raw_chat_completion",
        lambda *args, **kwargs: (calls.append(1) or ("raw fallback", 3)),
    )

    result, tokens = execute_agent(
        "system", "unique default empty fallback task", model="model", api_base="https://example.com/v1",
        api_key="sentinel-key", agent_name="", disable_thinking=True, max_retries=0,
    )

    assert result == "raw fallback"
    assert tokens == 3
    assert calls == [1]


def test_streaming_empty_content_fallback_can_be_disabled(monkeypatch):
    calls = []

    class FakeChatOpenAI:
        def __init__(self, **_kwargs):
            pass

        def stream(self, _messages):
            yield SimpleNamespace(content="", usage_metadata={"total_tokens": 0})

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr("competition.executor._raw_chat_completion", lambda *args, **kwargs: calls.append(1))
    set_stream_callback(lambda *_args: None)
    try:
        result, tokens = execute_agent(
            "system", "unique streaming empty fallback task", model="model", api_base="https://example.com/v1",
            api_key="sentinel-key", agent_name="", disable_thinking=True, max_retries=0,
            allow_empty_content_fallback=False,
        )
    finally:
        clear_stream_callback()

    assert result is None
    assert tokens == 0
    assert calls == []


def test_worker_context_isolated_and_stream_callback_is_not_copied():
    marker = object()

    def cancel():
        return False

    def progress(_payload):
        return None
    set_user_context("worker-user", {"active_group": "worker-group"})
    set_thread_context("worker-thread")
    set_cancel_checker(cancel)
    set_progress_callback(progress)
    set_stream_callback(marker)

    snapshots = [capture_executor_context(), capture_executor_context()]

    def observe():
        return (
            executor_module._cv_user_id.get(),
            executor_module._cv_user_settings.get(),
            executor_module._tl.thread_id,
            executor_module._tl.cancel_checker is cancel,
            executor_module._tl.progress_callback is progress,
            executor_module._tl.stream_callback,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        observed = list(pool.map(lambda snapshot: run_in_executor_context(snapshot, observe), snapshots))

    assert observed == [
        ("worker-user", {"active_group": "worker-group"}, "worker-thread", True, True, None),
        ("worker-user", {"active_group": "worker-group"}, "worker-thread", True, True, None),
    ]
    assert executor_module._tl.stream_callback is marker

    clear_stream_callback()
    clear_progress_callback()
    clear_cancel_checker()
    executor_module.clear_thread_context()
    executor_module.clear_user_context()


def test_concurrent_token_accounting_is_exact():
    before_total = executor_module.get_total_tokens()
    before_agent = executor_module.get_agent_tokens().get("parallel-test", 0)

    def record_many():
        for _ in range(100):
            _record_token_usage("parallel-test", 1)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _index: record_many(), range(8)))

    assert executor_module.get_total_tokens() - before_total == 800
    assert executor_module.get_agent_tokens().get("parallel-test", 0) - before_agent == 800
