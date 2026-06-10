"""Deep Writer node (P1) — extended report with full export suite.

Per COMPETITION_PLAN.md §3.1: ReportData + HTML export + Feishu Doc push.
Reuses normal-mode Writer's ReportData generation.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def deep_writer_node(state: dict) -> dict:
    """Graph node: generate deep-mode report with extended sections.

    Reuses normal-mode Writer's section building + adds deep-specific sections.
    """
    analysis = state.get("analysis_result") or {}
    verdict = state.get("review_verdict") or {}
    collected = (state.get("collected_data") or []) + (state.get("deep_collected_data") or [])
    persona = state.get("persona", "pm")
    target_products = state.get("target_products", [])
    quality = verdict.get("quality_summary", {})

    from competition.nodes.writer import (
        _build_review_package,
        _build_sections,
        _build_title,
        _build_traceability_map,
        _compute_report_metrics,
        writer_self_check,
    )

    sections = _build_sections(analysis, verdict, persona, target_products, None, collected, quality)
    # Add deep-mode specific sections
    sections.append({
        "id": "appendix-deep-sources",
        "title": "附录 B: 深度模式数据来源",
        "content": f"深度模式额外采集了 {len(state.get('deep_collected_data') or [])} 条数据，来自视频/抖音/飞书文档等深层源。",
        "content_type": "text", "source_ids": [], "chart_path": None, "subsections": None,
    })

    traceability = _build_traceability_map(collected)
    forecast = analysis.get("forecast")
    metrics = _compute_report_metrics(collected, verdict, traceability)
    review_package = _build_review_package(
        {"sections": sections, "products": target_products}, collected, quality
    )

    report_data = {
        "persona": persona,
        "title": _build_title(target_products, persona) + " (深度模式)",
        "generated_at": _now_iso(),
        "products": target_products,
        "sections": sections,
        "traceability_map": traceability,
        "quality_summary": quality,
        "forecast": forecast,
        "metrics": metrics,
    }

    issues = writer_self_check(report_data, target_products)
    if issues:
        logger.warning("Deep Writer self-check: %d issues", len(issues))

    return {
        "report_data": report_data,
        "traceability_map": traceability,
        "review_package": review_package,
        "deep_report": _generate_html_export(report_data),
    }


def _generate_html_export(report_data: dict) -> str:
    """Generate self-contained HTML export from ReportData (P2)."""
    title = report_data.get("title", "竞品分析报告")
    sections_html = ""
    for s in report_data.get("sections", []):
        sections_html += f"<h2>{s.get('title', '')}</h2>\n"
        sections_html += f"<div>{s.get('content', '')}</div>\n"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>{title}</title></head>
<body>
<h1>{title}</h1>
<p>生成时间: {report_data.get('generated_at', '')} | 视角: {report_data.get('persona', '')}</p>
{sections_html}
<footer><p>CI-Agent 竞品分析系统 — 深度模式</p></footer>
</body>
</html>"""


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()
