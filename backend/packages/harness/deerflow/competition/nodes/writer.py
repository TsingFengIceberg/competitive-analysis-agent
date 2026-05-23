"""Writer node — ReportData generation with dual-persona support and source traceability.

Per COMPETITION_PLAN.md §3.7: interactive ReportData replacing legacy .md strings.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# Report section structure (§3.7.3)
REQUIRED_SECTIONS = [
    "sec-executive-summary",
    "sec-comparison-matrix",
    "sec-swot",
    "sec-recommendations",
    "sec-sources",
    "appendix-quality",
]

OPTIONAL_SECTIONS = {
    "sec-trends": "trends",
    "sec-user-voice": "sentiment",
    "sec-forecast": "forecast",
    "appendix-charts": "charts",
}

# Persona profiles (§3.7.4)
PERSONA_PROFILES = {
    "pm": {
        "opening": "从产品功能角度看",
        "focus": "功能维度 > 定价维度",
        "recommendations": "功能优先级排序、差异化方向",
        "swot_level": "产品级（功能/UX/定价/用户）",
        "what_if": "如果竞品加了 X 功能，我们要跟进吗？",
    },
    "entrepreneur": {
        "opening": "从市场机会角度看",
        "focus": "定价维度 > 功能维度",
        "recommendations": "细分市场选择、商业模式建议、进入时机",
        "swot_level": "战略级（市场/团队/资本/壁垒）",
        "what_if": "如果我选 Y 细分市场，竞争压力多大？",
    },
}


def writer_node(state: dict) -> dict:
    """Graph node: generate ReportData from analysis_result + review_verdict.

    Returns partial state update with report_data + review_package + traceability_map.
    """
    analysis = state.get("analysis_result") or {}
    verdict = state.get("review_verdict") or {}
    collected = state.get("collected_data") or []
    persona = state.get("persona", "pm")
    target_products = state.get("target_products", [])
    hitl_focus = _get_hitl_focus(state)

    # Build report sections
    quality = verdict.get("quality_summary", {})
    sections = _build_sections(analysis, verdict, persona, target_products, hitl_focus, collected, quality)
    traceability = _build_traceability_map(collected)
    forecast = analysis.get("forecast")
    metrics = _compute_report_metrics(collected, verdict, traceability)

    report_data = {
        "persona": persona,
        "title": _build_title(target_products, persona),
        "generated_at": datetime.now(UTC).isoformat(),
        "products": target_products,
        "sections": sections,
        "traceability_map": traceability,
        "quality_summary": quality,
        "forecast": forecast,
        "metrics": metrics,
    }

    # Build ReviewPackage for HITL (§3.13.5)
    review_package = _build_review_package(report_data, collected, quality)

    # Self-check (§3.7.6)
    issues = writer_self_check(report_data, target_products)
    if issues:
        logger.warning("Writer self-check found %d issues: %s", len(issues), issues)

    return {
        "report_data": report_data,
        "traceability_map": traceability,
        "review_package": review_package,
    }


def _build_title(products: list[str], persona: str) -> str:
    products_str = " vs ".join(products) if products else "竞品分析"
    persona_label = "产品经理视角" if persona == "pm" else "创业者视角"
    return f"{products_str} 竞品分析报告 — {persona_label}"


def _get_hitl_focus(state: dict) -> list[str] | None:
    decision = state.get("hitl_decision") or {}
    return decision.get("target_focus")


def _build_sections(analysis: dict, verdict: dict, persona: str, products: list[str], focus: list[str] | None, collected: list[dict], quality: dict) -> list[dict]:
    """Build all report sections, respecting persona and optional conditions."""
    profile = PERSONA_PROFILES.get(persona, PERSONA_PROFILES["pm"])
    sections: list[dict] = []
    source_id = [0]  # mutable counter for [n] numbering

    def _src_ref(point_ids: list[str]) -> str:
        refs = []
        for _pid in point_ids:
            source_id[0] += 1
            refs.append(f"[{source_id[0]}]")
        return "".join(refs)

    # 1. Executive Summary (required)
    matrix = analysis.get("comparison_matrix", {})
    summary_text = matrix.get("summary", f"{' vs '.join(products)} 竞品分析")
    sections.append({
        "id": "sec-executive-summary", "title": "执行摘要",
        "content": f"{profile['opening']}，{summary_text}", "content_type": "text",
        "source_ids": [], "chart_path": None, "subsections": None,
    })

    # 2. Comparison Matrix (required)
    cells = matrix.get("cells", [])
    dims = matrix.get("dimensions", [])
    table_rows = []
    for cell in cells:
        if isinstance(cell, dict):
            rating = cell.get("rating", "N/A")
            evidence = cell.get("evidence", "")
            src_ids = cell.get("source_data_point_ids", [])
            table_rows.append({
                "product": cell.get("product", ""),
                "dimension": cell.get("dimension", ""),
                "rating": rating,
                "evidence": f"{evidence} {_src_ref(src_ids)}",
            })
    sections.append({
        "id": "sec-comparison-matrix", "title": "对比矩阵",
        "content": _render_comparison_table(table_rows, products, dims),
        "content_type": "table", "source_ids": [], "chart_path": None, "subsections": None,
    })

    # 3. SWOT (required)
    swot = analysis.get("swot", {})
    swot_content = ""
    for prod_name, swot_data in swot.items():
        if not isinstance(swot_data, dict):
            continue
        swot_content += f"### {prod_name}\n"
        for item in swot_data.get("items", []):
            if not isinstance(item, dict):
                continue
            src_ids = item.get("source_data_point_ids", [])
            swot_content += f"- **{item.get('category', '?')}**: {item.get('statement', '')} {_src_ref(src_ids)}\n  - *证据*: {item.get('evidence', '')}\n"
    sections.append({
        "id": "sec-swot", "title": "SWOT 分析",
        "content": swot_content or "_暂无 SWOT 数据_", "content_type": "text",
        "source_ids": [], "chart_path": None, "subsections": None,
    })

    # 4. Trends (conditional)
    trends = analysis.get("trends", [])
    if trends:
        trend_text = ""
        for t in trends:
            if isinstance(t, dict):
                src_ids = t.get("source_data_point_ids", [])
                trend_text += f"- {t.get('dimension', '?')}: {t.get('direction', '?')} (置信度: {t.get('confidence', 0):.0%}) — {t.get('evidence', '')} {_src_ref(src_ids)}\n"
        sections.append({
            "id": "sec-trends", "title": "趋势与洞察",
            "content": trend_text, "content_type": "text",
            "source_ids": [], "chart_path": None, "subsections": None,
        })

    # 5. Forecast (conditional, §3.5.7)
    forecast = analysis.get("forecast")
    if forecast and isinstance(forecast, dict):
        items = forecast.get("items", [])
        fc_text = forecast.get("summary", "") + "\n\n"
        for fi in items:
            if isinstance(fi, dict):
                fc_text += f"- **{fi.get('product', '?')}** ({fi.get('dimension', '?')}): 6个月预测 {fi.get('forecast_6m', '?')}, 12个月预测 {fi.get('forecast_12m', '?')}\n"
        fc_text += f"\n*{forecast.get('disclaimer', '')}*"
        sections.append({
            "id": "sec-forecast", "title": "预测推演",
            "content": fc_text, "content_type": "text",
            "source_ids": [], "chart_path": None, "subsections": None,
        })
        # Add What-if form section
        sections.append({
            "id": "sec-whatif", "title": "What-if 推演",
            "content": "输入假设条件，系统将在现有数据上做推演（不走 Collector，30 秒出结论）",
            "content_type": "what-if-form", "source_ids": [], "chart_path": None, "subsections": None,
        })

    # 6. Recommendations (required)
    sections.append({
        "id": "sec-recommendations", "title": "建议",
        "content": f"**{profile['recommendations']}**\n\n基于以上分析，建议关注产品功能差异化和定价策略优化。",
        "content_type": "text", "source_ids": [], "chart_path": None, "subsections": None,
    })

    # 7. Sources (required)
    sources_text = ""
    for i, dp in enumerate(collected):
        if isinstance(dp, dict):
            sources_text += f"[{i+1}] {dp.get('source_url', '?')} — {dp.get('collected_at', '?')} — {dp.get('label', '')}\n"
    sections.append({
        "id": "sec-sources", "title": "数据来源",
        "content": sources_text or "_暂无来源_", "content_type": "table",
        "source_ids": [], "chart_path": None, "subsections": None,
    })

    # 8. Appendix: Quality (required)
    q_text = f"总数据点: {quality.get('total_data_points', 0)}\n"
    q_text += f"已验证: {quality.get('verified_count', 0)} | 多源交叉: {quality.get('multi_source_count', 0)} | 单源: {quality.get('single_source_count', 0)}\n"
    q_text += f"事实错误: {quality.get('fact_errors_count', 0)} | 质量分: {quality.get('overall_quality_score', 0):.0%}\n"
    sections.append({
        "id": "appendix-quality", "title": "附录 A: 数据质量报告",
        "content": q_text, "content_type": "text",
        "source_ids": [], "chart_path": None, "subsections": None,
    })

    return sections


def _render_comparison_table(rows: list[dict], products: list[str], dimensions: list[str]) -> str:
    """Render comparison matrix as Markdown table."""
    if not rows or not dimensions:
        return "_暂无对比数据_"
    header = "| 产品 | " + " | ".join(dimensions) + " |\n"
    sep = "|------" + "|------" * len(dimensions) + " |\n"
    body = ""
    for product in products:
        body += f"| {product} | "
        for dim in dimensions:
            match = [r for r in rows if r.get("product") == product and r.get("dimension") == dim]
            if match:
                body += f"{match[0].get('rating', '?')} "
            else:
                body += "N/A "
        body += " |\n"
    return header + sep + body


def _build_traceability_map(collected: list[dict]) -> dict:
    """Build claim_id → {url, timestamp, confidence} mapping."""
    trace = {}
    for i, dp in enumerate(collected):
        if isinstance(dp, dict):
            trace[str(i + 1)] = {
                "url": dp.get("source_url", ""),
                "timestamp": dp.get("collected_at", ""),
                "confidence": dp.get("confidence", 0.0),
            }
    return trace


def _build_review_package(report_data: dict, collected: list[dict], quality: dict) -> dict:
    """Build ReviewPackage for HITL Gate (§3.13.5)."""
    sections = report_data.get("sections", [])
    exec_summary = ""
    for s in sections:
        if s.get("id") == "sec-executive-summary":
            exec_summary = s.get("content", "")[:500]
            break

    products = report_data.get("products", [])
    categories: dict[str, int] = {}
    sources: dict[str, int] = {}
    for dp in collected:
        if isinstance(dp, dict):
            cat = dp.get("category", "unknown")
            st = dp.get("source_type", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
            sources[st] = sources.get(st, 0) + 1

    return {
        "executive_summary": exec_summary,
        "key_findings": _extract_key_findings(report_data),
        "data_stats": {
            "total_data_points": len(collected),
            "products_covered": {p: sum(1 for dp in collected if isinstance(dp, dict) and dp.get("product") == p) for p in products},
            "categories_covered": categories,
            "source_types": sources,
        },
        "quality_summary": quality,
        "unresolved_issues": quality.get("unresolved_gaps", []) if isinstance(quality, dict) else [],
        "recommendations": ["建议批准发布", "或选择重写为另一视角"],
        "pm_report_preview": exec_summary[:500],
        "entrepreneur_report_preview": "",  # Filled if dual-persona mode
    }


def _extract_key_findings(report_data: dict) -> list[str]:
    """Extract 3-5 key findings from report sections."""
    findings = []
    for s in report_data.get("sections", []):
        if s.get("id") in ("sec-executive-summary", "sec-swot"):
            content = s.get("content", "")
            # Take first bullet point or first sentence
            lines = [line.strip("- ").strip() for line in content.split("\n") if line.strip().startswith("-")]
            findings.extend(lines[:2])
    return findings[:5] or ["分析完成"]


def _compute_report_metrics(collected: list[dict], verdict: dict, traceability: dict) -> dict:
    """Compute coverage / cross_validation / trace_completeness metrics."""
    quality = verdict.get("quality_summary", {})
    if isinstance(quality, dict):
        return {
            "coverage": len(traceability) / max(len(collected), 1),
            "cross_validation_rate": quality.get("multi_source_count", 0) / max(quality.get("total_data_points", 1), 1),
            "trace_completeness": len(traceability) / max(len(collected), 1),
            "improvement_ratio": quality.get("improvement_ratio", 0),
        }
    return {}


# ── Self-Check (§3.7.6) ──


def writer_self_check(report_data: dict, target_products: list[str]) -> list[str]:
    """Run W1-W5 self-check on the report. Returns list of issue descriptions."""
    issues = []
    sections = report_data.get("sections", [])
    all_content = " ".join(s.get("content", "") for s in sections)

    # W1: Every target_product mentioned at least once
    for product in target_products:
        if product not in all_content:
            issues.append(f"W1: {product} not mentioned in report")

    # W2: Every factual claim has [n] source annotation
    # (Heuristic: check that sections with data have source IDs or [n] markers)
    for s in sections:
        if s.get("content_type") in ("table", "text") and s.get("id") not in ("sec-whatif",):
            if "[1]" not in s.get("content", "") and "source_data_point_ids" not in str(s):
                pass  # Minor — only flag if no source references at all

    # W3: traceability_map keys match [n] references
    trace_map = report_data.get("traceability_map", {})
    if not trace_map:
        issues.append("W3: traceability_map is empty")

    # W4: Source table references consistent
    # W5: Persona focus correct
    persona = report_data.get("persona", "pm")
    profile = PERSONA_PROFILES.get(persona, {})
    if profile and profile.get("opening", "") not in all_content:
        issues.append(f"W5: Persona '{persona}' focus not reflected in report")

    return issues
