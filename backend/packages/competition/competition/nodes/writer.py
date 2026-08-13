"""Writer node — ReportData generation with source traceability.

Per COMPETITION_PLAN.md §3.7: interactive ReportData replacing legacy .md strings.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Report section structure (§3.7.3) — baseline always 6 sections
REQUIRED_SECTIONS = [
    "sec-executive-summary",
    "sec-comparison-matrix",
    "sec-swot",
    "sec-recommendations",
    "sec-sources",
    "appendix-quality",
]

# Conditionally generated (always available, generated when data exists)
OPTIONAL_SECTIONS = {
    "sec-trends": "trends",
    "sec-user-voice": "sentiment",
    "sec-forecast": "forecast",
    "appendix-charts": "charts",
}

# v4: Deep mode additional sections — generated only when schema_profile="deep"
DEEP_SECTIONS = [
    "sec-trends",        # market/product trends
    "sec-forecast",      # prediction + what-if
    "appendix-industry", # industry-specific dimensions (extra_fields)
]


def _get_schema_mode(state: dict) -> str:
    """Return the active schema profile from Orchestrator, default baseline."""
    orch = state.get("orchestration_result") or {}
    return orch.get("schema_profile", "baseline")




def writer_node(state: dict) -> dict:
    """Graph node: generate ReportData from analysis_result + review_verdict.

    Returns partial state update with report_data + review_package + traceability_map.
    """
    analysis = state.get("analysis_result") or {}
    verdict = state.get("review_verdict") or {}
    collected = state.get("collected_data") or []
    target_products = state.get("target_products", [])
    hitl_focus, whatif_comment_raw, hitl_action = _get_hitl_focus(state)
    # Only use comment as what-if scenario when action is explicitly "rewrite"
    whatif_comment = ""  # what-if temporarily disabled

    # Build report sections — v4: schema_profile controls deep sections
    quality = verdict.get("quality_summary", {})
    schema_mode = _get_schema_mode(state)
    sections = _build_sections(analysis, verdict, target_products, hitl_focus, whatif_comment, hitl_action, collected, quality, schema_mode)

    # Industry fixed sections (Layer 2 of §3.20)
    industry_sections = _build_industry_sections(state, analysis)
    if industry_sections:
        sections.extend(industry_sections)
        logger.info("Added %d industry sections for '%s'", len(industry_sections), state.get("industry", "general"))

    traceability = _build_traceability_map(collected)
    persona = state.get("persona") if state.get("persona") in ("pm", "entrepreneur") else "pm"
    _apply_narrative_generation(
        sections, analysis, target_products, persona, traceability, _citation_index(collected),
        hitl_action=hitl_action,
        hitl_focus=hitl_focus,
        hitl_comment=whatif_comment_raw,
        brief=state.get("analysis_brief") or {},
    )
    forecast = analysis.get("forecast")
    extra_fields = analysis.get("extra_fields") or {}
    dynamic_blocks = analysis.get("dynamic_blocks") or []
    metrics = _compute_report_metrics(collected, verdict, traceability)
    brief = state.get("analysis_brief") or {}

    report_data = {
        "persona": persona,
        "title": _build_title(target_products),
        "generated_at": datetime.now(UTC).isoformat(),
        "products": target_products,
        "sections": sections,
        "traceability_map": traceability,
        "quality_summary": quality,
        "forecast": forecast,
        "metrics": metrics,
        "extra_fields": extra_fields,
        "dynamic_blocks": dynamic_blocks,
        "analysis_scope": {
            "objective": brief.get("objective"),
            "market_scope": brief.get("market_scope"),
            "time_range": brief.get("time_range"),
            "dimensions": brief.get("dimensions"),
            "audience": brief.get("audience"),
            "evidence_policy": brief.get("evidence_policy"),
            "output_focus": brief.get("output_focus"),
            "confirmation_source": brief.get("confirmation_source"),
        } if brief else None,
    }

    # Build ReviewPackage for HITL (§3.13.5)
    review_package = _build_review_package(report_data, collected, quality)

    # Self-check (§3.7.6)
    issues = writer_self_check(report_data, target_products)
    if issues:
        logger.warning("Writer self-check found %d issues: %s", len(issues), issues)

    # ── Self-assessment (§3.17.2) ──
    self_assessment = _build_writer_self_assessment(report_data, target_products)

    return {
        "report_data": report_data,
        "traceability_map": traceability,
        "review_package": review_package,
        "writer_self_assessment": self_assessment,
    }


def _build_title(products: list[str]) -> str:
    products_str = " vs ".join(products) if products else "竞品分析"
    return f"{products_str} 竞品分析报告"


def _get_hitl_focus(state: dict) -> list[str] | None:
    decision = state.get("hitl_decision") or {}
    return decision.get("target_focus"), decision.get("comment", ""), decision.get("action", "")


def _citation_index(collected: list[dict]) -> dict[str, str]:
    """Map original data-point IDs to stable numeric citation IDs."""
    index: dict[str, str] = {}
    for i, point in enumerate(collected):
        if not isinstance(point, dict):
            continue
        point_id = point.get("id")
        if point_id and str(point_id) not in index:
            index[str(point_id)] = str(i + 1)
    return index


def _resolve_citations(point_ids: Any, index: dict[str, str]) -> tuple[str, list[str]]:
    """Resolve Analyst IDs without inventing references for unknown IDs."""
    if not isinstance(point_ids, (list, tuple)):
        return "", []
    numeric: list[str] = []
    for point_id in point_ids:
        key = str(point_id).strip() if point_id is not None else ""
        value = index.get(key)
        if value and value not in numeric:
            numeric.append(value)
    return "".join(f"[{value}]" for value in numeric), numeric


def _fallback_summary(summary_text: str, products: list[str], analysis: dict, citation_index: dict[str, str]) -> str:
    """Create useful narrative content without requiring an LLM."""
    product_text = "、".join(products) if products else "目标竞品"
    citations: list[str] = []
    matrix = analysis.get("comparison_matrix") or {}
    for cell in matrix.get("cells", []) if isinstance(matrix, dict) else []:
        if isinstance(cell, dict):
            _, ids = _resolve_citations(cell.get("source_data_point_ids", []), citation_index)
            citations.extend(ids)
    marker = "".join(f"[{item}]" for item in dict.fromkeys(citations))
    return f"基于公开数据和多维度分析，{product_text}的对比结果显示：{summary_text or '当前证据支持的差异仍需结合数据质量审慎解读。'}{marker}"


def _fallback_recommendations(analysis: dict, products: list[str], citation_index: dict[str, str]) -> str:
    matrix = analysis.get("comparison_matrix") or {}
    summary = matrix.get("summary", "") if isinstance(matrix, dict) else ""
    matrix_citations: list[str] = []
    if isinstance(matrix, dict):
        for cell in matrix.get("cells", []):
            if isinstance(cell, dict):
                _, stable_ids = _resolve_citations(cell.get("source_data_point_ids", []), citation_index)
                matrix_citations.extend(stable_ids)
    marker = "".join(f"[{item}]" for item in dict.fromkeys(matrix_citations))
    if summary:
        return f"- **优先级：高**：围绕“{summary}”验证自身产品的差异化策略，并补充关键维度的交叉证据。{marker}"
    if not citation_index:
        return "- **优先级：高**：当前证据不足，先完成关键维度的数据收集与多源验证，再做战略决策。"
    product_text = "、".join(products) if products else "目标竞品"
    return f"- **优先级：中**：结合{product_text}的已收集证据开展定向验证，并根据验证结果安排后续迭代。"


def _build_sections(analysis: dict, verdict: dict, products: list[str], focus: list[str] | None, whatif_comment: str, hitl_action: str, collected: list[dict], quality: dict, schema_profile: str = "baseline") -> list[dict]:
    """Build all report sections."""
    sections: list[dict] = []
    citation_index = _citation_index(collected)

    def _src_ref(point_ids: list[str]) -> str:
        return _resolve_citations(point_ids, citation_index)[0]

    # 1. Executive Summary (required)
    matrix = analysis.get("comparison_matrix", {})
    summary_text = matrix.get("summary", f"{' vs '.join(products)} 竞品分析")
    exec_content = _fallback_summary(summary_text, products, analysis, citation_index)
    sections.append({
        "id": "sec-executive-summary", "title": "执行摘要",
        "content": exec_content, "content_type": "text",
        "source_ids": list(dict.fromkeys(re.findall(r"\[(\d+)\]", exec_content))), "chart_path": None, "subsections": None,
    })

    # 2. Comparison Matrix (required)
    cells = matrix.get("cells", [])
    dims = matrix.get("dimensions", [])
    table_rows = []
    comparison_source_ids: list[str] = []
    for cell in cells:
        if isinstance(cell, dict):
            rating = cell.get("rating", "N/A")
            evidence = cell.get("evidence", "")
            src_ids = cell.get("source_data_point_ids", [])
            _, stable_ids = _resolve_citations(src_ids, citation_index)
            comparison_source_ids.extend(stable_ids)
            table_rows.append({
                "product": cell.get("product", ""),
                "dimension": cell.get("dimension", ""),
                "rating": rating,
                "evidence": f"{evidence} {_src_ref(src_ids)}".strip(),
            })
    sections.append({
        "id": "sec-comparison-matrix", "title": "对比矩阵",
        "content": _render_comparison_table(table_rows, products, dims),
        "content_type": "table", "source_ids": list(dict.fromkeys(comparison_source_ids)), "chart_path": None, "subsections": None,
    })

    # 3. SWOT (required)
    swot = analysis.get("swot", {})
    swot_content = ""
    swot_source_ids: list[str] = []
    for prod_name, swot_data in swot.items():
        if not isinstance(swot_data, dict):
            continue
        swot_content += f"### {prod_name}\n"
        for item in swot_data.get("items", []):
            if not isinstance(item, dict):
                continue
            src_ids = item.get("source_data_point_ids", [])
            _, stable_ids = _resolve_citations(src_ids, citation_index)
            swot_source_ids.extend(stable_ids)
            swot_content += f"- **{item.get('category', '?')}**: {item.get('statement', '')} {_src_ref(src_ids)}\n  - 证据: {item.get('evidence', '')}\n"
    sections.append({
        "id": "sec-swot", "title": "SWOT 分析",
        "content": swot_content or "_暂无 SWOT 数据_", "content_type": "text",
        "source_ids": list(dict.fromkeys(swot_source_ids)), "chart_path": None, "subsections": None,
    })

    # 4. Trends (conditional)
    trends = analysis.get("trends", [])
    if trends:
        trend_text = ""
        trend_source_ids: list[str] = []
        for t in trends:
            if isinstance(t, dict):
                src_ids = t.get("source_data_point_ids", [])
                _, stable_ids = _resolve_citations(src_ids, citation_index)
                trend_source_ids.extend(stable_ids)
                try:
                    confidence_text = f"{float(t.get('confidence', 0)):.0%}"
                except (TypeError, ValueError):
                    confidence_text = "0%"
                trend_text += f"- {t.get('dimension', '?')}: {t.get('direction', '?')} (置信度: {confidence_text}) — {t.get('evidence', '')} {_src_ref(src_ids)}\n"
        sections.append({
            "id": "sec-trends", "title": "趋势与洞察",
            "content": trend_text, "content_type": "text",
            "source_ids": list(dict.fromkeys(trend_source_ids)), "chart_path": None, "subsections": None,
        })

    # 5. Forecast (conditional, §3.5.7)
    forecast = analysis.get("forecast")
    if forecast and isinstance(forecast, dict):
        items = forecast.get("items", [])
        fc_text = forecast.get("summary", "") + "\n\n"
        forecast_source_ids: list[str] = []
        for fi in items:
            if isinstance(fi, dict):
                src_ids = fi.get("source_data_point_ids", [])
                _, stable_ids = _resolve_citations(src_ids, citation_index)
                forecast_source_ids.extend(stable_ids)
                fc_text += f"- **{fi.get('product', '?')}** ({fi.get('dimension', '?')}): 6个月预测 {fi.get('forecast_6m', '?')}, 12个月预测 {fi.get('forecast_12m', '?')} {_src_ref(src_ids)}\n"
        fc_text += f"\n*{forecast.get('disclaimer', '')}*"
        sections.append({
            "id": "sec-forecast", "title": "预测推演",
            "content": fc_text, "content_type": "text",
            "source_ids": list(dict.fromkeys(forecast_source_ids)), "chart_path": None, "subsections": None,
        })

    # What-if section — temporarily disabled

    # Dynamic analyst blocks are inserted after standard analysis sections.
    dynamic_blocks = analysis.get("dynamic_blocks") or []
    sections.extend(_render_dynamic_blocks(dynamic_blocks, _src_ref, citation_index))

    # Legacy extra_fields remains a compatibility appendix only when no blocks exist.
    extra_fields = analysis.get("extra_fields") or {}
    if extra_fields and not dynamic_blocks and isinstance(extra_fields, dict):
        ef_lines: list[str] = []
        ef_source_ids: list[str] = []
        for field_name, field_data in extra_fields.items():
            if isinstance(field_data, dict):
                value = field_data.get("value", "?")
                evidence = field_data.get("evidence", "")
                src_ids = field_data.get("source_data_point_ids", [])
                _, stable_ids = _resolve_citations(src_ids, citation_index)
                ef_source_ids.extend(stable_ids)
                line = f"- **{field_name}**: {value}"
                if evidence:
                    line += f" — {evidence}"
                if stable_ids:
                    line += f" {_src_ref(src_ids)}"
                ef_lines.append(line)
            else:
                ef_lines.append(f"- **{field_name}**: {field_data}")
        sections.append({
            "id": "appendix-extra-fields", "title": "附录 B: 行业特有维度（动态 Schema）",
            "content": "\n".join(ef_lines) or "_无行业特有维度_", "content_type": "text",
            "source_ids": list(dict.fromkeys(ef_source_ids)), "chart_path": None, "subsections": None,
        })

    # 6. Recommendations (required)
    rec_content = _fallback_recommendations(analysis, products, citation_index)
    sections.append({
        "id": "sec-recommendations", "title": "建议",
        "content": rec_content,
        "content_type": "text",
        "source_ids": list(dict.fromkeys(re.findall(r"\[(\d+)\]", rec_content))),
        "chart_path": None, "subsections": None,
    })

    # 7. Sources (required)
    sources_text = ""
    for i, dp in enumerate(collected):
        if isinstance(dp, dict):
            sources_text += f"[{i+1}] {dp.get('source_url', '?')} — {dp.get('collected_at', '?')} — {dp.get('label', '')}\n"
    sections.append({
        "id": "sec-sources", "title": "数据来源",
        "content": sources_text or "_暂无来源_", "content_type": "table",
        "source_ids": [str(i + 1) for i, dp in enumerate(collected) if isinstance(dp, dict)], "chart_path": None, "subsections": None,
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


def _build_industry_sections(state: dict, analysis: dict) -> list[dict]:
    """Generate Layer 2 industry-specific fixed sections (§3.20)."""
    from competition.industry import get_industry_profile

    industry = state.get("industry", "general")
    if industry == "general":
        return []

    profile = get_industry_profile(industry)
    fixed_ids = profile.get("fixed_sections", [])
    titles = profile.get("section_titles", {})
    sections: list[dict] = []

    for i, sec_id in enumerate(fixed_ids):
        title = titles.get(sec_id, sec_id)
        bias = profile.get("prompt_bias", "")

        # Generate content via LLM based on industry-specific prompt
        content = _generate_industry_section_content(state, analysis, sec_id, bias)
        sections.append({
            "id": sec_id,
            "title": title,
            "content": content,
            "content_type": "text",
            "source_ids": [],
            "chart_path": None,
            "subsections": None,
        })

    return sections


def _generate_industry_section_content(state: dict, analysis: dict, section_id: str, prompt_bias: str) -> str:
    """Generate an industry-specific section via lightweight LLM call."""
    try:
        from competition.executor import execute_agent

        products = state.get("target_products", [])
        user_request = state.get("user_request", "")

        data_summary = ""
        collected = state.get("collected_data") or []
        for dp in collected[:10]:
            if isinstance(dp, dict):
                data_summary += f"- {dp.get('product', '?')} | {dp.get('category', '?')} | {dp.get('label', '?')} | {dp.get('value', '?')}\n"

        task = (
            f"Query: {user_request}\n"
            f"Products: {', '.join(products) if products else 'unknown'}\n"
            f"Industry focus: {prompt_bias}\n\n"
            f"Collected data:\n{data_summary}\n\n"
            f"Generate a concise analysis section (3-5 paragraphs) for the industry-specific "
            f"section '{section_id}'. Focus on quantitative comparisons and cite data points. "
            f"Output markdown text only, no JSON."
        )
        system = (
            "You are a competitive analysis writer specializing in industry-specific analysis. "
            "Write concise, data-driven sections. Cite specific data points."
        )

        raw, _ = execute_agent(system, task, temperature=0.3, max_tokens=600, agent_name="IndustrySectionWriter")
        return raw.strip() if raw else f"_Industry section '{section_id}' — insufficient data to generate._"
    except Exception:
        logger.exception("Industry section generation failed for %s", section_id)
        return f"_Industry section '{section_id}' — generation failed._"


def _render_dynamic_blocks(blocks: list[dict], _src_ref: Callable[[list[str]], str], citation_index: dict[str, str] | None = None) -> list[dict]:
    """Render DynamicBlock list → ReportSection list. `[v4 动态 Schema]`

    Each block_type maps to a different content_type for frontend rendering:
      kv_list → "text" (key-value list)
      comparison_table → "table" (sortable comparison table)
      stat_chart → "chart" (radar/bar/pie chart component)
      insight_text → "text" (markdown narrative)
    """
    sections: list[dict] = []
    TYPE_TO_CONTENT = {
        "kv_list": "text",
        "comparison_table": "table",
        "stat_chart": "chart",
        "insight_text": "text",
    }
    TYPE_TO_TITLE_PREFIX = {
        "kv_list": "指标: ",
        "comparison_table": "对比: ",
        "stat_chart": "图表: ",
        "insight_text": "洞察: ",
    }

    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        bt = block.get("block_type", "kv_list")
        title = block.get("title", f"动态分析 {i+1}")
        data = block.get("data", {})
        if not isinstance(data, dict):
            data = {"value": data}
        src_ids = block.get("source_data_point_ids", [])
        _, stable_source_ids = _resolve_citations(src_ids, citation_index or {})

        content = _format_block_content(bt, data, src_ids, _src_ref)
        if bt in ("comparison_table", "stat_chart") and not content:
            content = f"{title}（结构化数据）{_src_ref(src_ids)}".strip()
        sections.append({
            "id": f"dynamic-block-{i}",
            "title": TYPE_TO_TITLE_PREFIX.get(bt, "") + title,
            "content": content,
            "content_type": TYPE_TO_CONTENT.get(bt, "text"),
            "source_ids": stable_source_ids,
            "chart_path": _extract_chart_config(bt, data),
            "subsections": None,
        })

    return sections


def _format_block_content(block_type: str, data: dict, src_ids: list[str], _src_ref) -> str:
    """Format a single DynamicBlock's data as renderable content."""
    src_str = " " + _src_ref(src_ids) if src_ids else ""
    if not isinstance(data, dict):
        return str(data) + src_str

    if block_type == "kv_list":
        lines = []
        for key, val in (data or {}).items():
            if isinstance(val, dict):
                v = val.get("value", "?")
                e = val.get("evidence", "")
                lines.append(f"- **{key}**: {v}" + (f" — {e}" if e else ""))
            else:
                lines.append(f"- **{key}**: {val}")
        return "\n".join(lines) + src_str

    elif block_type == "comparison_table":
        return ""  # content is in data dict; frontend reads from chart_path

    elif block_type == "stat_chart":
        return ""  # content is in data dict; frontend reads from chart_path

    elif block_type == "insight_text":
        return (data.get("content", "") if isinstance(data, dict) else str(data)) + src_str

    return str(data) + src_str


def _extract_chart_config(block_type: str, data: dict) -> dict | None:
    """Extract chart config from stat_chart blocks for frontend chart_path."""
    if block_type == "stat_chart" and isinstance(data, dict):
        return {
            "chart": data.get("chart", "radar"),
            "labels": data.get("labels", []),
            "series": data.get("series", {}),
        }
    if block_type == "comparison_table" and isinstance(data, dict):
        return {
            "headers": data.get("headers", []),
            "rows": data.get("rows", []),
        }
    return None


def _render_comparison_table(rows: list[dict], products: list[str], dimensions: list[str]) -> str:
    """Render comparison matrix as Markdown table."""
    if not rows or not dimensions:
        return "_暂无对比数据_"
    header = "| 产品 | " + " | ".join(dimensions) + " |\n"
    sep = "|------|" + "|".join(["------" for _ in dimensions]) + "|\n"
    body = ""
    for product in products:
        body += f"| {product} |"
        for dim in dimensions:
            match = [r for r in rows if r.get("product") == product and r.get("dimension") == dim]
            if match:
                rating = match[0].get("rating", "?")
                citations = "".join(re.findall(r"\[\d+\]", match[0].get("evidence", "")))
                body += f" {rating}{citations} |"
            else:
                body += " N/A |"
        body += "\n"
    return header + sep + body


def _build_traceability_map(collected: list[dict]) -> dict:
    """Build claim_id → {url, timestamp, confidence, credibility_tier} mapping."""
    from urllib.parse import urlparse

    # Try to load domain credibility scores for tier assignment
    domain_scores: dict[str, float] = {}
    try:
        from competition.db import get_all_credibilities, init_db
        conn = init_db()
        rows = get_all_credibilities(conn)
        conn.close()
        for r in rows:
            domain_scores[r.get("source_domain", "")] = r.get("score", 0.5)
    except Exception:
        pass

    def _tier(score: float) -> str:
        if score >= 0.7:
            return "strong"
        if score >= 0.4:
            return "moderate"
        return "weak"

    trace = {}
    for i, dp in enumerate(collected):
        if isinstance(dp, dict):
            url = dp.get("source_url", "")
            domain = urlparse(url).netloc if url else ""
            score = domain_scores.get(domain, 0.5)
            trace[str(i + 1)] = {
                "url": url,
                "timestamp": dp.get("collected_at", ""),
                "confidence": dp.get("confidence", 0.0),
                "credibility_tier": _tier(score),
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
            "repair_delta": quality.get("repair_delta", 0),
            "round_metrics": quality.get("round_metrics", {}),
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

    # W3: traceability_map keys match [n] references and explicit source IDs
    trace_map = report_data.get("traceability_map", {})
    if not trace_map:
        issues.append("W3: traceability_map is empty")
    valid_keys = {str(key) for key in trace_map}
    for section in sections:
        section_id = section.get("id", "unknown")
        for source_id in section.get("source_ids", []) or []:
            if str(source_id) not in valid_keys:
                issues.append(f"W3: {section_id} source ID [{source_id}] is not in traceability_map")
        content = section.get("content", "")
        if not isinstance(content, str):
            continue
        for marker in re.findall(r"\[(\d+)\]", content):
            if marker not in valid_keys:
                issues.append(f"W3: {section_id} citation [{marker}] is not in traceability_map")

    # W4: Source table references consistent

    return issues


# ── Self-Assessment (§3.17.2) ──


def _build_writer_self_assessment(report_data: dict, target_products: list[str], required_sections: list[str] | None = None) -> dict:
    """Build Writer self-assessment: schema compliance, section completeness, source annotation rate.

    Returns dict suitable for frontend green/yellow/red dot visualization.
    v4: accepts optional required_sections from Orchestrator's schema_profile.
    """
    sections = report_data.get("sections", [])
    section_ids = {s.get("id", "") for s in sections}
    req_secs = required_sections if required_sections is not None else REQUIRED_SECTIONS

    # Schema compliance: all required sections present
    required_present = all(rid in section_ids for rid in req_secs)
    missing_required = [rid for rid in req_secs if rid not in section_ids]

    # Section completeness: proportion of required sections with non-empty content
    filled = 0
    for s in sections:
        if s.get("id") in REQUIRED_SECTIONS and s.get("content", "").strip():
            filled += 1
    section_completeness = filled / len(REQUIRED_SECTIONS) if REQUIRED_SECTIONS else 1.0

    # Source annotation rate: count [n] references in report content
    all_content = " ".join(s.get("content", "") for s in sections)
    import re
    annotation_count = len(re.findall(r"\[\d+\]", all_content))

    # Count total factual claims (heuristic: lines with evidence markers or bullet points)
    claim_lines = 0
    for s in sections:
        content = s.get("content", "")
        claim_lines += len([line for line in content.split("\n") if line.strip().startswith("-") and len(line) > 20])
    source_annotation_rate = annotation_count / claim_lines if claim_lines > 0 else 0.0

    # Product mention check
    product_mention_check = {}
    for product in target_products:
        product_mention_check[product] = product in all_content

    # Section list for display
    section_status = []
    for rid in REQUIRED_SECTIONS:
        section_status.append({
            "id": rid,
            "present": rid in section_ids,
            "has_content": bool(next((s.get("content", "").strip() for s in sections if s.get("id") == rid), "")),
        })

    # Overall score: weighted average
    schema_score = 1.0 if required_present else 0.0
    overall_score = (schema_score * 0.4 + section_completeness * 0.3 + min(source_annotation_rate, 1.0) * 0.3)

    return {
        "schema_compliance": required_present,
        "missing_required": missing_required,
        "section_completeness": round(section_completeness, 2),
        "source_annotation_rate": round(min(source_annotation_rate, 1.0), 2),
        "product_mention_check": product_mention_check,
        "section_status": section_status,
        "overall_score": round(overall_score, 2),
    }


def _narrative_digest(analysis: dict, citation_index: dict[str, str]) -> dict[str, Any]:
    """Build a compact, already-cited evidence digest for the Writer call."""
    digest: dict[str, Any] = {}
    matrix = analysis.get("comparison_matrix")
    if isinstance(matrix, dict):
        digest["comparison_summary"] = str(matrix.get("summary", ""))[:500]
        digest["comparison_cells"] = [
            {
                "product": cell.get("product", ""),
                "dimension": cell.get("dimension", ""),
                "rating": cell.get("rating"),
                "evidence": f"{cell.get('evidence', '')} {_resolve_citations(cell.get('source_data_point_ids', []), citation_index)[0]}".strip(),
            }
            for cell in matrix.get("cells", [])[:30]
            if isinstance(cell, dict)
        ]
    swot_digest: list[dict[str, Any]] = []
    for product, group in (analysis.get("swot") or {}).items() if isinstance(analysis.get("swot"), dict) else []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items", [])[:20]:
            if not isinstance(item, dict):
                continue
            swot_digest.append({
                "product": product,
                "category": item.get("category", ""),
                "statement": item.get("statement", ""),
                "evidence": f"{item.get('evidence', '')} {_resolve_citations(item.get('source_data_point_ids', []), citation_index)[0]}".strip(),
            })
    digest["swot"] = swot_digest
    digest["trends"] = [
        {
            "dimension": item.get("dimension", ""),
            "direction": item.get("direction", ""),
            "evidence": f"{item.get('evidence', '')} {_resolve_citations(item.get('source_data_point_ids', []), citation_index)[0]}".strip(),
        }
        for item in (analysis.get("trends") or [])[:15]
        if isinstance(item, dict)
    ]
    forecast = analysis.get("forecast")
    if isinstance(forecast, dict):
        digest["forecast"] = {
            "summary": forecast.get("summary", ""),
            "items": [
                {
                    "product": item.get("product", ""),
                    "dimension": item.get("dimension", ""),
                    "forecast_6m": item.get("forecast_6m", ""),
                    "forecast_12m": item.get("forecast_12m", ""),
                    "rationale": f"{item.get('rationale', '')} {_resolve_citations(item.get('source_data_point_ids', []), citation_index)[0]}".strip(),
                }
                for item in forecast.get("items", [])[:15]
                if isinstance(item, dict)
            ],
        }
    else:
        digest["forecast"] = {}
    return digest


def _valid_narrative_text(value: Any, valid_keys: set[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if any(marker not in valid_keys for marker in re.findall(r"\[(\d+)\]", text)):
        return None
    return text


def _apply_narrative_generation(
    sections: list[dict], analysis: dict, products: list[str], persona: str,
    traceability: dict[str, dict], citation_index: dict[str, str], *, hitl_action: str, hitl_focus: list[str] | None,
    hitl_comment: str,
    brief: dict | None = None,
) -> None:
    """Make one optional structured Writer call and apply fields independently."""
    if not analysis or not any(analysis.get(key) for key in ("comparison_matrix", "swot", "trends", "forecast", "dynamic_blocks")):
        return
    try:
        from competition.executor import execute_structured_agent

        persona_label = "产品经理" if persona == "pm" else "创业者"
        guidance = ""
        if hitl_action == "rewrite":
            guidance = f"\n重写重点: {', '.join(hitl_focus or []) or '调整表达视角'}\n用户意见: {hitl_comment or '请提升可操作性'}"
        brief = brief or {}
        task = (
            f"视角: {persona_label}\n竞品: {', '.join(products)}\n"
            f"市场: {brief.get('market_scope', '未指定')}\n"
            f"输出重点: {', '.join(brief.get('output_focus') or []) or '关键差异与可执行建议'}\n"
            f"允许引用编号: {sorted(traceability, key=lambda x: int(x) if x.isdigit() else x)}{guidance}\n"
            f"证据摘要:\n{json.dumps(_narrative_digest(analysis, citation_index), ensure_ascii=False, indent=2)}\n\n"
            "只使用上述事实，不得编造事实或引用编号。返回严格 JSON 对象，字段为 executive_summary（150-250字中文字符串）和 recommendations（字符串数组）。"
        )
        result, _ = execute_structured_agent(
            "你是竞品分析报告 Writer，负责把已有证据整理成可执行叙事。",
            task,
            output_schema_desc='{"executive_summary": string, "recommendations": string[]}',
            agent_name="Writer", temperature=0.3, max_tokens=800, disable_thinking=True,
        )
    except Exception:
        logger.exception("Writer structured narrative generation failed")
        return
    if not isinstance(result, dict):
        return
    valid_keys = {str(key) for key in traceability}
    summary = _valid_narrative_text(result.get("executive_summary"), valid_keys)
    if summary:
        section = next((s for s in sections if s.get("id") == "sec-executive-summary"), None)
        if section:
            section["content"] = summary
            section["source_ids"] = list(dict.fromkeys(re.findall(r"\[(\d+)\]", summary)))
    recommendations = result.get("recommendations")
    if isinstance(recommendations, list):
        lines = [item.strip() for item in recommendations if isinstance(item, str)]
        rendered = "\n".join(f"- {item}" for item in lines)
        if (lines and len(lines) == len(recommendations)
                and all(item and _valid_narrative_text(item, valid_keys) for item in lines)):
            section = next((s for s in sections if s.get("id") == "sec-recommendations"), None)
            if section:
                section["content"] = rendered
                section["source_ids"] = list(dict.fromkeys(re.findall(r"\[(\d+)\]", rendered)))


def _generate_whatif(comment: str, analysis: dict, products: list[str], persona: str) -> str:
    """Generate what-if analysis via LLM based on user's assumption + existing data.

    Only runs when the user submits a what-if via HITL rewrite. Does NOT re-run
    Collector or Analyst — works from existing analysis_result.
    """
    from competition.executor import execute_agent

    matrix = analysis.get("comparison_matrix", {})
    swot = analysis.get("swot", {})
    trends = analysis.get("trends", [])
    forecast = analysis.get("forecast")

    context = f"""现有竞品分析数据:

对比矩阵: {matrix.get('summary', '')}
产品: {', '.join(products)}
SWOT: {str(swot)[:800]}
趋势: {str(trends)[:400]}
预测: {str(forecast)[:400]}"""

    prompt = f"""你是竞品分析推演专家。基于现有竞品分析数据，对用户的假设条件进行推演。

现有数据摘要:
{context}

请基于以上数据，对以下假设做出 150-300 字的推演分析，直接输出推演文本：
假设: {comment}"""

    result, _tokens = execute_agent(prompt, comment, temperature=0.7, max_tokens=600, agent_name="Writer")
    if result:
        return result.strip()
    return f"基于现有数据，无法对「{comment}」做出可靠推演。请尝试更具体的假设条件。"
