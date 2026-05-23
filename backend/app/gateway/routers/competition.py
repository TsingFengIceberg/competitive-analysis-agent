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
from typing import AsyncGenerator

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
    }

    _store[thread_id] = {
        "status": "running",
        "state": initial_state,
        "created_at": datetime.now(UTC).isoformat(),
        "query": request.query,
        "products": request.target_products,
    }

    # Launch graph in background (in production: via RunManager)
    asyncio.create_task(_run_graph_async(thread_id))

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

    return ReportResponse(
        thread_id=thread_id,
        status=status,
        report_data=report_data,
        metrics=metrics,
        error=error,
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


# ── Internal ──


async def _run_graph_async(thread_id: str) -> None:
    """Run the competition graph in background, updating _store as it progresses."""
    try:
        from deerflow.competition.graph import build_competition_graph
        from deerflow.competition.state import CompetitionState

        entry = _store.get(thread_id)
        if not entry:
            return

        graph = build_competition_graph()
        initial_state = CompetitionState(**entry["state"])

        # Stream execution — updates store on each node completion
        for event in graph.stream(initial_state, stream_mode=["values", "updates"]):
            # event is {node_name: state_update_dict}
            for node_name, update in event.items():
                if isinstance(update, dict):
                    current = _store[thread_id].get("state", {})
                    current.update(update)  # noqa: PD020 ambiguous-variable-name
                    _store[thread_id]["state"] = current

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
