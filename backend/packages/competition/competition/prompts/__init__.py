"""Prompt loading utility for CI-Agent.

Per CLAUDE.md §5.5: Prompt 存为 Markdown 文件，不在代码中硬编码长文本。
加载方式：pathlib.Path(__file__).parent / "{agent}.md"
"""

from __future__ import annotations

from pathlib import Path

_PROMPT_DIR = Path(__file__).parent

_CACHE: dict[str, str] = {}


def load_prompt(agent: str) -> str:
    """Load a Markdown prompt template for the given agent.

    Args:
        agent: One of 'collector' / 'analyst' / 'reviewer' / 'writer'.

    Returns:
        Prompt template string. Variables like {task_description}
        or {persona_profile} should be filled by the caller via str.format().
    """
    if agent not in _CACHE:
        path = _PROMPT_DIR / f"{agent}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        _CACHE[agent] = path.read_text(encoding="utf-8")
    return _CACHE[agent]


def load_prompt_with_vars(agent: str, **kwargs: str) -> str:
    """Load prompt and inject variables.

    Uses safe substitution: only replaces known {var} placeholders,
    leaves JSON braces and other curly brackets untouched.
    """
    template = load_prompt(agent)
    result = template
    for key, value in kwargs.items():
        placeholder = "{" + key + "}"
        result = result.replace(placeholder, value)
    return result
