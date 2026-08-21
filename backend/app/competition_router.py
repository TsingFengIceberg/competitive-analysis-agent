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
import queue as _queue_mod
import threading

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from competition.branchtree.checkpoint_ops import CheckpointOps
from competition.branchtree.store import BranchSnapshotStore

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
    uploaded_files: list[str] | None = Field(default=None, description="Sandbox paths of uploaded files")
    context_report: dict | None = Field(default=None, description="Previous report data to use as analysis context")
    confirmation_mode: str = Field(default="auto", description="auto | always | skip")


class AnalyzeResponse(BaseModel):
    """Response after starting an analysis."""

    thread_id: str
    status: str = "running"  # "running" | "awaiting_confirmation" | "completed" | "failed"
    analysis_brief: dict | None = None


class ReportResponse(BaseModel):
    """Response for report retrieval."""

    thread_id: str
    status: str
    query: str = ""
    title: str = ""
    report_data: dict | None = None
    metrics: dict | None = None
    error: str | None = None
    history_count: int = 0
    token_usage: list[dict] = []
    created_at: str | None = None
    phases: list[dict] = []
    analysis_brief: dict | None = None


class ConfirmAnalysisRequest(BaseModel):
    """Editable Analysis Brief submitted to start a waiting thread."""

    expected_revision: int = Field(..., ge=1)
    brief: dict


class SettingsUpdateRequest(BaseModel):
    settings: dict
    expected_updated_at: str = ""


class SettingsConnectionRequest(BaseModel):
    kind: str
    name: str = Field(..., min_length=1, max_length=120)


class StreamEvent(BaseModel):
    """Single SSE event payload."""

    event: str  # "node_start" | "node_end" | "state_update" | "error" | "end"
    node: str | None = None
    data: dict | None = None


class PhaseTraceEntry(BaseModel):
    """Per-phase trace data for the process viewer panel (R9/R10)."""

    phase_key: str
    label: str
    icon: str
    agent_name: str
    tokens: int = 0
    start_time: str | None = None
    end_time: str | None = None
    duration_ms: int = 0
    status: str = "completed"
    content: dict[str, str] = {}
    details: list[dict] = []
    json_output: dict | None = None


class GenerationTrace(BaseModel):
    """One generation unit (initial analysis or HITL re-execution)."""

    version: int
    generation_id: str | None = None
    report_version: int | None = None
    parent_report_version: int | None = None
    association: str = "unresolved"
    action: str
    label: str
    phases: list[PhaseTraceEntry]


class DagNode(BaseModel):
    id: str
    label: str
    icon: str
    status: str


class DagEdge(BaseModel):
    id: str
    from_: str = Field(alias="from")
    to: str
    type: str
    active: bool = False

    model_config = {"populate_by_name": True}


class DagStructure(BaseModel):
    nodes: list[DagNode]
    edges: list[DagEdge]


class TraceResponse(BaseModel):
    """Full execution trace for the process viewer panel."""

    thread_id: str
    generations: list[GenerationTrace]
    dag: DagStructure
    current_version: int | None = None


# ── Runtime store (status, current state, token usage — ephemeral) ──
# Version history is persisted in _history_store (SQLite branch_snapshots).

_store: dict[str, dict] = {}
_cancel_flags: dict[str, bool] = {}  # thread_id → cancelled (cooperative cancellation)

# ── SSE streaming (§19) ──
#
# A thread can have more than one browser subscribed to its stream (for
# example, the user may have the report open in two tabs).  A single queue per
# thread makes those clients compete for events, so live delivery is modelled
# as one bounded queue per subscriber.  ``_stream_queues`` remains as a small
# compatibility/orphan queue for older tests and for events emitted before a
# subscriber has connected; replay is still sourced from ``_event_buffers``.
_stream_queues: dict[str, _queue_mod.Queue] = {}
_stream_subscribers: dict[str, set[_queue_mod.Queue]] = {}
_stream_lock = threading.RLock()
_event_counters: dict[str, int] = {}  # thread_id → monotonic event id
_event_buffers: dict[str, list[tuple[int, str]]] = {}  # thread_id → [(id, formatted_sse_line)]
MAX_BUFFERED_EVENTS = 128


def _get_or_create_queue(thread_id: str) -> _queue_mod.Queue:
    """Get or create a thread-safe queue for a thread's SSE stream."""
    with _stream_lock:
        if thread_id not in _stream_queues:
            _stream_queues[thread_id] = _queue_mod.Queue(maxsize=1024)
        return _stream_queues[thread_id]


def _reset_stream_queue(thread_id: str) -> None:
    """Reset the compatibility queue without disconnecting live subscribers.

    Re-analysis starts a new generation, but existing browser connections must
    stay subscribed so they receive the new generation's events.
    """
    with _stream_lock:
        _stream_queues[thread_id] = _queue_mod.Queue(maxsize=1024)


def _register_stream_subscriber(thread_id: str) -> _queue_mod.Queue:
    """Create and register an independent bounded queue for one SSE client."""
    subscriber: _queue_mod.Queue = _queue_mod.Queue(maxsize=1024)
    with _stream_lock:
        _stream_subscribers.setdefault(thread_id, set()).add(subscriber)
    return subscriber


def _unregister_stream_subscriber(thread_id: str, subscriber: _queue_mod.Queue) -> None:
    """Remove a disconnected SSE client and release its queue."""
    with _stream_lock:
        subscribers = _stream_subscribers.get(thread_id)
        if not subscribers:
            return
        subscribers.discard(subscriber)
        if not subscribers:
            _stream_subscribers.pop(thread_id, None)


def _put_queue_frame(
    q: _queue_mod.Queue,
    frame: str,
    thread_id: str,
    event_type: str,
) -> None:
    """Put a frame into one subscriber queue, isolating slow consumers."""
    try:
        q.put_nowait(frame)
        return
    except _queue_mod.Full:
        # Drop the oldest live frame for this client only.  A terminal frame
        # therefore remains deliverable even when that client is slow.
        try:
            q.get_nowait()
        except _queue_mod.Empty:
            pass
        try:
            q.put_nowait(frame)
        except _queue_mod.Full:
            logging.getLogger(__name__).warning(
                "SSE live queue saturated for %s [%s]; dropped frame",
                thread_id[:12],
                event_type,
            )


def _put_stream_frame(thread_id: str, frame: str, event_type: str) -> None:
    # Keep the legacy/orphan queue behaviour for callers that emit before a
    # client connects, while broadcasting the same frame to every subscriber.
    with _stream_lock:
        queues = [_get_or_create_queue(thread_id)]
        queues.extend(_stream_subscribers.get(thread_id, ()))
        unique_queues = list(dict.fromkeys(queues))
    for q in unique_queues:
        _put_queue_frame(q, frame, thread_id, event_type)


def _format_sse(event: str, data, *, event_id: str | None = None) -> str:
    """Format a single SSE frame matching the standard SSE wire format.

    Field order: event: -> data: -> id: (optional) -> blank line.
    """
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


def _frame_event_id(frame: str) -> str | None:
    """Return the SSE id from a formatted frame, if it has one."""
    for line in frame.splitlines():
        if line.startswith("id: "):
            return line[4:]
    return None


def _emit_event(thread_id: str, event_type: str, data: dict) -> None:
    """Emit an SSE event into the thread's stream queue (thread-safe).

    Events are assigned monotonic IDs and buffered for Last-Event-ID replay.
    Uses _get_or_create_queue so events are buffered even if the SSE client
    hasn't connected yet — critical for the ~2min product-resolution phase.
    """
    import logging
    _log = logging.getLogger(__name__)
    try:
        with _stream_lock:
            if event_type == "end" and data.get("status") == "interrupted":
                existing = _event_buffers.get(thread_id, [])
                if existing and "event: end" in existing[-1][1] and '"status": "interrupted"' in existing[-1][1]:
                    return
            # Assign monotonic event ID
            seq = _event_counters.get(thread_id, 0) + 1
            _event_counters[thread_id] = seq
            event_id = f"{thread_id[-8:]}-{seq:05d}"

            # Format and buffer
            frame = _format_sse(event_type, data, event_id=event_id)

            # Circular buffer for replay
            buf = _event_buffers.setdefault(thread_id, [])
            buf.append((seq, frame))
            if len(buf) > MAX_BUFFERED_EVENTS:
                del buf[: len(buf) - MAX_BUFFERED_EVENTS]

        # Push to live queue
        _put_stream_frame(thread_id, frame, event_type)
        _log.info("SSE emit #%d [%s]", seq, event_type)
    except Exception:
        _log.exception("SSE emit failed for %s [%s]", thread_id, event_type)


# ── User helpers (§User System) ──


def _get_user_id(request: Request | None = None) -> str:
    """Get the current user ID from JWT cookie, falling back to 'default'."""
    if request is None:
        return "default"
    token = request.cookies.get("access_token", "")
    if not token:
        return "default"
    try:
        import jwt as _jwt
        payload = _jwt.decode(token, options={"verify_signature": False})
        user_id = payload.get("sub", "")
        return user_id if user_id else "default"
    except Exception:
        return "default"


async def _ensure_demo_user() -> None:
    """No-op: independent gateway has no auth DB. All users are 'default'."""
    logger.info("Demo user: not required (no-auth mode)")


def _associate_thread(thread_id: str, user_id: str) -> None:
    """Record which user owns a thread."""
    if user_id and user_id != "default":
        _thread_owners[thread_id] = user_id


def _get_user_threads(user_id: str) -> list[str]:
    """Return all thread_ids belonging to a user."""
    if user_id == "default":
        return list(_store.keys())
    return [tid for tid, uid in _thread_owners.items() if uid == user_id]


def _assert_thread_access(thread_id: str, request: Request | None = None) -> None:
    """Reject cross-user access while preserving the local debug-mode fallback."""
    user_id = _get_user_id(request)
    if user_id == "default":
        return
    owner = _thread_owners.get(thread_id)
    if owner is None:
        try:
            from competition.db import get_analysis, init_db
            conn = init_db()
            record = get_analysis(thread_id, conn=conn)
            conn.close()
            owner = record.get("user_id") if record else None
            if owner:
                _thread_owners[thread_id] = owner
        except Exception:
            owner = None
    if owner != user_id:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")


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


def _load_phases(thread_id: str) -> list[dict]:
    """Load persisted phase records from DB for history reconstruction."""
    try:
        from competition.db import get_phases, init_db
        conn = init_db()
        phases = get_phases(thread_id, conn=conn)
        conn.close()
        return phases
    except Exception:
        return []


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


def _safe_dict(obj) -> dict | None:
    """Convert a Pydantic model or dict to a plain dict for JSON serialization."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return None


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
        from competition.executor import execute_agent

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



def _verify_products_via_search(
    candidates: list[str],
    strictness: int = 1,
    query_hint: str = "",
    *,
    return_audit: bool = False,
    preserve_membership: bool = False,
) -> list[str] | tuple[list[str], list[dict]]:
    """Verify & correct product names: search for ground truth, then LLM judges.

    Step 2-3 of the resolution pipeline:
      Step 2: Search each candidate (no judgment — just collect titles).
      Step 3: Single LLM call judges all candidates against search titles + query context.
              Corrects typos, expands partial names, keeps confirmed names.

    Deleted: alias table triage (C1/C2/C3), canonical name extraction, all string-matching rules.
    Reason: hardcoded rules can't understand domain context (e.g. "Power" + "数据分析工具" = "Power BI").
    """
    try:
        from competition.tools.search import search as web_search
    except ImportError:
        audit = [{"requested_name": name, "resolved_name": name, "confidence": "low"} for name in candidates]
        return (list(candidates), audit) if return_audit else candidates

    # ── Step 2: Search each candidate (parallel, collect titles only, no judgment) ──
    # Strategy: dual queries per candidate:
    #   1. Context search (quoted): candidate + co-competitor → competitive landscape
    #   2. Independent search (UNquoted): candidate alone → search engine auto-corrects typos
    # Quoted search ("Noton") forces exact-match, blocking auto-correction.
    # Unquoted search (Noton product) lets the engine suggest "Notion" in results.
    search_titles: dict[str, list[str]] = {}

    def _search_one(name: str) -> tuple[str, list[str]] | None:
        """Search for a single candidate. Returns (name, titles) or None if discarded."""
        # Small jitter to avoid thundering herd on search API (especially DDG rate limits)
        import random as _random
        import time as _time
        _time.sleep(_random.uniform(0, 0.5))
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

            if not all_titles:
                # Fallback: direct name search (works across all strictness levels)
                resp3 = web_search(name, max_results=3)
                if resp3 and resp3.results:
                    all_titles = [r.title if hasattr(r, "title") else r.get("title", "") for r in resp3.results]
                    logger.info("Product '%s' — fallback search found %d results", name, len(all_titles))
                elif strictness >= 2:
                    logger.warning("Product '%s' — no search results, keeping as-is", name)
                else:
                    logger.info("Product '%s' discarded (no search results)", name)
                    return None
        except Exception:
            if strictness >= 2:
                logger.warning("Search failed for '%s' — keeping", name)
            else:
                logger.info("Product '%s' discarded (search error)", name)
                return None

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
        audit = [{"requested_name": name, "resolved_name": name, "confidence": "low"} for name in candidates]
        result = list(candidates) if preserve_membership else []
        return (result, audit) if return_audit else result

    # ── Step 3: LLM judges all candidates at once ──
    resolved = _llm_judge_and_correct(search_titles, query_hint)

    # Merge: LLM output drives, fall back to originals for anything missing
    result: list[str] = []
    audit: list[dict] = []
    accepted_names: set[str] = set()
    for name in candidates:
        if name in resolved:
            decision = resolved[name]
            corrected = decision["resolved"]
            confidence = decision["confidence"]
            if preserve_membership and (confidence != "high" or corrected.casefold() in accepted_names):
                corrected = name
            if corrected != name:
                logger.info("LLM judge: '%s' → '%s'", name, corrected)
            else:
                logger.info("LLM judge: '%s' confirmed", name)
            result.append(corrected)
            accepted_names.add(corrected.casefold())
            audit.append({"requested_name": name, "resolved_name": corrected, "confidence": confidence})
        else:
            logger.info("LLM judge: '%s' not in response — keeping original", name)
            result.append(name)
            audit.append({"requested_name": name, "resolved_name": name, "confidence": "low"})

    return (result, audit) if return_audit else result


def _llm_judge_and_correct(
    search_titles: dict[str, list[str]],
    query_hint: str = "",
) -> dict[str, dict[str, str]]:
    """Single LLM call: judge all candidates against search titles + query context.

    Replaces the old Phase 2 batch LLM + all C1/C2/C3 rules. The LLM sees:
      - The user's original query (domain context)
      - Each candidate name
      - Search result titles for that candidate (ground truth)

    Returns a mapping of original_name → resolved_name.
    Candidates not in the returned dict are kept as-is by the caller.
    """
    try:
        from competition.executor import execute_agent
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
        result: dict[str, dict[str, str]] = {}
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
                result[orig] = {"resolved": orig, "confidence": "low"}
            else:
                normalized_confidence = confidence if confidence in {"high", "medium", "low"} else "low"
                result[orig] = {"resolved": resolved, "confidence": normalized_confidence}
                logger.debug("LLM judge: '%s' → '%s' [%s]", orig, resolved, confidence)

        corrected = sum(1 for k, v in result.items() if v["resolved"].lower() != k.lower())
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
    """Create an analysis thread and start only after its Brief is effective."""
    import uuid
    from datetime import UTC, datetime

    from competition.brief import brief_from_request_with_optional_model, detect_confirmation_mode, validate_confirmation_brief
    from competition.db import claim_analysis_start, init_db, upsert_analysis
    from competition.db import list_history as _db_list_history

    thread_id = f"comp-{uuid.uuid4().hex[:12]}"
    user_id = _get_user_id(fastapi_request)
    _associate_thread(thread_id, user_id)

    mode = detect_confirmation_mode(request.query, request.confirmation_mode)
    brief_builder = brief_from_request_with_optional_model
    brief_future = asyncio.get_event_loop().run_in_executor(
        None, brief_builder, request.query, request.target_products, request.industry, request.persona,
    )
    brief = await brief_future if brief_future is not None else brief_builder(
        request.query, request.target_products, request.industry, request.persona,
    )
    if mode == "skip" and brief.readiness != "ready":
        raise HTTPException(
            status_code=422,
            detail={"message": "confirmation_mode=skip requires at least two clear products and an unambiguous scope", "analysis_brief": brief.model_dump()},
        )

    # Persist to DB on creation (§18)
    # Generate initial title: "新建分析 {N}"
    conn = init_db()
    existing_count = len(_db_list_history(conn, limit=1000))
    conn.close()
    initial_title = f"新建分析 {existing_count + 1}"

    # Store entry immediately — frontend can start polling right away
    _store[thread_id] = {
        "status": "awaiting_confirmation",
        "state": {
            "messages": [],
            "user_request": request.query,
            "target_products": brief.target_products,
            "analysis_brief": brief.model_dump(),
            "persona": request.persona,
            "industry": request.industry,
            "collected_data": [],
            "context_report": request.context_report,
        },
        "created_at": datetime.now(UTC).isoformat(),
        "query": request.query,
        "products": brief.target_products,
        "title": initial_title,
    }

    upsert_analysis(
        thread_id=thread_id, status="awaiting_confirmation", user_id=user_id,
        query=request.query, products=brief.target_products,
        industry=request.industry, persona=request.persona,
        title=initial_title, analysis_brief=brief.model_dump(),
    )

    if mode == "always" or brief.readiness != "ready":
        return AnalyzeResponse(thread_id=thread_id, status="awaiting_confirmation", analysis_brief=brief.model_dump())

    confirmed = validate_confirmation_brief(brief).model_copy(update={
        "confirmation_source": "bypass" if mode == "skip" else "auto",
    })
    result = claim_analysis_start(
        thread_id, brief.revision, confirmed.model_dump(),
        confirmation_source="bypass" if mode == "skip" else "auto",
    )
    if result.get("result") != "claimed":
        raise HTTPException(status_code=409, detail="Unable to claim analysis start")
    _start_analysis_worker(thread_id, request.query, confirmed.model_dump(), user_id)

    return AnalyzeResponse(thread_id=thread_id, status="running", analysis_brief=confirmed.model_dump())


def _start_analysis_worker(thread_id: str, query: str, analysis_brief: dict, user_id: str = "default") -> None:
    """Submit exactly one resolver/graph worker after the DB claim."""
    entry = _store.get(thread_id)
    if entry is not None:
        entry["status"] = "running"
        entry.setdefault("state", {})["analysis_brief"] = analysis_brief
        entry["state"]["target_products"] = analysis_brief.get("target_products", [])
    try:
        asyncio.get_event_loop().run_in_executor(
            None, _resolve_and_run_graph, thread_id, query,
            analysis_brief.get("target_products", []), user_id, analysis_brief,
        )
    except Exception as exc:
        from competition.db import restore_analysis_to_waiting
        restore_analysis_to_waiting(thread_id, error=f"Worker submission failed: {exc}")
        if entry is not None:
            entry["status"] = "awaiting_confirmation"
        raise HTTPException(status_code=503, detail="Analysis worker could not be started") from exc


@router.post("/{thread_id}/confirm", response_model=AnalyzeResponse)
async def confirm_analysis(thread_id: str, body: ConfirmAnalysisRequest, fastapi_request: Request) -> AnalyzeResponse:
    """Validate and atomically start a waiting Analysis Brief."""
    from competition.brief import validate_confirmation_brief
    from competition.db import claim_analysis_start, init_db

    _assert_thread_access(thread_id, fastapi_request)

    entry = _store.get(thread_id)
    if entry is None:
        entry = _restore_state_from_db(thread_id)
        if entry is not None:
            _store[thread_id] = entry
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

    try:
        confirmed = validate_confirmation_brief(body.brief)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    conn = init_db()
    try:
        result = claim_analysis_start(thread_id, body.expected_revision, confirmed.model_dump(), conn=conn)
    finally:
        conn.close()
    if result.get("result") == "not_found":
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")
    if result.get("result") == "conflict":
        raise HTTPException(status_code=409, detail={"message": "Brief revision or lifecycle conflict", "analysis_brief": result.get("brief")})
    if result.get("result") == "idempotent":
        return AnalyzeResponse(thread_id=thread_id, status=result.get("status", "running"), analysis_brief=result.get("brief"))

    _start_analysis_worker(thread_id, result.get("query", entry.get("query", "")), result["brief"], result.get("user_id", "default"))
    return AnalyzeResponse(thread_id=thread_id, status="running", analysis_brief=result["brief"])


@router.post("/{thread_id}/cancel")
async def cancel_analysis(thread_id: str, fastapi_request: Request) -> dict:
    """Cancel a running analysis. Data is preserved with status='interrupted'.

    Uses cooperative cancellation — the background thread checks the flag
    at node boundaries and exits gracefully, saving current state to DB.
    """
    _assert_thread_access(thread_id, fastapi_request)
    entry = _store.get(thread_id)
    if entry is None:
        entry = _restore_state_from_db(thread_id)
        if entry is not None:
            _store[thread_id] = entry
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

    if entry.get("status") == "awaiting_confirmation":
        entry["status"] = "interrupted"
        entry.setdefault("state", {})["error"] = "用户手动终止分析"
        try:
            from competition.db import upsert_analysis
            upsert_analysis(
                thread_id=thread_id, status="interrupted",
                user_id=_thread_owners.get(thread_id, "default"),
                query=entry.get("query", ""), products=entry.get("products", []),
            )
        except Exception:
            logger.exception("Failed to persist awaiting cancellation for %s", thread_id)
        return {"thread_id": thread_id, "status": "interrupted", "message": "Analysis cancelled before confirmation"}

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
        from competition.db import upsert_analysis
        upsert_analysis(
            thread_id=thread_id, status="interrupted",
            user_id=_thread_owners.get(thread_id, "default"),
            query=_store[thread_id].get("query", ""),
            products=_store[thread_id].get("products", []),
        )
    except Exception:
        pass

    # Notify every SSE client through the same monotonic/replayable path as
    # graph events.  The old code only wrote to the shared queue, so one tab
    # could consume the cancellation event before another tab saw it.
    _emit_event(
        thread_id,
        "end",
        {"status": "interrupted", "message": "分析已终止"},
    )

    return {"thread_id": thread_id, "status": "cancelling", "message": "Cancellation requested"}


@router.get("/report/{thread_id}", response_model=ReportResponse)
async def get_report(
    thread_id: str,
    summary: bool = Query(False, description="Return a lightweight polling payload while analysis is active"),
    fastapi_request: Request = None,
) -> ReportResponse:
    """Get the generated report for a completed analysis."""
    _assert_thread_access(thread_id, fastapi_request)
    entry = _store.get(thread_id)
    if entry is None:
        # Fallback: load from SQLite (survives gateway restart)
        from competition.db import get_analysis, init_db
        conn = init_db()
        db_record = get_analysis(thread_id, conn=conn)
        conn.close()
        if db_record is None:
            raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

        history = _list_history(thread_id)
        record_status = db_record.get("status", "unknown")
        compact = summary and record_status not in {"completed", "approved", "failed", "interrupted", "error"}
        return ReportResponse(
            thread_id=thread_id,
            status=record_status,
            query=db_record.get("query", ""),
            title=db_record.get("title", ""),
            report_data=None if compact else db_record.get("report_data"),
            metrics=None if compact else db_record.get("metrics"),
            error=None,
            history_count=len(history),
            token_usage=[] if compact else db_record.get("token_usage", []),
            created_at=db_record.get("created_at"),
            phases=[] if compact else _load_phases(thread_id),
            analysis_brief=db_record.get("analysis_brief"),
        )

    status = entry.get("status", "unknown")
    report_data = entry.get("state", {}).get("report_data")
    metrics = entry.get("state", {}).get("report_data", {}).get("metrics") if report_data else None
    error = entry.get("state", {}).get("error")
    history = _list_history(thread_id)
    token_usage_list = entry.get("token_usage", [])

    compact = summary and status not in {"completed", "approved", "failed", "interrupted", "error"}
    return ReportResponse(
        thread_id=thread_id,
        status=status,
        query=entry.get("query", ""),
        title=entry.get("title", ""),
        report_data=None if compact else report_data,
        metrics=None if compact else metrics,
        error=error,
        history_count=len(history),
        token_usage=[] if compact else token_usage_list,
        created_at=entry.get("created_at"),
        phases=[] if compact else _load_phases(thread_id),
        analysis_brief=entry.get("state", {}).get("analysis_brief"),
    )


@router.get("/report/{thread_id}/history")
async def get_report_history(thread_id: str, fastapi_request: Request = None):
    """Get report revision history (from persisted BranchSnapshotStore)."""
    _assert_thread_access(thread_id, fastapi_request)
    entry = _store.get(thread_id)
    if entry is None:
        # Fallback: return history from DB even when _store is gone (gateway restart)
        from competition.db import get_analysis, init_db
        conn = init_db()
        db_record = get_analysis(thread_id, conn=conn)
        conn.close()
        if db_record is None:
            raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")
        history = _list_history(thread_id)
        return {"history": history, "count": len(history)}
    history = _list_history(thread_id)
    return {"history": history, "count": len(history)}


@router.get("/report/{thread_id}/trace")
async def get_execution_trace(thread_id: str, fastapi_request: Request = None) -> dict:
    """Return per-phase trace data for ALL analysis generations (R9/R10 process viewer)."""
    _assert_thread_access(thread_id, fastapi_request)
    from competition.db import get_phases, init_db

    conn = init_db()
    phase_rows = get_phases(thread_id, conn=conn)
    conn.close()

    # Keep the integer grouping for the legacy DAG calculation. New rows are
    # grouped by opaque generation_id below so report versions never drift from
    # reanalysis rounds or forks.
    version_phases: dict[int, list[dict]] = {}
    for p in phase_rows:
        v = p.get("version", 0)
        version_phases.setdefault(v, []).append(p)

    history_rows: list[dict] = []
    try:
        history_rows = _history_store.list_by_thread(thread_id)
    except Exception:
        pass

    version_actions = {row["version"]: row.get("action", "initial") for row in history_rows}
    exact_reports: dict[str, dict] = {}
    for row in history_rows:
        metadata = row.get("metadata_json") or {}
        generation_id = metadata.get("generation_id")
        if generation_id:
            exact_reports[str(generation_id)] = row

    action_label_map = {"initial": "初始分析", "rewrite": "重写", "reanalyze": "重分析", "replan": "重采集"}
    agent_map = {
        "orchestrator": "Orchestrator", "collector": "Collector",
        "analyst": "Analyst", "reviewer": "Reviewer",
        "writer": "Writer", "hitl_gate": "HITL Gate",
    }

    generations: list[GenerationTrace] = []
    grouped_phases: dict[tuple[str, str], list[dict]] = {}
    for phase in phase_rows:
        generation_id = phase.get("generation_id")
        group_key = ("exact", str(generation_id)) if generation_id else ("legacy", str(phase.get("version", 0)))
        grouped_phases.setdefault(group_key, []).append(phase)

    def _legacy_association(version: int) -> tuple[int | None, str, dict | None]:
        candidates = [row for row in history_rows if row.get("action", "initial") == version_actions.get(version, "initial")]
        if len(candidates) == 1:
            return candidates[0].get("version"), "legacy_inferred", candidates[0]
        return None, "unresolved", None

    for (association_kind, group_id), group_rows in sorted(grouped_phases.items(), key=lambda item: min(
        (row.get("start_time") or "") for row in item[1]
    )):
        version = int(group_rows[0].get("version", 0))
        exact_row = exact_reports.get(group_id) if association_kind == "exact" else None
        report_version = exact_row.get("version") if exact_row else None
        association = "exact" if exact_row else ("unresolved" if association_kind == "exact" else "legacy_inferred")
        if not exact_row and association_kind == "legacy":
            report_version, association, exact_row = _legacy_association(version)
        action = (exact_row or {}).get("action") if exact_row else version_actions.get(version, "initial")
        action = action or "initial"
        base_label = action_label_map.get(action, action)
        label = base_label if report_version in (None, 1) else f"{base_label} #{report_version}"
        if report_version is None and association_kind == "exact":
            label = f"{base_label}（未生成报告）"

        phases = []
        for p in group_rows:
            agent_name = p["phase_key"]
            for prefix, name in agent_map.items():
                if p["phase_key"].startswith(prefix):
                    agent_name = name
                    break
            start = p.get("start_time")
            end = p.get("end_time")
            duration_ms = 0
            if start and end:
                try:
                    from datetime import datetime as _dt
                    s = _dt.fromisoformat(start)
                    e = _dt.fromisoformat(end)
                    duration_ms = int((e - s).total_seconds() * 1000)
                except Exception:
                    pass

            phases.append(PhaseTraceEntry(
                phase_key=p["phase_key"], label=p["label"], icon=p["icon"],
                agent_name=agent_name, tokens=p.get("tokens", 0),
                start_time=start, end_time=end, duration_ms=duration_ms,
                status=p.get("status", "completed"),
                content=p.get("content", {}), details=p.get("details", []),
                json_output=p.get("json_output"),
            ))

        generations.append(GenerationTrace(
            version=version, generation_id=(group_id if association_kind == "exact" else None),
            report_version=report_version,
            parent_report_version=(exact_row or {}).get("parent_version") if exact_row else None,
            association=association, action=action, label=label, phases=phases,
        ))

    # Build dynamic DAG from actual execution data (not hardcoded)
    # Collect all phase keys and detect feedback loops from execution history
    all_phase_keys: set[str] = set()
    for phases in version_phases.values():
        for p in phases:
            all_phase_keys.add(p["phase_key"])

    def _node_ran(node_id: str) -> bool:
        return any(k == node_id or k.startswith(node_id + "_") or k.startswith(node_id) for k in all_phase_keys)

    # Detect feedback loops: if collector/analyst/writer ran in multiple versions, a loop happened
    collector_gens = {v for v, phases in version_phases.items()
                      if any(p["phase_key"].startswith("collector") for p in phases)}
    has_reviewer_feedback = len(collector_gens) > 1
    has_hitl_replan = any(a == "replan" for a in version_actions.values())
    has_hitl_reanalyze = any(a == "reanalyze" for a in version_actions.values())
    has_hitl_rewrite = any(a == "rewrite" for a in version_actions.values())

    dag = DagStructure(
        nodes=[
            DagNode(id="orchestrator", label="解析意图", icon="🎯", status="done" if _node_ran("orchestrator") else "waiting"),
            DagNode(id="collector", label="信息采集", icon="🔍", status="done" if _node_ran("collector") else "waiting"),
            DagNode(id="analyst", label="对比分析", icon="📊", status="done" if _node_ran("analyst") else "waiting"),
            DagNode(id="reviewer", label="质量审查", icon="✅", status="done" if _node_ran("reviewer") else "waiting"),
            DagNode(id="writer", label="报告生成", icon="📝", status="done" if _node_ran("writer") else "waiting"),
            DagNode(id="hitl_gate", label="等待审批", icon="👤", status="done" if _node_ran("hitl_gate") else "waiting"),
        ],
        edges=[
            # Main forward edges: active if both endpoints ran
            DagEdge(id="e1", from_="orchestrator", to="collector", type="main",
                    active=_node_ran("orchestrator") and _node_ran("collector")),
            DagEdge(id="e2", from_="collector", to="analyst", type="main",
                    active=_node_ran("collector") and _node_ran("analyst")),
            DagEdge(id="e3", from_="analyst", to="reviewer", type="main",
                    active=_node_ran("analyst") and _node_ran("reviewer")),
            DagEdge(id="e4", from_="reviewer", to="writer", type="main",
                    active=_node_ran("reviewer") and _node_ran("writer")),
            DagEdge(id="e5", from_="writer", to="hitl_gate", type="main",
                    active=_node_ran("writer") and _node_ran("hitl_gate")),
            # Feedback edges: only active if the corresponding loop actually happened
            DagEdge(id="e6", from_="reviewer", to="collector", type="feedback",
                    active=has_reviewer_feedback),
            DagEdge(id="e7", from_="hitl_gate", to="collector", type="hitl_replan",
                    active=has_hitl_replan),
            DagEdge(id="e8", from_="hitl_gate", to="analyst", type="hitl_reanalyze",
                    active=has_hitl_reanalyze),
            DagEdge(id="e9", from_="hitl_gate", to="writer", type="hitl_rewrite",
                    active=has_hitl_rewrite),
        ],
    )

    current_version = max((row.get("version") for row in history_rows), default=None)
    return TraceResponse(
        thread_id=thread_id, generations=generations, dag=dag, current_version=current_version,
    ).model_dump(by_alias=True)


class HitlDecisionRequest(BaseModel):
    """HITL decision or what-if input from frontend."""

    action: str = "rewrite"  # "approve" | "rewrite" | "reanalyze" | "replan" | "auto"
    comment: str = ""
    target_focus: list[str] | None = None
    fork_version: int | None = None  # If set, fork from this historical version instead of current


class SectionUpdate(BaseModel):
    """Single section edit for human correction (R6)."""

    id: str
    content: str


class SectionUpdateRequest(BaseModel):
    """Request body for human correction endpoint."""

    sections: list[SectionUpdate]


class SectionUpdateResponse(BaseModel):
    """Response after applying human corrections."""

    thread_id: str
    updated_count: int
    edit_count: int
    improvement_ratio: float | None = None


@router.patch("/report/{thread_id}/sections", response_model=SectionUpdateResponse)
async def update_sections(thread_id: str, body: SectionUpdateRequest) -> SectionUpdateResponse:
    """Apply human corrections to report sections (R6 — feedback improvement quantification)."""
    entry = _store.get(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

    state = entry.get("state", {})
    report_data = state.get("report_data")
    if not report_data:
        raise HTTPException(status_code=409, detail="No report data available")

    # Convert Pydantic model to dict if needed
    if hasattr(report_data, "model_dump"):
        report_dict = report_data.model_dump()
    else:
        report_dict = dict(report_data)

    # Apply section updates
    sections: list[dict] = report_dict.get("sections", [])
    section_by_id: dict[str, dict] = {s["id"]: s for s in sections}
    updated = 0
    for update in body.sections:
        if update.id in section_by_id:
            section_by_id[update.id]["content"] = update.content
            updated += 1

    # Track edit count for R6 improvement_ratio
    edit_count = entry.setdefault("_edit_count", 0) + 1
    entry["_edit_count"] = edit_count
    entry["state"]["report_data"] = report_dict
    _store[thread_id] = entry

    # Compute improvement ratio (simplified proxy: 1/edit_count)
    improvement_ratio = round(1.0 / edit_count, 4) if edit_count > 0 else None

    # Persist to DB
    try:
        from competition.db import upsert_analysis
        upsert_analysis(
            thread_id=thread_id,
            report_data=report_dict,
            metrics=report_dict.get("metrics"),
        )
    except Exception:
        pass

    return SectionUpdateResponse(
        thread_id=thread_id,
        updated_count=updated,
        edit_count=edit_count,
        improvement_ratio=improvement_ratio,
    )


def _restore_state_from_db(thread_id: str) -> dict | None:
    """Reconstruct in-memory entry from SQLite so reanalysis works after restart.

    Loads report_data + phases (with json_output from each node) and rebuilds
    a state dict containing the key fields needed by _reanalyze_sync.
    """
    import json as _json

    try:
        from competition.db import get_analysis, get_phases, init_db

        conn = init_db()
        db_record = get_analysis(thread_id, conn=conn)
        if db_record is None:
            conn.close()
            return None

        report_data = db_record.get("report_data") or {}
        if isinstance(report_data, str):
            report_data = _json.loads(report_data)

        products_raw = db_record.get("products") or "[]"
        target_products: list[str] = _json.loads(products_raw) if isinstance(products_raw, str) else list(products_raw or [])

        # Reconstruct state from phase json_output fields
        state: dict = {
            "report_data": report_data,
            "target_products": target_products,
            "user_request": db_record.get("query", ""),
            "persona": db_record.get("persona") or "pm",
            "industry": db_record.get("industry") or "general",
            "orchestration_result": {},
            "collected_data": [],
            "analysis_result": {},
            "review_verdict": {},
            "analysis_brief": db_record.get("analysis_brief"),
            "product_resolution": None,
        }

        # Load per-phase structured outputs into the state
        phases = get_phases(thread_id, conn=conn)
        conn.close()

        for p in phases:
            jo = p.get("json_output")
            if not jo:
                continue
            if isinstance(jo, str):
                jo = _json.loads(jo)
            phase_key = p.get("phase_key", "")
            version = p.get("version") or 0
            # Only restore version 0 (original) for base state
            if version != 0:
                continue
            if phase_key == "orchestrator":
                state["orchestration_result"] = jo
            elif phase_key == "collector":
                # collector json_output has summary + data_points_count, not full data
                state["collection_summary"] = jo.get("summary", {})
            elif phase_key == "analyst":
                state["analysis_result"] = jo
            elif phase_key == "reviewer":
                state["review_verdict"] = jo
            elif phase_key == "writer":
                # ReportData stored as json_output; keep as backup if report_data missing
                if not state.get("report_data"):
                    state["report_data"] = jo

        entry = {
            "state": state,
            "query": db_record.get("query", ""),
            "products": target_products,
            "status": db_record.get("status", "completed"),
            "created_at": db_record.get("created_at", ""),
            "token_usage": db_record.get("token_usage") if isinstance(db_record.get("token_usage"), list) else _json.loads(db_record.get("token_usage") or "[]"),
            "analysis_brief": db_record.get("analysis_brief"),
        }
        logger.info("Restored state for %s from DB (v=%d phases)", thread_id[:12], len(phases))
        return entry
    except Exception:
        logger.exception("Failed to restore state for %s from DB", thread_id)
        return None


@router.put("/report/{thread_id}", response_model=ReportResponse)
async def submit_decision(thread_id: str, decision: HitlDecisionRequest, fastapi_request: Request) -> ReportResponse:
    """Handle HITL decision or what-if rewrite request.

    For "rewrite" (what-if): runs Writer with the existing analysis + user's
    what-if assumption, generates updated report without re-running Collector/Analyst.
    """
    import asyncio

    _assert_thread_access(thread_id, fastapi_request)
    entry = _store.get(thread_id)
    if entry is None:
        # Try to restore state from DB (survives gateway restart)
        entry = _restore_state_from_db(thread_id)
        if entry is not None:
            _store[thread_id] = entry
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

    if entry.get("status") == "running":
        raise HTTPException(status_code=409, detail="分析正在进行中，请等待完成后再提交")

    if entry.get("status") == "approved":
        raise HTTPException(status_code=409, detail="报告已批准发布，无法再修改")

    state = entry.get("state", {})

    action = decision.action
    comment = decision.comment
    target_focus = decision.target_focus
    # Preserve a precise workbench comment as an explicit focus contract so a
    # targeted collection does not degrade into a generic rework run.
    if action == "replan" and not target_focus and comment.strip():
        target_focus = [comment.strip()]
    if action == "auto":
        from competition.nodes.rework_intent import parse_rework_intent
        intent = parse_rework_intent(state, comment)
        action = intent["action"]
        comment = intent["comment"]
        target_focus = intent["target_focus"]
        state["rework_intent"] = intent
        logger.info("Auto rework intent for %s: action=%s focus=%s", thread_id[:12], action, target_focus)

    state["hitl_decision"] = {
        "action": action,
        "comment": comment,
        "target_focus": target_focus,
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

    if action in ("rewrite", "reanalyze", "replan"):
        _reset_stream_queue(thread_id)
        _store[thread_id]["status"] = "running"
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _reanalyze_sync, thread_id, action)

    if action == "approve":
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
    """Run reanalysis in background thread and emit SSE phase events.

    Emits progress + node_end events so the frontend can render per-phase
    bubbles for HITL re-executions (re-collect, re-analyze, rewrite).
    """
    import logging
    logger = logging.getLogger(__name__)
    class _ReanalysisCancelled(Exception):
        """Internal signal used to stop a re-execution without marking it done."""

    from competition.executor import (
        clear_cancel_checker,
        clear_progress_callback,
        clear_stream_callback,
        set_cancel_checker,
        set_progress_callback,
        set_stream_callback,
    )

    try:
        entry = _store.get(thread_id)
        if not entry:
            return
        state = entry["state"]

        # Extract fork parent before processing (set by submit_decision for historical fork)
        fork_parent = state.pop("_fork_parent_version", None)
        from uuid import uuid4
        generation_id = str(uuid4())
        entry["generation_id"] = generation_id
        state["generation_id"] = generation_id

        # Inject user feedback into user_request for reanalyze/replan
        comment = state.get("hitl_decision", {}).get("comment", "")
        if comment and action in ("reanalyze", "replan"):
            state["user_request"] = f"{state.get('user_request', '')}\n\n用户反馈意见: {comment}"
            logger.info("Reanalysis with feedback: %s", comment[:100])

        from competition.nodes.writer import writer_node

        # Track reanalysis round for unique phase keys (writer_r2, analyst_r2, ...)
        round_num = entry.setdefault("reanalysis_round", 0) + 1
        entry["reanalysis_round"] = round_num
        suffix = f"_r{round_num}"

        action_labels = {"rewrite": "重写报告", "reanalyze": "重新分析", "replan": "重新搜索"}
        label = f"{action_labels.get(action, action)}"

        # ── Node metadata for re-execution phases ──
        _RE_NODES: dict[str, tuple[str, str, str]] = {
            "collector": ("collector", "📊", "重新采集"),
            "analyst":   ("analyst",   "🔍", "重新分析"),
            "reviewer":  ("reviewer",  "✅", "重新审查"),
            "writer":    ("writer",    "📝", "重写报告"),
        }

        # Set up streaming callback so re-execution phase content is captured
        _re_content: dict[str, str] = {}  # agent_name → accumulated text

        def _re_stream(agent_name: str, chunk_text: str) -> None:
            nonlocal _chunk_seq
            _chunk_seq += 1
            _emit_event(thread_id, "messages-tuple", [{
                "type": "AIMessageChunk",
                "name": agent_name or "analysis",
                "content": chunk_text,
                "id": f"comp-{thread_id[-8:]}-re-{_chunk_seq}",
            }])
            if chunk_text and chunk_text != "\x00THINK\x00":
                _re_content[agent_name] = _re_content.get(agent_name, "") + chunk_text

        def _re_progress(payload: dict) -> None:
            allowed = {
                key: payload[key]
                for key in ("phase", "task_key", "section_id", "status", "completed", "total", "message")
                if key in payload
            }
            _emit_event(thread_id, "progress", allowed)

        _chunk_seq = 0
        set_stream_callback(_re_stream)
        set_cancel_checker(lambda: _cancel_flags.get(thread_id, False))
        set_progress_callback(_re_progress)

        def _stop_if_cancelled() -> None:
            if not _cancel_flags.get(thread_id, False):
                return
            _cancel_flags.pop(thread_id, None)
            if _store.get(thread_id, {}).get("status") != "interrupted":
                _finalize_cancelled(thread_id)
            raise _ReanalysisCancelled

        def _run_re_node(node_key: str, node_fn, st: dict) -> None:
            """Execute one re-execution node and emit SSE phase events."""
            nonlocal _re_content
            _stop_if_cancelled()
            _, icon, display_label = _RE_NODES[node_key]
            phase_key = f"{node_key}{suffix}"
            start_time = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()

            _emit_event(thread_id, "progress", {
                "phase": phase_key,
                "label": display_label,
                "icon": icon,
                "message": f"{display_label} 开始…",
            })

            from competition.executor import get_total_tokens
            tokens_before = get_total_tokens()
            try:
                result = node_fn(st)
            except Exception:
                logger.exception("%s node failed", node_key)
                result = {}
            _stop_if_cancelled()
            st.update(result)
            tokens_after = get_total_tokens()
            delta_tokens = max(tokens_after - tokens_before, 0)
            end_time = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()

            _emit_event(thread_id, "node_end", {
                "node": phase_key,
                "label": display_label,
                "icon": icon,
                "status": "done",
                "progress": f"{display_label} 完成",
                "tokens": delta_tokens,
            })

            # Extract structured JSON output from the node result
            _json_output: dict | None = None
            if node_key == "collector":
                _json_output = {"summary": _safe_dict(result.get("collection_summary")), "data_points_count": len(result.get("collected_data") or [])}
            elif node_key == "analyst":
                _json_output = _safe_dict(result.get("analysis_result"))
            elif node_key == "reviewer":
                _json_output = _safe_dict(result.get("review_verdict"))
            elif node_key == "writer":
                _json_output = _safe_dict(result.get("report_data"))

            # Persist re-execution phase with captured content
            from competition.db import save_phase
            save_phase(
                thread_id=thread_id, phase_key=phase_key,
                label=display_label, icon=icon, status="completed",
                start_time=start_time, end_time=end_time,
                tokens=delta_tokens, content=dict(_re_content), details=[],
                json_output=_json_output,
                version=round_num,
                generation_id=generation_id,
            )
            _re_content.clear()

        _stop_if_cancelled()

        # Change status so frontend SSE reconnects
        _store[thread_id]["status"] = "running"
        _stop_if_cancelled()
        _store[thread_id]["state"] = state

        if action == "rewrite":
            _run_re_node("writer", writer_node, state)
        elif action == "reanalyze":
            from competition.nodes.analyst import analyst_node
            from competition.nodes.reviewer import reviewer_node

            # Reset review state so G7/G8 re-validates the new analysis data
            state["review_round"] = 0
            state.pop("review_verdict", None)
            state.pop("review_package", None)

            logger.info("Reanalysis starting for %s", thread_id[:12])
            _run_re_node("analyst", analyst_node, state)
            _run_re_node("reviewer", reviewer_node, state)
            _run_re_node("writer", writer_node, state)
            logger.info("Reanalysis completed for %s", thread_id[:12])
        elif action == "replan":
            from competition.nodes.analyst import analyst_node
            from competition.nodes.collector import collector_node
            from competition.nodes.reviewer import reviewer_node

            # Reset review state so G7/G8 re-validates the new collected data
            state["review_round"] = 0
            state.pop("review_verdict", None)
            state.pop("review_package", None)

            logger.info("Replan starting for %s", thread_id[:12])
            _run_re_node("collector", collector_node, state)
            _run_re_node("analyst", analyst_node, state)
            _run_re_node("reviewer", reviewer_node, state)
            _run_re_node("writer", writer_node, state)
            logger.info("Replan completed for %s", thread_id[:12])

        _store[thread_id]["state"] = state
        _add_token_entry(thread_id, label)
        _store[thread_id]["status"] = "completed"

        # Emit completion so frontend stops the re-execution SSE stream
        _emit_event(thread_id, "end", {"status": "completed"})

        # Save new report as a version after reanalysis completes
        new_report = state.get("report_data")
        if new_report:
            parent = fork_parent if fork_parent is not None else _current_db_version(thread_id)
            _history_store.insert(
                thread_id, parent, "",
                action,
                {"report_data": new_report.model_dump() if hasattr(new_report, "model_dump") else new_report,
                 "comment": state.get("hitl_decision", {}).get("comment", ""),
                 "generation_id": generation_id},
            )
            logger.info("Saved post-%s report v%d for %s",
                        action, _current_db_version(thread_id), thread_id[:12])
    except _ReanalysisCancelled:
        logger.info("Reanalysis %s cancelled", thread_id)
    except Exception as e:
        logger.exception("Reanalysis %s failed: %s", thread_id, e)
        if thread_id in _store:
            _store[thread_id]["status"] = "failed"
            _store[thread_id]["state"]["error"] = str(e)
        _emit_event(thread_id, "error", {"error": str(e)[:200], "status": "failed"})
    finally:
        clear_stream_callback()
        clear_cancel_checker()
        clear_progress_callback()


def _save_to_db(thread_id: str, entry: dict) -> None:
    """Persist an approved report to the SQLite analysis_history table."""
    try:
        from competition.db import init_db, record_analysis

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


@router.get("/report/{thread_id}/export-feishu")
async def export_to_feishu(thread_id: str, fastapi_request: Request):
    """Export a completed report to Feishu Docx. Returns the doc URL."""
    from competition.db import get_user_settings
    from competition.executor import clear_user_context, set_user_context
    from competition.feishu_doc import export_report_to_doc, is_manual_export_enabled

    user_id = _get_user_id(fastapi_request)
    user_settings = get_user_settings(user_id) if user_id != "default" else None
    set_user_context(user_id, user_settings)
    try:
        if not is_manual_export_enabled():
            raise HTTPException(status_code=400, detail="飞书手动导出未开启，请在设置中启用 doc_manual_export")

        entry = _store.get(thread_id)
        if entry is None:
            # Fallback: load from SQLite
            from competition.db import get_analysis, init_db
            conn = init_db()
            db_record = get_analysis(thread_id, conn=conn)
            conn.close()
            if db_record is None:
                raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")
            report = db_record.get("report_data") or {}
            title = db_record.get("title", "")
        else:
            report = entry.get("state", {}).get("report_data") or {}
            title = report.get("title", "") if isinstance(report, dict) else str(getattr(report, "title", ""))

        products = report.get("products", []) if isinstance(report, dict) else getattr(report, "products", [])

        md = _render_report_markdown({"state": {"report_data": report}, "title": title, "products": products})
        doc_url = export_report_to_doc(str(title), md)
        if doc_url:
            return {"status": "ok", "doc_url": doc_url}
        raise HTTPException(status_code=500, detail="飞书文档创建失败，请检查 app_id/app_secret/tenant/open_id 和应用权限")
    finally:
        clear_user_context()


@router.get("/stream/{thread_id}")
async def stream(
    thread_id: str,
    fastapi_request: Request,
    last_event_id_query: str | None = Query(default=None, alias="last_event_id"),
):
    """SSE stream of graph execution events.

    Supports Last-Event-ID header for reconnection.
    Events are formatted with event:, data:, and id: fields matching
    the standard SSE wire format.
    """
    _assert_thread_access(thread_id, fastapi_request)
    entry = _store.get(thread_id)
    if entry is None:
        # Try to restore from DB (survives gateway restart)
        entry = _restore_state_from_db(thread_id)
        if entry is not None:
            _store[thread_id] = entry
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")
    if entry.get("status") == "awaiting_confirmation":
        raise HTTPException(status_code=409, detail="Analysis is awaiting Brief confirmation")

    # Native EventSource reconnects can carry Last-Event-ID in the header, but
    # the frontend also performs bounded manual reconnects so it can expose a
    # degraded state. Those new EventSource instances cannot set headers, so
    # accept the equivalent query parameter as a backwards-compatible fallback.
    last_event_id = fastapi_request.headers.get("Last-Event-ID") or last_event_id_query

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
    user_id = _get_user_id(fastapi_request) if fastapi_request else "default"
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
    try:
        from competition.db import init_db
        from competition.db import list_history as db_list_history
        conn = init_db()
        persisted = db_list_history(conn, limit=limit, user_id=user_id)
        conn.close()
        by_id = {item["thread_id"]: item for item in persisted}
        for item in history:
            by_id[item["thread_id"]] = {**by_id.get(item["thread_id"], {}), **item}
        history = sorted(by_id.values(), key=lambda item: item.get("created_at", ""), reverse=True)[:limit]
    except Exception:
        logger.exception("Failed to merge persisted competition history")
    return {"history": history, "total": len(history), "user_id": user_id}


@router.get("/me")
async def current_user(fastapi_request: Request):
    """Return current user info for the frontend auth state."""
    user_id = _get_user_id(fastapi_request)
    thread_count = len(_get_user_threads(user_id))

    email = None
    if user_id != "default":
        try:
            import os as _os
            import sqlite3 as _sqlite
            auth_db = _os.path.join(_os.path.dirname(__file__), "..", "..", ".ci-agent", "auth.db")
            if _os.path.exists(auth_db):
                ac = _sqlite.connect(auth_db)
                row = ac.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
                ac.close()
                if row:
                    email = row[0]
        except Exception:
            pass

    config_mode = "db"
    try:
        from competition.config_mode import is_file_mode
        config_mode = "file" if is_file_mode() else "db"
    except Exception:
        pass

    return {
        "user_id": user_id,
        "authenticated": user_id != "default",
        "thread_count": thread_count,
        "email": email or "",
        "config_mode": config_mode,
    }


# ── User Settings (§User System) ──


@router.get("/settings")
async def get_settings(fastapi_request: Request):
    """Get current user's settings."""
    from competition.db import get_user_settings
    user_id = _get_user_id(fastapi_request)
    settings = get_user_settings(user_id)
    return {"user_id": user_id, "settings": settings}


@router.put("/settings")
async def save_settings(body: SettingsUpdateRequest | dict, fastapi_request: Request):
    """Save current user's settings."""
    from competition.db import save_user_settings_if_current
    user_id = _get_user_id(fastapi_request)
    if user_id == "default":
        raise HTTPException(status_code=401, detail="Login required to save settings")
    payload = body if isinstance(body, dict) else body.model_dump()
    settings = payload.get("settings", payload)
    expected = str(payload.get("expected_updated_at", ""))
    result = save_user_settings_if_current(user_id, settings, expected)
    if result["result"] == "conflict":
        raise HTTPException(status_code=409, detail={"code": "settings_conflict", "message": "设置已在其他窗口更新。", "settings": result["settings"]})
    return {"ok": True, "user_id": user_id, "settings": result["settings"]}


@router.post("/settings/test-connection")
async def test_settings_connection(body: SettingsConnectionRequest, fastapi_request: Request):
    """Run one explicit bounded check against a provider already saved by this user."""
    from competition.db import get_user_settings
    from competition.settings_connection import ConnectionCheckError, run_connection_check

    user_id = _get_user_id(fastapi_request)
    if user_id == "default":
        raise HTTPException(status_code=401, detail="Login required to test settings")
    try:
        return await asyncio.to_thread(run_connection_check, body.kind, body.name, get_user_settings(user_id))
    except ConnectionCheckError as exc:
        status = 504 if exc.code == "timeout" else 422 if exc.code == "missing_config" else 400
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from None


@router.post("/settings/migrate")
async def migrate_data(fastapi_request: Request):
    """Assign all 'default' user data to the current user."""
    from competition.db import migrate_default_data
    user_id = _get_user_id(fastapi_request)
    if user_id == "default":
        raise HTTPException(status_code=401, detail="Login required to migrate data")
    count = migrate_default_data(user_id)
    return {"ok": True, "migrated_rows": count, "user_id": user_id}


@router.get("/db-history")
async def list_db_history(limit: int = Query(default=20, le=100), fastapi_request: Request = None):
    """List analysis records saved to SQLite (approved reports)."""
    try:
        from competition.db import init_db
        from competition.db import list_history as db_list_history

        user_id = _get_user_id(fastapi_request)
        conn = init_db()
        records = db_list_history(conn, limit=limit, user_id=user_id)
        conn.close()
        return {"history": records, "total": len(records)}
    except Exception as e:
        logger.exception("Failed to read DB history: %s", e)
        return {"history": [], "total": 0, "error": str(e)}


@router.get("/db-report/{thread_id}")
async def get_db_report(thread_id: str, fastapi_request: Request = None):
    """Retrieve a saved (approved) report from the SQLite database."""
    _assert_thread_access(thread_id, fastapi_request)
    try:
        from competition.db import get_analysis, init_db

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
async def delete_db_report(thread_id: str, fastapi_request: Request = None):
    """Delete a saved report from the SQLite database."""
    _assert_thread_access(thread_id, fastapi_request)
    try:
        from competition.db import delete_analysis, delete_phase_history, init_db

        conn = init_db()
        deleted = delete_analysis(thread_id, conn=conn)
        delete_phase_history(thread_id, conn=conn)
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
async def pin_db_report(thread_id: str, pinned: bool = True, fastapi_request: Request = None):
    """Pin or unpin a saved report (pinned reports sort first and cannot be deleted)."""
    _assert_thread_access(thread_id, fastapi_request)
    try:
        from competition.db import init_db, pin_analysis

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


class RenameRequest(BaseModel):
    title: str


@router.patch("/db-report/{thread_id}/title")
async def rename_db_report(thread_id: str, body: RenameRequest, fastapi_request: Request = None):
    """Rename a saved report."""
    _assert_thread_access(thread_id, fastapi_request)
    try:
        from competition.db import get_analysis, init_db, upsert_analysis

        conn = init_db()
        record = get_analysis(thread_id, conn=conn)
        if record is None:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Report not found: {thread_id}")

        upsert_analysis(thread_id=thread_id, title=body.title, conn=conn)
        conn.close()
        return {"title": body.title, "thread_id": thread_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to rename report %s: %s", thread_id, e)
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
    from competition.executor import get_agent_tokens, get_total_tokens

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
        from competition.db import upsert_analysis
        upsert_analysis(
            thread_id=thread_id, status="interrupted",
            user_id=_thread_owners.get(thread_id, "default"),
            query=_store[thread_id].get("query", ""),
            products=_store[thread_id].get("products", []),
        )
    except Exception:
        pass
    _emit_event(thread_id, "end", {"status": "interrupted", "message": "分析已终止"})


def _resolve_and_run_graph(
    thread_id: str,
    query: str,
    explicit_products: list[str],
    user_id: str = "default",
    analysis_brief: dict | None = None,
) -> None:
    """ProductResolver (pre-graph) → Orchestrator (graph entry).

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

    # Set per-user context for settings override in executor
    from competition.executor import set_user_context
    set_user_context(user_id)

    # One opaque ID joins resolving/graph phases to the report version created
    # later. Failed runs retain the ID but intentionally have no report version.
    from uuid import uuid4
    generation_id = str(uuid4())
    if thread_id in _store:
        _store[thread_id].setdefault("state", {})["generation_id"] = generation_id
        _store[thread_id]["generation_id"] = generation_id

    # Set cancel checker so LLM calls during product resolution can be interrupted
    from competition.executor import clear_cancel_checker, set_cancel_checker
    set_cancel_checker(lambda: _cancel_flags.get(thread_id, False))

    try:
        # ── Phase 1: ProductResolver (pre-graph) ──
        if _cancelled():
            clear_cancel_checker()
            _finalize_cancelled(thread_id)
            return
        # ── Phase 1: ProductResolver (pre-graph) ──
        resolve_start = __import__("datetime").datetime.now(__import__("datetime").UTC)
        _emit_event(thread_id, "progress", {
            "phase": "resolving",
            "message": "正在解析竞品名称...",
            "timestamp": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        })

        products: list[str] = []

        effective_brief = analysis_brief or (_store.get(thread_id, {}).get("state", {}).get("analysis_brief"))
        fixed_products = list((effective_brief or {}).get("target_products") or explicit_products)
        if fixed_products:
            for p in fixed_products:
                p = p.strip()
                if p and p not in products:
                    products.append(p)

        product_audit = [
            {"requested_name": product, "resolved_name": product, "confidence": "low"}
            for product in products
        ]
        if products:
            # Verify/correct explicit products via search + LLM judge
            # A confirmed Brief fixes membership; keep user order and spelling
            # when verification cannot establish a high-confidence correction.
            if effective_brief:
                # Verification may collect evidence and suggest corrections, but
                # the confirmed Brief owns membership, order, and user spelling.
                verified = _verify_products_via_search(
                    products, 1, query, return_audit=True, preserve_membership=True,
                )
                products, product_audit = verified

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
        resolve_end = __import__("datetime").datetime.now(__import__("datetime").UTC)
        _emit_event(thread_id, "progress", {
            "phase": "resolved",
            "message": f"竞品解析完成: {', '.join(products)}",
            "products": products,
            "timestamp": resolve_end.isoformat(),
        })

        # Persist resolving + resolved phases so history reconstruction has them
        from competition.db import save_phase as _sp
        _sp(thread_id=thread_id, phase_key="resolving", label="竞品解析", icon="🔎",
            status="completed", start_time=resolve_start.isoformat(), end_time=resolve_end.isoformat(),
            tokens=0, content={}, details=[
                {"message": "正在解析竞品名称...", "phase": "resolving"},
                {"message": f"竞品解析完成: {', '.join(products)}", "phase": "resolved", "products": products},
            ], generation_id=generation_id)

        # Update store with verified products
        if thread_id in _store:
            _store[thread_id]["products"] = products
            _store[thread_id]["status"] = "running"
            _store[thread_id]["state"]["target_products"] = products
            _store[thread_id]["state"]["product_resolution"] = product_audit
            _store[thread_id]["state"]["complexity"] = (effective_brief or {}).get("complexity", "standard")
            if effective_brief:
                _store[thread_id]["state"]["analysis_brief"] = effective_brief

        # Auto-generate title from resolved products
        try:
            n = len(products)
            if n == 1:
                title = f"{products[0]} 竞品分析"
            elif n == 2:
                title = f"{products[0]} vs {products[1]}"
            elif n >= 3:
                title = f"{products[0]}、{products[1]} 等产品竞品分析"
            else:
                title = ""
            if title:
                from competition.db import upsert_analysis as _ua
                _ua(thread_id=thread_id, title=title, status="running", products=products)
                _store[thread_id]["title"] = title
                _emit_event(thread_id, "title", {"title": title, "thread_id": thread_id})
        except Exception:
            pass  # Title is cosmetic; don't block analysis

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
    finally:
        from competition.executor import clear_user_context
        clear_user_context()


def _run_graph_sync(thread_id: str) -> None:
    """Run the competition graph synchronously (called from thread executor).

    LLM calls (langchain) are synchronous and would block the asyncio event loop
    for ~2 minutes. This function runs in a separate thread so the event loop
    stays free to handle other requests.
    """
    try:
        from competition.graph import build_competition_graph
        from competition.state import CompetitionState

        entry = _store.get(thread_id)
        if not entry:
            return
        generation_id = entry.get("generation_id") or entry.get("state", {}).get("generation_id")

        from competition.graph import register_nodes
        from competition.nodes.analyst import analyst_node
        from competition.nodes.collector import collector_node
        from competition.nodes.error_handler import error_handler_node
        from competition.nodes.hitl_gate import hitl_gate_node
        from competition.nodes.orchestrator import orchestrator_node
        from competition.nodes.reviewer import reviewer_node
        from competition.nodes.writer import writer_node

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
        # via this callback, matching the standard messages-tuple SSE format.
        from competition.executor import (
            clear_cancel_checker,
            clear_progress_callback,
            clear_stream_callback,
            set_cancel_checker,
            set_progress_callback,
            set_stream_callback,
        )

        _chunk_seq = 0
        _phase_content: dict[str, str] = {}  # agent_name → accumulated streaming text
        _node_start_time: str = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()

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
            if chunk_text == "\x00THINK\x00":
                label = _AGENT_LABELS.get(agent_name, agent_name or "分析")
                _emit_event(thread_id, "progress", {"message": f"{label} 正在深度思考..."})
                return
            # Accumulate streaming content for phase persistence
            if chunk_text:
                _phase_content[agent_name] = _phase_content.get(agent_name, "") + chunk_text
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

        def _writer_progress(payload: dict) -> None:
            allowed = {
                key: payload[key]
                for key in ("phase", "task_key", "section_id", "status", "completed", "total", "message")
                if key in payload
            }
            _emit_event(thread_id, "progress", allowed)

        set_stream_callback(_stream_chunk_labeled)
        set_cancel_checker(lambda: _cancel_flags.get(thread_id, False))
        set_progress_callback(_writer_progress)

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
                clear_progress_callback()
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
                node_json: dict | None = None
                if update.get("orchestration_result") and not prev_state.get("orchestration_result"):
                    current_node = "orchestrator"
                    node_json = _safe_dict(update.get("orchestration_result"))
                elif update.get("collection_summary") and not prev_state.get("collection_summary"):
                    current_node = "collector"
                    progress = f"已采集 {update['collection_summary'].get('total_data_points', 0)} 条数据"
                    node_json = {"summary": _safe_dict(update.get("collection_summary")), "data_points_count": len(update.get("collected_data") or [])}
                elif update.get("analysis_result") and not prev_state.get("analysis_result"):
                    current_node = "analyst"
                    progress = "对比矩阵+SWOT已生成"
                    node_json = _safe_dict(update.get("analysis_result"))
                elif update.get("review_verdict") and not prev_state.get("review_verdict"):
                    current_node = "reviewer"
                    progress = "质量审查完成"
                    node_json = _safe_dict(update.get("review_verdict"))
                elif update.get("report_data") and not prev_state.get("report_data"):
                    current_node = "writer"
                    progress = "报告已生成"
                    node_json = _safe_dict(update.get("report_data"))
                prev_state = update

                if current_node:
                    from competition.db import upsert_analysis
                    from competition.executor import get_total_tokens
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
                    # Persist phase content for history reconstruction
                    from competition.db import save_phase as _sp
                    _now = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()

                    _sp(
                        thread_id=thread_id, phase_key=current_node,
                        label=_NODE_LABELS.get(current_node, current_node),
                        icon="⚙️", status="completed",
                        start_time=_node_start_time, end_time=_now,
                        tokens=max(delta_tokens, 0),
                        content=dict(_phase_content),
                        details=[],
                        json_output=node_json,
                        version=0,
                        generation_id=generation_id,
                    )
                    _phase_content.clear()
                    _node_start_time = _now  # next phase starts now

                flags = []
                if current_node:
                    flags.append(current_node)
                if update.get("error"):
                    flags.append(f"error={update['error'][:50]}")
                logger.info("Analysis %s event#%d: %s", thread_id[:12], event_num, " → ".join(flags) if flags else "init")

        state = _store[thread_id]["state"]
        terminal_error = str(state.get("error") or "").strip()
        if terminal_error:
            failure_message = terminal_error.removeprefix("FATAL:").strip() or "分析未生成有效结果"
            _add_token_entry(thread_id, "初始分析")
            _store[thread_id]["status"] = "failed"

            from competition.db import upsert_analysis
            rd = state.get("report_data")
            upsert_analysis(
                thread_id=thread_id,
                status="failed",
                current_node="",
                progress=f"失败: {failure_message[:100]}",
                report_data=rd.model_dump() if hasattr(rd, "model_dump") else rd,
                metrics=(rd.get("metrics") if isinstance(rd, dict) else None),
                token_usage=_store[thread_id].get("token_usage", []),
            )
            _emit_event(thread_id, "error", {"error": failure_message[:200], "status": "failed"})
            clear_stream_callback()
            clear_cancel_checker()
            clear_progress_callback()
            logger.error("Analysis %s failed at graph termination: %s", thread_id, failure_message)
            return

        # Emit completion
        _emit_event(thread_id, "end", {"status": "completed"})
        clear_stream_callback()
        clear_cancel_checker()
        clear_progress_callback()

        _add_token_entry(thread_id, "初始分析")
        _store[thread_id]["status"] = "completed"

        # Persist completion to DB (§18)
        from competition.db import upsert_analysis
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
                {"report_data": rd.model_dump() if hasattr(rd, "model_dump") else rd,
                 "generation_id": _store[thread_id].get("generation_id") or state.get("generation_id")})

        logger.info("Analysis %s completed", thread_id)

        # ── Feishu: auto-export doc + notification ──
        try:
            from competition.feishu_doc import export_report_to_doc, is_doc_export_enabled
            from competition.feishu_notify import is_notify_enabled, notify_analysis_complete

            st = _store[thread_id].get("state", {})
            rd = st.get("report_data")
            if rd:
                title = rd.get("title", "") if isinstance(rd, dict) else str(getattr(rd, "title", ""))
                products = rd.get("products", []) if isinstance(rd, dict) else getattr(rd, "products", [])
                products_str = ", ".join(products[:3])

                doc_url = ""
                if is_doc_export_enabled():
                    md = _render_report_markdown({"state": {"report_data": rd}, "products": products, "title": title})
                    doc_url = export_report_to_doc(str(title), md) or ""

                if is_notify_enabled():
                    notify_analysis_complete(thread_id, str(title), products_str, doc_url)
        except Exception as ex:
            logger.warning("Feishu post-completion error: %s", ex)

    except Exception as e:
        logger.exception("Analysis %s failed: %s", thread_id, e)
        clear_stream_callback()
        clear_cancel_checker()
        clear_progress_callback()
        _emit_event(thread_id, "error", {"error": str(e)[:200], "status": "failed"})
        if thread_id in _store:
            _store[thread_id]["status"] = "failed"
            _store[thread_id]["state"]["error"] = str(e)
            from competition.db import upsert_analysis
            upsert_analysis(thread_id=thread_id, status="failed", progress=f"失败: {str(e)[:100]}")


def _stream_events_sync(thread_id: str, last_event_id: str | None = None):
    """SSE event stream — sync generator matching the standard SSE wire format.

    - Uses pre-formatted SSE frames from _emit_event (event: + data: + id:)
    - Supports Last-Event-ID replay for reconnection
    - Heartbeat via SSE comment lines (: heartbeat) every 15s
    - No hard timeout — stays alive as long as the analysis is running
    """
    import time as _time

    subscriber = _register_stream_subscriber(thread_id)
    try:
        # Register before taking the snapshot.  Any event emitted after this
        # point is queued for this client, so replay and live delivery have no
        # registration gap.
        with _stream_lock:
            entry = _store.get(thread_id)
            buffered = list(_event_buffers.get(thread_id, []))
        # Events emitted between subscriber registration and the first live
        # read are present both in this snapshot and in the subscriber queue.
        # Remember the snapshot IDs so those queued copies are not delivered a
        # second time after replay.  Events emitted after this snapshot have a
        # new ID and are delivered normally.
        snapshot_event_ids = {
            event_id
            for _seq, frame in buffered
            if (event_id := _frame_event_id(frame)) is not None
        }

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

        # ── Replay buffered events ──
        # A first connection catches up with the retained buffer (including
        # events emitted during product resolution before the UI connected).
        # A reconnect starts strictly after the browser's Last-Event-ID.  If
        # that ID was evicted, replay all retained events rather than silently
        # losing the remainder of the run.
        replay_frames: list[str]
        if last_event_id:
            replay_index = next(
                (
                    index
                    for index, (_seq, frame) in enumerate(buffered)
                    if f"id: {last_event_id}" in frame
                ),
                None,
            )
            replay_frames = [
                frame for _seq, frame in (
                    buffered[replay_index + 1 :] if replay_index is not None else buffered
                )
            ]
        else:
            replay_frames = [frame for _seq, frame in buffered]

        for frame in replay_frames:
            yield frame

        # If a completed run is replayed after its terminal event, close the
        # connection.  Also close when Last-Event-ID already points at the
        # terminal event (so a reconnect after a lost response does not leave
        # an idle stream open for five minutes).  When a new re-analysis is
        # already running, keep the connection open even if retained history
        # contains an older end.
        current_status = entry.get("status", "")
        if current_status not in {"running", "awaiting_confirmation"}:
            if not replay_frames:
                return
            if "event: error" in replay_frames[-1] or "event: end" in replay_frames[-1]:
                return

        # ── Live event loop ──
        last_heartbeat = _time.monotonic()
        heartbeat_interval = 15

        while True:
            try:
                frame = subscriber.get(timeout=heartbeat_interval)
                if _frame_event_id(frame) in snapshot_event_ids:
                    continue
                yield frame
                last_heartbeat = _time.monotonic()

                # Detect end/error to terminate stream
                if "event: error" in frame or "event: end" in frame:
                    return

            except _queue_mod.Empty:
                # No event — send SSE comment heartbeat
                elapsed = _time.monotonic() - last_heartbeat
                if elapsed >= 300:  # 5 min of total idle → terminate
                    yield _format_sse("end", {"status": "timeout"}, event_id=f"{thread_id[-8:]}-timeout")
                    return
                yield ": heartbeat\n\n"
    finally:
        _unregister_stream_subscriber(thread_id, subscriber)
