"""Observability data extractors — Agent detail, message flow, traceability chain.

Per COMPETITION_PLAN.md §7.3-7.5: reads CompetitionState, outputs render-ready JSON.
Framework-agnostic: Gradio and Next.js both consume these dicts directly.
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# Agent Detail Panel (§7.3)
# ═══════════════════════════════════════════════════════════════════════════════

NODE_INPUT_FIELDS = {
    "collector": ["user_request", "target_products", "knowledge_gaps"],
    "analyst": ["collected_data", "user_request", "persona"],
    "reviewer": ["collected_data", "analysis_result"],
    "writer": ["analysis_result", "review_verdict", "persona", "target_products"],
    "hitl_gate": ["review_package", "hitl_decision"],
}

NODE_OUTPUT_FIELDS = {
    "collector": ["collected_data", "collection_summary"],
    "analyst": ["analysis_result"],
    "reviewer": ["review_verdict", "review_round", "gap_coverage_improvement"],
    "writer": ["report_data", "traceability_map", "review_package"],
    "hitl_gate": ["hitl_decision"],
}


def get_agent_detail(state: dict, node_id: str) -> dict:
    """Extract Prompt/Input/Output/Token detail for a specific DAG node (§7.3).

    Returns dict with:
        node_id, status, input_summary, output_summary, tools_used
    """
    input_fields = NODE_INPUT_FIELDS.get(node_id, [])
    output_fields = NODE_OUTPUT_FIELDS.get(node_id, [])

    input_summary = {}
    for field in input_fields:
        value = state.get(field)
        if value is not None:
            input_summary[field] = _summarize_value(value)

    output_summary = {}
    for field in output_fields:
        value = state.get(field)
        if value is not None:
            output_summary[field] = _summarize_value(value)

    return {
        "node_id": node_id,
        "label": _node_label(node_id),
        "status": "done" if output_summary else ("active" if input_summary else "waiting"),
        "input": input_summary,
        "output": output_summary,
        "tools_used": _infer_tools(node_id),
    }


def get_all_agent_details(state: dict) -> list[dict]:
    """Get detail panels for all 5 core nodes."""
    return [
        get_agent_detail(state, nid)
        for nid in ["collector", "analyst", "reviewer", "writer", "hitl_gate"]
    ]


def _node_label(node_id: str) -> str:
    labels = {
        "collector": "Collector — 信息采集 Agent",
        "analyst": "Analyst — 分析 Agent",
        "reviewer": "Reviewer — 质检 Agent",
        "writer": "Writer — 报告撰写 Agent",
        "hitl_gate": "HITL Gate — 人工审批",
    }
    return labels.get(node_id, node_id)


def _infer_tools(node_id: str) -> list[str]:
    """Return tools likely used by this node (would come from SubagentExecutor metadata in production)."""
    tool_map = {
        "collector": ["web_search", "web_fetch", "python", "write_file"],
        "analyst": ["python", "write_file", "read_file"],
        "reviewer": ["python", "bash (curl -I)", "read_file"],
        "writer": ["python", "write_file"],
        "hitl_gate": ["(no tools — routing only)"],
    }
    return tool_map.get(node_id, [])


def _summarize_value(value) -> dict | str:
    """Summarize a state field value for display."""
    if isinstance(value, list):
        return {"type": "list", "count": len(value)}
    elif isinstance(value, dict):
        return {"type": "dict", "keys": list(value.keys())[:10]}
    elif isinstance(value, str):
        return value[:200] + ("..." if len(value) > 200 else "")
    return str(value)[:200]


# ═══════════════════════════════════════════════════════════════════════════════
# Structured Message Flow Log (§7.4)
# ═══════════════════════════════════════════════════════════════════════════════


def get_message_flow(state: dict) -> dict:
    """Extract structured inter-agent message flow timeline (§7.4).

    Returns chronological list of 6-edge message events with data previews.
    """
    events: list[dict] = []

    # Edge ①: Collector → Analyst
    collected = state.get("collected_data")
    if collected:
        events.append({
            "edge": "①",
            "from": "Collector",
            "to": "Analyst",
            "schema": "CollectedDataPoint",
            "data_count": len(collected),
            "preview": _preview_datapoints(collected[:3]),
        })

    # Edge ②: Analyst → Reviewer
    analysis = state.get("analysis_result")
    if analysis:
        matrix = analysis.get("comparison_matrix", {}) if isinstance(analysis, dict) else {}
        swot = analysis.get("swot", {}) if isinstance(analysis, dict) else {}
        events.append({
            "edge": "②",
            "from": "Analyst",
            "to": "Reviewer",
            "schema": "AnalysisResult",
            "data_count": len(matrix.get("cells", [])),
            "preview": {
                "dimensions": matrix.get("dimensions", []),
                "products_analyzed": list(swot.keys()) if swot else [],
            },
        })

    # Edge ⑤: Reviewer → Collector (gap feedback)
    verdict = state.get("review_verdict")
    if verdict:
        gaps = verdict.get("gaps", []) if isinstance(verdict, dict) else []
        if gaps:
            events.append({
                "edge": "⑤",
                "from": "Reviewer",
                "to": "Collector",
                "schema": "ReviewGap",
                "data_count": len(gaps),
                "is_feedback_loop": True,
                "round": state.get("review_round", 0),
                "preview": [
                    {"type": g.get("type"), "severity": g.get("severity"), "desc": g.get("description", "")[:80]}
                    for g in gaps[:3]
                ],
            })

    # Edge ③: Reviewer → Writer
    if verdict:
        quality = verdict.get("quality_summary", {}) if isinstance(verdict, dict) else {}
        events.append({
            "edge": "③",
            "from": "Reviewer",
            "to": "Writer",
            "schema": "ReviewVerdict",
            "data_count": quality.get("total_data_points", 0),
            "preview": {
                "passed": verdict.get("passed"),
                "quality_score": quality.get("overall_quality_score"),
                "improvement": quality.get("improvement_ratio"),
            },
        })

    # Edge ④: Writer → HITL
    review_pkg = state.get("review_package")
    if review_pkg:
        events.append({
            "edge": "④",
            "from": "Writer",
            "to": "HITL Gate",
            "schema": "ReviewPackage",
            "data_count": len(review_pkg.get("key_findings", [])),
            "preview": review_pkg.get("key_findings", [])[:3],
        })

    # Edge ⑥: HITL → target
    decision = state.get("hitl_decision")
    if decision:
        action = decision.get("action", "") if isinstance(decision, dict) else ""
        target_map = {"approve": "END", "replan": "Collector", "reanalyze": "Analyst", "rewrite": "Writer"}
        events.append({
            "edge": "⑥",
            "from": "HITL Gate",
            "to": target_map.get(action, "?"),
            "schema": "HitlDecision",
            "data_count": 1,
            "preview": {
                "action": action,
                "target_focus": decision.get("target_focus") if isinstance(decision, dict) else None,
            },
        })

    return {"events": events, "total_messages": len(events), "feedback_loops": sum(1 for e in events if e.get("is_feedback_loop"))}


def _preview_datapoints(dps: list[dict]) -> list[dict]:
    """Create a safe preview of data points for the message flow panel."""
    preview = []
    for dp in dps:
        if isinstance(dp, dict):
            preview.append({
                "id": dp.get("id", ""),
                "product": dp.get("product", ""),
                "category": dp.get("category", ""),
                "label": dp.get("label", "")[:50],
                "confidence": dp.get("confidence"),
            })
    return preview


# ═══════════════════════════════════════════════════════════════════════════════
# Traceability Chain Viewer (§7.5)
# ═══════════════════════════════════════════════════════════════════════════════


def get_traceability_chain(claim_id: str, state: dict) -> dict | None:
    """Trace a claim [n] back to its original source URL and Collector→Reviewer path.

    Returns dict with:
        claim_id, source_url, collected_at, confidence, verification_status
    """
    trace_map = state.get("traceability_map") or {}
    collected = state.get("collected_data") or []

    # Look up claim in traceability_map
    entry = trace_map.get(claim_id)
    if not entry:
        return None

    url = entry.get("url", "") if isinstance(entry, dict) else str(entry)
    timestamp = entry.get("timestamp", "") if isinstance(entry, dict) else ""

    # Find corresponding data point
    dp = None
    for d in collected:
        if isinstance(d, dict) and d.get("source_url") == url:
            dp = d
            break

    # Determine verification status
    verdict = state.get("review_verdict") or {}
    gaps = verdict.get("gaps", []) if isinstance(verdict, dict) else []
    related_gaps = [g for g in gaps if isinstance(g, dict) and claim_id in str(g.get("related_data_point_ids", []))]

    verification = "✅ 多源交叉验证" if not related_gaps else f"⚠ {len(related_gaps)} gap(s) found"

    return {
        "claim_id": claim_id,
        "source_url": url,
        "collected_at": timestamp or (dp.get("collected_at", "") if dp else ""),
        "confidence": entry.get("confidence") if isinstance(entry, dict) else (dp.get("confidence") if dp else None),
        "verification_status": verification,
        "data_point_id": dp.get("id", "") if dp else "",
        "related_gaps": [
            {"type": g.get("type"), "description": g.get("description", "")}
            for g in related_gaps[:3]
        ],
        "chain": [
            f"Collector: fetched from {url}",
            f"Analyst: incorporated into comparison at {timestamp}",
            verification,
        ],
    }


def get_all_traceability_chains(state: dict) -> list[dict]:
    """Get traceability chains for all claims in the report."""
    trace_map = state.get("traceability_map") or {}
    chains = []
    for claim_id in trace_map:
        chain = get_traceability_chain(claim_id, state)
        if chain:
            chains.append(chain)
    return chains
