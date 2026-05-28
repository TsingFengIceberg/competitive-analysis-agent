"""Competition analysis API router — App layer gateway.

Per COMPETITION_PLAN.md §8 Week 2:
- POST /api/competition/analyze — Start competitive analysis
- GET /api/competition/report/{thread_id} — Get generated report
- GET /api/competition/stream/{thread_id} — SSE stream of graph execution
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/competition", tags=["competition"])


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


# ── In-memory store (replaced by DF checkpointer in production) ──

_store: dict[str, dict] = {}


# ── Routes ──


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """Start a competitive analysis. Returns thread_id for polling/streaming."""
    import uuid
    from datetime import UTC, datetime

    thread_id = f"comp-{uuid.uuid4().hex[:12]}"

    # Build initial state
    initial_state = {
        "messages": [],
        "user_request": request.query,
        "target_products": request.target_products,
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
        "products": request.target_products,
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
    history = entry.get("report_history", [])
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
    """Get report revision history."""
    entry = _store.get(thread_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")
    history = entry.get("report_history", [])
    return {"history": history, "count": len(history)}


class HitlDecisionRequest(BaseModel):
    """HITL decision or what-if input from frontend."""

    action: str = "rewrite"  # "approve" | "rewrite" | "reanalyze" | "replan"
    comment: str = ""
    target_focus: list[str] | None = None


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

    # Always record the decision and trigger action (with or without comment)
    state["hitl_decision"] = {
        "action": decision.action,
        "comment": decision.comment,
        "target_focus": decision.target_focus,
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    }
    _store[thread_id]["state"] = state

    if decision.action in ("rewrite", "reanalyze", "replan"):
        # Fire background thread, return immediately
        _store[thread_id]["status"] = "running"
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _reanalyze_sync, thread_id, decision.action)

    if decision.action == "approve":
        _store[thread_id]["status"] = "approved"
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
    import copy
    import logging
    logger = logging.getLogger(__name__)

    try:
        entry = _store.get(thread_id)
        if not entry:
            return
        state = entry["state"]

        # Save current report to history before overwriting
        old_report = state.get("report_data")
        if old_report:
            history = entry.setdefault("report_history", [])
            history.append({
                "version": len(history) + 1,
                "timestamp": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
                "hitl_decision": copy.deepcopy(state.get("hitl_decision", {})),
                "report_data": copy.deepcopy(old_report),
            })
            logger.info("Saved report v%d to history for %s", len(history), thread_id[:12])

        # Inject user feedback into user_request for reanalyze/replan (Analyst sees it)
        # For rewrite, the comment is used as what-if scenario by Writer directly
        comment = state.get("hitl_decision", {}).get("comment", "")
        if comment and action in ("reanalyze", "replan"):
            state["user_request"] = f"{state.get('user_request', '')}\n\n用户反馈意见: {comment}"
            logger.info("Reanalysis with feedback: %s", comment[:100])

        from deerflow.competition.nodes.writer import writer_node

        if action == "rewrite":
            # What-if: Writer only
            result = writer_node(state)
            state.update(result)
        elif action == "reanalyze":
            # Full reanalysis: Analyst → Reviewer → Writer
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
            # Full replan: Collector → Analyst → Reviewer → Writer
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
        version = len(entry.get("report_history", [])) + 1
        label = f"{action_labels.get(action, action)} v{version}"
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
    """List recent analysis history."""
    history = []
    for tid, entry in list(_store.items())[-limit:]:
        history.append({
            "thread_id": tid,
            "query": entry.get("query", ""),
            "products": entry.get("products", []),
            "status": entry.get("status", "unknown"),
            "created_at": entry.get("created_at", ""),
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

        graph = build_competition_graph()
        initial_state = CompetitionState(**entry["state"])

        # Stream execution — updates store on each node completion
        event_num = 0
        for event in graph.stream(initial_state, stream_mode=["values"]):
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
