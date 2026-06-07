"""Lightweight LLM executor for competition nodes.

Bridges the gap between placeholder stubs and full SubagentExecutor integration.
Uses langchain ChatOpenAI directly with the Doubao model from config.yaml.

Streaming support (§19 SSE): When a stream callback is set via ``set_stream_callback``,
``execute_agent()`` uses ``llm.stream()`` and invokes the callback for each token
chunk, enabling chat-like SSE streaming.
"""

from __future__ import annotations

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

# Competition agent model config — all values come from environment variables.
# Set DOUBAO_MODEL, DOUBAO_API_BASE, and DOUBAO_API_KEY before starting the gateway.
DOUBAO_MODEL = os.environ.get("DOUBAO_MODEL", "")
DOUBAO_API_BASE = os.environ.get("DOUBAO_API_BASE", "")
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")

# Global token counter for competition analysis session
_total_tokens_used = 0
_agent_tokens: dict[str, int] = {}

# Thread-local storage for SSE streaming callback (§19)
# Simpler than contextvars — the entire graph runs on one executor thread,
# so thread-local storage correctly isolates concurrent analyses.
_tl = threading.local()


def set_stream_callback(cb) -> None:
    """Set the SSE stream callback for the current thread."""
    _tl.stream_callback = cb


def clear_stream_callback() -> None:
    """Remove the SSE stream callback."""
    _tl.stream_callback = None


def set_cancel_checker(checker) -> None:
    """Set a cancellation checker for the current thread.

    The checker is a callable that returns True when the analysis should stop.
    Called inside LLM streaming loops for responsive cancellation.
    """
    _tl.cancel_checker = checker


def clear_cancel_checker() -> None:
    """Remove the cancellation checker."""
    _tl.cancel_checker = None


def get_total_tokens() -> int:
    """Return cumulative tokens used across all LLM calls in this process."""
    return _total_tokens_used


def get_agent_tokens() -> dict[str, int]:
    """Return per-agent token breakdown for this process."""
    return dict(_agent_tokens)


def execute_agent(
    system_prompt: str,
    task: str,
    model: str = DOUBAO_MODEL,
    api_base: str = DOUBAO_API_BASE,
    api_key: str = DOUBAO_API_KEY,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    agent_name: str = "",
    disable_thinking: bool = False,
) -> tuple[str | None, int]:
    """Execute a single LLM call, returning (content, token_count).

    Handles thinking models transparently: if LangChain returns empty content
    (common with Doubao seed thinking mode), falls back to raw HTTP parsing
    that properly extracts reasoning_content.

    Set disable_thinking=True to use non-thinking mode (faster, for simple tasks).
    """
    # Check for cancellation before any LLM call
    cancel_checker = getattr(_tl, "cancel_checker", None)
    if cancel_checker and cancel_checker():
        logger.info("LLM call cancelled before start for %s", agent_name)
        return (None, 0)

    try:
        from langchain_openai import ChatOpenAI

        llm_kwargs: dict = {
            "model": model,
            "base_url": api_base,
            "api_key": api_key,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": 300,
            "max_retries": 2,
        }
        if disable_thinking:
            llm_kwargs["model_kwargs"] = {"thinking": {"type": "disabled"}}

        llm = ChatOpenAI(**llm_kwargs)

        messages: list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        # Check for SSE streaming callback (§19)
        cb = getattr(_tl, "stream_callback", None)
        if cb is not None:
            # Emit a thinking indicator immediately so the UI doesn't look frozen.
            # Thinking models (Doubao seed) may spend 30-60s reasoning with zero
            # content chunks — the sentinel tells the SSE layer to show a progress
            # event while the real content is generated.
            if not disable_thinking:
                try:
                    cb(agent_name, "\x00THINK\x00")
                except Exception:
                    pass

            # Streaming mode — yield token chunks to the callback
            full_content: list[str] = []
            total_usage = 0
            last_chunk_usage = 0
            for chunk in llm.stream(messages):
                # Check cancellation flag — allows responsive termination
                if cancel_checker and cancel_checker():
                    logger.info("Streaming cancelled for %s", agent_name)
                    break
                chunk_content = _extract_content(chunk)
                if chunk_content:
                    full_content.append(str(chunk_content))
                    try:
                        cb(agent_name, str(chunk_content))
                    except Exception:
                        pass  # callback failure shouldn't break the LLM call
                # Try to extract usage from every chunk (last chunk often has it)
                chunk_usage = _extract_usage(chunk)
                if chunk_usage:
                    last_chunk_usage = chunk_usage

            content = "".join(full_content)
            # Prefer usage from last chunk, fall back to character-based estimate
            # (Doubao API often doesn't include usage in streaming responses)
            usage = last_chunk_usage if last_chunk_usage > 0 else (len(content) // 4)

            # Fallback: if streaming produced empty content (thinking models may
            # put output in reasoning_content, inaccessible via streaming chunks),
            # retry via raw HTTP which properly extracts reasoning_content.
            if not content:
                logger.info("Streaming returned empty content — retrying via raw HTTP for %s", agent_name)
                content, usage = _raw_chat_completion(model, api_base, api_key, messages, max_tokens, temperature, disable_thinking)
                # Stream the fallback content through the callback so SSE clients
                # receive it (the streaming loop above produced nothing).
                if content and cb is not None:
                    try:
                        cb(agent_name, content)
                    except Exception:
                        pass
        else:
            # Non-streaming mode (original behavior)
            response = llm.invoke(messages)
            content = _extract_content(response)
            usage = _extract_usage(response)

            # If LangChain dropped the content (thinking model), retry via raw HTTP
            if not content:
                logger.info("LangChain returned empty content — retrying via raw HTTP for %s", agent_name)
                content, usage = _raw_chat_completion(model, api_base, api_key, messages, max_tokens, temperature, disable_thinking)

        logger.info("Agent response: %d chars (%d tokens)", len(str(content)), usage)
        global _total_tokens_used
        _total_tokens_used += usage
        if agent_name:
            _agent_tokens[agent_name] = _agent_tokens.get(agent_name, 0) + usage
        return (str(content) if content else None, usage)

    except Exception as e:
        logger.exception("LLM call failed: %s", e)
        return (None, 0)


def _extract_content(response) -> str:
    """Extract text content from a LangChain AIMessage, handling thinking models.

    Some providers (Doubao seed) put output in reasoning_content while
    LangChain's ChatOpenAI strips it. This checks all known locations.
    """
    content = getattr(response, "content", None)
    if content:
        return str(content)

    # Check content_blocks (newer LangChain format)
    blocks = getattr(response, "content_blocks", None)
    if blocks:
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                return str(b.get("text", ""))

    # Check additional_kwargs for reasoning_content or similar
    ak = getattr(response, "additional_kwargs", {}) or {}
    for key in ("reasoning_content", "content", "text", "reasoning"):
        val = ak.get(key)
        if val and isinstance(val, str) and val.strip():
            return val

    return ""


def _extract_usage(response) -> int:
    """Extract token usage from various LangChain response formats."""
    meta = getattr(response, "response_metadata", {}) or {}
    token_info = meta.get("token_usage", {}) or {}
    if token_info:
        return token_info.get("total_tokens", 0)
    if hasattr(response, "usage_metadata"):
        u = response.usage_metadata
        return u.get("total_tokens", 0) if u else 0
    return 0


def _raw_chat_completion(
    model: str, api_base: str, api_key: str,
    messages: list, max_tokens: int, temperature: float,
    disable_thinking: bool = False,
) -> tuple[str, int]:
    """Raw HTTP call to OpenAI-compatible chat completions API.

    Used as fallback when LangChain drops content from thinking models.
    Properly extracts both content and reasoning_content from the response.
    """
    import urllib.request

    payload_dict: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if disable_thinking:
        payload_dict["thinking"] = {"type": "disabled"}

    payload = json.dumps(payload_dict).encode()

    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())

    choice = data["choices"][0]
    msg = choice.get("message", {})

    # Try content first, then reasoning_content
    content = msg.get("content", "") or ""
    if not content:
        content = msg.get("reasoning_content", "") or ""

    usage = data.get("usage", {}).get("total_tokens", 0)
    return (str(content) if content else "", usage)


def execute_structured_agent(
    system_prompt: str,
    task: str,
    output_schema_desc: str = "JSON",
    agent_name: str = "",
    disable_thinking: bool = False,
    **kwargs,
) -> tuple[dict | list | str | None, int]:
    """Execute LLM call and attempt to parse the output as JSON. Returns (result, token_count)."""
    raw, tokens = execute_agent(system_prompt, task, agent_name=agent_name, disable_thinking=disable_thinking, **kwargs)
    if raw is None:
        return (None, tokens)

    # Try to extract JSON from the response (may be wrapped in markdown code blocks)
    json_str = raw.strip()
    if json_str.startswith("```"):
        # Remove markdown code fences
        lines = json_str.split("\n")
        json_str = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        return (json.loads(json_str), tokens)
    except json.JSONDecodeError:
        # Return raw text if not valid JSON
        logger.warning("Could not parse agent output as JSON (%d chars)", len(raw))
        return (raw, tokens)


def is_available() -> bool:
    """Check if the Doubao model is configured and accessible."""
    try:
        import importlib.util
        return importlib.util.find_spec("langchain_openai") is not None
    except ImportError:
        return False
