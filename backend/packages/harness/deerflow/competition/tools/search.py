"""Multi-backend real web search toolkit for competition Collector.

Provides direct search + fetch APIs usable without the full SubagentExecutor sandbox.
Backends (ordered by preference):
  1. Tavily  — AI-optimised search + extract (TAVILY_API_KEY)
  2. DDG     — free text search, no API key needed (fallback)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")

# Track search stats for visibility in UI
_search_stats: dict = {"total_queries": 0, "total_results": 0, "backend": "", "queries": []}


def _get_search_config() -> dict:
    """Load search backend config from search_config.json or competition config.

    Priority:
      1. backend/search_config.json (easy toggle: true/false per backend)
      2. config.yaml competition.search section
      3. Defaults (all enabled)

    Returns {"tavily": bool, "ddg": bool, "jina": bool, "fetch_top_n": int, "fetch_timeout": int}.
    """
    import json
    from pathlib import Path

    # 1. Try standalone search_config.json
    config_path = Path(__file__).parent.parent.parent.parent.parent / "search_config.json"
    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text())
            return {
                "tavily": raw.get("tavily", True),
                "ddg": raw.get("ddg", True),
                "jina": raw.get("jina", False),
                "fetch_top_n": raw.get("fetch_top_n", 3),
                "fetch_timeout": raw.get("fetch_timeout", 15),
            }
        except Exception:
            logger.debug("Failed to parse search_config.json", exc_info=True)

    # 2. Try config.yaml competition.search section
    try:
        from deerflow.config import get_app_config
        app = get_app_config()
        raw_comp = getattr(app, "competition", None)
        if raw_comp and hasattr(raw_comp, "search"):
            cfg = raw_comp.search
            return {
                "tavily": cfg.tavily,
                "ddg": cfg.ddg,
                "jina": cfg.jina,
                "fetch_top_n": cfg.fetch_top_n,
                "fetch_timeout": cfg.fetch_timeout,
            }
    except Exception:
        logger.debug("Could not load competition search config, using defaults", exc_info=True)

    # 3. Defaults
    return {"tavily": True, "ddg": True, "jina": False, "fetch_top_n": 3, "fetch_timeout": 15}


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
    """Multi-backend web search. Reads competition.search config for backend toggles.

    Config in config.yaml:
      competition:
        search:
          tavily: false   # set to false to skip Tavily
          ddg: true
          jina: false
    """
    cfg = _get_search_config()
    _search_stats["total_queries"] += 1
    _search_stats["queries"].append(query)

    if cfg["tavily"] and TAVILY_API_KEY and TAVILY_API_KEY not in ("your-tavily-api-key", ""):
        response = _tavily_search(query, max_results)
        if response.results:
            _search_stats["total_results"] += len(response.results)
            _search_stats["backend"] = response.backend
            return response

    if cfg["ddg"]:
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


def multi_search(queries: list[str], max_results: int = 5, fetch_top: int = 3) -> list[SearchResult]:
    """Run multiple searches + fetch top results for richer content.

    Args:
        queries: List of search query strings.
        max_results: Max results per query.
        fetch_top: How many search results to deep-fetch per query.

    Returns deduplicated list of SearchResult with raw_content populated.
    """
    seen: set[str] = set()
    all_results: list[SearchResult] = []

    for q in queries:
        response = search(q, max_results)
        for r in response.results:
            if r.url in seen:
                continue
            seen.add(r.url)
            all_results.append(r)

    # Fetch top results to enrich content
    to_fetch = all_results[:fetch_top * len(queries)]
    for r in to_fetch:
        content = fetch(r.url)
        if content:
            r.raw_content = content

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


# ── Search query expansion ──

_CATEGORY_QUERY_TEMPLATES = {
    "features": [
        "{product} features capabilities",
        "{product} vs competitors comparison",
    ],
    "pricing": [
        "{product} pricing plans tiers",
        "{product} price per month free trial",
    ],
    "users": [
        "{product} user reviews ratings",
        "{product} customer review site:g2.com",
    ],
    "market": [
        "{product} market share funding",
        "{product} growth trends 2025 2026",
    ],
}


def build_search_queries(products: list[str], categories: list[str] | None = None) -> list[str]:
    """Generate diverse search queries for each product × category."""
    cats = categories or list(_CATEGORY_QUERY_TEMPLATES.keys())
    queries = []
    for product in products:
        for cat in cats:
            templates = _CATEGORY_QUERY_TEMPLATES.get(cat, ["{product}"])
            for tmpl in templates[:2]:
                queries.append(tmpl.format(product=product))
    return queries


def format_search_context(results: list[SearchResult], max_results: int = 30, max_chars_per: int = 1500) -> str:
    """Format search results as a compact context string for LLM extraction.

    Caps total context size to avoid overwhelming the LLM:
      - max_results: top N results to include (prioritises fetched)
      - max_chars_per: truncate each result's content to this length
    """
    # Sort: results with raw_content first, then by snippet length
    def _priority(r: SearchResult) -> int:
        return len(r.raw_content) if r.raw_content else 0
    sorted_results = sorted(results, key=_priority, reverse=True)

    parts: list[str] = []
    count = 0
    for r in sorted_results:
        if count >= max_results:
            break
        content = r.raw_content or r.snippet or ""
        if not content.strip():
            continue
        entry = (
            f"### [{count + 1}] {r.title}\n"
            f"URL: {r.url}\n"
            f"{content[:max_chars_per]}"
        )
        parts.append(entry)
        count += 1

    if not parts:
        return ""

    return "\n\n".join(parts)
