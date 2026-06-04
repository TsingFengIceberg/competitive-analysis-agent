"""DAG execution state extractor — reads CompetitionState, outputs render-ready JSON.

Per COMPETITION_PLAN.md §7.2: node highlighter + edge animation + feedback loop visualization.
Framework-agnostic: Gradio (gr.Plot) and Next.js (ReactFlow) consume the same JSON.
"""

from __future__ import annotations

from typing import Literal

NodeStatus = Literal["waiting", "active", "done", "error", "hitl_pending"]

# DAG topology — fixed, not derived from state
DAG_TOPOLOGY = {
    "nodes": [
        {"id": "collector", "label": "Collector", "description": "多源采集 + 去重 + 软停止"},
        {"id": "analyst", "label": "Analyst", "description": "对比矩阵 + SWOT + 趋势 + 预测"},
        {"id": "reviewer", "label": "Reviewer", "description": "8 项计算验证 + gap 生成"},
        {"id": "writer", "label": "Writer", "description": "ReportData 交互报告 + 双视角"},
        {"id": "hitl_gate", "label": "HITL Gate", "description": "4 向审批 + 自由文本"},
        {"id": "error_handler", "label": "Error Handler", "description": "D/C 类故障降级"},
        {"id": "deep_collector", "label": "Deep Collector", "description": "增量采集 + 深层源"},
        {"id": "deep_analyst", "label": "Deep Analyst", "description": "细分 + 财务 + 全量可视化"},
        {"id": "deep_reviewer", "label": "Deep Reviewer", "description": "5 轮验证宽松上限"},
        {"id": "deep_writer", "label": "Deep Writer", "description": "深度报告 + HTML 导出"},
        {"id": "deep_hitl", "label": "Deep HITL", "description": "二次审批"},
        {"id": "deep_error_handler", "label": "Deep Error", "description": "深度模式降级"},
        {"id": "feishu_delivery", "label": "Feishu Delivery", "description": "飞书文档 + Bot 通知"},
    ],
    "edges": [
        # Normal mode
        {"id": "c2a", "from": "collector", "to": "analyst", "type": "normal"},
        {"id": "a2r", "from": "analyst", "to": "reviewer", "type": "normal"},
        {"id": "r2w", "from": "reviewer", "to": "writer", "type": "normal", "condition": "passed"},
        {"id": "r2c", "from": "reviewer", "to": "collector", "type": "feedback", "condition": "gap + round<2", "style": "dashed"},
        {"id": "w2h", "from": "writer", "to": "hitl_gate", "type": "normal"},
        {"id": "h2end", "from": "hitl_gate", "to": "__end__", "type": "normal", "condition": "approve"},
        {"id": "h2c", "from": "hitl_gate", "to": "collector", "type": "feedback", "condition": "replan"},
        {"id": "h2a", "from": "hitl_gate", "to": "analyst", "type": "feedback", "condition": "reanalyze"},
        {"id": "h2w", "from": "hitl_gate", "to": "writer", "type": "feedback", "condition": "rewrite"},
        {"id": "c2err", "from": "collector", "to": "error_handler", "type": "error"},
        {"id": "a2err", "from": "analyst", "to": "error_handler", "type": "error"},
        {"id": "r2err", "from": "reviewer", "to": "error_handler", "type": "error"},
        {"id": "w2err", "from": "writer", "to": "error_handler", "type": "error"},
        # Deep mode
        {"id": "h2dc", "from": "hitl_gate", "to": "deep_collector", "type": "deep", "condition": "approve + deep_mode"},
        {"id": "dc2da", "from": "deep_collector", "to": "deep_analyst", "type": "deep"},
        {"id": "da2dr", "from": "deep_analyst", "to": "deep_reviewer", "type": "deep"},
        {"id": "dr2dw", "from": "deep_reviewer", "to": "deep_writer", "type": "deep", "condition": "passed / round>=5"},
        {"id": "dr2dc", "from": "deep_reviewer", "to": "deep_collector", "type": "deep_feedback", "condition": "gap", "style": "dashed"},
        {"id": "dw2dh", "from": "deep_writer", "to": "deep_hitl", "type": "deep"},
        {"id": "dh2f", "from": "deep_hitl", "to": "feishu_delivery", "type": "deep", "condition": "approve"},
        {"id": "dc2derr", "from": "deep_collector", "to": "deep_error_handler", "type": "deep_error"},
        {"id": "da2derr", "from": "deep_analyst", "to": "deep_error_handler", "type": "deep_error"},
        {"id": "dr2derr", "from": "deep_reviewer", "to": "deep_error_handler", "type": "deep_error"},
        {"id": "dw2derr", "from": "deep_writer", "to": "deep_error_handler", "type": "deep_error"},
    ],
}

# Node completion order for state inference (§7.2)
_NODE_ORDER = [
    "collector", "analyst", "reviewer", "writer", "hitl_gate",
    "deep_collector", "deep_analyst", "deep_reviewer", "deep_writer",
    "deep_hitl", "feishu_delivery",
]


def get_dag_state(state: dict) -> dict:
    """Extract current DAG visualization state from CompetitionState.

    Returns render-ready dict with node statuses, edge highlights, and annotations.
    Frontend (Gradio/Next.js) consumes this JSON directly.
    """
    error = state.get("error")
    current_node = _infer_current_node(state)

    # Compute per-node status
    node_states: dict[str, dict] = {}
    for node in DAG_TOPOLOGY["nodes"]:
        nid = node["id"]
        status = _compute_node_status(nid, state, current_node, error)
        annotation = _compute_node_annotation(nid, state)
        self_assessment = _get_self_assessment(nid, state)
        node_states[nid] = {
            **node,
            "status": status,
            "annotation": annotation,
            "self_assessment": self_assessment,
            "style": _node_style(status),
        }

    # Compute per-edge highlights + annotations
    edge_states: list[dict] = []
    for edge in DAG_TOPOLOGY["edges"]:
        edge_data = {**edge}
        annotation = _compute_edge_annotation(edge, state)
        if annotation:
            edge_data["annotation"] = annotation
        edge_data["active"] = _is_edge_active(edge, node_states, state)
        edge_states.append(edge_data)

    return {
        "nodes": list(node_states.values()),
        "edges": edge_states,
        "current_node": current_node,
        "deep_mode_active": bool(state.get("deep_mode")),
        "review_round": state.get("review_round", 0),
        "deep_review_round": state.get("deep_review_round", 0),
        "error": error,
        "summary": _build_summary(state),
    }


def _infer_current_node(state: dict) -> str | None:
    """Infer which node is currently active from state fields.

    Walk the expected execution order, find the first incomplete node.
    """
    has_data = bool(state.get("collected_data"))
    has_analysis = bool(state.get("analysis_result"))
    has_verdict = bool(state.get("review_verdict"))
    has_report = bool(state.get("report_data"))
    has_decision = bool(state.get("hitl_decision"))

    if state.get("error"):
        return "error_handler"

    if not has_data:
        return "collector"
    if not has_analysis:
        return "analyst"
    if not has_verdict:
        return "reviewer"
    if not has_report:
        return "writer"
    if not has_decision:
        return "hitl_gate"

    # Normal mode done — check deep
    if state.get("deep_mode"):
        deep_round = state.get("deep_review_round", 0)
        if not state.get("deep_collected_data"):
            return "deep_collector"
        # Simplified: deep mode state inference
        if deep_round > 0 and not state.get("deep_report"):
            return "deep_reviewer"
        if not state.get("deep_report"):
            return "deep_writer"

    return None  # All done


def _compute_node_status(node_id: str, state: dict, current: str | None, error: str | None) -> NodeStatus:
    """Compute visual status for a single DAG node."""
    if error and node_id == "error_handler":
        return "active"

    # Deep mode nodes: only visible in deep mode
    if node_id.startswith("deep_") and not state.get("deep_mode"):
        return "waiting"
    if node_id == "feishu_delivery" and not state.get("deep_mode"):
        return "waiting"

    # Done detection
    if node_id == "collector" and state.get("collected_data"):
        return "done"
    if node_id == "analyst" and state.get("analysis_result"):
        return "done"
    if node_id == "reviewer" and state.get("review_verdict"):
        return "done"
    if node_id == "writer" and state.get("report_data"):
        return "done"
    if node_id == "hitl_gate" and state.get("hitl_decision"):
        decision = state.get("hitl_decision", {})
        action = decision.get("action", "")
        if action == "approve":
            return "done"
        return "hitl_pending"

    # Active
    if current == node_id:
        return "active"

    return "waiting"


def _compute_node_annotation(node_id: str, state: dict) -> str | None:
    """Compute annotation text for a DAG node."""
    if node_id == "collector":
        data = state.get("collected_data") or []
        if data:
            summary = state.get("collection_summary") or {}
            return f"{len(data)} data points, stopped: {summary.get('stopped_by', '?')}"
    elif node_id == "reviewer":
        verdict = state.get("review_verdict") or {}
        gaps = verdict.get("gaps", [])
        if gaps:
            return f"{len(gaps)} gap(s)"
        if verdict.get("passed"):
            return "passed"
    elif node_id == "writer":
        if state.get("report_data"):
            return "generated"
    elif node_id == "hitl_gate":
        decision = state.get("hitl_decision") or {}
        action = decision.get("action", "")
        if action:
            return f"→ {action}"
    return None


def _compute_edge_annotation(edge: dict, state: dict) -> str | None:
    """Compute annotation for an edge."""
    edge_id = edge["id"]
    if edge_id == "r2c":
        review_round = state.get("review_round", 0)
        return f"round {review_round}/2" if review_round > 0 else None
    if edge_id == "r2w":
        verdict = state.get("review_verdict") or {}
        if verdict.get("passed"):
            return "passed"
        review_round = state.get("review_round", 0)
        if review_round >= 2:
            return "forced"
    return None


def _is_edge_active(edge: dict, node_states: dict, state: dict) -> bool:
    """Check if an edge should be highlighted (active flow)."""
    from_id = edge["from"]
    to_id = edge["to"]
    from_status = node_states.get(from_id, {}).get("status", "waiting")
    to_status = node_states.get(to_id, {}).get("status", "waiting")

    # Active: source is done, target is active or waiting
    if from_status == "done" and to_status in ("active", "waiting"):
        # Feedback edges only active when gap exists
        if edge.get("type") in ("feedback", "deep_feedback"):
            verdict = state.get("review_verdict") or {}
            has_gaps = len(verdict.get("gaps", [])) > 0
            review_round = state.get("review_round", 0)
            return has_gaps and review_round < 2
        # Deep edges only active in deep mode
        if edge.get("type") == "deep" and not state.get("deep_mode"):
            return False
        return True
    return False


def _node_style(status: NodeStatus) -> dict:
    """Return visual style for a node status."""
    styles = {
        "waiting": {"color": "#9E9E9E", "icon": "⚪", "animation": None},
        "active": {"color": "#4CAF50", "icon": "🟢", "animation": "pulse"},
        "done": {"color": "#2196F3", "icon": "✅", "animation": None},
        "error": {"color": "#F44336", "icon": "🔴", "animation": None},
        "hitl_pending": {"color": "#FF9800", "icon": "🟡", "animation": "blink"},
    }
    return styles.get(status, styles["waiting"])


def _get_self_assessment(node_id: str, state: dict) -> dict | None:
    """Extract self-assessment data for a node from the state.

    Returns a dict with 'score' (0.0-1.0) and 'label' for frontend display,
    or None if self-assessment is not yet computed for this node.
    """
    assessment_map = {
        "collector": "collector_self_assessment",
        "analyst": "analyst_self_assessment",
        "writer": "writer_self_assessment",
    }

    key = assessment_map.get(node_id)
    if not key:
        return None

    data = state.get(key)
    if not data:
        return None

    # Extract the primary score based on node type
    if node_id == "collector":
        score = data.get("coverage_score", 0)
    elif node_id == "analyst":
        score = data.get("cross_validated_ratio", 0)
    elif node_id == "writer":
        score = data.get("overall_score", data.get("section_completeness", 0))
    else:
        return None

    # Determine color tier
    if score >= 0.8:
        tier = "green"
    elif score >= 0.6:
        tier = "yellow"
    else:
        tier = "red"

    return {
        "score": score,
        "tier": tier,
        "details": {
            k: v for k, v in data.items()
            if k not in ("section_status", "product_mention_check", "missing_required")
        },
    }


def _build_summary(state: dict) -> dict:
    """Build overall DAG summary for the bottom status bar (§7.7)."""
    collected = len(state.get("collected_data") or [])
    review_round = state.get("review_round", 0)
    improvement = state.get("gap_coverage_improvement")

    return {
        "total_data_points": collected,
        "review_rounds": review_round,
        "improvement_ratio": improvement,
        "deep_mode": bool(state.get("deep_mode")),
    }
