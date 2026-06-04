"""Multi-backend real web search toolkit for competition Collector.

Provides direct search + fetch APIs usable without the full SubagentExecutor sandbox.
Backends (ordered by preference):
  1. Tavily  — AI-optimised search + extract (TAVILY_API_KEY)
  2. DDG     — free text search, no API key needed (fallback)

Adaptive context strategy:
  - Model context registry (local JSON cache) → API query fallback → env override → default
  - Budget calculator: model_window * 0.8 - fixed_reserves = available for search
  - Three tiers: large (unlimited), medium (capped), small (two-pass progressive)
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
DOUBAO_API_BASE = os.environ.get("DOUBAO_API_BASE", "")

# ── Model context registry ──

# Built-in registry — covers common models without needing API calls
_BUILTIN_CONTEXT: dict[str, int] = {
    "doubao-seed-2-0-lite": 128_000,
    "doubao-seed-2-0-mini": 128_000,
    "doubao-seed-2-0-pro": 256_000,
    "doubao-seed-2-0": 128_000,
    "doubao-seed-1-8": 128_000,
    "doubao-seed-1-6": 128_000,
    "doubao-seed-1-6-lite": 32_000,
    "doubao-seed-1-6-flash": 32_000,
    "doubao-1-5-lite-32k": 32_000,
    "doubao-1-5-pro-32k": 32_000,
    "doubao-1-5-pro-256k": 256_000,
    "doubao-pro-32k": 32_000,
    "doubao-pro-128k": 128_000,
    "doubao-pro-256k": 256_000,
    "doubao-lite-32k": 32_000,
    "doubao-lite-128k": 128_000,
    "doubao-vision-pro-32k": 32_000,
    "deepseek-chat": 64_000,
    "deepseek-reasoner": 64_000,
    "deepseek-v3": 128_000,
    "deepseek-r1": 128_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-3.5-turbo": 16_000,
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "qwen-max": 32_000,
    "qwen-plus": 131_072,
    "qwen-turbo": 1_000_000,
    "llama-3": 8_000,
    "llama-3.1": 128_000,
    "gemini-1.5-pro": 2_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
    "mistral-large": 128_000,
    "mistral-small": 32_000,
}


def _registry_path() -> Path:
    return Path(__file__).parent.parent.parent.parent.parent / "model_context_registry.json"


def _load_registry() -> dict[str, int]:
    """Load persisted registry from disk, merge with built-in (built-in wins on conflict)."""
    merged = dict(_BUILTIN_CONTEXT)
    path = _registry_path()
    if path.exists():
        try:
            persisted = json.loads(path.read_text())
            if isinstance(persisted, dict):
                for k, v in persisted.items():
                    if k not in merged:
                        merged[k] = v
        except Exception:
            logger.debug("Failed to load model context registry", exc_info=True)
    return merged


def _save_registry_entry(model_key: str, limit: int) -> None:
    """Persist a discovered context limit to disk."""
    path = _registry_path()
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            pass
    existing[model_key] = limit
    try:
        path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    except Exception:
        logger.debug("Failed to save registry entry", exc_info=True)


def _parse_model_name_for_context(model_name: str) -> int | None:
    """Extract context window from model name patterns like '-32k', '-128k', '-256k'."""
    m = re.search(r"(\d+)k", model_name.lower())
    if m:
        return int(m.group(1)) * 1000
    m = re.search(r"(\d+)m", model_name.lower())
    if m:
        return int(m.group(1)) * 1_000_000
    return None


def _query_doubao_models() -> dict[str, int] | None:
    """Query Doubao /v1/models endpoint, parse context from model names.

    Doubao doesn't expose max_context_length as a field, but model names encode it
    (e.g. 'doubao-pro-128k-240515'). Seed-series models are matched against built-in.
    """
    if not DOUBAO_API_BASE or not DOUBAO_API_KEY:
        return None
    try:
        import urllib.request
        url = f"{DOUBAO_API_BASE.rstrip('/')}/models"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {DOUBAO_API_KEY}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        logger.debug("Failed to query Doubao models endpoint", exc_info=True)
        return None

    found: dict[str, int] = {}
    for m in data.get("data", []):
        mid = m.get("id", "")
        limit = _parse_model_name_for_context(mid)
        if limit:
            found[mid] = limit
    return found if found else None


def _query_anthropic_models(api_key: str) -> dict[str, int] | None:
    """Query Anthropic /v1/models endpoint which returns max_input_tokens per model."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None

    found: dict[str, int] = {}
    for m in data.get("data", []):
        mid = m.get("id", "")
        limit = m.get("max_input_tokens") or m.get("context_window")
        if mid and limit:
            found[mid] = limit
    return found if found else None


def _query_deepseek_models(api_key: str, api_base: str | None = None) -> dict[str, int] | None:
    """Query DeepSeek /v1/models endpoint which returns max_context_length per model."""
    base = (api_base or "https://api.deepseek.com").rstrip("/")
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{base}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None

    found: dict[str, int] = {}
    for m in data.get("data", []):
        mid = m.get("id", "")
        limit = m.get("max_context_length")
        if mid and limit:
            found[mid] = limit
    return found if found else None


def _resolve_model_name() -> str:
    """Resolve the real model name from the endpoint via a minimal API call.

    When DOUBAO_MODEL is an endpoint ID (ep-xxx) rather than a model name,
    the chat completions response includes the real model name we can match
    against the registry. This call uses 1 token and is cached per process.
    """
    model = os.environ.get("DOUBAO_MODEL", "")
    if not model or not model.startswith("ep-"):
        return model  # not an endpoint ID, no resolution needed

    if not DOUBAO_API_BASE or not DOUBAO_API_KEY:
        return model

    try:
        import urllib.request
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 2,
        }).encode()
        req = urllib.request.Request(
            f"{DOUBAO_API_BASE.rstrip('/')}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DOUBAO_API_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            real_name = data.get("model", "")
            if real_name and real_name != model:
                logger.info("Resolved endpoint %s → model %s", model[:30], real_name)
                return real_name
    except Exception:
        logger.debug("Failed to resolve model name from endpoint", exc_info=True)

    return model


# Cache resolved model name per process
_resolved_model_name: str | None = None


def get_model_name() -> str:
    """Return the resolved model name (cached)."""
    global _resolved_model_name
    if _resolved_model_name is None:
        _resolved_model_name = _resolve_model_name()
    return _resolved_model_name


def get_model_context_limit(model_name: str = "") -> int:
    """Return the context window size (in tokens) for a given model.

    Resolution order:
      1. Built-in registry (instant, zero cost)
      2. Env override: DOUBAO_CONTEXT_WINDOW (or model-specific env)
      3. Model name pattern (e.g. '-128k' suffix)
      4. API query (Doubao/Anthropic/DeepSeek — if key available)
      5. Conservative default: 32K

    Discovered values are persisted to model_context_registry.json.
    """
    if not model_name:
        model_name = os.environ.get("DOUBAO_MODEL", "")

    env_override = os.environ.get("DOUBAO_CONTEXT_WINDOW")
    if env_override:
        try:
            return int(env_override)
        except ValueError:
            pass

    # 1. Check registry (built-in + persisted)
    registry = _load_registry()

    def _lookup(name: str) -> int | None:
        if name in registry:
            return registry[name]
        for key, limit in sorted(registry.items(), key=lambda x: -len(x[0])):
            if key in name:
                return limit
        return None

    result = _lookup(model_name)
    if result:
        return result

    # 2. Auto-resolve endpoint ID → real model name → re-check registry
    if model_name.startswith("ep-"):
        resolved = get_model_name()
        if resolved and resolved != model_name:
            result = _lookup(resolved)
            if result:
                _save_registry_entry(model_name, result)
                logger.info("Endpoint %s → %s (%dK context)", model_name[:30], resolved[:40], result // 1000)
                return result
            model_name = resolved  # continue with real name

    # 3. Parse model name pattern
    name_limit = _parse_model_name_for_context(model_name)
    if name_limit:
        _save_registry_entry(model_name, name_limit)
        return name_limit

    # 4. API query: Doubao model list (enrich registry for future)
    doubao_models = _query_doubao_models()
    if doubao_models:
        for mid, limit in doubao_models.items():
            _save_registry_entry(mid, limit)
        result = _lookup(model_name)
        if result:
            return result

    # 5. Conservative default
    logger.warning("Unknown model '%s' — assuming 32K context. Set DOUBAO_CONTEXT_WINDOW in .env.", model_name[:60])
    return 32_000


# ── Context budget calculator ──

# Fixed reserves (in characters, not tokens)
_SYSTEM_PROMPT_CHARS = 2000
_TASK_TEMPLATE_CHARS = 3000
_OUTPUT_RESERVE_CHARS = 6000
_SAFETY_MARGIN = 0.20


@dataclass
class ContextBudget:
    tokens: int           # model context window in tokens
    chars: int            # ~tokens * 0.75 for mixed CN/EN text
    available: int        # chars available for search text
    tier: str             # "large" | "medium" | "small"
    max_results: int      # how many search results to include
    max_chars_per: int    # how many chars per result
    fetch_top_n: int      # how many results to deep-fetch
    multi_pass: bool      # whether to batch & merge (small contexts only)


def calculate_budget(model_name: str = "") -> ContextBudget:
    """Calculate the available context budget for search results.

    Returns a ContextBudget with recommended strategy parameters.
    """
    tokens = get_model_context_limit(model_name)
    chars = int(tokens * 0.75)  # rough CN/EN mixed conversion
    fixed = _SYSTEM_PROMPT_CHARS + _TASK_TEMPLATE_CHARS + _OUTPUT_RESERVE_CHARS
    available = int(chars * (1 - _SAFETY_MARGIN)) - fixed
    available = max(available, 3000)  # minimum viable budget

    # Determine tier
    if available > 60_000:
        tier = "large"
        max_results = 30
        max_chars_per = 2000
        fetch_top_n = 3
        multi_pass = False
    elif available > 15_000:
        tier = "medium"
        max_results = 30
        max_chars_per = 1500
        fetch_top_n = 2
        multi_pass = False
    else:
        tier = "small"
        max_results = 20
        max_chars_per = 800
        fetch_top_n = 1
        multi_pass = True   # use batch-by-product for tiny contexts

    # Allow search_config.json strategy overrides
    cfg = _get_search_config()
    strategy = cfg.get("strategy", {})
    if strategy.get("mode") == "manual":
        for t in ("large_budget", "medium_budget", "small_budget"):
            override = strategy.get(t, {})
            if override.get("tier") == tier or t.startswith(tier[0]):
                max_results = override.get("max_results", max_results)
                max_chars_per = override.get("max_chars_per", max_chars_per)
                fetch_top_n = override.get("fetch_top_n", fetch_top_n)
                multi_pass = override.get("multi_pass", multi_pass)
                break

    logger.warning(
        "📐 Context budget: tier=%s tokens=%d available=%d chars → %d results × %d chars (multi_pass=%s)",
        tier, tokens, available, max_results, max_chars_per, multi_pass,
    )

    return ContextBudget(
        tokens=tokens, chars=chars, available=available,
        tier=tier, max_results=max_results, max_chars_per=max_chars_per,
        fetch_top_n=fetch_top_n, multi_pass=multi_pass,
    )

# Track search stats for visibility in UI
_search_stats: dict = {"total_queries": 0, "total_results": 0, "backend": "", "queries": []}


def _get_search_config() -> dict:
    """Load search backend config from search_config.json.

    Returns full config dict including strategy section.
    """
    config_path = Path(__file__).parent.parent.parent.parent.parent / "search_config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except Exception:
            logger.debug("Failed to parse search_config.json", exc_info=True)

    # Defaults
    return {
        "tavily": True, "ddg": True, "jina": False,
        "fetch_top_n": 3, "fetch_timeout": 15,
        "strategy": {"mode": "auto"},
    }


def get_search_stats() -> dict:
    """Return the current search session stats (for UI observability)."""
    return dict(_search_stats)


def _reset_search_stats() -> None:
    _search_stats.update({"total_queries": 0, "total_results": 0, "backend": "", "queries": []})


@dataclass
class SearchResult:
    """Normalised search result across backends."""
    title: str = ""
    url: str = ""
    snippet: str = ""
    raw_content: str = ""   # populated by fetch


@dataclass
class SearchResponse:
    query: str = ""
    results: list[SearchResult] = field(default_factory=list)
    backend: str = ""


# ── Public API ──


def search(query: str, max_results: int = 5) -> SearchResponse:
    """Multi-backend web search. Backend priority is configurable via search_config.json.

    Backends: volcengine (字节搜索) > tavily > ddg
    """
    cfg = _get_search_config()
    _search_stats["total_queries"] += 1
    _search_stats["queries"].append(query)

    # 1. Volcengine (ByteDance native search — uses same API key as LLM)
    if cfg.get("volcengine", True) and DOUBAO_API_KEY:
        response = _volcengine_search(query, max_results)
        if response.results:
            _search_stats["total_results"] += len(response.results)
            _search_stats["backend"] = response.backend
            return response

    # 2. Tavily
    if cfg.get("tavily", False) and TAVILY_API_KEY and TAVILY_API_KEY not in ("your-tavily-api-key", ""):
        response = _tavily_search(query, max_results)
        if response.results:
            _search_stats["total_results"] += len(response.results)
            _search_stats["backend"] = response.backend
            return response

    # 3. DDG (free fallback)
    if cfg.get("ddg", True):
        response = _ddg_search(query, max_results)
        _search_stats["total_results"] += len(response.results)
        _search_stats["backend"] = "ddg 🦆"
        return response

    logger.warning("No search backend enabled — returning empty results")
    _search_stats["backend"] = "none"
    return SearchResponse(query=query, backend="none")


def fetch(url: str) -> str | None:
    """Fetch and extract readable content from a URL."""
    if TAVILY_API_KEY and TAVILY_API_KEY not in ("your-tavily-api-key", ""):
        content = _tavily_extract(url)
        if content:
            return content
    return None


def multi_search(queries: list[str], max_results: int = 5, fetch_top: int = 2) -> list[SearchResult]:
    """Run multiple searches + fetch top results for richer content.

    Args:
        queries: List of search query strings.
        max_results: Max results per query.
        fetch_top: How many search results to deep-fetch per query.

    Returns deduplicated list of SearchResult with raw_content populated.
    """
    seen: set[str] = set()
    all_results: list[SearchResult] = []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Parallel search with 4 concurrent workers
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_to_q = {pool.submit(search, q, max_results): q for q in queries}
        for future in as_completed(future_to_q):
            q = future_to_q[future]
            try:
                response = future.result(timeout=45)
                for r in response.results:
                    if r.url not in seen:
                        seen.add(r.url)
                        all_results.append(r)
            except Exception:
                logger.warning("Search failed for: %s", q[:60])

    # Parallel fetch
    to_fetch = all_results[:fetch_top * len(queries)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        future_to_r = {pool.submit(fetch, r.url): r for r in to_fetch}
        for future in as_completed(future_to_r):
            r = future_to_r[future]
            try:
                content = future.result(timeout=20)
                if content:
                    r.raw_content = content
            except Exception:
                pass

    return all_results


# ── Tavily backend ──


def _tavily_search(query: str, max_results: int = 5) -> SearchResponse:
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        res = client.search(query, max_results=max_results, search_depth="advanced")
        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
            )
            for r in res.get("results", [])
        ]
        logger.info("Tavily search '%s': %d results", query, len(results))
        return SearchResponse(query=query, results=results, backend="tavily")
    except Exception as e:
        logger.warning("Tavily search failed: %s", e)
        return SearchResponse(query=query, backend="tavily")


def _tavily_extract(url: str) -> str | None:
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        res = client.extract([url])
        if res.get("failed_results"):
            return None
        for r in res.get("results", []):
            raw = r.get("raw_content", "")
            if raw:
                return raw[:6000]
        return None
    except Exception as e:
        logger.warning("Tavily extract failed for %s: %s", url, e)
        return None


# ── DuckDuckGo fallback ──


def _ddg_search(query: str, max_results: int = 5) -> SearchResponse:
    try:
        from ddgs import DDGS
        ddgs = DDGS(timeout=30)
        raw = list(ddgs.text(query, max_results=max_results))
        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("href", r.get("link", "")),
                snippet=r.get("body", r.get("snippet", "")),
            )
            for r in raw
        ]
        logger.info("DDG search '%s': %d results", query, len(results))
        return SearchResponse(query=query, results=results, backend="ddg")
    except ImportError:
        logger.warning("ddgs not installed — web search unavailable")
        return SearchResponse(query=query, backend="ddg")
    except Exception as e:
        logger.warning("DDG search failed: %s", e)
        return SearchResponse(query=query, backend="ddg")


# ── Volcengine web search (ByteDance native) ──


def _volcengine_search(query: str, max_results: int = 5) -> SearchResponse:
    """Use Volcengine Responses API with web_search tool for ByteDance-native search.

    The Responses API returns AI-synthesized answers backed by real web search.
    We ask the model to return raw results as JSON for structured extraction.
    Uses the same DOUBAO_API_KEY and DOUBAO_API_BASE as the LLM calls.
    """
    if not DOUBAO_API_BASE or not DOUBAO_API_KEY:
        return SearchResponse(query=query, backend="volcengine")

    try:
        import urllib.request
        payload = json.dumps({
            "model": os.environ.get("DOUBAO_MODEL", ""),
            "tools": [{"type": "web_search"}],
            "input": [{"role": "user", "content": (
                f"Search for: {query}. "
                "Return ONLY the raw search results as a JSON array of {{title, url, snippet}} objects. "
                f"Max {max_results} results. Do not add commentary."
            )}],
            "max_output_tokens": max_results * 400,
        }).encode()
        req = urllib.request.Request(
            f"{DOUBAO_API_BASE.rstrip('/')}/responses",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DOUBAO_API_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        if "error" in data:
            logger.warning("Volcengine search error: %s", data["error"].get("message", "")[:200])
            return SearchResponse(query=query, backend="volcengine")

        # Extract text from response
        text = ""
        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        text = c.get("text", "")
                        break

        # Parse JSON from response text
        results: list[SearchResult] = []
        try:
            # Try direct JSON parse
            parsed = json.loads(text)
            if isinstance(parsed, list):
                for r in parsed:
                    if isinstance(r, dict):
                        results.append(SearchResult(
                            title=r.get("title", ""),
                            url=r.get("url", ""),
                            snippet=r.get("snippet", ""),
                        ))
        except json.JSONDecodeError:
            # Fallback: extract JSON array from text
            import re as _re
            match = _re.search(r"\[.*\]", text, _re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                    for r in parsed:
                        if isinstance(r, dict):
                            results.append(SearchResult(
                                title=r.get("title", ""),
                                url=r.get("url", ""),
                                snippet=r.get("snippet", ""),
                            ))
                except json.JSONDecodeError:
                    pass

        logger.info("Volcengine search '%s': %d results (字节搜索)", query, len(results))
        return SearchResponse(query=query, results=results, backend="volcengine 🔥")

    except Exception as e:
        logger.warning("Volcengine search failed: %s", e)
        return SearchResponse(query=query, backend="volcengine")


# ── Search query expansion ──

_CATEGORY_QUERY_TEMPLATES = {
    "features": [
        "{product} features capabilities comparison",
    ],
    "pricing": [
        "{product} pricing plans tiers",
    ],
    "users": [
        "{product} user reviews ratings",
    ],
    "market": [
        "{product} market share growth trends",
    ],
}


def build_search_queries(products: list[str], categories: list[str] | None = None, complexity: str = "standard") -> list[str]:
    """Generate search queries for each product × category.

    Uses 1 query per category (not 2+), since Volcengine web_search returns
    comprehensive results for each query. Also adds a broad per-product query.

    Complexity adjustment (§3.17.1):
    - quick: only 2 core categories (features + pricing), 1 query per product
    - standard: all 4 categories (features/pricing/users/market)
    - deep: all 4 categories + extra deep-dive queries per product
    """
    all_cats = categories or list(_CATEGORY_QUERY_TEMPLATES.keys())

    if complexity == "quick":
        # Fewer categories for simple comparison
        cats = [c for c in all_cats if c in ("features", "pricing")]
        if not cats:
            cats = all_cats[:2]
    elif complexity == "deep":
        cats = all_cats
    else:
        cats = all_cats

    queries = []
    for product in products:
        for cat in cats:
            tmpl = _CATEGORY_QUERY_TEMPLATES.get(cat, ["{product}"])
            queries.append(tmpl[0].format(product=product))

    # Deep mode: add extra strategic queries per product
    if complexity == "deep":
        deep_templates = [
            "{product} SWOT analysis competitive landscape",
            "{product} user reviews G2 Capterra rating",
            "{product} pricing tiers comparison 2026",
        ]
        for product in products:
            for tmpl in deep_templates:
                queries.append(tmpl.format(product=product))

    return queries


def format_search_context(results: list[SearchResult], budget: ContextBudget | None = None) -> str:
    """Format search results as a compact context string for LLM extraction.

    When budget is provided, uses its max_results and max_chars_per.
    Otherwise defaults to 30 results × 1500 chars.
    Prioritises fetched content over snippet-only.
    """
    max_n = budget.max_results if budget else 30
    max_ch = budget.max_chars_per if budget else 1500

    def _priority(r: SearchResult) -> int:
        return len(r.raw_content) if r.raw_content else 0
    sorted_results = sorted(results, key=_priority, reverse=True)

    parts: list[str] = []
    count = 0
    for r in sorted_results:
        if count >= max_n:
            break
        content = r.raw_content or r.snippet or ""
        if not content.strip():
            continue
        entry = (
            f"### [{count + 1}] {r.title}\n"
            f"URL: {r.url}\n"
            f"{content[:max_ch]}"
        )
        parts.append(entry)
        count += 1

    if not parts:
        return ""

    total_chars = sum(len(p) for p in parts)
    logger.info("Search context: %d results, ~%d chars (tier=%s, max=%d×%d)",
                count, total_chars, budget.tier if budget else "none", max_n, max_ch)

    return "\n\n".join(parts)
