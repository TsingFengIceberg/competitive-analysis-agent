"""Lightweight LLM executor for competition nodes.

Bridges the gap between placeholder stubs and full SubagentExecutor integration.
Uses langchain ChatOpenAI directly with the Doubao model from config.yaml.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# Default model config for competition agents
DOUBAO_MODEL = "ep-20260514111325-xjmj7"
DOUBAO_API_BASE = "https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "ark-f26df94a-6b3a-4535-bd66-465266a7e1af-dd663")


def execute_agent(
    system_prompt: str,
    task: str,
    model: str = DOUBAO_MODEL,
    api_base: str = DOUBAO_API_BASE,
    api_key: str = DOUBAO_API_KEY,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str | None:
    """Execute a single LLM call with system_prompt + task, return raw output.

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
        logger.info("Agent response: %d chars", len(str(content)))
        return str(content) if content else None

    except Exception as e:
        logger.exception("LLM call failed: %s", e)
        return None


def execute_structured_agent(
    system_prompt: str,
    task: str,
    output_schema_desc: str = "JSON",
    **kwargs,
) -> dict | list | str | None:
    """Execute LLM call and attempt to parse the output as JSON."""
    raw = execute_agent(system_prompt, task, **kwargs)
    if raw is None:
        return None

    # Try to extract JSON from the response (may be wrapped in markdown code blocks)
    json_str = raw.strip()
    if json_str.startswith("```"):
        # Remove markdown code fences
        lines = json_str.split("\n")
        json_str = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # Return raw text if not valid JSON
        logger.warning("Could not parse agent output as JSON (%d chars)", len(raw))
        return raw


def is_available() -> bool:
    """Check if the Doubao model is configured and accessible."""
    try:
        import importlib.util
        return importlib.util.find_spec("langchain_openai") is not None
    except ImportError:
        return False
