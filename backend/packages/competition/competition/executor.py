"""Lightweight LLM executor for competition nodes.

Bridges the gap between placeholder stubs and full SubagentExecutor integration.
Uses langchain ChatOpenAI directly with the Doubao model from config.yaml.

Streaming support (§19 SSE): When a stream callback is set via ``set_stream_callback``,
``execute_agent()`` uses ``llm.stream()`` and invokes the callback for each token
chunk, enabling chat-like SSE streaming.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

# Competition agent model config — reads provider info from config.yaml + env.
DOUBAO_API_BASE = os.environ.get("DOUBAO_API_BASE", "")
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")

# Global token counter for competition analysis session
_total_tokens_used = 0
_agent_tokens: dict[str, int] = {}

# Thread-local storage for SSE streaming callback (§19)
# Simpler than contextvars — the entire graph runs on one executor thread,
# so thread-local storage correctly isolates concurrent analyses.
_tl = threading.local()

# ContextVars for user context — must cross thread boundaries because
# search.py spawns its own ThreadPoolExecutor for parallel searches.
# NOTE: ContextVars do NOT propagate through ThreadPoolExecutor on this
# Python build (3.12.3), so we also use a module-level fallback dict.
_cv_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_id", default=None)
_cv_user_settings: contextvars.ContextVar[dict | None] = contextvars.ContextVar("current_user_settings", default=None)

# Module-level fallback for cross-thread access (ContextVar doesn't propagate
# through ThreadPoolExecutor on Python 3.12.3 / asyncio thread pools).
_global_user_id: str | None = None
_global_user_settings: dict | None = None
_global_user_lock = threading.Lock()

# ── Thread context (request tracing) ──


def set_thread_context(thread_id: str) -> None:
    """Set the thread_id for the current analysis context (enables per-thread logging)."""
    _tl.thread_id = thread_id


def clear_thread_context() -> None:
    """Clear the analysis context."""
    _tl.thread_id = None


def set_user_context(user_id: str, user_settings: dict | None = None) -> None:
    """Set current user context for per-user settings override.

    Stores in both ContextVar (for same-thread) and global (for cross-thread
    access from search.py's ThreadPoolExecutor workers).
    """
    _cv_user_id.set(user_id)
    _cv_user_settings.set(user_settings)
    global _global_user_id, _global_user_settings
    with _global_user_lock:
        _global_user_id = user_id
        _global_user_settings = user_settings
    logger.debug("set_user_context: user_id=%s thread=%s", user_id, threading.current_thread().name)


def clear_user_context() -> None:
    """Clear user context."""
    _cv_user_id.set(None)
    _cv_user_settings.set(None)
    global _global_user_id, _global_user_settings
    with _global_user_lock:
        _global_user_id = None
        _global_user_settings = None


def _get_user_settings() -> dict | None:
    """Get current user's settings (lazily loaded from DB if needed).

    Tries ContextVar first (same-thread), then global fallback (cross-thread).
    """
    settings = _cv_user_settings.get()
    user_id = _cv_user_id.get()

    # Fallback to global if ContextVar is empty (cross-thread case)
    if not user_id or user_id == "default":
        global _global_user_id, _global_user_settings
        with _global_user_lock:
            user_id = _global_user_id
            if settings is None:
                settings = _global_user_settings

    if settings is not None:
        return settings

    logger.debug("_get_user_settings: current_user_id=%s thread=%s", user_id, threading.current_thread().name)
    if not user_id or user_id == "default":
        return None
    try:
        from competition.db import get_user_settings as db_get_user_settings
        settings = db_get_user_settings(user_id)
        # Cache in both ContextVar and global
        _cv_user_settings.set(settings)
        with _global_user_lock:
            _global_user_settings = settings
        return settings
    except Exception:
        return None


def _get_active_config_group() -> dict:
    """Get the active config_group from user_settings, or empty dict."""
    us = _get_user_settings()
    if not us:
        return {}
    active = us.get("active_group", "groupA")
    groups = us.get("config_groups")
    if isinstance(groups, list):
        for g in groups:
            if isinstance(g, dict) and g.get("name") == active:
                return g
    return {}


def _thread_prefix() -> str:
    """Return a log prefix like '[comp-abc123] ' if context is set."""
    tid = getattr(_tl, "thread_id", None)
    return f"[{tid[:12]}] " if tid else ""

# ── Reliability Harness (§Torrent2002-inspired) ──


def _get_call_history() -> list[str]:
    """Return the per-thread call-signature history for circuit breaker tracking."""
    hist = getattr(_tl, "call_history", None)
    if hist is None:
        hist = []
        _tl.call_history = hist
    return hist


def _record_agent_call(agent_name: str, task_preview: str) -> None:
    """Append a call signature to the per-thread history."""
    sig = f"{agent_name}:{task_preview[:120]}"
    _get_call_history().append(sig)
    # Keep only the last 10 entries
    if len(_get_call_history()) > 10:
        _get_call_history()[:] = _get_call_history()[-10:]


def _check_circuit_breaker(agent_name: str, task_preview: str) -> str | None:
    """Return an error message if the same call has been made 3+ consecutive times.

    This prevents LLM loops where a node retries an identical task repeatedly,
    burning tokens for no gain.
    """
    history = _get_call_history()
    sig = f"{agent_name}:{task_preview[:120]}"
    # Check last 3 entries
    if len(history) >= 3 and history[-3:] == [sig, sig, sig]:
        return (
            f"Circuit breaker tripped: {agent_name} has made 3 identical calls. "
            f"Task preview: {task_preview[:100]}"
        )
    return None


def _reset_call_history() -> None:
    """Clear call history for a new analysis run."""
    _tl.call_history = []


def reset_reliability_state() -> None:
    """Reset all per-thread reliability state. Call at start of each analysis."""
    _reset_call_history()


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


def _sanitize_stream_chunk(text: str) -> str:
    """Strip partial thinking/reasoning markers from streaming chunks."""
    # Let the THINK sentinel pass through (it's a UI hint, not model output)
    if text == "\x00THINK\x00":
        return text
    import re
    text = re.sub(r"```\s*THINK\s*[\s\S]*?```", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<thinking[\s\S]*?/thinking>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<reasoning[\s\S]*?/reasoning>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bTHINK\b", "", text)
    return text


def _resolve_model(agent_name: str) -> str:
    """Resolve per-agent model from config.yaml."""
    model, _, _ = _resolve_provider(agent_name)
    return model


def _resolve_provider(agent_name: str) -> tuple[str, str, str]:
    """Resolve (model, api_base, api_key) for an agent.

    In DB mode (default): reads from user_settings.config_groups + provider_keys/bases.
    In file mode (CI_AGENT_CONFIG_MODE=file): reads from config.yaml + .env.
    """
    from competition.config_mode import is_file_mode

    if not agent_name:
        return "", "", ""

    # ── File mode: config.yaml + .env ──
    if is_file_mode():
        return _resolve_provider_from_file(agent_name)

    # ── DB mode: user_settings only ──
    try:
        user_settings = _get_user_settings()
        config_group = _get_active_config_group()

        if user_settings and config_group:
            ag = agent_name.lower()
            provider_name = str(
                (config_group.get("agent_configs", {}) or {}).get(ag, {}).get("provider")
                or config_group.get("default_provider") or ""
            )
            if not provider_name:
                return "", "", ""

            user_keys = user_settings.get("provider_keys", {}) or {}
            api_key = (user_keys.get(provider_name) if isinstance(user_keys, dict) else "") or ""
            if not api_key:
                return "", "", ""

            bases = user_settings.get("provider_bases", {}) or {}
            api_base = (bases.get(provider_name) if isinstance(bases, dict) else "") or ""

            model = str(
                (config_group.get("agent_configs", {}) or {}).get(ag, {}).get("model")
                or config_group.get("default_model") or ""
            )

            return model, api_base, api_key
    except Exception:
        pass

    return "", "", ""


def _resolve_provider_from_file(agent_name: str) -> tuple[str, str, str]:
    """Resolve (model, api_base, api_key) from config.yaml + .env (legacy mode)."""
    import os as _os
    default_base = _os.environ.get("DOUBAO_API_BASE", "")
    default_key = _os.environ.get("DOUBAO_API_KEY", "")

    try:
        import yaml
        from pathlib import Path
        for p in (Path("config.yaml"), Path("backend/config.yaml"),
                  Path(__file__).parent.parent.parent.parent.parent / "config.yaml",
                  Path(__file__).parent.parent.parent.parent.parent.parent / "config.yaml"):
            if not p.exists():
                continue
            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            comp = cfg.get("competition") or {}
            active = comp.get("active_group") or ""
            groups = comp.get("groups") or {}
            group_cfg = groups.get(active, {}) if active and groups else comp
            agent_cfg = group_cfg.get(agent_name.lower()) or {}
            provider_name = agent_cfg.get("provider") or group_cfg.get("default_provider") or comp.get("default_provider") or "doubao"
            providers = comp.get("providers") or {}
            prov = providers.get(provider_name) or {}
            key_env = prov.get("api_key_env", "")
            api_key = _os.environ.get(key_env, "") or default_key
            api_base = prov.get("api_base", "") or default_base
            model = agent_cfg.get("model") or group_cfg.get("default_model") or comp.get("default_model") or ""
            if api_key and api_base:
                return str(model), str(api_base), str(api_key)
    except Exception:
        pass
    return "", default_base, default_key


def execute_agent(
    system_prompt: str,
    task: str,
    model: str = "",
    api_base: str = DOUBAO_API_BASE,
    api_key: str = DOUBAO_API_KEY,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    agent_name: str = "",
    disable_thinking: bool = False,
    timeout_seconds: int = 300,
    max_retries: int = 2,
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
        logger.info("%sLLM call cancelled before start for %s", _thread_prefix(), agent_name)
        return (None, 0)

    # Circuit breaker: detect repeated identical calls (prevents LLM loops)
    cb_error = _check_circuit_breaker(agent_name, task[:200])
    if cb_error:
        logger.warning("Circuit breaker: %s", cb_error)
        return (None, 0)

    _record_agent_call(agent_name, task[:200])

    try:
        from langchain_openai import ChatOpenAI

        # ── Per-agent provider resolution (config.yaml + env) ──
        if agent_name:
            cfg_model, cfg_base, cfg_key = _resolve_provider(agent_name)
            if cfg_key:
                model = cfg_model
                api_base = cfg_base
                api_key = cfg_key

            # Per-agent parameter overrides from DB config_group.agent_configs
            cg = _get_active_config_group()
            agent_params = (cg.get("agent_configs", {}) or {}).get(agent_name.lower(), {})
            if isinstance(agent_params, dict):
                if "temperature" in agent_params:
                    temperature = float(agent_params["temperature"])
                if "max_tokens" in agent_params:
                    max_tokens = int(agent_params["max_tokens"])

        llm_kwargs: dict = {
            "model": model,
            "base_url": api_base,
            "api_key": api_key,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout_seconds,
            "max_retries": max_retries,
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
            # Wrap callback to strip thinking tokens before they reach SSE clients
            _raw_cb = cb
            cb = lambda name, text: _raw_cb(name, _sanitize_stream_chunk(text))
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
                content, usage = _raw_chat_completion(model, api_base, api_key, messages, max_tokens, temperature, disable_thinking, timeout_seconds)
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
                content, usage = _raw_chat_completion(model, api_base, api_key, messages, max_tokens, temperature, disable_thinking, timeout_seconds)

        logger.info("%sAgent response: %d chars (%d tokens)", _thread_prefix(), len(str(content)), usage)
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
    Also strips any thinking/reasoning XML tags that the model may output.
    """
    import re

    content = getattr(response, "content", None)
    if content:
        text = str(content)
        # Strip thinking/reasoning XML blocks that leak through from the model
        text = re.sub(r"```\s*THINK\s*[\s\S]*?```", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<thinking[\s\S]*?/thinking>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<reasoning[\s\S]*?/reasoning>", "", text, flags=re.IGNORECASE)
        return text.strip()

    # Check content_blocks (newer LangChain format)
    blocks = getattr(response, "content_blocks", None)
    if blocks:
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                text = str(b.get("text", ""))
                text = re.sub(r"```\s*THINK\s*[\s\S]*?```", "", text, flags=re.IGNORECASE)
                text = re.sub(r"<thinking[\s\S]*?/thinking>", "", text, flags=re.IGNORECASE)
                text = re.sub(r"<reasoning[\s\S]*?/reasoning>", "", text, flags=re.IGNORECASE)
                return text.strip()

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
    timeout_seconds: int = 300,
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
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        data = json.loads(resp.read())

    choice = data["choices"][0]
    msg = choice.get("message", {})

    # Try content first, then reasoning_content
    content = msg.get("content", "") or ""
    if not content:
        content = msg.get("reasoning_content", "") or ""

    usage = data.get("usage", {}).get("total_tokens", 0)
    return (str(content) if content else "", usage)


def _repair_json(text: str) -> str:
    """Attempt to fix common LLM formatting errors in JSON output.

    Doubao and other models sometimes output Chinese punctuation, unquoted keys,
    trailing commas, and other minor deviations from strict JSON.
    """
    import re

    s = text
    # 1. Chinese punctuation → ASCII
    s = s.replace("：", ":")  # Chinese colon ：
    s = s.replace("，", ",")  # Chinese comma ，
    # 2. Remove trailing commas before } or ]
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    # 3. Quote unquoted keys (word at line start after { or , that's followed by :)
    s = re.sub(r'(^|\{|,)\s*\n?\s*([a-zA-Z_一-鿿][a-zA-Z0-9_\-.一-鿿]*)\s*:', r'\1"\2":', s, flags=re.MULTILINE)
    # 4. Single-quoted keys → double-quoted
    s = re.sub(r"'([^']*)'\s*:", r'"\1":', s)
    return s


def execute_structured_agent(
    system_prompt: str,
    task: str,
    output_schema_desc: str = "JSON",
    agent_name: str = "",
    disable_thinking: bool = False,
    timeout_seconds: int = 300,
    max_retries: int = 2,
    **kwargs,
) -> tuple[dict | list | str | None, int]:
    """Execute LLM call and attempt to parse the output as JSON. Returns (result, token_count)."""
    raw, tokens = execute_agent(
        system_prompt,
        task,
        agent_name=agent_name,
        disable_thinking=disable_thinking,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        **kwargs,
    )
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
        # Attempt repair for common LLM formatting errors
        try:
            repaired = _repair_json(json_str)
            if repaired != json_str:
                result = json.loads(repaired)
                logger.info("JSON repair succeeded for %s (%d → %d chars)", agent_name, len(json_str), len(repaired))
                return (result, tokens)
        except (json.JSONDecodeError, Exception):
            pass
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
