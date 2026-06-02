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
    return {
        "version": version,
        "parent_version": meta.get("parent_version"),
        "action": meta.get("action"),
        "is_approved": meta.get("is_approved"),
        "created_at": meta.get("created_at"),
        "report_data": state.get("report_data") if version == _current_db_version(thread_id) else None,
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
        result.append({
            "version": r["version"],
            "parent_version": r["parent_version"],
            "checkpoint_id": r["checkpoint_id"],
            "action": r["action"],
            "is_approved": r["is_approved"],
            "created_at": r["created_at"],
            "metadata": r.get("metadata_json", {}),
            "report_data": state.get("report_data") if is_latest else None,
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

# Known product aliases for quick correction (avoid LLM call for common cases)
_PRODUCT_ALIASES: dict[str, str] = {
    "copilot": "GitHub Copilot",
    "github copilot": "GitHub Copilot",
    "gh copilot": "GitHub Copilot",
    "cursor": "Cursor",
    "cursor ai": "Cursor",
    "cursor ide": "Cursor",
    "windsurf": "Windsurf",
    "windsurf ide": "Windsurf",
    "codeium": "Codeium",
    "codeium windsurf": "Windsurf",
    "claude": "Claude",
    "claude code": "Claude Code",
    "claude ai": "Claude",
    "chatgpt": "ChatGPT",
    "gpt": "ChatGPT",
    "copilot x": "GitHub Copilot",
    "tabnine": "TabNine",
    "kite": "Kite",
    "jetbrains ai": "JetBrains AI",
    "aws codewhisperer": "Amazon CodeWhisperer",
    "codewhisperer": "Amazon CodeWhisperer",
    "qwen": "Qwen",
    "tongyi": "Tongyi Lingma",
    "lingma": "Tongyi Lingma",
    "codex": "OpenAI Codex",
    "replit": "Replit",
    "replit ghostwriter": "Replit",
    "v0": "Vercel v0",
    "vercel": "Vercel v0",
    "bolt": "Bolt.new",
    "lovable": "Lovable",
    "devin": "Devin",
    "cognition": "Devin",
    "sourcegraph": "Sourcegraph Cody",
    "cody": "Sourcegraph Cody",
    "augment": "Augment Code",
    "augment code": "Augment Code",
    "super maven": "Supermaven",
    "supermaven": "Supermaven",
}


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

        verified = _verify_products_via_search(new_candidates, strictness=round_num)
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



def _verify_products_via_search(candidates: list[str], strictness: int = 1) -> list[str]:
    """Verify product names via web search with progressive permissiveness.

    strictness=1: exact match required (search must return results for name)
    strictness=2: broader search, accept if any result mentions the name
    strictness=3: very permissive, accept almost everything
    """
    try:
        from deerflow.competition.tools.search import search as web_search
    except ImportError:
        return candidates

    verified: list[str] = []
    for name in candidates:
        key = name.lower()
        if key in _PRODUCT_ALIASES:
            corrected = _PRODUCT_ALIASES[key]
            if corrected not in verified:
                verified.append(corrected)
            continue

        try:
            if strictness <= 2:
                response = web_search(f'"{name}" software tool', max_results=3)
            else:
                # Round 3: just search the name, no quotes, very broad
                response = web_search(f"{name} tool", max_results=2)

            if response.results:
                verified.append(name)
            elif strictness >= 2:
                # Try an even broader search
                response2 = web_search(name, max_results=2)
                if response2.results:
                    verified.append(name)
                else:
                    logger.warning("Product '%s' unverified (round %d) — keeping", name, strictness)
                    verified.append(name)  # round 2+ accepts unverified
            else:
                logger.info("Product '%s' discarded (strict verification failed)", name)
        except Exception:
            if strictness >= 2:
                verified.append(name)

    return verified


async def _resolve_products(query: str, explicit_products: list[str]) -> list[str]:
    """Resolve target products with auto-extraction and typo correction.

    Strategy:
      1. If explicit products provided, normalize each via alias table + LLM correction
      2. If empty, extract from query text via regex → LLM fallback
      3. Guarantee: at least one product is returned (never empty)
    """
    import logging
    _log = logging.getLogger(__name__)

    products: list[str] = []

    if explicit_products:
        # Normalize each explicit product
        for p in explicit_products:
            p = p.strip()
            if not p:
                continue
            key = p.lower()
            corrected = _PRODUCT_ALIASES.get(key)
            if corrected:
                if corrected not in products:
                    products.append(corrected)
            else:
                # Unknown product — keep as-is but try fuzzy correction later
                if p not in products:
                    products.append(p)
    else:
        # No explicit products — extract from query via LLM
        pass

    # LLM extraction when no explicit products
    if not products:
        _log.info("No products from explicit list — extracting via LLM")
        import asyncio
        loop = asyncio.get_event_loop()
        products = await loop.run_in_executor(None, _llm_extract_products, query)

    # If still empty, return empty — caller will surface error to user
    if not products:
        _log.warning("Could not extract any products from query: '%s'", query[:80])

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for p in products:
        if p.lower() not in seen:
            seen.add(p.lower())
            result.append(p)

    _log.info("Resolved products: %s (from query: '%s')", result, query[:80])
    return result


# ── Routes ──


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Start a competitive analysis. Returns thread_id for polling/streaming."""
    import uuid
    from datetime import UTC, datetime

    thread_id = f"comp-{uuid.uuid4().hex[:12]}"

    # Resolve target products: explicit list > NLP extraction from query > LLM fallback
    target_products = await _resolve_products(request.query, request.target_products)

    if not target_products:
        raise HTTPException(
            status_code=400,
            detail="无法从分析请求中提取竞品名称，请在「竞品名称」输入框中明确指定（逗号分隔）。",
        )

    # Build initial state
    initial_state = {
        "messages": [],
        "user_request": request.query,
        "target_products": target_products,
        "persona": request.persona,
        "deep_mode": request.deep_mode,
        "collected_data": [],
        "context_report": request.context_report,
    }

    _store[thread_id] = {
        "status": "running",
        "state": initial_state,
        "created_at": datetime.now(UTC).isoformat(),
        "query": request.query,
        "products": target_products,
    }

    # Launch graph in background thread (sync LLM calls would block asyncio event loop)
    asyncio.get_event_loop().run_in_executor(None, _run_graph_sync, thread_id)

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
                {"comment": state.get("hitl_decision", {}).get("comment", "")},
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
            _history_store.insert(thread_id, None, "", "initial")

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
