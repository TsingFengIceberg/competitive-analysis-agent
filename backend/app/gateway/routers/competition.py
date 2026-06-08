"""Competition analysis API router — App layer gateway.

Per COMPETITION_PLAN.md §8 Week 2:
- POST /api/competition/analyze — Start competitive analysis
- GET /api/competition/report/{thread_id} — Get generated report
- GET /api/competition/stream/{thread_id} — SSE stream of graph execution

Version history is persisted via BranchSnapshotStore (branchtree module).
Runtime state (_store) tracks status, current state dict, and token usage.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from deerflow.branchtree.checkpoint_ops import CheckpointOps
from deerflow.branchtree.store import BranchSnapshotStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/competition", tags=["competition"])

# ── Persisted version history ──

_history_store = BranchSnapshotStore()

# ── Checkpoint replay support (P1) ──

_replay_saver = InMemorySaver()
_replay_ops = CheckpointOps(_replay_saver)

# ── User-aware storage (§User System) ──

_thread_owners: dict[str, str] = {}  # thread_id → user_id


# ── Request / Response Models ──


class AnalyzeRequest(BaseModel):
    """Request body for starting a competitive analysis."""

    query: str = Field(..., description="Natural language analysis request")
    target_products: list[str] = Field(default_factory=list, description="Products to compare. Optional — leave empty for AI auto-detection.")
    industry: str = Field(default="general", description="Industry selection: 'saas' | 'devtools' | 'ai' | 'database' | 'hardware' | 'gaming' | 'general'")
    persona: str = Field(default="pm", description="'pm' | 'entrepreneur' | 'both'")
    deep_mode: bool = Field(default=False, description="Enable deep mode pipeline after normal mode")
    uploaded_files: list[str] | None = Field(default=None, description="Sandbox paths of uploaded files")
    context_report: dict | None = Field(default=None, description="Previous report data to use as analysis context")


class AnalyzeResponse(BaseModel):
    """Response after starting an analysis."""

    thread_id: str
    status: str = "running"  # "running" | "completed" | "failed"


class ReportResponse(BaseModel):
    """Response for report retrieval."""

    thread_id: str
    status: str
    report_data: dict | None = None
    metrics: dict | None = None
    error: str | None = None
    history_count: int = 0
    token_usage: list[dict] = []
    created_at: str | None = None


class StreamEvent(BaseModel):
    """Single SSE event payload."""

    event: str  # "node_start" | "node_end" | "state_update" | "error" | "end"
    node: str | None = None
    data: dict | None = None


# ── Runtime store (status, current state, token usage — ephemeral) ──
# Version history is persisted in _history_store (SQLite branch_snapshots).

_store: dict[str, dict] = {}
_cancel_flags: dict[str, bool] = {}  # thread_id → cancelled (cooperative cancellation)

# ── SSE streaming (§19) ──
import queue as _queue_mod
_stream_queues: dict[str, _queue_mod.Queue] = {}
_event_counters: dict[str, int] = {}  # thread_id → monotonic event id
_event_buffers: dict[str, list[tuple[int, str]]] = {}  # thread_id → [(id, formatted_sse_line)]
MAX_BUFFERED_EVENTS = 64


def _get_or_create_queue(thread_id: str) -> _queue_mod.Queue:
    """Get or create a thread-safe queue for a thread's SSE stream."""
    if thread_id not in _stream_queues:
        _stream_queues[thread_id] = _queue_mod.Queue(maxsize=256)
    return _stream_queues[thread_id]


def _format_sse(event: str, data, *, event_id: str | None = None) -> str:
    """Format a single SSE frame matching DF's wire format.

    Field order: event: -> data: -> id: (optional) -> blank line.
    """
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


def _emit_event(thread_id: str, event_type: str, data: dict) -> None:
    """Emit an SSE event into the thread's stream queue (thread-safe).

    Events are assigned monotonic IDs and buffered for Last-Event-ID replay.
    Uses _get_or_create_queue so events are buffered even if the SSE client
    hasn't connected yet — critical for the ~2min product-resolution phase.
    """
    import logging
    _log = logging.getLogger(__name__)
    try:
        # Assign monotonic event ID
        seq = _event_counters.get(thread_id, 0) + 1
        _event_counters[thread_id] = seq
        event_id = f"{thread_id[-8:]}-{seq:05d}"

        # Format and buffer
        frame = _format_sse(event_type, data, event_id=event_id)

        # Circular buffer for replay
        buf = _event_buffers.get(thread_id)
        if buf is None:
            buf = []
            _event_buffers[thread_id] = buf
        buf.append((seq, frame))
        if len(buf) > MAX_BUFFERED_EVENTS:
            buf.pop(0)

        # Push to live queue
        q = _get_or_create_queue(thread_id)
        q.put_nowait(frame)
        _log.info("SSE emit #%d [%s] queue_depth=%d", seq, event_type, q.qsize())
    except Exception:
        _log.exception("SSE emit failed for %s [%s]", thread_id, event_type)


# ── User helpers (§User System) ──


async def _get_user_id(request: Request | None = None) -> str:
    """Get the current user ID from auth context, falling back to 'default'.

    Uses DeerFlow's existing auth middleware. Returns 'default' when:
    - No request provided (background thread)
    - User is not authenticated (public access)
    """
    if request is None:
        return "default"
    try:
        from app.gateway.deps import get_optional_user_from_request

        user = await get_optional_user_from_request(request)
        if user and hasattr(user, "id"):
            return str(user.id)
    except Exception:
        pass
    return "default"


async def _ensure_demo_user() -> None:
    """Create a demo account if it doesn't exist (`demo@deerflow.demo` / `demo1234`).

    For competition submission: judges can log in with demo@deerflow.demo / demo1234
    and see pre-populated analysis history. Also used for auto-login on the
    competition page.
    """
    try:
        from app.gateway.deps import get_local_provider

        provider = get_local_provider()
        existing = await provider.get_user_by_email("demo@deerflow.demo")
        if existing:
            logger.info("Demo user already exists")
            return
        await provider.create_user("demo@deerflow.demo", "demo1234", system_role="user")
        logger.info("Created demo user: demo@deerflow.demo / demo1234")
    except Exception:
        logger.warning("Demo user creation skipped (auth DB may not be ready)")


def _associate_thread(thread_id: str, user_id: str) -> None:
    """Record which user owns a thread."""
    if user_id and user_id != "default":
        _thread_owners[thread_id] = user_id


def _get_user_threads(user_id: str) -> list[str]:
    """Return all thread_ids belonging to a user."""
    if user_id == "default":
        return list(_store.keys())
    return [tid for tid, uid in _thread_owners.items() if uid == user_id]


def _snapshot_to_history(thread_id: str, version: int) -> dict | None:
    """Read a single version from history store and attach report data from runtime state."""
    meta = _history_store.get(thread_id, version)
    if meta is None:
        return None
    entry = _store.get(thread_id, {})
    state = entry.get("state", {})
    # Prefer report_data from stored metadata (available for all versions)
    stored_rd = (meta.get("metadata_json") or {}).get("report_data")
    if stored_rd is None and version == _current_db_version(thread_id):
        stored_rd = state.get("report_data")
        if stored_rd is not None and hasattr(stored_rd, "model_dump"):
            stored_rd = stored_rd.model_dump()
    return {
        "version": version,
        "parent_version": meta.get("parent_version"),
        "action": meta.get("action"),
        "is_approved": meta.get("is_approved"),
        "created_at": meta.get("created_at"),
        "report_data": stored_rd,
        "analysis_result": state.get("analysis_result") if version == _current_db_version(thread_id) else None,
        "collected_data": state.get("collected_data") if version == _current_db_version(thread_id) else None,
    }


def _list_history(thread_id: str) -> list[dict]:
    """List all version entries from history store, enriching with runtime state for latest."""
    rows = _history_store.list_by_thread(thread_id)
    latest = _current_db_version(thread_id)
    entry = _store.get(thread_id, {})
    state = entry.get("state", {})
    result = []
    for r in rows:
        is_latest = r["version"] == latest
        stored_rd = (r.get("metadata_json") or {}).get("report_data")
        if stored_rd is None and is_latest:
            rd = state.get("report_data")
            if rd is not None and hasattr(rd, "model_dump"):
                stored_rd = rd.model_dump()
        result.append({
            "version": r["version"],
            "parent_version": r["parent_version"],
            "checkpoint_id": r["checkpoint_id"],
            "action": r["action"],
            "is_approved": r["is_approved"],
            "created_at": r["created_at"],
            "metadata": r.get("metadata_json", {}),
            "report_data": stored_rd,
            "analysis_result": state.get("analysis_result") if is_latest else None,
            "collected_data": state.get("collected_data") if is_latest else None,
        })
    return result


def _current_db_version(thread_id: str) -> int | None:
    """Get the latest version number from history store."""
    rows = _history_store.list_by_thread(thread_id)
    if not rows:
        return None
    return max(r["version"] for r in rows)


def _assess_complexity(query: str, products: list[str]) -> str:
    """Determine task complexity (quick/standard/deep) based on query + products.

    Heuristic assessment (§3.17.1) — no extra LLM call needed:
    - quick: 1-2 products, short query, no deep-analysis keywords
    - standard: 2-4 products, normal query
    - deep: 5+ products, long query, or contains strategic/forecast keywords

    Stored in state["complexity"] — Collector uses this to adjust search budget.
    """
    n_products = len(products)
    query_lower = query.lower()
    query_len = len(query)

    # Deep indicators: strategic keywords or explicit depth requests
    deep_keywords = [
        "深度", "全面", "预测", "战略", "市场格局", "全景", "详细",
        "deep", "comprehensive", "strategic", "forecast", "landscape",
        "详细对比", "完整分析", "竞争格局",
    ]
    deep_score = sum(1 for kw in deep_keywords if kw in query_lower)

    # Quick indicators: simple compare/overview
    quick_keywords = ["对比", "比较", "区别", "vs", "compare", "versus", "diff", "哪个好"]
    quick_score = sum(1 for kw in quick_keywords if kw in query_lower)

    if n_products >= 5 or deep_score >= 2 or query_len > 200:
        return "deep"
    elif n_products >= 3 or query_len > 80 or (deep_score >= 1 and n_products >= 2):
        return "standard"
    elif n_products <= 2 and quick_score >= 1 and deep_score == 0:
        return "quick"
    else:
        return "standard"


# ── Product name extraction & correction ──

def _llm_extract_products(query: str, thread_id: str | None = None) -> list[str]:
    """Multi-round LLM+Search extraction with progressive relaxation.

    Round 1: LLM extracts → search strictly verifies each candidate
    Round 2: Retry with broader search, accept partial matches
    Round 3: Most permissive — accept any search hit, only filter complete garbage

    Stops early once we have ≥2 verified products, or after round 3.
    Synchronous — caller must wrap in executor.

    If thread_id is provided, emits intermediate SSE progress events
    so the frontend shows live updates during the ~2-3min resolution phase.
    """
    all_candidates: list[str] = []

    for round_num in range(1, 4):
        remaining = _build_round_prompt(query, all_candidates, round_num)

        if thread_id:
            _emit_event(thread_id, "progress", {
                "phase": "resolving",
                "message": f"第 {round_num} 轮: LLM 提取竞品名称...",
                "round": round_num,
            })

        new_candidates = _llm_extract_candidates(remaining)
        if not new_candidates:
            if thread_id:
                _emit_event(thread_id, "progress", {
                    "phase": "resolving",
                    "message": f"第 {round_num} 轮: 未提取到新候选",
                    "round": round_num,
                })
            continue

        if thread_id:
            _emit_event(thread_id, "progress", {
                "phase": "resolving",
                "message": f"第 {round_num} 轮: 候选 {', '.join(new_candidates)} → 搜索验证...",
                "round": round_num,
                "candidates": new_candidates,
            })

        verified = _verify_products_via_search(new_candidates, strictness=round_num, query_hint=query)
        for v in verified:
            if v not in all_candidates:
                all_candidates.append(v)

        logger.info("Product extraction round %d: got %d candidates, %d verified (total: %d)",
                     round_num, len(new_candidates), len(verified), len(all_candidates))

        if thread_id:
            _emit_event(thread_id, "progress", {
                "phase": "resolving",
                "message": f"第 {round_num} 轮: {len(verified)} 个验证通过 ({', '.join(verified) if verified else '无'})",
                "round": round_num,
                "verified": verified,
            })

        if len(all_candidates) >= 2:
            break

    return all_candidates


def _build_round_prompt(query: str, already_found: list[str], round_num: int) -> str:
    """Build progressively more permissive extraction prompts."""
    base = (
        f"User request: {query}\n\n"
        "Extract the names of software products or tools they want to compare. "
        "Return ONLY a JSON array of product name strings.\n"
    )
    if already_found:
        base += f"Already identified: {json.dumps(already_found)}. Find any ADDITIONAL products.\n"

    if round_num == 1:
        base += "Be strict: only extract clearly named, well-known tools."
    elif round_num == 2:
        base += (
            "Be moderate: include products mentioned by description or nickname. "
            "Resolve references like '微软的那个AI编程工具' → 'GitHub Copilot'. "
            "If uncertain, still include the candidate."
        )
    else:
        base += (
            "Be very permissive: extract ANY possible product mention, even vague ones. "
            "Resolve ALL indirect references. Infer from context. If the query seems to "
            "compare tools in a specific domain, list the most likely candidates even "
            "if not explicitly named. Return at least 2 products."
        )
    return base


def _llm_extract_candidates(query: str) -> list[str]:
    """LLM extracts candidate product names from a prompt string."""
    try:
        from deerflow.competition.executor import execute_agent

        prompt = (
            "You are a product name extractor. "
            "Return ONLY a JSON array of product name strings, e.g. [\"GitHub Copilot\", \"Cursor\"]."
        )
        result, _tokens = execute_agent(
            prompt, query, temperature=0.0, max_tokens=200, agent_name="ProductResolver",
        )
        if result:
            text = result.strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(p).strip() for p in parsed if str(p).strip()]
    except Exception:
        logger.warning("LLM candidate extraction failed", exc_info=True)
    return []



def _verify_products_via_search(candidates: list[str], strictness: int = 1, query_hint: str = "") -> list[str]:
    """Verify & correct product names: search for ground truth, then LLM judges.

    Step 2-3 of the resolution pipeline:
      Step 2: Search each candidate (no judgment — just collect titles).
      Step 3: Single LLM call judges all candidates against search titles + query context.
              Corrects typos, expands partial names, keeps confirmed names.

    Deleted: alias table triage (C1/C2/C3), canonical name extraction, all string-matching rules.
    Reason: hardcoded rules can't understand domain context (e.g. "Power" + "数据分析工具" = "Power BI").
    """
    try:
        from deerflow.competition.tools.search import search as web_search
    except ImportError:
        return candidates

    # ── Step 2: Search each candidate (parallel, collect titles only, no judgment) ──
    # Strategy: dual queries per candidate:
    #   1. Context search (quoted): candidate + co-competitor → competitive landscape
    #   2. Independent search (UNquoted): candidate alone → search engine auto-corrects typos
    # Quoted search ("Noton") forces exact-match, blocking auto-correction.
    # Unquoted search (Noton product) lets the engine suggest "Notion" in results.
    search_titles: dict[str, list[str]] = {}

    def _search_one(name: str) -> tuple[str, list[str]] | None:
        """Search for a single candidate. Returns (name, titles) or None if discarded."""
        all_titles: list[str] = []
        try:
            other_names = [c for c in candidates if c.lower() != name.lower()]
            context = other_names[0] if other_names else None

            if strictness <= 2:
                # Context search: quoted for precision (find co-mentioned pages)
                if context:
                    resp = web_search(f'"{name}" "{context}"', max_results=5)
                    if resp and resp.results:
                        t = [r.title if hasattr(r, "title") else r.get("title", "") for r in resp.results]
                        all_titles.extend(t)

                # Independent search: UNquoted — lets search engine auto-correct typos
                resp2 = web_search(f'{name} product', max_results=5)
                if resp2 and resp2.results:
                    t2 = [r.title if hasattr(r, "title") else r.get("title", "") for r in resp2.results]
                    for title in t2:
                        if title not in all_titles:
                            all_titles.append(title)
            else:
                resp = web_search(f"{name} product review", max_results=3)
                if resp and resp.results:
                    all_titles = [r.title if hasattr(r, "title") else r.get("title", "") for r in resp.results]

            all_titles = all_titles[:8]

            if not all_titles and strictness >= 2:
                resp3 = web_search(name, max_results=3)
                if resp3 and resp3.results:
                    all_titles = [r.title if hasattr(r, "title") else r.get("title", "") for r in resp3.results]
                    logger.info("Product '%s' — fallback search found %d results", name, len(all_titles))
                else:
                    logger.warning("Product '%s' — no search results, keeping as-is", name)
            elif not all_titles:
                logger.info("Product '%s' discarded (no search results)", name)
                return None
        except Exception:
            if strictness < 2:
                return None
            logger.warning("Search failed for '%s' — keeping", name)

        return (name, all_titles)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=min(len(candidates), 8)) as executor:
        futures = {executor.submit(_search_one, name): name for name in candidates}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    search_titles[result[0]] = result[1]
            except Exception:
                logger.warning("Search task failed for '%s'", futures[future], exc_info=True)

    if not search_titles:
        return []

    # ── Step 3: LLM judges all candidates at once ──
    resolved = _llm_judge_and_correct(search_titles, query_hint)

    # Merge: LLM output drives, fall back to originals for anything missing
    result: list[str] = []
    for name in candidates:
        if name in resolved:
            corrected = resolved[name]
            if corrected != name:
                logger.info("LLM judge: '%s' → '%s'", name, corrected)
            else:
                logger.info("LLM judge: '%s' confirmed", name)
            result.append(corrected)
        else:
            logger.info("LLM judge: '%s' not in response — keeping original", name)
            result.append(name)

    return result


def _llm_judge_and_correct(
    search_titles: dict[str, list[str]],
    query_hint: str = "",
) -> dict[str, str]:
    """Single LLM call: judge all candidates against search titles + query context.

    Replaces the old Phase 2 batch LLM + all C1/C2/C3 rules. The LLM sees:
      - The user's original query (domain context)
      - Each candidate name
      - Search result titles for that candidate (ground truth)

    Returns a mapping of original_name → resolved_name.
    Candidates not in the returned dict are kept as-is by the caller.
    """
    try:
        from deerflow.competition.executor import execute_agent
    except ImportError:
        return {}

    if not search_titles:
        return {}

    # ── Build the task prompt ──
    parts: list[str] = []

    if query_hint:
        parts.append(f"User query: \"{query_hint}\"\n")

    parts.append("Candidates to resolve:\n")
    for name, titles in search_titles.items():
        if titles:
            lines = "\n".join(f"      {i+1}. {t}" for i, t in enumerate(titles[:5]))
            parts.append(f'  - "{name}" → search titles:\n{lines}\n')
        else:
            parts.append(f'  - "{name}" → search titles: (no results)\n')

    task = "\n".join(parts)
    task += (
        "\nFor each candidate, determine the canonical product name. Use these rules:\n"
        "\n"
        "1. **Search titles are ground truth.** If titles consistently show a different "
        "but related name (e.g. \"Notion\" when candidate is \"Noton\"), the titles are correct.\n"
        "2. **Query context is critical for disambiguation.** The user's query tells you "
        "the product domain. Use it to expand common words and abbreviations:\n"
        '   - "Power" + "数据分析" → "Power BI" (data analytics domain)\n'
        '   - "Tab" + "数据分析" → "Tableau" (data analytics domain)\n'
        '   - "force" + "CRM" → "Salesforce" (CRM domain)\n'
        '   - "spot" + "CRM" → "HubSpot" (CRM domain)\n'
        '   - "DD" + "监控" → "Datadog" (monitoring domain)\n'
        '   - "SF" + "CRM" → "Salesforce" (CRM domain)\n'
        "3. **Correct typos aggressively.** Common misspellings of well-known products "
        "should be corrected even when search titles are sparse or mixed. "
        "Examples: Noton→Notion, MonngoDB→MongoDB, Githbu→GitHub, Postgre→PostgreSQL. "
        "The independent search is unquoted so the search engine may auto-correct; "
        "if even ONE title shows the corrected name, that's strong evidence.\n"
        "4. **Be concise.** \"Power BI\" not \"Microsoft Power BI Desktop\". "
        "\"Salesforce\" not \"Salesforce CRM Platform\".\n"
        "5. **Don't hallucinate.** If search titles don't clearly support a correction, "
        "keep the original name. Do NOT guess based on domain alone — there must be "
        "evidence in the search titles.\n"
        "6. **Proper nouns stay proper.** Respect original capitalization: \"MongoDB\", \"GitHub\", \"iOS\".\n"
        "7. **Each candidate is independent.** Don't change candidate A because candidate B's "
        "search results are about a different product. Judge each candidate on its OWN titles.\n"
        "\n"
        "Return ONLY a JSON array. Each entry must have three fields:\n"
        '  {"original": "<candidate>", "resolved": "<canonical name>", "confidence": "<high|medium|low>"}\n'
        "\n"
        "- **high**: Search titles overwhelmingly confirm the resolved name.\n"
        "- **medium**: Reasonable inference from query context + partial title evidence.\n"
        "- **low**: Sparse results, keeping original as best guess.\n"
        "\n"
        "Include EVERY candidate in the output.\n"
    )

    try:
        raw, tokens = execute_agent(
            (
                "You are a product name resolver. Your job: determine the canonical "
                "product name for each candidate by cross-referencing search titles "
                "with the user's original query context.\n"
                "\n"
                "CRITICAL: The user's query tells you the product DOMAIN. "
                "Common English words in a tech context are almost always partial names:\n"
                "  - CRM context: force→Salesforce, spot→HubSpot, sugar→SugarCRM\n"
                "  - Data analytics: power→Power BI, tab→Tableau, looker→Looker\n"
                "  - Monitoring: dd→Datadog, pd→PagerDuty\n"
                "  - Design: figma→Figma, sketch→Sketch, xd→Adobe XD\n"
                "\n"
                "TYPO CORRECTION: The independent search for each candidate is UNQUOTED, "
                "so the search engine may auto-correct typos (e.g. searching 'Noton product' "
                "may return titles about 'Notion'). When you see a candidate that looks like "
                "a misspelling of a well-known product AND the independent search titles "
                "mention that product, correct it. Common typos:\n"
                "  - Noton → Notion, MonngoDB → MongoDB, Githbu → GitHub\n"
                "  - Postgre → PostgreSQL, Doker → Docker, Kubernets → Kubernetes\n"
                "  - Figam → Figma, Sktech → Sketch, Obisidian → Obsidian\n"
                "\n"
                "Use search titles as evidence to support or refine these expansions. "
                "A candidate with 0 search results should still be expanded if the "
                "query context is clear (use medium confidence). "
                "Return ONLY valid JSON array."
            ),
            task,
            temperature=0.0,
            max_tokens=500,
            agent_name="ProductJudge",
        )
        if not raw:
            logger.warning("LLM judge returned empty — keeping %d candidates as-is", len(search_titles))
            return {}

        parsed = _parse_json_safe(raw)
        if not isinstance(parsed, list):
            logger.warning("LLM judge returned non-array: %s", str(parsed)[:100])
            return {}

        # Convert to {original: resolved} mapping with validation
        result: dict[str, str] = {}
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            orig = entry.get("original", "")
            resolved = entry.get("resolved", "")
            confidence = entry.get("confidence", "medium")
            if not orig or not resolved:
                continue
            # Length guard: reject overly long / descriptive names
            if len(resolved) > 50:
                logger.warning("LLM judge returned overly long name for '%s': '%s' — keeping original",
                             orig, resolved[:80])
                result[orig] = orig
            else:
                result[orig] = resolved
                logger.debug("LLM judge: '%s' → '%s' [%s]", orig, resolved, confidence)

        corrected = sum(1 for k, v in result.items() if v.lower() != k.lower())
        logger.info("LLM judge: %d/%d candidates corrected (%d tokens)",
                    corrected, len(result), tokens)
        return result

    except Exception:
        logger.warning("LLM judge failed — keeping all candidates as-is", exc_info=True)
        return {}


def _parse_json_safe(raw: str) -> dict | list | None:
    """Extract JSON from LLM output, handling markdown code blocks."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ── Routes ──


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest, fastapi_request: Request) -> AnalyzeResponse:
    """Start a competitive analysis. Returns thread_id immediately.

    Product resolution (LLM + search, ~2min) runs in background thread,
    then graph execution starts automatically once products are resolved.
    Frontend polls /report/{thread_id} for status updates.
    """
    import uuid
    from datetime import UTC, datetime

    thread_id = f"comp-{uuid.uuid4().hex[:12]}"
    user_id = await _get_user_id(fastapi_request)
    _associate_thread(thread_id, user_id)

    # Store entry immediately — frontend can start polling right away
    _store[thread_id] = {
        "status": "running",
        "state": {
            "messages": [],
            "user_request": request.query,
            "target_products": request.target_products or [],
            "persona": request.persona,
            "industry": request.industry,
            "deep_mode": request.deep_mode,
            "collected_data": [],
            "context_report": request.context_report,
        },
        "created_at": datetime.now(UTC).isoformat(),
        "query": request.query,
        "products": [],
    }

    # Persist to DB on creation (§18)
    from deerflow.competition.db import upsert_analysis
    upsert_analysis(
        thread_id=thread_id, status="running", user_id=user_id,
        query=request.query, products=request.target_products or [],
        industry=request.industry, persona=request.persona,
    )

    # Resolve products + run graph entirely in background thread
    # (sync LLM + search calls take ~2min and would block the event loop)
    asyncio.get_event_loop().run_in_executor(
        None, _resolve_and_run_graph, thread_id, request.query, request.target_products,
    )

    return AnalyzeResponse(thread_id=thread_id, status="running")


@router.post("/{thread_id}/cancel")
async def cancel_analysis(thread_id: str) -> dict:
    """Cancel a running analysis. Data is preserved with status='interrupted'.

    Uses cooperative cancellation — the background thread checks the flag
    at node boundaries and exits gracefully, saving current state to DB.
    """
    entry = _store.get(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

    if entry.get("status") != "running":
        return {"thread_id": thread_id, "status": entry["status"], "message": "Analysis is not running"}

    # Set cooperative cancellation flag — the worker thread checks this
    _cancel_flags[thread_id] = True

    # Immediately mark as interrupted in the store so the frontend sees the
    # status change right away (polling every 2s). The background thread will
    # also call _finalize_cancelled when it reaches a check point, which is
    # idempotent.
    _store[thread_id]["status"] = "interrupted"
    _store[thread_id]["state"]["error"] = "用户手动终止分析"
    try:
        from deerflow.competition.db import upsert_analysis
        upsert_analysis(
            thread_id=thread_id, status="interrupted",
            user_id=_thread_owners.get(thread_id, "default"),
            query=_store[thread_id].get("query", ""),
            products=_store[thread_id].get("products", []),
        )
    except Exception:
        pass

    # Notify SSE clients
    q = _stream_queues.get(thread_id)
    if q:
        try:
            q.put_nowait(_format_sse("end", {"status": "interrupted", "message": "分析已终止"}, event_id=f"{thread_id[-8:]}-cancel"))
        except Exception:
            pass

    return {"thread_id": thread_id, "status": "cancelling", "message": "Cancellation requested"}


@router.get("/report/{thread_id}", response_model=ReportResponse)
async def get_report(thread_id: str) -> ReportResponse:
    """Get the generated report for a completed analysis."""
    entry = _store.get(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

    status = entry.get("status", "unknown")
    report_data = entry.get("state", {}).get("report_data")
    metrics = entry.get("state", {}).get("report_data", {}).get("metrics") if report_data else None
    error = entry.get("state", {}).get("error")
    history = _list_history(thread_id)
    token_usage_list = entry.get("token_usage", [])

    return ReportResponse(
        thread_id=thread_id,
        status=status,
        report_data=report_data,
        metrics=metrics,
        error=error,
        history_count=len(history),
        token_usage=token_usage_list,
        created_at=entry.get("created_at"),
    )


@router.get("/report/{thread_id}/history")
async def get_report_history(thread_id: str):
    """Get report revision history (from persisted BranchSnapshotStore)."""
    entry = _store.get(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")
    history = _list_history(thread_id)
    return {"history": history, "count": len(history)}


class HitlDecisionRequest(BaseModel):
    """HITL decision or what-if input from frontend."""

    action: str = "rewrite"  # "approve" | "rewrite" | "reanalyze" | "replan"
    comment: str = ""
    target_focus: list[str] | None = None
    fork_version: int | None = None  # If set, fork from this historical version instead of current


@router.put("/report/{thread_id}", response_model=ReportResponse)
async def submit_decision(thread_id: str, decision: HitlDecisionRequest) -> ReportResponse:
    """Handle HITL decision or what-if rewrite request.

    For "rewrite" (what-if): runs Writer with the existing analysis + user's
    what-if assumption, generates updated report without re-running Collector/Analyst.
    """
    import asyncio

    entry = _store.get(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

    if entry.get("status") == "running":
        raise HTTPException(status_code=409, detail="分析正在进行中，请等待完成后再提交")

    if entry.get("status") == "approved":
        raise HTTPException(status_code=409, detail="报告已批准发布，无法再修改")

    state = entry.get("state", {})

    state["hitl_decision"] = {
        "action": decision.action,
        "comment": decision.comment,
        "target_focus": decision.target_focus,
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    }

    if decision.fork_version is not None and decision.fork_version > 0:
        # Fork from a historical version: mark fork parent for _reanalyze_sync
        # (_reanalyze_sync handles saving the old state as a version entry)
        target = _history_store.get(thread_id, decision.fork_version)
        if target:
            state["_fork_parent_version"] = decision.fork_version
            logger.info("Forked thread %s from v%d → new branch", thread_id[:12], decision.fork_version)

    _store[thread_id]["state"] = state

    if decision.action in ("rewrite", "reanalyze", "replan"):
        _store[thread_id]["status"] = "running"
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _reanalyze_sync, thread_id, decision.action)

    if decision.action == "approve":
        _store[thread_id]["status"] = "approved"
        # Mark latest version as approved in history store
        latest = _current_db_version(thread_id)
        if latest:
            _history_store.approve(thread_id, latest)
        # Persist to SQLite
        _save_to_db(thread_id, entry)

    report_data = state.get("report_data")
    metrics = report_data.get("metrics") if report_data else None
    error = state.get("error")

    return ReportResponse(
        thread_id=thread_id,
        status=_store[thread_id]["status"],
        report_data=report_data,
        metrics=metrics,
        error=error,
    )


def _reanalyze_sync(thread_id: str, action: str) -> None:
    """Run reanalysis in background thread: Analyst → Reviewer → Writer."""
    import logging
    logger = logging.getLogger(__name__)

    try:
        entry = _store.get(thread_id)
        if not entry:
            return
        state = entry["state"]

        # Extract fork parent before processing (set by submit_decision for historical fork)
        fork_parent = state.pop("_fork_parent_version", None)

        # Inject user feedback into user_request for reanalyze/replan
        comment = state.get("hitl_decision", {}).get("comment", "")
        if comment and action in ("reanalyze", "replan"):
            state["user_request"] = f"{state.get('user_request', '')}\n\n用户反馈意见: {comment}"
            logger.info("Reanalysis with feedback: %s", comment[:100])

        from deerflow.competition.nodes.writer import writer_node

        if action == "rewrite":
            result = writer_node(state)
            state.update(result)
        elif action == "reanalyze":
            from deerflow.competition.nodes.analyst import analyst_node
            from deerflow.competition.nodes.reviewer import reviewer_node

            logger.info("Reanalysis starting for %s", thread_id[:12])
            result = analyst_node(state)
            state.update(result)
            result = reviewer_node(state)
            state.update(result)
            result = writer_node(state)
            state.update(result)
            logger.info("Reanalysis completed for %s", thread_id[:12])
        elif action == "replan":
            from deerflow.competition.nodes.analyst import analyst_node
            from deerflow.competition.nodes.collector import collector_node
            from deerflow.competition.nodes.reviewer import reviewer_node

            logger.info("Replan starting for %s", thread_id[:12])
            result = collector_node(state)
            state.update(result)
            result = analyst_node(state)
            state.update(result)
            result = reviewer_node(state)
            state.update(result)
            result = writer_node(state)
            state.update(result)
            logger.info("Replan completed for %s", thread_id[:12])

        action_labels = {"rewrite": "重写报告", "reanalyze": "重新分析", "replan": "重新搜索"}
        label = f"{action_labels.get(action, action)}"
        _store[thread_id]["state"] = state
        _add_token_entry(thread_id, label)
        _store[thread_id]["status"] = "completed"

        # Save new report as a version after reanalysis completes
        new_report = state.get("report_data")
        if new_report:
            parent = fork_parent if fork_parent is not None else _current_db_version(thread_id)
            _history_store.insert(
                thread_id, parent, "",
                action,
                {"report_data": new_report.model_dump() if hasattr(new_report, "model_dump") else new_report,
                 "comment": state.get("hitl_decision", {}).get("comment", "")},
            )
            logger.info("Saved post-%s report v%d for %s",
                        action, _current_db_version(thread_id), thread_id[:12])
    except Exception as e:
        logger.exception("Reanalysis %s failed: %s", thread_id, e)
        if thread_id in _store:
            _store[thread_id]["status"] = "failed"
            _store[thread_id]["state"]["error"] = str(e)


def _save_to_db(thread_id: str, entry: dict) -> None:
    """Persist an approved report to the SQLite analysis_history table."""
    try:
        from deerflow.competition.db import init_db, record_analysis

        conn = init_db()
        state = entry.get("state", {})
        report = state.get("report_data") or {}
        sections = report.get("sections", [])
        # Extract key findings from report sections
        findings: list[str] = []
        for s in sections:
            if s.get("id") in ("sec-executive-summary", "sec-swot"):
                for line in s.get("content", "").split("\n"):
                    stripped = line.strip("- ").strip()
                    if stripped and len(stripped) > 10:
                        findings.append(stripped[:200])
        record_analysis(
            thread_id=thread_id,
            query=entry.get("query", ""),
            products=entry.get("products", []),
            persona=report.get("persona", "pm"),
            deep_mode=False,
            key_findings=findings[:5],
            report_path="",
            metrics=report.get("metrics") or {},
            report_data=report,
            conn=conn,
        )
        conn.close()
        logger.info("Saved approved report %s to DB", thread_id[:12])
    except Exception as e:
        logger.exception("Failed to save report %s to DB: %s", thread_id, e)


def _render_report_markdown(entry: dict) -> str:
    """Render a competition report as a Markdown string for export."""
    report = entry.get("state", {}).get("report_data") or {}
    lines: list[str] = []
    lines.append(f"# {report.get('title', '竞品分析报告')}")
    lines.append(f"\n*生成时间: {report.get('generated_at', '')}*")
    lines.append(f"*视角: {report.get('persona', '')}*")
    lines.append(f"*产品: {', '.join(report.get('products', []))}*\n")
    lines.append("---\n")
    for section in report.get("sections", []):
        lines.append(f"## {section.get('title', '')}")
        content = section.get("content", "")
        if section.get("content_type") == "table":
            lines.append(content)
        else:
            lines.append(content)
        lines.append("")
    # Metrics footer
    metrics = report.get("metrics") or {}
    if metrics:
        lines.append("---\n")
        lines.append("## 报告指标")
        lines.append(f"- 覆盖率: {metrics.get('coverage', 0):.0%}")
        lines.append(f"- 交叉验证率: {metrics.get('cross_validation_rate', 0):.0%}")
        lines.append(f"- 溯源完成度: {metrics.get('trace_completeness', 0):.0%}")
    return "\n".join(lines)


# ── Survey Response `[§14, feature flag]` ──


class SurveyResponseRequest(BaseModel):
    """Single survey response submission. `[§14 问卷回传]`"""

    question_id: str
    answer: str | list[str]
    respondent_label: str = "anonymous"


@router.post("/report/{thread_id}/survey-response")
async def submit_survey_response(thread_id: str, response: SurveyResponseRequest) -> dict:
    """Submit a survey response for a running questionnaire. `[§14 问卷调研]`

    Responses are accumulated in state["survey_responses"] (Annotated[list, op_add]).
    When sufficient responses are collected, Collector can be re-invoked to
    structure them as CollectedDataPoint[] for Analyst consumption.

    Currently gated: enable_questionnaire=False by default. This endpoint is
    reserved for the §14 questionnaire feedback loop.
    """
    entry = _store.get(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

    state = entry.get("state", {})
    if not state.get("enable_questionnaire"):
        raise HTTPException(
            status_code=409,
            detail="问卷功能未开启（enable_questionnaire=False）。请先启用。",
        )

    questionnaire = state.get("questionnaire")
    if not questionnaire:
        raise HTTPException(status_code=409, detail="该分析尚未生成问卷。请等待 Collector 完成后重试。")

    # Validate question_id exists in questionnaire
    valid_ids = {q.get("id") for q in questionnaire.get("questions", [])}
    if response.question_id not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 question_id: {response.question_id}。有效 ID: {valid_ids}",
        )

    entry_data = {
        "question_id": response.question_id,
        "answer": response.answer,
        "respondent_label": response.respondent_label,
        "submitted_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    }

    # Append to survey_responses (op_add accumulator in state)
    existing = state.get("survey_responses") or []
    existing.append(entry_data)
    state["survey_responses"] = existing
    _store[thread_id]["state"] = state

    logger.info("Survey response submitted: thread=%s q=%s label=%s",
                thread_id[:12], response.question_id, response.respondent_label)

    return {"status": "received", "total_responses": len(existing)}


@router.get("/report/{thread_id}/export")
async def export_report(thread_id: str, format: str = "md"):
    """Export an approved report as Markdown (md) or JSON (json)."""
    from fastapi.responses import PlainTextResponse

    entry = _store.get(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

    if entry.get("status") != "approved":
        raise HTTPException(status_code=409, detail="报告尚未批准发布，无法导出")

    if format == "json":
        import json
        report = entry.get("state", {}).get("report_data") or {}
        return PlainTextResponse(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=report-{thread_id[:12]}.json"},
        )

    md = _render_report_markdown(entry)
    return PlainTextResponse(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=report-{thread_id[:12]}.md"},
    )


@router.get("/stream/{thread_id}")
async def stream(thread_id: str, fastapi_request: Request):
    """SSE stream of graph execution events.

    Supports Last-Event-ID header for reconnection (DF-compatible).
    Events are formatted with event:, data:, and id: fields matching
    the DF chat SSE wire format.
    """
    entry = _store.get(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

    last_event_id = fastapi_request.headers.get("Last-Event-ID")

    return StreamingResponse(
        _stream_events_sync(thread_id, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history")
async def list_history(limit: int = Query(default=10, le=50), fastapi_request: Request = None):
    """List recent analysis history, filtered by current user if authenticated."""
    user_id = await _get_user_id(fastapi_request) if fastapi_request else "default"
    history = []
    for tid, entry in list(_store.items()):
        # Filter by user if authenticated
        if user_id != "default":
            owner = _thread_owners.get(tid, "default")
            if owner != user_id:
                continue
        history.append({
            "thread_id": tid,
            "query": entry.get("query", ""),
            "products": entry.get("products", []),
            "status": entry.get("status", "unknown"),
            "created_at": entry.get("created_at", ""),
            "versions": len(_history_store.list_by_thread(tid)),
        })
    # Return most recent first, limited
    history.sort(key=lambda h: h.get("created_at", ""), reverse=True)
    history = history[:limit]
    return {"history": history, "total": len(history), "user_id": user_id}


@router.get("/me")
async def current_user(fastapi_request: Request):
    """Return current user info for the frontend auth state."""
    user_id = await _get_user_id(fastapi_request)
    thread_count = len(_get_user_threads(user_id))
    return {
        "user_id": user_id,
        "authenticated": user_id != "default",
        "thread_count": thread_count,
    }


@router.get("/db-history")
async def list_db_history(limit: int = Query(default=20, le=100)):
    """List analysis records saved to SQLite (approved reports)."""
    try:
        from deerflow.competition.db import init_db
        from deerflow.competition.db import list_history as db_list_history

        conn = init_db()
        records = db_list_history(conn, limit=limit)
        conn.close()
        return {"history": records, "total": len(records)}
    except Exception as e:
        logger.exception("Failed to read DB history: %s", e)
        return {"history": [], "total": 0, "error": str(e)}


@router.get("/db-report/{thread_id}")
async def get_db_report(thread_id: str):
    """Retrieve a saved (approved) report from the SQLite database."""
    try:
        from deerflow.competition.db import get_analysis, init_db

        conn = init_db()
        record = get_analysis(thread_id, conn=conn)
        conn.close()
        if record is None:
            raise HTTPException(status_code=404, detail=f"Report not found in DB: {thread_id}")
        return record
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to read DB report %s: %s", thread_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/db-report/{thread_id}")
async def delete_db_report(thread_id: str):
    """Delete a saved report from the SQLite database."""
    try:
        from deerflow.competition.db import delete_analysis, init_db

        conn = init_db()
        deleted = delete_analysis(thread_id, conn=conn)
        conn.close()
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Report not found: {thread_id}")
        return {"deleted": True, "thread_id": thread_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to delete DB report %s: %s", thread_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/db-report/{thread_id}/pin")
async def pin_db_report(thread_id: str, pinned: bool = True):
    """Pin or unpin a saved report (pinned reports sort first and cannot be deleted)."""
    try:
        from deerflow.competition.db import pin_analysis, init_db

        conn = init_db()
        updated = pin_analysis(thread_id, pinned, conn=conn)
        conn.close()
        if not updated:
            raise HTTPException(status_code=404, detail=f"Report not found: {thread_id}")
        return {"pinned": pinned, "thread_id": thread_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to pin DB report %s: %s", thread_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Execution Replay (P1) ──


@router.get("/report/{thread_id}/timeline")
async def get_execution_timeline(thread_id: str):
    """Get checkpoint timeline for execution replay.

    Returns all checkpoints for a thread as a tree structure,
    suitable for a frontend timeline slider.
    """
    try:
        history = _replay_ops.get_history(thread_id)
        tree = _replay_ops.build_tree(thread_id)
        return {
            "thread_id": thread_id,
            "checkpoints": [
                {
                    "checkpoint_id": h.config.get("configurable", {}).get("checkpoint_id", ""),
                    "parent_checkpoint_id": h.parent_config.get("configurable", {}).get("checkpoint_id") if h.parent_config else None,
                    "created_at": h.created_at,
                    "source": h.metadata.get("source") if h.metadata else None,
                    "step": h.metadata.get("step") if h.metadata else None,
                }
                for h in history
            ],
            "tree": {k: v for k, v in tree.items()},
            "count": len(history),
        }
    except Exception as e:
        logger.exception("Failed to get timeline for %s: %s", thread_id, e)
        return {"thread_id": thread_id, "checkpoints": [], "tree": {}, "count": 0, "error": str(e)}


@router.get("/report/{thread_id}/checkpoint/{checkpoint_id}")
async def get_checkpoint_state(thread_id: str, checkpoint_id: str):
    """Get the full state at a specific checkpoint for replay."""
    try:
        state = _replay_ops.get_state(thread_id, checkpoint_id)
        return {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "state": state.values,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Failed to get checkpoint %s: %s", checkpoint_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Internal ──


def _add_token_entry(thread_id: str, label: str) -> None:
    """Snapshot current cumulative tokens and record a labelled entry.

    Called after each graph run or HITL action so the frontend can render a
    segmented token bar coloured by version.
    """
    from deerflow.competition.executor import get_agent_tokens, get_total_tokens

    total = get_total_tokens()
    agents = get_agent_tokens()
    entries: list[dict] = _store[thread_id].setdefault("token_usage", [])
    prev_total = entries[-1]["cumulative"] if entries else 0
    delta = total - prev_total
    entries.append({
        "label": label,
        "tokens": max(delta, 0),
        "cumulative": total,
        "agents": agents,
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    })
    logger.info("Token entry [%s] for %s: +%d tokens (cumulative %d)", label, thread_id[:12], max(delta, 0), total)


def _finalize_cancelled(thread_id: str) -> None:
    """Mark an analysis as interrupted and persist current state to DB."""
    if thread_id not in _store:
        return
    _store[thread_id]["status"] = "interrupted"
    _store[thread_id]["state"]["error"] = "用户手动终止分析"
    try:
        from deerflow.competition.db import upsert_analysis
        upsert_analysis(
            thread_id=thread_id, status="interrupted",
            user_id=_thread_owners.get(thread_id, "default"),
            query=_store[thread_id].get("query", ""),
            products=_store[thread_id].get("products", []),
        )
    except Exception:
        pass
    _emit_event(thread_id, "end", {"status": "interrupted", "message": "分析已终止"})


def _resolve_and_run_graph(thread_id: str, query: str, explicit_products: list[str]) -> None:
    """ProductResolver (pre-graph) → Orchestrator (graph entry) `[v4 Plan D]`.

    Phase 1 (pre-graph): ProductResolver — LLM extract + search verify + LLM correct
      → verified products → state["target_products"]
    Phase 2 (graph): Orchestrator → Collector → ... — semantic strategy from verified products

    Runs in background thread because LLM + search calls are synchronous and
    take ~2min total, which would block the event loop.

    Checks _cancel_flags at key points for cooperative cancellation.
    """
    import logging
    _log = logging.getLogger(__name__)

    def _cancelled() -> bool:
        return _cancel_flags.pop(thread_id, False)

    # Set cancel checker so LLM calls during product resolution can be interrupted
    from deerflow.competition.executor import set_cancel_checker, clear_cancel_checker
    set_cancel_checker(lambda: _cancel_flags.get(thread_id, False))

    try:
        # ── Phase 1: ProductResolver (pre-graph) ──
        if _cancelled():
            clear_cancel_checker()
            _finalize_cancelled(thread_id)
            return
        # ── Phase 1: ProductResolver (pre-graph) ──
        _emit_event(thread_id, "progress", {
            "phase": "resolving",
            "message": "正在解析竞品名称...",
            "timestamp": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        })

        products: list[str] = []

        if explicit_products:
            for p in explicit_products:
                p = p.strip()
                if p and p not in products:
                    products.append(p)

        if products:
            # Verify/correct explicit products via search + LLM judge
            products = _verify_products_via_search(products, 1, query)

        if not products:
            # No explicit products — extract from query via LLM + search
            _log.info("No explicit products — extracting via ProductResolver")
            products = _llm_extract_products(query, thread_id)

        # Deduplicate while preserving order
        seen: set[str] = set()
        resolved: list[str] = []
        for p in products:
            if p.lower() not in seen:
                seen.add(p.lower())
                resolved.append(p)
        products = resolved

        _log.info("ProductResolver: %s (query: '%.80s')", products, query)

        if not products:
            _log.warning("ProductResolver found 0 products — marking as failed")
            if thread_id in _store:
                _store[thread_id]["status"] = "failed"
                _store[thread_id]["state"]["error"] = (
                    "无法从分析请求中提取竞品名称，请在「竞品名称」输入框中明确指定（逗号分隔）。"
                )
            _emit_event(thread_id, "error", {"error": "无法解析竞品名称", "status": "failed"})
            return

        # Emit products resolved event
        _emit_event(thread_id, "progress", {
            "phase": "resolved",
            "message": f"竞品解析完成: {', '.join(products)}",
            "products": products,
            "timestamp": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        })

        # Update store with verified products
        if thread_id in _store:
            _store[thread_id]["products"] = products
            _store[thread_id]["status"] = "running"
            _store[thread_id]["state"]["target_products"] = products
            _store[thread_id]["state"]["complexity"] = "standard"

        if _cancelled():
            clear_cancel_checker()
            _finalize_cancelled(thread_id)
            return

        # ── Phase 2: Graph (Orchestrator → Collector → ...) ──
        clear_cancel_checker()  # _run_graph_sync sets its own
        _run_graph_sync(thread_id)

    except Exception as e:
        _log.exception("Resolve+graph failed for %s: %s", thread_id, e)
        if thread_id in _store:
            _store[thread_id]["status"] = "failed"
            _store[thread_id]["state"]["error"] = str(e)


def _run_graph_sync(thread_id: str) -> None:
    """Run the competition graph synchronously (called from thread executor).

    LLM calls (langchain) are synchronous and would block the asyncio event loop
    for ~2 minutes. This function runs in a separate thread so the event loop
    stays free to handle other requests.
    """
    try:
        from deerflow.competition.graph import build_competition_graph
        from deerflow.competition.state import CompetitionState

        entry = _store.get(thread_id)
        if not entry:
            return

        from deerflow.competition.graph import register_nodes
        from deerflow.competition.nodes.analyst import analyst_node
        from deerflow.competition.nodes.collector import collector_node
        from deerflow.competition.nodes.error_handler import error_handler_node
        from deerflow.competition.nodes.hitl_gate import hitl_gate_node
        from deerflow.competition.nodes.orchestrator import orchestrator_node
        from deerflow.competition.nodes.reviewer import reviewer_node
        from deerflow.competition.nodes.writer import writer_node

        register_nodes({
            "orchestrator": orchestrator_node,
            "collector": collector_node,
            "analyst": analyst_node,
            "reviewer": reviewer_node,
            "writer": writer_node,
            "hitl_gate": hitl_gate_node,
            "error_handler": error_handler_node,
        })

        graph = build_competition_graph(checkpointer=_replay_saver)
        initial_state = CompetitionState(**entry["state"])

        # ── Set up SSE streaming callback (§19) ──
        # Each LLM call inside nodes will stream token chunks to the frontend
        # via this callback, matching DF chat's messages-tuple SSE format.
        from deerflow.competition.executor import set_stream_callback, clear_stream_callback
        from deerflow.competition.executor import set_cancel_checker, clear_cancel_checker

        _chunk_seq = 0

        def _stream_chunk(agent_name: str, chunk_text: str) -> None:
            nonlocal _chunk_seq
            _chunk_seq += 1
            _emit_event(thread_id, "messages-tuple", [{
                "type": "AIMessageChunk",
                "name": agent_name or "analysis",
                "content": chunk_text,
                "id": f"comp-{thread_id[-8:]}-chunk-{_chunk_seq}",
            }])

        _current_agent: list = [""]

        # Agent display names for the thinking progress events
        _AGENT_LABELS = {
            "Orchestrator": "解析意图", "Collector": "信息采集",
            "Analyst": "对比分析", "Reviewer": "质量审查",
            "Writer": "报告生成",
        }

        def _stream_chunk_labeled(agent_name: str, chunk_text: str) -> None:
            nonlocal _chunk_seq
            # Thinking sentinel: emitted before streaming starts for thinking models.
            # Show a progress indicator so the user knows the agent is working.
            if chunk_text == "\x00THINK\x00":
                label = _AGENT_LABELS.get(agent_name, agent_name or "分析")
                _emit_event(thread_id, "progress", {"message": f"{label} 正在深度思考..."})
                return
            if agent_name and agent_name != _current_agent[0]:
                _current_agent[0] = agent_name
                # Emit agent label as a system chunk
                _emit_event(thread_id, "messages-tuple", [{
                    "type": "AIMessageChunk",
                    "name": "system",
                    "content": f"\n\n**[{agent_name}]** ",
                    "id": f"comp-{thread_id[-8:]}-label-{_chunk_seq}",
                }])
            _stream_chunk(agent_name, chunk_text)

        set_stream_callback(_stream_chunk_labeled)
        set_cancel_checker(lambda: _cancel_flags.get(thread_id, False))

        # Stream execution — updates store + DB on each node completion (§18)
        event_num = 0
        prev_state: dict = {}
        prev_total_tokens = 0
        _NODE_LABELS = {
            "orchestrator": "解析意图", "collector": "信息采集",
            "analyst": "对比分析", "reviewer": "质量审查",
            "writer": "报告生成", "hitl_gate": "等待审批",
        }
        for event in graph.stream(initial_state, {"configurable": {"thread_id": thread_id}}, stream_mode=["values"]):
            event_num += 1

            # Cooperative cancellation — check flag before processing each node boundary
            if _cancel_flags.pop(thread_id, False):
                _finalize_cancelled(thread_id)
                clear_stream_callback()
                clear_cancel_checker()
                return

            if isinstance(event, tuple):
                update = event[-1]
            else:
                update = event
            if isinstance(update, dict):
                _store[thread_id]["state"] = update

                # Detect which node just completed by diffing against previous state
                current_node = None
                progress = None
                if update.get("orchestration_result") and not prev_state.get("orchestration_result"):
                    current_node = "orchestrator"
                elif update.get("collection_summary") and not prev_state.get("collection_summary"):
                    current_node = "collector"
                    progress = f"已采集 {update['collection_summary'].get('total_data_points', 0)} 条数据"
                elif update.get("analysis_result") and not prev_state.get("analysis_result"):
                    current_node = "analyst"; progress = "对比矩阵+SWOT已生成"
                elif update.get("review_verdict") and not prev_state.get("review_verdict"):
                    current_node = "reviewer"; progress = "质量审查完成"
                elif update.get("report_data") and not prev_state.get("report_data"):
                    current_node = "writer"; progress = "报告已生成"
                prev_state = update

                if current_node:
                    from deerflow.competition.db import upsert_analysis
                    from deerflow.competition.executor import get_total_tokens
                    current_total = get_total_tokens()
                    delta_tokens = current_total - prev_total_tokens
                    prev_total_tokens = current_total
                    upsert_analysis(
                        thread_id=thread_id, status="running",
                        current_node=current_node, progress=progress or _NODE_LABELS.get(current_node, ""),
                    )
                    # SSE event (§19)
                    _emit_event(thread_id, "node_end", {
                        "node": current_node,
                        "status": "done",
                        "progress": progress or _NODE_LABELS.get(current_node, ""),
                        "tokens": max(delta_tokens, 0),
                        "timestamp": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
                    })

                flags = []
                if current_node:
                    flags.append(current_node)
                if update.get("error"):
                    flags.append(f"error={update['error'][:50]}")
                logger.info("Analysis %s event#%d: %s", thread_id[:12], event_num, " → ".join(flags) if flags else "init")

        # Emit completion
        _emit_event(thread_id, "end", {"status": "completed"})
        clear_stream_callback()
        clear_cancel_checker()

        _add_token_entry(thread_id, "初始分析")
        _store[thread_id]["status"] = "completed"

        # Persist completion to DB (§18)
        from deerflow.competition.db import upsert_analysis
        state = _store[thread_id]["state"]
        rd = state.get("report_data")
        upsert_analysis(
            thread_id=thread_id, status="completed",
            current_node="", progress="分析完成",
            report_data=rd.model_dump() if hasattr(rd, "model_dump") else rd,
            metrics=(rd.get("metrics") if isinstance(rd, dict) else None),
            token_usage=_store[thread_id].get("token_usage", []),
        )

        # Record initial version in history store
        if _current_db_version(thread_id) is None and _store[thread_id].get("state", {}).get("report_data"):
            rd = _store[thread_id]["state"]["report_data"]
            _history_store.insert(thread_id, None, "", "initial",
                {"report_data": rd.model_dump() if hasattr(rd, "model_dump") else rd})

        logger.info("Analysis %s completed", thread_id)

    except Exception as e:
        logger.exception("Analysis %s failed: %s", thread_id, e)
        clear_stream_callback()
        clear_cancel_checker()
        _emit_event(thread_id, "error", {"error": str(e)[:200], "status": "failed"})
        if thread_id in _store:
            _store[thread_id]["status"] = "failed"
            _store[thread_id]["state"]["error"] = str(e)
            from deerflow.competition.db import upsert_analysis
            upsert_analysis(thread_id=thread_id, status="failed", progress=f"失败: {str(e)[:100]}")


def _stream_events_sync(thread_id: str, last_event_id: str | None = None):
    """SSE event stream — sync generator matching DF's SSE wire format.

    - Uses pre-formatted SSE frames from _emit_event (event: + data: + id:)
    - Supports Last-Event-ID replay for reconnection
    - Heartbeat via SSE comment lines (: heartbeat) every 15s
    - No hard timeout — stays alive as long as the analysis is running
    """
    import time as _time

    q = _get_or_create_queue(thread_id)

    # ── Replay buffered events after Last-Event-ID ──
    if last_event_id:
        buf = _event_buffers.get(thread_id, [])
        replay_started = False
        for seq, frame in buf:
            if not replay_started:
                if f"id: {last_event_id}" in frame:
                    replay_started = True
                continue
            yield frame
        if replay_started:
            pass  # Client is catching up — continue to live stream

    # ── Initial metadata + state ──
    entry = _store.get(thread_id)
    if entry:
        init_id = f"{thread_id[-8:]}-init"
        yield _format_sse("metadata", {
            "run_id": thread_id,
            "thread_id": thread_id,
            "query": entry.get("query", ""),
            "products": entry.get("products", []),
        }, event_id=init_id)
        yield _format_sse("values", {
            "status": entry.get("status", "unknown"),
            "thread_id": thread_id,
        }, event_id=f"{thread_id[-8:]}-values")
    else:
        yield _format_sse("error", {"error": "Thread not found"}, event_id=f"{thread_id[-8:]}-err")
        return

    # ── Live event loop ──
    last_heartbeat = _time.monotonic()
    heartbeat_interval = 15

    while True:
        try:
            frame = q.get(timeout=heartbeat_interval)
            yield frame
            last_heartbeat = _time.monotonic()

            # Detect end/error to terminate stream
            if 'event: error' in frame or 'event: end' in frame:
                return

        except _queue_mod.Empty:
            # No event — send SSE comment heartbeat (same format as DF)
            elapsed = _time.monotonic() - last_heartbeat
            if elapsed >= 300:  # 5 min of total idle → terminate
                yield _format_sse("end", {"status": "timeout"}, event_id=f"{thread_id[-8:]}-timeout")
                return
            yield ": heartbeat\n\n"
