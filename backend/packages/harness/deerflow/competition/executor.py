"""Lightweight LLM executor for competition nodes.

Bridges the gap between placeholder stubs and full SubagentExecutor integration.
Uses langchain ChatOpenAI directly with the Doubao model from config.yaml.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# Competition agent model config — all values come from environment variables.
# Set DOUBAO_MODEL, DOUBAO_API_BASE, and DOUBAO_API_KEY before starting the gateway.
DOUBAO_MODEL = os.environ.get("DOUBAO_MODEL", "")
DOUBAO_API_BASE = os.environ.get("DOUBAO_API_BASE", "")
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")

# Global token counter for competition analysis session
_total_tokens_used = 0
_agent_tokens: dict[str, int] = {}


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
) -> tuple[str | None, int]:
    """Execute a single LLM call, returning (content, token_count).

    Handles thinking models transparently: if LangChain returns empty content
    (common with Doubao seed thinking mode), falls back to raw HTTP parsing
    that properly extracts reasoning_content.
    """
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=model,
            base_url=api_base,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=300,
            max_retries=2,
        )

        messages: list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        response = llm.invoke(messages)
        content = _extract_content(response)
        usage = _extract_usage(response)

        # If LangChain dropped the content (thinking model), retry via raw HTTP
        if not content:
            logger.info("LangChain returned empty content — retrying via raw HTTP for %s", agent_name)
            content, usage = _raw_chat_completion(model, api_base, api_key, messages, max_tokens, temperature)

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
) -> tuple[str, int]:
    """Raw HTTP call to OpenAI-compatible chat completions API.

    Used as fallback when LangChain drops content from thinking models.
    Properly extracts both content and reasoning_content from the response.
    """
    import urllib.request

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()

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
    **kwargs,
) -> tuple[dict | list | str | None, int]:
    """Execute LLM call and attempt to parse the output as JSON. Returns (result, token_count)."""
    raw, tokens = execute_agent(system_prompt, task, agent_name=agent_name, **kwargs)
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
