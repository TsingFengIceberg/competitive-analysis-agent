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
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
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


# ── Request / Response Models ──


class AnalyzeRequest(BaseModel):
    """Request body for starting a competitive analysis."""

    query: str = Field(..., description="Natural language analysis request")
    target_products: list[str] = Field(..., description="Products to compare, e.g. ['Cursor', 'Copilot']")
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


# ── Product name extraction & correction ──

def _llm_extract_products(query: str) -> list[str]:
    """Multi-round LLM+Search extraction with progressive relaxation.

    Round 1: LLM extracts → search strictly verifies each candidate
    Round 2: Retry with broader search, accept partial matches
    Round 3: Most permissive — accept any search hit, only filter complete garbage

    Stops early once we have ≥2 verified products, or after round 3.
    Synchronous — caller must wrap in executor.
    """
    all_candidates: list[str] = []

    for round_num in range(1, 4):
        remaining = _build_round_prompt(query, all_candidates, round_num)
        new_candidates = _llm_extract_candidates(remaining)
        if not new_candidates:
            continue

        verified = _verify_products_via_search(new_candidates, strictness=round_num, query_hint=query)
        for v in verified:
            if v not in all_candidates:
                all_candidates.append(v)

        logger.info("Product extraction round %d: got %d candidates, %d verified (total: %d)",
                     round_num, len(new_candidates), len(verified), len(all_candidates))

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
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Start a competitive analysis. Returns thread_id immediately.

    Product resolution (LLM + search, ~2min) runs in background thread,
    then graph execution starts automatically once products are resolved.
    Frontend polls /report/{thread_id} for status updates.
    """
    import uuid
    from datetime import UTC, datetime

    thread_id = f"comp-{uuid.uuid4().hex[:12]}"

    # Store entry immediately — frontend can start polling right away
    _store[thread_id] = {
        "status": "running",
        "state": {
            "messages": [],
            "user_request": request.query,
            "target_products": request.target_products or [],
            "persona": request.persona,
            "deep_mode": request.deep_mode,
            "collected_data": [],
            "context_report": request.context_report,
        },
        "created_at": datetime.now(UTC).isoformat(),
        "query": request.query,
        "products": [],
    }

    # Resolve products + run graph entirely in background thread
    # (sync LLM + search calls take ~2min and would block the event loop)
    asyncio.get_event_loop().run_in_executor(
        None, _resolve_and_run_graph, thread_id, request.query, request.target_products,
    )

    return AnalyzeResponse(thread_id=thread_id, status="running")


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

        # Save current report as a version in history store before overwriting
        old_report = state.get("report_data")
        if old_report:
            fork_parent = state.pop("_fork_parent_version", None)
            parent = fork_parent if fork_parent is not None else _current_db_version(thread_id)
            _history_store.insert(
                thread_id, parent, "",
                action,
                {"comment": state.get("hitl_decision", {}).get("comment", ""),
                 "report_data": old_report.model_dump() if hasattr(old_report, "model_dump") else old_report},
            )
            logger.info("Saved report v%d (parent=v%s) to history for %s",
                        _current_db_version(thread_id), parent, thread_id[:12])

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
async def stream(thread_id: str):
    """SSE stream of graph execution events."""
    entry = _store.get(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")

    return StreamingResponse(
        _stream_events(thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history")
async def list_history(limit: int = Query(default=10, le=50)):
    """List recent analysis history (from runtime store)."""
    history = []
    for tid, entry in list(_store.items())[-limit:]:
        history.append({
            "thread_id": tid,
            "query": entry.get("query", ""),
            "products": entry.get("products", []),
            "status": entry.get("status", "unknown"),
            "created_at": entry.get("created_at", ""),
            "versions": len(_history_store.list_by_thread(tid)),
        })
    return {"history": history, "total": len(history)}


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


def _resolve_and_run_graph(thread_id: str, query: str, explicit_products: list[str]) -> None:
    """Resolve products then run graph — all synchronous, called from thread executor.

    Runs in background thread because:
      1. _llm_extract_products() makes LLM calls (~20-30s)
      2. _verify_products_via_search() makes search + LLM calls (~60-120s)
      3. _run_graph_sync() runs the full graph (~5-10min)
    Total: 5-10 minutes of synchronous LLM calls that would block the event loop.
    """
    import logging
    _log = logging.getLogger(__name__)

    try:
        # ── Step 1: Resolve products ──
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
            # No explicit products — extract from query via LLM
            _log.info("No products from explicit list — extracting via LLM")
            products = _llm_extract_products(query)

        # Deduplicate while preserving order
        seen: set[str] = set()
        resolved: list[str] = []
        for p in products:
            if p.lower() not in seen:
                seen.add(p.lower())
                resolved.append(p)
        products = resolved

        _log.info("Resolved products: %s (from query: '%s')", products, query[:80])

        if not products:
            _log.warning("Could not resolve any products — marking as failed")
            if thread_id in _store:
                _store[thread_id]["status"] = "failed"
                _store[thread_id]["state"]["error"] = (
                    "无法从分析请求中提取竞品名称，请在「竞品名称」输入框中明确指定（逗号分隔）。"
                )
            return

        # Update store with resolved products
        if thread_id in _store:
            _store[thread_id]["products"] = products
            _store[thread_id]["status"] = "running"
            _store[thread_id]["state"]["target_products"] = products

        # ── Step 2: Run the graph ──
        _run_graph_sync(thread_id)

    except Exception as e:
        _log.exception("Resolution+graph failed for %s: %s", thread_id, e)
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
        from deerflow.competition.nodes.reviewer import reviewer_node
        from deerflow.competition.nodes.writer import writer_node

        register_nodes({
            "collector": collector_node,
            "analyst": analyst_node,
            "reviewer": reviewer_node,
            "writer": writer_node,
            "hitl_gate": hitl_gate_node,
            "error_handler": error_handler_node,
        })

        graph = build_competition_graph(checkpointer=_replay_saver)
        initial_state = CompetitionState(**entry["state"])

        # Stream execution — updates store on each node completion
        event_num = 0
        for event in graph.stream(initial_state, {"configurable": {"thread_id": thread_id}}, stream_mode=["values"]):
            event_num += 1
            # LangGraph stream returns (mode, data) tuple or dict
            if isinstance(event, tuple):
                update = event[-1]  # last element is always the data
            else:
                update = event
            if isinstance(update, dict):
                _store[thread_id]["state"] = update
                # Log key fields present in this event to trace pipeline
                flags = []
                if update.get("collection_summary"):
                    flags.append("collected")
                if update.get("analysis_result"):
                    flags.append("analyzed")
                if update.get("review_verdict"):
                    flags.append("reviewed")
                if update.get("report_data"):
                    flags.append("written")
                if update.get("hitl_decision"):
                    flags.append("hitl_decided")
                if update.get("error"):
                    flags.append(f"error={update['error'][:50]}")
                logger.info("Analysis %s event#%d: %s", thread_id[:12], event_num, " → ".join(flags) if flags else "init")

        _add_token_entry(thread_id, "初始分析")
        _store[thread_id]["status"] = "completed"

        # Record initial version in history store
        if _current_db_version(thread_id) is None and _store[thread_id].get("state", {}).get("report_data"):
            rd = _store[thread_id]["state"]["report_data"]
            _history_store.insert(thread_id, None, "", "initial",
                {"report_data": rd.model_dump() if hasattr(rd, "model_dump") else rd})

        logger.info("Analysis %s completed", thread_id)

    except Exception as e:
        logger.exception("Analysis %s failed: %s", thread_id, e)
        if thread_id in _store:
            _store[thread_id]["status"] = "failed"
            _store[thread_id]["state"]["error"] = str(e)


async def _stream_events(thread_id: str) -> AsyncGenerator[str, None]:
    """Generate SSE events for a running analysis."""
    last_status = "running"

    while last_status == "running":
        entry = _store.get(thread_id)
        if entry is None:
            yield f"event: error\ndata: {json.dumps({'error': 'Thread not found'})}\n\n"
            return

        current_status = entry.get("status", "unknown")
        if current_status != last_status:
            last_status = current_status

        state = entry.get("state", {})
        event_data = {
            "thread_id": thread_id,
            "status": current_status,
            "collected_count": len(state.get("collected_data") or []),
            "review_round": state.get("review_round", 0),
            "has_analysis": state.get("analysis_result") is not None,
            "has_report": state.get("report_data") is not None,
        }

        yield f"event: state_update\ndata: {json.dumps(event_data, default=str)}\n\n"

        if current_status in ("completed", "failed"):
            yield f"event: end\ndata: {json.dumps({'status': current_status})}\n\n"
            return

        await asyncio.sleep(1.0)  # Poll every second
