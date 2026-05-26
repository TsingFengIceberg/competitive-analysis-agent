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
    """Execute a single LLM call with system_prompt + task, return (content, token_count).

    This is a lightweight alternative to SubagentExecutor that works without
    the full DF sandbox runtime. Used for competition demo.
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

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        response = llm.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        # Extract token usage from response metadata
        usage = 0
        meta = getattr(response, "response_metadata", {})
        token_info = meta.get("token_usage", {})
        if token_info:
            usage = token_info.get("total_tokens", 0)
        elif hasattr(response, "usage_metadata"):
            u = response.usage_metadata
            usage = u.get("total_tokens", 0) if u else 0
        logger.info("Agent response: %d chars (%d tokens)", len(str(content)), usage)
        global _total_tokens_used
        _total_tokens_used += usage
        if agent_name:
            _agent_tokens[agent_name] = _agent_tokens.get(agent_name, 0) + usage
        return (str(content) if content else None, usage)

    except Exception as e:
        logger.exception("LLM call failed: %s", e)
        return (None, 0)


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
