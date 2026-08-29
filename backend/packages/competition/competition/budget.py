"""Optional, deterministic token-budget policy for one competition run.

The policy is deliberately separate from provider pricing. It limits model
output tokens and records why a call was clamped or skipped; callers can still
use the existing complexity and context budgets independently.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BudgetPolicy:
    enabled: bool = False
    total_tokens: int | None = None
    stage_tokens: dict[str, int] | None = None


def resolve_policy(state: dict[str, Any]) -> BudgetPolicy:
    raw = state.get("budget_policy")
    if not isinstance(raw, dict):
        raw = {}
        env_total = os.environ.get("CI_AGENT_TOTAL_TOKEN_BUDGET", "").strip()
        env_stages = os.environ.get("CI_AGENT_STAGE_TOKEN_BUDGETS", "").strip()
        if env_total:
            raw["total_tokens"] = env_total
        if env_stages:
            try:
                parsed = json.loads(env_stages)
                if isinstance(parsed, dict):
                    raw["stage_tokens"] = parsed
            except json.JSONDecodeError:
                pass
    stage_tokens: dict[str, int] = {}
    for stage, value in (raw.get("stage_tokens") or {}).items():
        try:
            stage_tokens[str(stage)] = max(1, int(value))
        except (TypeError, ValueError):
            continue
    try:
        total = int(raw["total_tokens"]) if raw.get("total_tokens") is not None else None
    except (TypeError, ValueError):
        total = None
    total = max(1, total) if total is not None else None
    enabled = bool(raw.get("enabled", total is not None or stage_tokens))
    return BudgetPolicy(enabled=enabled, total_tokens=total, stage_tokens=stage_tokens or None)


def used_tokens(stage_results: list[dict] | None) -> tuple[int, dict[str, int]]:
    total = 0
    by_stage: dict[str, int] = {}
    for result in stage_results or []:
        if not isinstance(result, dict):
            continue
        stage = str(result.get("stage") or "")
        tokens = max(0, int((result.get("token_usage") or {}).get("total_tokens", 0) or 0))
        total += tokens
        if stage:
            by_stage[stage] = by_stage.get(stage, 0) + tokens
    return total, by_stage


def limits_for_stage(state: dict[str, Any], stage: str) -> dict[str, Any]:
    policy = resolve_policy(state)
    used_total, used_by_stage = used_tokens(state.get("stage_results"))
    total_remaining = None if policy.total_tokens is None else max(0, policy.total_tokens - used_total)
    stage_limit = (policy.stage_tokens or {}).get(stage)
    stage_remaining = None if stage_limit is None else max(0, stage_limit - used_by_stage.get(stage, 0))
    effective = [value for value in (total_remaining, stage_remaining) if value is not None]
    return {
        "enabled": policy.enabled,
        "total_limit": policy.total_tokens,
        "stage_limit": stage_limit,
        "used_total": used_total,
        "used_stage": used_by_stage.get(stage, 0),
        "total_remaining": total_remaining,
        "stage_remaining": stage_remaining,
        "effective_remaining": min(effective) if effective else None,
    }


def summarize(state: dict[str, Any], *, stage: str, actual_tokens: int = 0) -> dict[str, Any]:
    limits = limits_for_stage(state, stage)
    limits["actual_stage_tokens"] = max(0, int(actual_tokens or 0))
    limits["exhausted"] = bool(
        limits["enabled"] and limits["effective_remaining"] is not None and limits["effective_remaining"] <= 0
    )
    return limits
